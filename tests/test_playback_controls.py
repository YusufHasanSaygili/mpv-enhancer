from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QSlider

from mpv_enhancer.domain.models import Playlist, QueueItem
from mpv_enhancer.domain.settings import EffectivePlaybackSettings
from mpv_enhancer.infrastructure.mpv.json_ipc import JsonValue, MpvIpcEvent
from mpv_enhancer.infrastructure.mpv.playback import (
    MpvJsonPlaybackAdapter,
    PlaybackEndKind,
    PlaybackEvent,
    PlaybackEventType,
)
from mpv_enhancer.ui.playback_controller import (
    PlaybackController,
    PlaybackPhase,
    PlaybackState,
)
from mpv_enhancer.ui.queue_model import QueueListModel
from mpv_enhancer.ui.transport_controls import TransportControls


class FakePlaybackAdapter:
    def __init__(self) -> None:
        self.loaded: list[Path] = []
        self.generations: list[int] = []
        self.paused: list[bool] = []
        self.seeks: list[float] = []
        self.stop_calls = 0
        self.settings: list[EffectivePlaybackSettings] = []
        self.listener: Callable[[str, JsonValue], None] | None = None
        self.event_listener: Callable[[PlaybackEvent], None] | None = None

    def begin_observing(
        self,
        listener: Callable[[str, JsonValue], None],
        event_listener: Callable[[PlaybackEvent], None],
    ) -> None:
        self.listener = listener
        self.event_listener = event_listener

    def load_file(self, path: Path, generation: int) -> None:
        self.loaded.append(path)
        self.generations.append(generation)

    def apply_settings(self, settings: EffectivePlaybackSettings) -> None:
        self.settings.append(settings)

    def set_paused(self, paused: bool) -> None:
        self.paused.append(paused)

    def seek_absolute(self, seconds: float) -> None:
        self.seeks.append(seconds)

    def stop(self) -> None:
        self.stop_calls += 1

    def emit(self, name: str, value: JsonValue) -> None:
        assert self.listener is not None
        self.listener(name, value)

    def emit_event(self, event: PlaybackEvent) -> None:
        assert self.event_listener is not None
        self.event_listener(event)


class FakeIpcClient:
    def __init__(self) -> None:
        self.commands: list[tuple[JsonValue, ...]] = []
        self.observers: list[tuple[str, Callable[[str, JsonValue], None]]] = []

    def request(self, command: Sequence[JsonValue]) -> object:
        self.commands.append(tuple(command))
        return object()

    def observe_property(
        self,
        name: str,
        listener: Callable[[str, JsonValue], None],
    ) -> object:
        self.observers.append((name, listener))
        return object()


def _item(name: str) -> QueueItem:
    return QueueItem.create(Path("synthetic") / name)


def test_controller_loads_and_navigates_queue_by_stable_current_identity() -> None:
    first = _item("episode one.mkv")
    second = _item("-episode 'two' 雪.mkv")
    third = _item("episode three.mkv")
    model = QueueListModel(Playlist((first, second, third)))
    adapter = FakePlaybackAdapter()
    controller = PlaybackController(model, adapter)

    assert controller.load_row(1)
    assert model.current_item_id == second.item_id
    assert adapter.loaded == [second.source_path]

    assert controller.next()
    assert model.current_item_id == third.item_id
    assert controller.previous()
    assert model.current_item_id == second.item_id
    assert adapter.loaded == [second.source_path, third.source_path, second.source_path]


def test_controller_maps_play_pause_seek_stop_and_property_progress() -> None:
    item = _item("episode.mkv")
    model = QueueListModel(Playlist((item,)))
    adapter = FakePlaybackAdapter()
    controller = PlaybackController(model, adapter)
    states: list[PlaybackState] = []
    controller.stateChanged.connect(states.append)
    assert controller.load_row(0)
    adapter.emit_event(
        PlaybackEvent(PlaybackEventType.FILE_LOADED, adapter.generations[-1])
    )

    adapter.emit("duration", 125.5)
    adapter.emit("time-pos", 30.25)
    adapter.emit("pause", True)
    controller.toggle_play_pause()
    controller.seek_absolute(999)
    controller.stop()

    assert adapter.paused == [False]
    assert adapter.seeks == [125.5]
    assert adapter.stop_calls == 1
    assert model.current_item_id is None
    assert any(state.duration_seconds == 125.5 for state in states)
    assert any(state.position_seconds == 30.25 for state in states)
    assert states[-1].phase is PlaybackPhase.STOPPED
    assert states[-1].generation == 2


def test_json_adapter_emits_safe_commands_and_observes_progress_properties() -> None:
    client = FakeIpcClient()
    adapter = MpvJsonPlaybackAdapter(client)

    def listener(_name: str, _value: JsonValue) -> None:
        pass

    def event_listener(_event: PlaybackEvent) -> None:
        pass

    adapter.begin_observing(listener, event_listener)
    adapter.load_file(Path("synthetic") / "- media 'snow' 雪.mkv", 7)
    adapter.set_paused(True)
    adapter.seek_absolute(42.5)
    adapter.stop()

    assert [name for name, _listener in client.observers] == [
        "duration",
        "time-pos",
        "pause",
    ]
    assert client.commands == [
        ("loadfile", "synthetic\\- media 'snow' 雪.mkv", "replace"),
        ("set_property", "pause", True),
        ("seek", 42.5, "absolute+exact"),
        ("stop",),
    ]


