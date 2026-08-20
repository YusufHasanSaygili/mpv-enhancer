import ctypes
import json
from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtWidgets import QLabel, QMainWindow

from mpv_enhancer.infrastructure.mpv.discovery import (
    MpvDiagnostics,
    MpvDiagnosticsStatus,
    MpvDiscoverySource,
)
from mpv_enhancer.infrastructure.mpv.embedded import (
    EmbeddedMpvSession,
    build_embedded_mpv_arguments,
)
from mpv_enhancer.infrastructure.mpv.json_ipc import JsonValue
from mpv_enhancer.infrastructure.mpv.pipe_transport import (
    NamedPipeCallbacks,
    PipeTransportState,
)
from mpv_enhancer.infrastructure.mpv.playback import PlaybackEvent
from mpv_enhancer.ui.main_window import MainWindow
from mpv_enhancer.ui.video_host import VideoHost


class FakeProcessSupervisor:
    def __init__(self, *, starts: bool = True) -> None:
        self.starts = starts
        self.start_calls: list[tuple[Path, tuple[str, ...]]] = []
        self.stop_calls = 0

    def start(self, executable: Path, arguments: Sequence[str]) -> bool:
        self.start_calls.append((executable, tuple(arguments)))
        return self.starts

    def stop(self) -> bool:
        self.stop_calls += 1
        return True


class FakePipeTransport:
    def __init__(self, callbacks: NamedPipeCallbacks) -> None:
        self.callbacks = callbacks
        self.pipe_name = r"\\.\pipe\mpv-enhancer-00000000000000000000000000000000"
        self.start_calls = 0
        self.stop_calls: list[int] = []
        self.sent: list[bytes] = []

    def start(self) -> None:
        self.start_calls += 1

    def send(self, payload: bytes) -> None:
        self.sent.append(payload)

    def stop(self, timeout_ms: int = 3_000) -> bool:
        self.stop_calls.append(timeout_ms)
        return True


class FakePlaybackSession:
    def __init__(self, host_hwnd: int) -> None:
        self.host_hwnd = host_hwnd
        self.started_with: list[Path] = []
        self.shutdown_calls = 0
        self.playback_adapter = NoopPlaybackAdapter()
        self.failure_listener: Callable[[str], None] | None = None
        self.recovered_listener: Callable[[], None] | None = None

    def start(self, executable: Path) -> bool:
        self.started_with.append(executable)
        return True

    def shutdown(self) -> bool:
        self.shutdown_calls += 1
        return True

    def set_failure_listener(self, listener: Callable[[str], None]) -> None:
        self.failure_listener = listener

    def set_recovered_listener(self, listener: Callable[[], None]) -> None:
        self.recovered_listener = listener

    def emit_failure(self, message: str) -> None:
        assert self.failure_listener is not None
        self.failure_listener(message)


class NoopPlaybackAdapter:
    def begin_observing(
        self,
        _listener: Callable[[str, JsonValue], None],
        _event_listener: Callable[[PlaybackEvent], None],
    ) -> None:
        pass

    def load_file(self, _path: Path, _generation: int) -> None:
        pass

    def set_paused(self, _paused: bool) -> None:
        pass

    def seek_absolute(self, _seconds: float) -> None:
        pass

    def stop(self) -> None:
        pass


def test_video_host_keeps_one_native_handle_through_window_transitions(qtbot) -> None:
    window = QMainWindow()
    host = VideoHost()
    window.setCentralWidget(host)
    qtbot.addWidget(window)
    window.show()
    original_handle = host.native_handle

    window.resize(1_100, 680)
    window.showMinimized()
    window.showNormal()
    window.showFullScreen()
    window.showNormal()

    assert host.native_handle == original_handle
    assert original_handle == ctypes.c_uint32(original_handle).value
    assert host.testAttribute(host.native_window_attribute)


def test_embedded_arguments_use_the_stable_handle_and_unique_pipe() -> None:
    pipe_name = r"\\.\pipe\mpv-enhancer-0123456789abcdef0123456789abcdef"

    arguments = build_embedded_mpv_arguments(0x1_0000_0001, pipe_name)

    assert "--wid=1" in arguments
    assert f"--input-ipc-server={pipe_name}" in arguments
    assert "--no-config" in arguments
    assert "--idle=yes" in arguments
    assert "--input-default-bindings=no" in arguments
    assert all(";" not in argument for argument in arguments)


