"""Smoke-test the installed application, queue, and optional real playback."""

import argparse
import time
import wave
from collections.abc import Callable, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication, QDoubleSpinBox

from mpv_enhancer.app import create_application
from mpv_enhancer.domain.models import Playlist, QueueItem
from mpv_enhancer.domain.selection_settings import SelectedSettingState
from mpv_enhancer.domain.settings import (
    SETTING_SPEC_REGISTRY,
    PlaybackSettings,
    SettingKey,
)
from mpv_enhancer.infrastructure.mpv.discovery import (
    MpvDiagnostics,
    MpvDiagnosticsStatus,
    MpvDiscoverySource,
)
from mpv_enhancer.infrastructure.mpv.json_ipc import JsonValue
from mpv_enhancer.infrastructure.mpv.playback import MpvJsonPlaybackAdapter
from mpv_enhancer.ui.main_window import MainWindow
from mpv_enhancer.ui.playback_controller import PlaybackController
from mpv_enhancer.ui.queue_model import QueueListModel

QUEUE_SMOKE_FILE_COUNT = 20
QUEUE_SMOKE_EXTENSIONS = (".mkv", ".mp4", ".mp3", ".webm", ".flac")
SETTING_SMOKE_SELECTED_EPISODES = (2, 4, 6)


class _RecordingIpcClient:
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


def main(argv: Sequence[str] | None = None) -> int:
    """Return success when the installed queue and requested playback pass."""
    arguments = _parse_arguments(argv)
    app = create_application(["mpv-enhancer-release-smoke"])
    window = MainWindow()
    try:
        window.show()
        app.processEvents()
        if not window.isVisible():
            raise RuntimeError("The MPV Enhancer release shell did not become visible.")
        _verify_queue_workflow(window)
        _verify_no_leak_playback_settings()
        if arguments.mpv is not None:
            _verify_playback_workflow(app, window, arguments.mpv)
    finally:
        window.close()
        app.processEvents()
    if window.isVisible():
        raise RuntimeError("The MPV Enhancer release shell did not close cleanly.")
    result = (
        "Installed MPV Enhancer passed the 20-file queue, episodes 2/4/6 "
        "multi-edit, mixed-state, and no-leak settings workflows."
    )
    if arguments.mpv is not None:
        result += " Embedded local playback with a Unicode leading-hyphen path passed."
    print(result)
    return 0


