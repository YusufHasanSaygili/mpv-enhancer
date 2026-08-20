from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QSlider

from mpv_enhancer.domain.models import Playlist, QueueItem
from mpv_enhancer.infrastructure.mpv.json_ipc import JsonValue
from mpv_enhancer.infrastructure.mpv.playback import MpvJsonPlaybackAdapter
from mpv_enhancer.ui.playback_controller import PlaybackController, PlaybackState
from mpv_enhancer.ui.queue_model import QueueListModel
from mpv_enhancer.ui.transport_controls import TransportControls


class FakePlaybackAdapter:
    def __init__(self) -> None:
        self.loaded: list[Path] = []
        self.paused: list[bool] = []
        self.seeks: list[float] = []
        self.stop_calls = 0
        self.listener: Callable[[str, JsonValue], None] | None = None

    def begin_observing(
        self,
        listener: Callable[[str, JsonValue], None],
    ) -> None:
        self.listener = listener

    def load_file(self, path: Path) -> None:
        self.loaded.append(path)

    def set_paused(self, paused: bool) -> None:
        self.paused.append(paused)

    def seek_absolute(self, seconds: float) -> None:
        self.seeks.append(seconds)

    def stop(self) -> None:
        self.stop_calls += 1

    def emit(self, name: str, value: JsonValue) -> None:
        assert self.listener is not None
        self.listener(name, value)


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
    assert states[-1] == PlaybackState()


def test_json_adapter_emits_safe_commands_and_observes_progress_properties() -> None:
    client = FakeIpcClient()
    adapter = MpvJsonPlaybackAdapter(client)

    def listener(_name: str, _value: JsonValue) -> None:
        pass

    adapter.begin_observing(listener)
    adapter.load_file(Path("synthetic") / "- media 'snow' 雪.mkv")
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