def test_transport_controls_render_progress_and_emit_user_requests(qtbot) -> None:
    controls = TransportControls()
    qtbot.addWidget(controls)
    play_pause = controls.findChild(QPushButton, "playPauseButton")
    previous = controls.findChild(QPushButton, "previousButton")
    next_button = controls.findChild(QPushButton, "nextButton")
    stop = controls.findChild(QPushButton, "stopButton")
    progress = controls.findChild(QSlider, "playbackProgress")
    time_label = controls.findChild(QLabel, "playbackTimeLabel")
    assert play_pause is not None
    assert previous is not None
    assert next_button is not None
    assert stop is not None
    assert progress is not None
    assert time_label is not None
    requests: list[str] = []
    controls.playPauseRequested.connect(lambda: requests.append("play-pause"))
    controls.previousRequested.connect(lambda: requests.append("previous"))
    controls.nextRequested.connect(lambda: requests.append("next"))
    controls.stopRequested.connect(lambda: requests.append("stop"))
    seeks: list[float] = []
    controls.seekRequested.connect(seeks.append)
    controls.apply_state(
        PlaybackState(paused=True, position_seconds=30.0, duration_seconds=125.0)
    )

    assert play_pause.text() == "Play"
    assert progress.maximum() == 125
    assert progress.value() == 30
    assert time_label.text() == "00:30 / 02:05"
    qtbot.mouseClick(play_pause, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(previous, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(next_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(stop, Qt.MouseButton.LeftButton)
    progress.setValue(45)
    progress.sliderReleased.emit()

    assert requests == ["play-pause", "previous", "next", "stop"]
    assert seeks == [45.0]


def test_stale_file_events_cannot_overwrite_or_advance_the_current_item() -> None:
    first = _item("first.mkv")
    second = _item("second.mkv")
    third = _item("third.mkv")
    model = QueueListModel(Playlist((first, second, third)))
    adapter = FakePlaybackAdapter()
    controller = PlaybackController(model, adapter)
    assert controller.load_row(0)
    first_generation = adapter.generations[-1]
    assert controller.next()
    second_generation = adapter.generations[-1]

    adapter.emit_event(PlaybackEvent(PlaybackEventType.FILE_LOADED, first_generation))
    adapter.emit_event(
        PlaybackEvent(
            PlaybackEventType.END_FILE,
            first_generation,
            PlaybackEndKind.EOF,
        )
    )

    assert model.current_item_id == second.item_id
    assert adapter.loaded == [first.source_path, second.source_path]
    assert controller.state.phase is PlaybackPhase.LOADING
    assert controller.state.generation == second_generation

    adapter.emit_event(PlaybackEvent(PlaybackEventType.FILE_LOADED, second_generation))
    adapter.emit_event(
        PlaybackEvent(
            PlaybackEventType.END_FILE,
            second_generation,
            PlaybackEndKind.EOF,
        )
    )

    assert model.current_item_id == third.item_id
    assert controller.state.phase is PlaybackPhase.LOADING
    third_generation = adapter.generations[-1]
    adapter.emit_event(PlaybackEvent(PlaybackEventType.FILE_LOADED, third_generation))
    adapter.emit_event(
        PlaybackEvent(
            PlaybackEventType.END_FILE,
            third_generation,
            PlaybackEndKind.ERROR,
        )
    )

    assert model.current_item_id == third.item_id
    assert controller.state.phase is PlaybackPhase.ERROR
    assert adapter.loaded == [
        first.source_path,
        second.source_path,
        third.source_path,
    ]


def test_json_adapter_maps_playlist_entries_to_load_generations_and_end_kinds() -> None:
    client = FakeIpcClient()
    adapter = MpvJsonPlaybackAdapter(client)
    events: list[PlaybackEvent] = []
    adapter.begin_observing(lambda _name, _value: None, events.append)
    adapter.load_file(Path("synthetic/first.mkv"), 11)
    adapter.load_file(Path("synthetic/second.mkv"), 12)

    adapter.handle_event(
        MpvIpcEvent("start-file", {"event": "start-file", "playlist_entry_id": 91})
    )
    adapter.handle_event(
        MpvIpcEvent(
            "file-loaded",
            {"event": "file-loaded"},
        )
    )
    adapter.handle_event(
        MpvIpcEvent(
            "end-file",
            {"event": "end-file", "playlist_entry_id": 91, "reason": "eof"},
        )
    )
    adapter.handle_event(
        MpvIpcEvent("start-file", {"event": "start-file", "playlist_entry_id": 92})
    )
    adapter.handle_event(
        MpvIpcEvent(
            "end-file",
            {
                "event": "end-file",
                "playlist_entry_id": 92,
                "reason": "error",
            },
        )
    )

    assert events == [
        PlaybackEvent(PlaybackEventType.FILE_LOADED, 11),
        PlaybackEvent(PlaybackEventType.END_FILE, 11, PlaybackEndKind.EOF),
        PlaybackEvent(PlaybackEventType.END_FILE, 12, PlaybackEndKind.ERROR),
    ]
