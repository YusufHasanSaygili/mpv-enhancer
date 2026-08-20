from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtWidgets import QDoubleSpinBox

from mpv_enhancer.domain.models import Playlist, QueueItem
from mpv_enhancer.domain.selection_settings import (
    SettingPatch,
    apply_selection_patch,
)
from mpv_enhancer.domain.settings import (
    EffectivePlaybackSettings,
    PlaybackSettings,
    SettingKey,
)
from mpv_enhancer.infrastructure.mpv.json_ipc import JsonValue
from mpv_enhancer.infrastructure.mpv.playback import MpvJsonPlaybackAdapter
from mpv_enhancer.infrastructure.mpv.settings_adapter import MpvSettingsAdapter
from mpv_enhancer.ui.main_window import MainWindow
from mpv_enhancer.ui.playback_controller import PlaybackController
from mpv_enhancer.ui.queue_model import QueueListModel


class RecordingIpcClient:
    def __init__(self) -> None:
        self.commands: list[tuple[JsonValue, ...]] = []

    def request(self, command: Sequence[JsonValue]) -> object:
        self.commands.append(tuple(command))
        return object()

    def observe_property(
        self,
        _name: str,
        _listener: Callable[[str, JsonValue], None],
    ) -> object:
        return object()


def _item(name: str, overrides: PlaybackSettings | None = None) -> QueueItem:
    return QueueItem.create(Path("synthetic") / name, overrides=overrides)


def test_settings_adapter_resets_then_applies_only_allowlisted_properties() -> None:
    client = RecordingIpcClient()
    adapter = MpvSettingsAdapter(client)

    adapter.apply(
        EffectivePlaybackSettings(
            speed=1.2,
            panscan=0.75,
            volume=80.0,
            mute=True,
            subtitle_visibility=False,
        )
    )

    assert client.commands == [
        ("set_property", "speed", 1.0),
        ("set_property", "panscan", 0.0),
        ("set_property", "volume", 100.0),
        ("set_property", "mute", False),
        ("set_property", "sub-visibility", True),
        ("set_property", "speed", 1.2),
        ("set_property", "panscan", 0.75),
        ("set_property", "volume", 80.0),
        ("set_property", "mute", True),
        ("set_property", "sub-visibility", False),
    ]


def test_controller_applies_settings_before_load_without_next_episode_leak() -> None:
    first = _item(
        "episode-01.mkv",
        PlaybackSettings(speed=1.2, panscan=1.0, mute=True),
    )
    second = _item("episode-02.mkv")
    model = QueueListModel(
        Playlist((first, second), defaults=PlaybackSettings(volume=85.0))
    )
    client = RecordingIpcClient()
    controller = PlaybackController(model, MpvJsonPlaybackAdapter(client))

    assert controller.load_row(0)
    assert controller.next()

    first_load = client.commands.index(
        ("loadfile", "synthetic\\episode-01.mkv", "replace")
    )
    second_load = client.commands.index(
        ("loadfile", "synthetic\\episode-02.mkv", "replace")
    )
    assert first_load == 10
    assert second_load == 21
    assert client.commands[16:21] == [
        ("set_property", "speed", 1.0),
        ("set_property", "panscan", 0.0),
        ("set_property", "volume", 85.0),
        ("set_property", "mute", False),
        ("set_property", "sub-visibility", True),
    ]


def test_current_item_setting_changes_are_applied_live_without_reload() -> None:
    item = _item("episode-01.mkv")
    model = QueueListModel(Playlist((item,)))
    client = RecordingIpcClient()
    controller = PlaybackController(model, MpvJsonPlaybackAdapter(client))
    assert controller.load_row(0)
    before_live_update = len(client.commands)
    updated = apply_selection_patch(
        model.items,
        (item.item_id,),
        SettingPatch(SettingKey.SPEED, 1.5),
    )
    model.replace_items(updated, item.item_id)

    assert controller.refresh_current_settings()
    assert len(client.commands) == before_live_update + 10
    assert client.commands[-5:] == [
        ("set_property", "speed", 1.5),
        ("set_property", "panscan", 0.0),
        ("set_property", "volume", 100.0),
        ("set_property", "mute", False),
        ("set_property", "sub-visibility", True),
    ]


def test_panel_patch_updates_only_selected_queue_items(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    first = _item("episode-01.mkv")
    second = _item("episode-02.mkv")
    window.queue_model.insert_item(0, first)
    window.queue_model.insert_item(1, second)
    window.queue_view.select_item_ids((second.item_id,))
    speed = window.settings_panel.findChild(QDoubleSpinBox, "speedControl")
    assert speed is not None

    speed.setValue(1.2)

    assert window.queue_model.items[0].overrides == PlaybackSettings()
    assert window.queue_model.items[1].overrides == PlaybackSettings(speed=1.2)
    assert window.queue_view.selected_item_ids == (second.item_id,)
