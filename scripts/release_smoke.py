"""Smoke-test the installed application, queue, and optional real playback."""

import argparse
import time
import wave
from collections.abc import Callable, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication

from mpv_enhancer.app import create_application
from mpv_enhancer.domain.models import QueueItem
from mpv_enhancer.infrastructure.mpv.discovery import (
    MpvDiagnostics,
    MpvDiagnosticsStatus,
    MpvDiscoverySource,
)
from mpv_enhancer.ui.main_window import MainWindow

QUEUE_SMOKE_FILE_COUNT = 20
QUEUE_SMOKE_EXTENSIONS = (".mkv", ".mp4", ".mp3", ".webm", ".flac")


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
        if arguments.mpv is not None:
            _verify_playback_workflow(app, window, arguments.mpv)
    finally:
        window.close()
        app.processEvents()
    if window.isVisible():
        raise RuntimeError("The MPV Enhancer release shell did not close cleanly.")
    result = (
        "Installed MPV Enhancer accepted, selected, reordered, and restored "
        f"{QUEUE_SMOKE_FILE_COUNT} media files."
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
