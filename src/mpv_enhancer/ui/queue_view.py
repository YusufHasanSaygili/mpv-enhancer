"""Queue view support for external Explorer file drops."""

from collections.abc import Callable
from uuid import UUID

from PySide6.QtCore import (
    QItemSelection,
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    QRect,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QKeySequence,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from mpv_enhancer.domain.models import QueueItem
from mpv_enhancer.ui.file_drop import ExternalFileDrop, parse_external_file_drop
from mpv_enhancer.ui.queue_model import QUEUE_ITEM_MIME_TYPE, QueueListModel


class QueueDragHandleDelegate(QStyledItemDelegate):
    """Paint a compact three-line drag handle before each queue title."""

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        text_option = QStyleOptionViewItem(option)
        text_option.rect = text_option.rect.adjusted(24, 0, 0, 0)
        super().paint(painter, text_option, index)

        handle = QRect(option.rect.left() + 6, option.rect.center().y() - 5, 12, 10)
        painter.save()
        painter.setPen(QPen(option.palette.mid().color(), 2))
        for offset in (0, 5, 10):
            painter.drawLine(
                handle.left(),
                handle.top() + offset,
                handle.right(),
                handle.top() + offset,
            )
        painter.restore()


class QueueDropListView(QListView):
    """Accept supported local media URLs and insert them at the shown row."""

    dropMessage = Signal(str)
    selectionSummaryChanged = Signal(str)

    def __init__(
        self,
        model: QueueListModel,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._queue_model = model
        self._insertion_row: int | None = None
        self._move_handler: Callable[[int, int], None] | None = None
        self.setObjectName("queueList")
        self.setAccessibleName("Playback queue")
        self.setModel(model)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.selectionModel().selectionChanged.connect(self._selection_changed)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setItemDelegate(QueueDragHandleDelegate(self))
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

        move_up_action = QAction("Move queue item up", self)
        move_up_action.setShortcut(QKeySequence("Alt+Up"))
        move_up_action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        move_up_action.triggered.connect(self.move_current_up)
        self.addAction(move_up_action)

        move_down_action = QAction("Move queue item down", self)
        move_down_action.setShortcut(QKeySequence("Alt+Down"))
        move_down_action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        move_down_action.triggered.connect(self.move_current_down)
        self.addAction(move_down_action)

    @property
    def insertion_row(self) -> int | None:
        """Return the row currently represented by the insertion indicator."""
        return self._insertion_row

    @property
    def selected_item_ids(self) -> tuple[UUID, ...]:
        """Return selected UUIDs in current queue order."""
        rows = sorted(index.row() for index in self.selectionModel().selectedRows())
        return tuple(self._queue_model.items[row].item_id for row in rows)

    def select_item_ids(self, item_ids: tuple[UUID, ...]) -> None:
        """Replace the selection using stable identities in current row order."""
        selection_model = self.selectionModel()
        selection_model.clearSelection()
        selected_ids = set(item_ids)
        first_index = QModelIndex()
        for row, item in enumerate(self._queue_model.items):
            if item.item_id not in selected_ids:
                continue
            index = self._queue_model.index(row, 0)
            selection_model.select(
                index,
                selection_model.SelectionFlag.Select
                | selection_model.SelectionFlag.Rows,
            )
            if not first_index.isValid():
                first_index = index
        if first_index.isValid():
            selection_model.setCurrentIndex(
                first_index,
                selection_model.SelectionFlag.NoUpdate,
            )

    def set_move_handler(self, handler: Callable[[int, int], None]) -> None:
        """Route queue moves through an undo-aware application command handler."""
        self._move_handler = handler

    @property
    def selection_summary(self) -> str:
        """Return an English count suitable for the selected-items panel."""
        count = len(self.selected_item_ids)
        if count == 0:
            return "No queue items selected"
        if count == 1:
            return "1 queue item selected"
        return f"{count} queue items selected"

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Accept URL drags so invalid entries can receive a clear result."""
        if event.mimeData().hasFormat(QUEUE_ITEM_MIME_TYPE):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
        elif event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        """Track and repaint the insertion row while a URL drag moves."""
        if not (
            event.mimeData().hasUrls()
            or event.mimeData().hasFormat(QUEUE_ITEM_MIME_TYPE)
        ):
            self._set_insertion_row(None)
            event.ignore()
            return
        self._set_insertion_row(self._insertion_row_at(event.position().toPoint()))
        if event.mimeData().hasFormat(QUEUE_ITEM_MIME_TYPE):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
        else:
            event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        """Remove the insertion indicator when the pointer leaves the queue."""
        self._set_insertion_row(None)
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        """Insert every supported URL in order and report partial rejection."""
        if event.mimeData().hasFormat(QUEUE_ITEM_MIME_TYPE):
            insertion_row = self._insertion_row
            if insertion_row is None:
                insertion_row = self._insertion_row_at(event.position().toPoint())
            move = self._queue_model.resolve_internal_move(
                event.mimeData(),
                insertion_row,
                QModelIndex(),
            )
            self._set_insertion_row(None)
            if move is not None:
                self._perform_move(*move)
                event.setDropAction(Qt.DropAction.MoveAction)
                event.accept()
            else:
                event.ignore()
            return
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

    def move_current_up(self) -> None:
        """Move the current row up once, preserving its UUID and metadata."""
        self._move_current_by(-1)

    def move_current_down(self) -> None:
        """Move the current row down once, preserving its UUID and metadata."""
        self._move_current_by(1)

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

    def _move_current_by(self, offset: int) -> None:
        current = self.currentIndex()
        if not current.isValid():
            return
        destination = current.row() + offset
        if not 0 <= destination < self._queue_model.rowCount():
            return
        self._perform_move(current.row(), destination)
        self.setCurrentIndex(self._queue_model.index(destination, 0))

    def _perform_move(self, source_row: int, destination_row: int) -> None:
        if self._move_handler is None:
            self._queue_model.move_item(source_row, destination_row)
        else:
            self._move_handler(source_row, destination_row)

    def _selection_changed(
        self,
        _selected: QItemSelection,
        _deselected: QItemSelection,
    ) -> None:
        self.selectionSummaryChanged.emit(self.selection_summary)


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
