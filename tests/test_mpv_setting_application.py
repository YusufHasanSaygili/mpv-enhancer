from collections.abc import Callable, Sequence
from concurrent.futures import Future
from pathlib import Path

from PySide6.QtWidgets import QDoubleSpinBox

from mpv_enhancer.domain.models import Playlist, QueueItem
from mpv_enhancer.domain.selection_settings import (
    SettingPatch,
    apply_selection_patch,
    reset_selection_setting,
)
from mpv_enhancer.domain.settings import (
    EffectivePlaybackSettings,
    LanguagePreferences,
    PlaybackSettings,
    SettingKey,
    TrackSelection,
)
from mpv_enhancer.infrastructure.mpv.json_ipc import (
    JsonValue,
    MpvIpcEvent,
    MpvIpcRequest,
)
from mpv_enhancer.infrastructure.mpv.playback import MpvJsonPlaybackAdapter
from mpv_enhancer.infrastructure.mpv.settings_adapter import MpvSettingsAdapter
from mpv_enhancer.ui.main_window import MainWindow
from mpv_enhancer.ui.playback_controller import PlaybackController
from mpv_enhancer.ui.queue_model import QueueListModel


class RecordingIpcClient:
    def __init__(self) -> None:
        self.commands: list[tuple[JsonValue, ...]] = []
        self.observers: list[tuple[str, Callable[[str, JsonValue], None]]] = []
        self.track_list_futures: list[Future[JsonValue]] = []
        self._next_request_id = 1

    def request(self, command: Sequence[JsonValue]) -> MpvIpcRequest:
        self.commands.append(tuple(command))
        future: Future[JsonValue] = Future()
        if tuple(command) == ("get_property", "track-list"):
            self.track_list_futures.append(future)
        else:
            future.set_result(None)
        request = MpvIpcRequest(self._next_request_id, future)
        self._next_request_id += 1
        return request

    def observe_property(
        self,
        name: str,
        listener: Callable[[str, JsonValue], None],
    ) -> object:
        self.observers.append((name, listener))
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
            subtitle_languages=LanguagePreferences.parse("tr,tur,en"),
            audio_languages=LanguagePreferences.parse("es,spa,en"),
            subtitle_track=TrackSelection.specific(7),
            audio_track=TrackSelection.off(),
            subtitle_delay=1.25,
            audio_delay=-0.5,
        )
    )

    assert client.commands == [
        ("set_property", "speed", 1.0),
        ("set_property", "panscan", 0.0),
        ("set_property", "video-aspect-override", "no"),
        ("set_property", "video-crop", ""),
        ("set_property", "volume", 100.0),
        ("set_property", "mute", False),
        ("set_property", "sub-visibility", True),
        ("set_property", "slang", ""),
        ("set_property", "alang", ""),
        ("set_property", "sid", "auto"),
        ("set_property", "aid", "auto"),
        ("set_property", "sub-delay", 0.0),
        ("set_property", "audio-delay", 0.0),
        ("set_property", "speed", 1.2),
        ("set_property", "panscan", 0.75),
        ("set_property", "video-aspect-override", "no"),
        ("set_property", "volume", 80.0),
        ("set_property", "mute", True),
        ("set_property", "sub-visibility", False),
        ("set_property", "slang", "tr,tur,en"),
        ("set_property", "alang", "es,spa,en"),
        ("set_property", "sid", 7),
        ("set_property", "aid", "no"),
        ("set_property", "sub-delay", 1.25),
        ("set_property", "audio-delay", -0.5),
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
    assert first_load == 25
    assert second_load == 51
    assert client.commands[39:51] == [
        ("set_property", "speed", 1.0),
        ("set_property", "panscan", 0.0),
        ("set_property", "video-aspect-override", "no"),
        ("set_property", "volume", 85.0),
        ("set_property", "mute", False),
        ("set_property", "sub-visibility", True),
        ("set_property", "slang", ""),
        ("set_property", "alang", ""),
        ("set_property", "sid", "auto"),
        ("set_property", "aid", "auto"),
        ("set_property", "sub-delay", 0.0),
        ("set_property", "audio-delay", 0.0),
    ]


def test_track_resolution_never_reuses_the_prior_loads_explicit_track_id() -> None:
    client = RecordingIpcClient()
    adapter = MpvJsonPlaybackAdapter(client)
    adapter.begin_observing(lambda _name, _value: None, lambda _event: None)
    first = EffectivePlaybackSettings(
        speed=1.0,
        panscan=0.0,
        volume=100.0,
        mute=False,
        subtitle_visibility=True,
        subtitle_track=TrackSelection.specific(7),
    )
    second = EffectivePlaybackSettings(
        speed=1.0,
        panscan=0.0,
        volume=100.0,
        mute=False,
        subtitle_visibility=True,
        subtitle_languages=LanguagePreferences.parse("es,spa,en"),
    )

    adapter.apply_settings(first)
    adapter.load_file(Path("synthetic/episode-06.mkv"), 1)
    adapter.handle_event(MpvIpcEvent("start-file", {"playlist_entry_id": 61}))
    adapter.handle_event(MpvIpcEvent("file-loaded", {"playlist_entry_id": 61}))
    second_load_start = len(client.commands)
    adapter.apply_settings(second)
    adapter.load_file(Path("synthetic/episode-07.mkv"), 2)
    adapter.handle_event(MpvIpcEvent("start-file", {"playlist_entry_id": 62}))
    adapter.handle_event(MpvIpcEvent("file-loaded", {"playlist_entry_id": 62}))
    client.track_list_futures[0].set_result([{"type": "sub", "id": 7, "lang": "tr"}])
    client.track_list_futures[1].set_result([{"type": "sub", "id": 2, "lang": "en"}])

    second_load_commands = client.commands[second_load_start:]
    assert ("set_property", "sid", "auto") in second_load_commands
    assert ("set_property", "sid", 2) in second_load_commands
    assert ("set_property", "sid", 7) not in second_load_commands


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
    assert len(client.commands) == before_live_update + 25
    assert client.commands[-12:] == [
        ("set_property", "speed", 1.5),
        ("set_property", "panscan", 0.0),
        ("set_property", "video-aspect-override", "no"),
        ("set_property", "volume", 100.0),
        ("set_property", "mute", False),
        ("set_property", "sub-visibility", True),
        ("set_property", "slang", ""),
        ("set_property", "alang", ""),
        ("set_property", "sid", "auto"),
        ("set_property", "aid", "auto"),
        ("set_property", "sub-delay", 0.0),
        ("set_property", "audio-delay", 0.0),
    ]


def test_visibility_and_signed_delays_update_and_reset_independently_live() -> None:
    item = _item("episode-01.mkv")
    model = QueueListModel(Playlist((item,)))
    client = RecordingIpcClient()
    controller = PlaybackController(model, MpvJsonPlaybackAdapter(client))
    assert controller.load_row(0)
    updated = apply_selection_patch(
        model.items,
        (item.item_id,),
        SettingPatch(SettingKey.SUBTITLE_VISIBILITY, False),
    )
    updated = apply_selection_patch(
        updated,
        (item.item_id,),
        SettingPatch(SettingKey.SUBTITLE_DELAY, -2.25),
    )
    updated = apply_selection_patch(
        updated,
        (item.item_id,),
        SettingPatch(SettingKey.AUDIO_DELAY, 1.5),
    )
    model.replace_items(updated, item.item_id)

    assert controller.refresh_current_settings()
    assert client.commands[-12:] == [
        ("set_property", "speed", 1.0),
        ("set_property", "panscan", 0.0),
        ("set_property", "video-aspect-override", "no"),
        ("set_property", "volume", 100.0),
        ("set_property", "mute", False),
        ("set_property", "sub-visibility", False),
        ("set_property", "slang", ""),
        ("set_property", "alang", ""),
        ("set_property", "sid", "auto"),
        ("set_property", "aid", "auto"),
        ("set_property", "sub-delay", -2.25),
        ("set_property", "audio-delay", 1.5),
    ]

    reset = reset_selection_setting(
        model.items,
        (item.item_id,),
        SettingKey.SUBTITLE_DELAY,
    )
    model.replace_items(reset, item.item_id)

    assert controller.refresh_current_settings()
    assert client.commands[-2:] == [
        ("set_property", "sub-delay", 0.0),
        ("set_property", "audio-delay", 1.5),
    ]
    assert model.items[0].overrides == PlaybackSettings(
        subtitle_visibility=False,
        audio_delay=1.5,
    )


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
