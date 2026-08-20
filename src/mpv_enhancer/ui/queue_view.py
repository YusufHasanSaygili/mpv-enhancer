"""Queue view support for external Explorer file drops."""

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import (
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import QAbstractItemView, QListView, QStyle, QWidget

from mpv_enhancer.domain.models import QueueItem
from mpv_enhancer.ui.file_drop import ExternalFileDrop, parse_external_file_drop
from mpv_enhancer.ui.queue_model import QueueListModel


class QueueDropListView(QListView):
    """Accept supported local media URLs and insert them at the shown row."""

    dropMessage = Signal(str)

    def __init__(
        self,
        model: QueueListModel,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._queue_model = model
        self._insertion_row: int | None = None
        self.setObjectName("queueList")
        self.setAccessibleName("Playback queue")
        self.setModel(model)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    @property
    def insertion_row(self) -> int | None:
        """Return the row currently represented by the insertion indicator."""
        return self._insertion_row

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Accept URL drags so invalid entries can receive a clear result."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        """Track and repaint the insertion row while a URL drag moves."""
        if not event.mimeData().hasUrls():
            self._set_insertion_row(None)
            event.ignore()
            return
        self._set_insertion_row(self._insertion_row_at(event.position().toPoint()))
        event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        """Remove the insertion indicator when the pointer leaves the queue."""
        self._set_insertion_row(None)
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        """Insert every supported URL in order and report partial rejection."""
        if not event.mimeData().hasUrls():
            self._set_insertion_row(None)
            event.ignore()
            return

        insertion_row = self._insertion_row
        if insertion_row is None:
            insertion_row = self._insertion_row_at(event.position().toPoint())
        result = parse_external_file_drop(event.mimeData())
        self._insert_paths(insertion_row, result)
        self.dropMessage.emit(_drop_result_message(result))
        self._set_insertion_row(None)
        event.acceptProposedAction()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Paint a high-contrast horizontal marker at the pending insert row."""
        super().paintEvent(event)
        if self._insertion_row is None:
            return

        y_position = self._indicator_y(self._insertion_row)
        painter = QPainter(self.viewport())
        pen = QPen(
            self.palette().highlight().color(),
            self.style().pixelMetric(QStyle.PixelMetric.PM_DefaultFrameWidth) + 2,
        )
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(4, y_position, max(4, self.viewport().width() - 4), y_position)

    def _insert_paths(self, insertion_row: int, result: ExternalFileDrop) -> None:
        for offset, path in enumerate(result.accepted_paths):
            self._queue_model.insert_item(
                insertion_row + offset,
                QueueItem.create(path),
            )

    def _insertion_row_at(self, position: QPoint) -> int:
        index = self.indexAt(position)
        if not index.isValid():
            return self._queue_model.rowCount()
        rect = self.visualRect(index)
        return index.row() + int(position.y() > rect.center().y())

    def _indicator_y(self, insertion_row: int) -> int:
        row_count = self._queue_model.rowCount()
        if row_count == 0:
            return 2
        if insertion_row >= row_count:
            return min(
                self.viewport().height() - 2,
                self.visualRect(self._queue_model.index(row_count - 1, 0)).bottom() + 1,
            )
        return max(
            2,
            self.visualRect(self._queue_model.index(insertion_row, 0)).top(),
        )

    def _set_insertion_row(self, row: int | None) -> None:
        if row == self._insertion_row:
            return
        self._insertion_row = row
        self.viewport().update()


def _drop_result_message(result: ExternalFileDrop) -> str:
    added_count = len(result.accepted_paths)
    rejected_count = result.rejected_count
    added_label = "media file" if added_count == 1 else "media files"
    if rejected_count == 0:
        return f"Added {added_count} {added_label}."
    rejected_label = "item" if rejected_count == 1 else "items"
    return (
        f"Added {added_count} {added_label}; skipped {rejected_count} "
        f"unsupported or invalid {rejected_label}."
    )