def test_embedded_session_starts_transport_only_after_the_owned_process() -> None:
    supervisor = FakeProcessSupervisor()
    transports: list[FakePipeTransport] = []

    def create_transport(callbacks: NamedPipeCallbacks) -> FakePipeTransport:
        transport = FakePipeTransport(callbacks)
        transports.append(transport)
        return transport

    session = EmbeddedMpvSession(
        321,
        process_supervisor=supervisor,
        transport_factory=create_transport,
    )

    assert session.start(Path("C:/Tools/mpv.exe"))
    assert len(supervisor.start_calls) == 1
    assert "--wid=321" in supervisor.start_calls[0][1]
    assert transports[0].start_calls == 1

    assert session.shutdown()
    assert transports[0].stop_calls == [3_000]
    assert supervisor.stop_calls == 1


def test_main_window_owns_embedded_session_and_full_screen_lifecycle(qtbot) -> None:
    sessions: list[FakePlaybackSession] = []

    def create_session(host_hwnd: int) -> FakePlaybackSession:
        session = FakePlaybackSession(host_hwnd)
        sessions.append(session)
        return session

    window = MainWindow(playback_session_factory=create_session)
    qtbot.addWidget(window)
    window.show()
    diagnostics = MpvDiagnostics(
        status=MpvDiagnosticsStatus.AVAILABLE,
        source=MpvDiscoverySource.SELECTED,
        executable=Path("C:/Tools/mpv.exe"),
        version="0.41.0",
        message="mpv is ready.",
    )
    window.configure_mpv_preferences(
        preference_store=None,
        discovery=None,
        diagnostics=diagnostics,
    )
    original_handle = window.video_host.native_handle

    window.toggle_full_screen()
    assert window.isFullScreen()
    assert window.video_host.native_handle == original_handle
    window.toggle_full_screen()

    assert not window.isFullScreen()
    assert sessions[0].host_hwnd == original_handle
    assert sessions[0].started_with == [Path("C:/Tools/mpv.exe")]

    sessions[0].emit_failure(
        "mpv stopped unexpectedly and restarted. Retry or stop playback."
    )
    failure_message = window.findChild(QLabel, "playbackFailureMessage")
    assert failure_message is not None
    assert failure_message.isVisible()
    assert "Retry or stop playback" in failure_message.text()

    window.close()
    assert sessions[0].shutdown_calls == 1


def test_embedded_session_reports_disconnect_and_restores_observations() -> None:
    supervisor = FakeProcessSupervisor()
    transports: list[FakePipeTransport] = []

    def create_transport(callbacks: NamedPipeCallbacks) -> FakePipeTransport:
        transport = FakePipeTransport(callbacks)
        transports.append(transport)
        return transport

    session = EmbeddedMpvSession(
        654,
        process_supervisor=supervisor,
        transport_factory=create_transport,
    )
    failures: list[str] = []
    recoveries: list[str] = []
    session.set_failure_listener(failures.append)
    session.set_recovered_listener(lambda: recoveries.append("recovered"))
    session.playback_adapter.begin_observing(
        lambda _name, _value: None,
        lambda _event: None,
    )
    assert session.start(Path("C:/Tools/mpv.exe"))
    transport = transports[0]

    transport.callbacks.state_changed(PipeTransportState.CONNECTED)
    transport.callbacks.state_changed(PipeTransportState.DISCONNECTED)
    transport.callbacks.state_changed(PipeTransportState.CONNECTED)
    recovery_probe = json.loads(transport.sent[-1])
    transport.callbacks.data_received(
        json.dumps(
            {
                "request_id": recovery_probe["request_id"],
                "error": "success",
                "data": "synthetic-version",
            }
        ).encode()
        + b"\n"
    )

    assert failures == ["Playback connection was lost. Retry or stop playback."]
    assert recoveries == ["recovered"]
    assert len(transport.sent) == 7
    assert session.shutdown()
