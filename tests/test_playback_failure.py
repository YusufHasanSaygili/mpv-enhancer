from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton

from mpv_enhancer.domain.models import Playlist, QueueItem
from mpv_enhancer.domain.settings import EffectivePlaybackSettings, VideoDimensions
from mpv_enhancer.infrastructure.mpv.json_ipc import JsonValue
from mpv_enhancer.infrastructure.mpv.playback import (
    PlaybackEndKind,
    PlaybackEvent,
    PlaybackEventType,
)
from mpv_enhancer.ui.playback_controller import PlaybackController, PlaybackPhase
from mpv_enhancer.ui.playback_failure import PlaybackFailurePanel
from mpv_enhancer.ui.queue_model import QueueListModel


class FailingPlaybackAdapter:
    def __init__(self) -> None:
        self.loaded: list[tuple[Path, int]] = []
        self.stop_calls = 0
        self.event_listener: Callable[[PlaybackEvent], None] | None = None

    def begin_observing(
        self,
        _property_listener: Callable[[str, JsonValue], None],
        event_listener: Callable[[PlaybackEvent], None],
    ) -> None:
        self.event_listener = event_listener

    def load_file(self, path: Path, generation: int) -> None:
        self.loaded.append((path, generation))

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
        self.stop_calls += 1

    def fail(self, generation: int) -> None:
        assert self.event_listener is not None
        self.event_listener(
            PlaybackEvent(
                PlaybackEventType.END_FILE,
                generation,
                PlaybackEndKind.ERROR,
            )
        )


def test_file_error_keeps_current_and_retry_uses_a_new_generation() -> None:
    item = QueueItem.create(Path("synthetic") / "private-looking-name.mkv")
    model = QueueListModel(Playlist((item,)))
    adapter = FailingPlaybackAdapter()
    controller = PlaybackController(model, adapter)
    failures: list[str] = []
    controller.failureOccurred.connect(failures.append)
    assert controller.load_row(0)
    first_generation = controller.state.generation

    adapter.fail(first_generation)

    assert controller.state.phase is PlaybackPhase.ERROR
    assert model.current_item_id == item.item_id
    assert failures == ["The file could not be played. Retry or stop playback."]
    assert "private-looking-name" not in failures[0]

    assert controller.retry_current()
    second_generation = controller.state.generation
    assert second_generation > first_generation
    assert adapter.loaded == [
        (item.source_path, first_generation),
        (item.source_path, second_generation),
    ]

    adapter.fail(second_generation)
    assert controller.stop()
    assert adapter.stop_calls == 1
    assert model.current_item_id is None


def test_failure_panel_exposes_english_retry_and_stop_actions(qtbot) -> None:
    panel = PlaybackFailurePanel()
    qtbot.addWidget(panel)
    retry = panel.findChild(QPushButton, "retryPlaybackButton")
    stop = panel.findChild(QPushButton, "stopFailedPlaybackButton")
    message = panel.findChild(QLabel, "playbackFailureMessage")
    assert retry is not None
    assert stop is not None
    assert message is not None
    actions: list[str] = []
    panel.retryRequested.connect(lambda: actions.append("retry"))
    panel.stopRequested.connect(lambda: actions.append("stop"))

    panel.show_failure("mpv stopped unexpectedly. Retry or stop playback.")

    assert panel.isVisible()
    assert message.text() == "mpv stopped unexpectedly. Retry or stop playback."
    assert retry.text() == "Retry"
    assert stop.text() == "Stop"
    qtbot.mouseClick(retry, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(stop, Qt.MouseButton.LeftButton)
    assert actions == ["retry", "stop"]

    panel.clear_failure()
    assert not panel.isVisible()
