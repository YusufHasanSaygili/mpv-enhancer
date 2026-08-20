from collections.abc import Callable, Sequence
from concurrent.futures import Future
from pathlib import Path

import pytest
from PySide6.QtWidgets import QDoubleSpinBox, QLabel, QSpinBox, QWidget

from mpv_enhancer.domain.models import QueueItem
from mpv_enhancer.domain.settings import (
    SETTING_SPEC_REGISTRY,
    EffectivePlaybackSettings,
    SettingKey,
    VideoDimensions,
)
from mpv_enhancer.infrastructure.mpv.capabilities import (
    MpvCapabilities,
    MpvCapabilityError,
    MpvCapabilityProbe,
)
from mpv_enhancer.infrastructure.mpv.discovery import (
    MpvDiagnostics,
    MpvDiagnosticsStatus,
    MpvDiscoverySource,
)
from mpv_enhancer.infrastructure.mpv.json_ipc import JsonValue, MpvIpcRequest
from mpv_enhancer.infrastructure.mpv.playback import (
    PlaybackEvent,
    PlaybackPropertyListener,
)
from mpv_enhancer.infrastructure.mpv.settings_adapter import MpvSettingsAdapter
from mpv_enhancer.ui.main_window import MainWindow
from mpv_enhancer.ui.settings_panel import SelectedItemsSettingsPanel


class ImmediateIpcClient:
    def __init__(self, replies: dict[str, JsonValue]) -> None:
        self.replies = replies
        self.commands: list[tuple[JsonValue, ...]] = []
        self._next_request_id = 1

    def request(self, command: Sequence[JsonValue]) -> MpvIpcRequest:
        self.commands.append(tuple(command))
        future: Future[JsonValue] = Future()
        property_name = command[1]
        assert isinstance(property_name, str)
        future.set_result(
            self.replies[property_name] if command[0] == "get_property" else None
        )
        request = MpvIpcRequest(self._next_request_id, future)
        self._next_request_id += 1
        return request


def test_probe_reads_version_property_and_command_lists_once_then_caches() -> None:
    client = ImmediateIpcClient(
        {
            "mpv-version": "0.41.0",
            "property-list": ["speed", "video-rotate", "brightness"],
            "command-list": [
                {"name": "loadfile", "args": []},
                {"name": "set", "args": []},
            ],
        }
    )
    probe = MpvCapabilityProbe(client)

    first = probe.probe().result()
    second = probe.probe().result()

    assert first is second
    assert first == MpvCapabilities(
        version="0.41.0",
        properties=frozenset({"speed", "video-rotate", "brightness"}),
        commands=frozenset({"loadfile", "set"}),
    )
    assert client.commands == [
        ("get_property", "mpv-version"),
        ("get_property", "property-list"),
        ("get_property", "command-list"),
    ]


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("mpv-version", ""),
        ("property-list", ["speed", 7]),
        ("command-list", [{"args": []}]),
    ],
)
def test_probe_rejects_malformed_capability_payloads(
    field: str,
    invalid: JsonValue,
) -> None:
    replies: dict[str, JsonValue] = {
        "mpv-version": "0.41.0",
        "property-list": ["speed"],
        "command-list": [{"name": "loadfile"}],
    }
    replies[field] = invalid

    with pytest.raises(MpvCapabilityError):
        MpvCapabilityProbe(ImmediateIpcClient(replies)).probe().result()


def test_panel_disables_only_rows_for_unsupported_properties(qtbot) -> None:
    panel = SelectedItemsSettingsPanel()
    qtbot.addWidget(panel)
    properties = {
        spec.mpv_property
        for spec in SETTING_SPEC_REGISTRY.specs
        if spec.key is not SettingKey.BRIGHTNESS
    }
    capabilities = MpvCapabilities(
        version="0.41.0",
        properties=frozenset(properties),
        commands=frozenset({"loadfile", "set"}),
    )

    panel.set_selected_items((QueueItem.create(Path("synthetic/episode-01.mkv")),))
    panel.set_capabilities(capabilities)

    brightness = panel.findChild(QSpinBox, "brightnessControl")
    speed = panel.findChild(QDoubleSpinBox, "speedControl")
    status = panel.findChild(QLabel, "capabilityStatusLabel")
    assert brightness is not None
    brightness_row = panel.findChild(QWidget, "brightnessEditorRow")
    assert brightness_row is not None
    assert not brightness_row.isEnabled()
    assert speed is not None
    assert speed.isEnabled()
    assert status is not None
    assert status.text() == "mpv 0.41.0: 1 setting is unavailable."
    assert "brightness" in brightness_row.toolTip()


