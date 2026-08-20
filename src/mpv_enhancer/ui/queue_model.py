"""Qt list model adapter for the ordered queue domain."""

from enum import IntEnum
from uuid import UUID

from PySide6.QtCore import (
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
)

from mpv_enhancer.domain.models import Playlist, QueueItem


class QueueRole(IntEnum):
    """Stable custom roles exposed by the queue list model."""

    ItemId = int(Qt.ItemDataRole.UserRole) + 1
    SourcePath = int(Qt.ItemDataRole.UserRole) + 2
    DisplayTitle = int(Qt.ItemDataRole.UserRole) + 3
    IsCurrent = int(Qt.ItemDataRole.UserRole) + 4


INVALID_INDEX = QModelIndex()


class QueueListModel(QAbstractListModel):
    """Expose a Playlist through Qt model notifications and read-only roles."""

    def __init__(self, playlist: Playlist | None = None) -> None:
        super().__init__()
        self._playlist = playlist if playlist is not None else Playlist()
        self._current_item_id: UUID | None = None

    @property
    def items(self) -> tuple[QueueItem, ...]:
        """Return the domain items in their current model order."""
        return self._playlist.items

    @property
    def current_item_id(self) -> UUID | None:
        """Return the UUID represented by the current-item role."""
        return self._current_item_id

    def rowCount(
        self,
        parent: QModelIndex | QPersistentModelIndex = INVALID_INDEX,
    ) -> int:
        """Return zero for child queries because this is a flat list model."""
        return 0 if parent.isValid() else len(self._playlist)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = int(Qt.ItemDataRole.DisplayRole),
    ) -> object | None:
        """Return queue data for valid first-column indexes."""
        if not index.isValid() or index.column() != 0:
            return None
        row = index.row()
        if not 0 <= row < len(self._playlist):
            return None
        item = self._playlist.item_at(row)
        if role in (int(Qt.ItemDataRole.DisplayRole), int(QueueRole.DisplayTitle)):
            return item.display_title
        if role == int(QueueRole.ItemId):
            return str(item.item_id)
        if role == int(QueueRole.SourcePath):
            return str(item.source_path)
        if role == int(QueueRole.IsCurrent):
            return item.item_id == self._current_item_id
        return None

    def roleNames(self) -> dict[int, QByteArray]:
        """Return stable English names for custom queue roles."""
        return {
            int(QueueRole.ItemId): QByteArray(b"itemId"),
            int(QueueRole.SourcePath): QByteArray(b"sourcePath"),
            int(QueueRole.DisplayTitle): QByteArray(b"displayTitle"),
            int(QueueRole.IsCurrent): QByteArray(b"isCurrent"),
        }

    def flags(
        self,
        index: QModelIndex | QPersistentModelIndex,
    ) -> Qt.ItemFlag:
        """Expose valid rows as enabled and selectable only."""
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def insert_item(self, row: int, item: QueueItem) -> None:
        """Insert one domain item with a matching Qt rows notification."""
        if not 0 <= row <= len(self._playlist):
            raise IndexError("Queue model insertion row is out of range.")
        if any(existing.item_id == item.item_id for existing in self._playlist):
            raise ValueError("Queue model items must have unique UUID identities.")
        self.beginInsertRows(QModelIndex(), row, row)
        self._playlist.insert(row, item)
        self.endInsertRows()

    def remove_item(self, item_id: UUID) -> QueueItem:
        """Remove one UUID with a matching Qt rows notification."""
        row = self._playlist.index_of(item_id)
        self.beginRemoveRows(QModelIndex(), row, row)
        removed = self._playlist.remove(item_id)
        if self._current_item_id == item_id:
            self._current_item_id = None
        self.endRemoveRows()
        return removed

    def move_item(self, source_row: int, destination_row: int) -> None:
        """Move one row to its final position and preserve domain identity."""
        self._playlist.item_at(source_row)
        self._playlist.item_at(destination_row)
        if source_row == destination_row:
            return
        destination_child = (
            destination_row + 1 if source_row < destination_row else destination_row
        )
        if not self.beginMoveRows(
            QModelIndex(),
            source_row,
            source_row,
            QModelIndex(),
            destination_child,
        ):
            raise RuntimeError("Qt rejected a valid queue row move.")
        self._playlist.move(source_row, destination_row)
        self.endMoveRows()

    def set_current_item(self, item_id: UUID | None) -> None:
        """Update the current UUID and notify only old and new affected rows."""
        if item_id == self._current_item_id:
            return
        new_row = None if item_id is None else self._playlist.index_of(item_id)
        old_row = (
            None
            if self._current_item_id is None
            else self._playlist.index_of(self._current_item_id)
        )
        self._current_item_id = item_id
        if old_row is not None:
            self._emit_current_changed(old_row)
        if new_row is not None:
            self._emit_current_changed(new_row)

    def _emit_current_changed(self, row: int) -> None:
        index = self.index(row, 0)
        self.dataChanged.emit(index, index, [int(QueueRole.IsCurrent)])
