"""Smoke-test the installed application and its released queue workflow."""

from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent

from mpv_enhancer.app import create_application
from mpv_enhancer.ui.main_window import MainWindow

QUEUE_SMOKE_FILE_COUNT = 20
QUEUE_SMOKE_EXTENSIONS = (".mkv", ".mp4", ".mp3", ".webm", ".flac")


def main() -> int:
    """Return success when the installed shell and 20-file queue flow pass."""
    app = create_application(["mpv-enhancer-release-smoke"])
    window = MainWindow()
    window.show()
    app.processEvents()
    if not window.isVisible():
        raise RuntimeError("The MPV Enhancer release shell did not become visible.")
    _verify_queue_workflow(window)
    window.close()
    app.processEvents()
    if window.isVisible():
        raise RuntimeError("The MPV Enhancer release shell did not close cleanly.")
    print(
        "Installed MPV Enhancer accepted, selected, reordered, and restored "
        f"{QUEUE_SMOKE_FILE_COUNT} media files."
    )
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


if __name__ == "__main__":
    raise SystemExit(main())