def test_adapter_skips_unsupported_properties_without_rejecting_playback() -> None:
    client = ImmediateIpcClient({})
    adapter = MpvSettingsAdapter(client)
    adapter.set_capabilities(
        MpvCapabilities(
            version="0.41.0",
            properties=frozenset({"speed"}),
            commands=frozenset({"loadfile", "set"}),
        )
    )

    adapter.apply(
        EffectivePlaybackSettings(
            speed=1.25,
            panscan=0.0,
            volume=100.0,
            mute=False,
            subtitle_visibility=True,
        )
    )

    assert client.commands == [
        ("set_property", "speed", 1.0),
        ("set_property", "speed", 1.25),
    ]


class NoopPlaybackAdapter:
    def begin_observing(
        self,
        _listener: PlaybackPropertyListener,
        _event_listener: Callable[[PlaybackEvent], None],
    ) -> None:
        pass

    def load_file(self, _path: Path, _generation: int) -> None:
        pass

    def apply_settings(
        self,
        _settings: EffectivePlaybackSettings,
        _source_dimensions: VideoDimensions | None = None,
    ) -> None:
        pass

    def set_paused(self, _paused: bool) -> None:
        pass

    def seek_absolute(self, _seconds: float) -> None:
        pass

    def stop(self) -> None:
        pass


class CapabilityPlaybackSession:
    def __init__(self, _host_hwnd: int) -> None:
        self.playback_adapter = NoopPlaybackAdapter()
        self.capabilities_listener: Callable[[MpvCapabilities], None] | None = None
        self.shutdown_calls = 0

    def start(self, _executable: Path) -> bool:
        return True

    def shutdown(self) -> bool:
        self.shutdown_calls += 1
        return True

    def set_failure_listener(self, _listener: Callable[[str], None]) -> None:
        pass

    def set_recovered_listener(self, _listener: Callable[[], None]) -> None:
        pass

    def set_capabilities_listener(
        self,
        listener: Callable[[MpvCapabilities], None],
    ) -> None:
        self.capabilities_listener = listener

    def emit_capabilities(self, capabilities: MpvCapabilities) -> None:
        assert self.capabilities_listener is not None
        self.capabilities_listener(capabilities)


def test_unsupported_setting_never_stops_basic_playback(qtbot) -> None:
    sessions: list[CapabilityPlaybackSession] = []

    def create_session(host_hwnd: int) -> CapabilityPlaybackSession:
        session = CapabilityPlaybackSession(host_hwnd)
        sessions.append(session)
        return session

    window = MainWindow(playback_session_factory=create_session)
    qtbot.addWidget(window)
    diagnostics = MpvDiagnostics(
        status=MpvDiagnosticsStatus.AVAILABLE,
        source=MpvDiscoverySource.SELECTED,
        executable=Path("synthetic/mpv.exe"),
        version="0.41.0",
        message="mpv is ready.",
    )
    window.configure_mpv_preferences(None, None, diagnostics)  # type: ignore[arg-type]
    properties = {
        spec.mpv_property
        for spec in SETTING_SPEC_REGISTRY.specs
        if spec.key is not SettingKey.GAMMA
    }

    sessions[0].emit_capabilities(
        MpvCapabilities(
            version="0.41.0",
            properties=frozenset(properties),
            commands=frozenset({"loadfile", "set"}),
        )
    )

    gamma_row = window.settings_panel.findChild(QWidget, "gammaEditorRow")
    assert gamma_row is not None
    assert not gamma_row.isEnabled()
    assert window.transport_controls.play_pause_button.isEnabled()
    assert sessions[0].shutdown_calls == 0