def _verify_queue_workflow(window: MainWindow) -> None:
    with TemporaryDirectory(prefix="mpv-enhancer-release-smoke-") as directory:
        root = Path(directory)
        paths = tuple(
            root
            / (
                f"episode-{number:02}"
                f"{QUEUE_SMOKE_EXTENSIONS[(number - 1) % len(QUEUE_SMOKE_EXTENSIONS)]}"
            )
            for number in range(1, QUEUE_SMOKE_FILE_COUNT + 1)
        )
        for path in paths:
            path.touch()

        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
        drop_event = QDropEvent(
            QPointF(8, 8),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        window.queue_view.dropEvent(drop_event)
        if not drop_event.isAccepted():
            raise RuntimeError("The release queue rejected supported local files.")
        if tuple(item.source_path for item in window.queue_model.items) != paths:
            raise RuntimeError("The release queue did not preserve the drop order.")

        original_items = window.queue_model.items
        item_ids = tuple(item.item_id for item in original_items)
        window.queue_view.select_item_ids(item_ids)
        if window.queue_view.selected_item_ids != item_ids:
            raise RuntimeError("The release queue did not select all 20 identities.")

        first_item = original_items[0]
        window.queue_controller.move_item(0, QUEUE_SMOKE_FILE_COUNT - 1)
        moved_item = window.queue_model.items[-1]
        if moved_item is not first_item or moved_item.item_id != first_item.item_id:
            raise RuntimeError("Queue reorder changed item identity or metadata.")

        window.queue_controller.undo_stack.undo()
        if window.queue_model.items != original_items:
            raise RuntimeError("Queue undo did not restore the exact original order.")
        if window.queue_view.selected_item_ids != item_ids:
            raise RuntimeError("Queue undo did not restore the full selection.")
        _verify_multi_item_settings(window, original_items)


def _verify_multi_item_settings(
    window: MainWindow,
    original_items: tuple[QueueItem, ...],
) -> None:
    selected_ids = tuple(
        original_items[episode - 1].item_id
        for episode in SETTING_SMOKE_SELECTED_EPISODES
    )
    window.queue_view.select_item_ids(selected_ids)
    speed = window.settings_panel.findChild(QDoubleSpinBox, "speedControl")
    panscan = window.settings_panel.findChild(QDoubleSpinBox, "panscanControl")
    if speed is None or panscan is None:
        raise RuntimeError("The installed settings controls were not available.")
    speed.setValue(1.2)
    window.queue_view.select_item_ids((original_items[3].item_id,))
    panscan.setValue(0.75)

    for episode, item in enumerate(window.queue_model.items, start=1):
        expected_speed = 1.2 if episode in SETTING_SMOKE_SELECTED_EPISODES else None
        expected_panscan = 0.75 if episode == 4 else None
        if item.overrides.speed != expected_speed:
            raise RuntimeError("Multi-edit changed speed on an unintended episode.")
        if item.overrides.panscan != expected_panscan:
            raise RuntimeError("Multi-edit changed pan-and-scan unexpectedly.")

    window.queue_view.select_item_ids(selected_ids)
    if (
        window.settings_panel.state_for(SettingKey.SPEED).value != 1.2
        or window.settings_panel.state_for(SettingKey.PANSCAN).state
        is not SelectedSettingState.MIXED
    ):
        raise RuntimeError("The installed multi-edit controls lost their state.")


def _verify_no_leak_playback_settings() -> None:
    first = QueueItem.create(
        Path("synthetic/episode-01.mkv"),
        overrides=PlaybackSettings(speed=1.2, panscan=1.0),
    )
    second = QueueItem.create(Path("synthetic/episode-02.mkv"))
    model = QueueListModel(Playlist((first, second)))
    client = _RecordingIpcClient()
    controller = PlaybackController(model, MpvJsonPlaybackAdapter(client))
    if not controller.load_row(0) or not controller.next():
        raise RuntimeError("The no-leak playback queue did not advance.")

    load_indexes = [
        index
        for index, command in enumerate(client.commands)
        if command and command[0] == "loadfile"
    ]
    managed_count = len(SETTING_SPEC_REGISTRY.specs)
    if load_indexes != [managed_count * 2, managed_count * 4 + 1]:
        raise RuntimeError("Effective settings were not applied before every load.")
    if client.commands[load_indexes[1] - managed_count : load_indexes[1]] != [
        ("set_property", "speed", 1.0),
        ("set_property", "panscan", 0.0),
        ("set_property", "volume", 100.0),
        ("set_property", "mute", False),
        ("set_property", "sub-visibility", True),
        ("set_property", "slang", ""),
        ("set_property", "alang", ""),
        ("set_property", "sid", "auto"),
        ("set_property", "aid", "auto"),
        ("set_property", "sub-delay", 0.0),
        ("set_property", "audio-delay", 0.0),
    ]:
        raise RuntimeError("Managed settings leaked into the next episode.")


def _verify_playback_workflow(
    app: QApplication,
    window: MainWindow,
    executable: Path,
) -> None:
    with TemporaryDirectory(prefix="mpv-enhancer-playback-smoke-") as directory:
        media_path = Path(directory) / "- snow's 雪.wav"
        _write_silent_wav(media_path)
        diagnostics = MpvDiagnostics(
            status=MpvDiagnosticsStatus.AVAILABLE,
            source=MpvDiscoverySource.SELECTED,
            executable=executable.resolve(),
            version="release-smoke",
            message="mpv is ready.",
        )
        window.configure_mpv_preferences(None, None, diagnostics)  # type: ignore[arg-type]
        item = QueueItem.create(media_path)
        row = len(window.queue_model.items)
        window.queue_model.insert_item(row, item)
        window.queue_view.setCurrentIndex(window.queue_model.index(row, 0))
        window.transport_controls.play_pause_button.click()
        _wait_for(app, lambda: window.queue_model.current_item_id == item.item_id)
        _wait_for(app, lambda: window.transport_controls.progress_slider.maximum() >= 3)
        window.transport_controls.stop_button.click()
        _wait_for(app, lambda: window.queue_model.current_item_id is None)


def _write_silent_wav(path: Path) -> None:
    sample_rate = 8_000
    duration_seconds = 4
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(b"\0\0" * sample_rate * duration_seconds)


def _wait_for(
    app: QApplication,
    predicate: Callable[[], bool],
    timeout_seconds: float = 10.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.025)
    raise RuntimeError("The release playback smoke test timed out.")


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mpv", type=Path)
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
