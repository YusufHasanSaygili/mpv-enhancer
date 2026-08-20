"""Undoable queue-edit commands at the Qt UI boundary."""

from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from PySide6.QtCore import QObject
from PySide6.QtGui import QUndoCommand, QUndoStack

from mpv_enhancer.domain.models import QueueItem
from mpv_enhancer.ui.queue_model import QueueListModel
from mpv_enhancer.ui.queue_view import QueueDropListView


class QueueEditOutcome(Enum):
    """Result of a requested queue edit that may require UI confirmation."""

    APPLIED = "applied"
    NO_CHANGE = "no_change"
    CURRENT_CONFIRMATION_REQUIRED = "current_confirmation_required"


@dataclass(frozen=True, slots=True)
class QueueSnapshot:
    """All identity-bearing queue state needed for exact undo and redo."""

    items: tuple[QueueItem, ...]
    current_item_id: UUID | None
    selected_item_ids: tuple[UUID, ...]


class QueueUndoController(QObject):
    """Create snapshot-based QUndoCommands for queue edits."""

    def __init__(self, model: QueueListModel, view: QueueDropListView) -> None:
        super().__init__(view)
        self._model = model
        self._view = view
        self.undo_stack = QUndoStack(self)
        self._view.set_move_handler(self.move_item)

    def remove_selected(
        self,
        *,
        stop_current: bool = False,
    ) -> QueueEditOutcome:
        """Remove selected identities unless the current item needs confirmation."""
        selected_ids = set(self._view.selected_item_ids)
        if not selected_ids:
            return QueueEditOutcome.NO_CHANGE
        if self._model.current_item_id in selected_ids and not stop_current:
            return QueueEditOutcome.CURRENT_CONFIRMATION_REQUIRED

        before = self._capture()
        remaining = tuple(
            item for item in before.items if item.item_id not in selected_ids
        )
        current = (
            None if before.current_item_id in selected_ids else before.current_item_id
        )
        after = QueueSnapshot(remaining, current, ())
        self._push("Remove queue items", before, after)
        return QueueEditOutcome.APPLIED

    def clear_queue(self, *, stop_current: bool = False) -> QueueEditOutcome:
        """Clear the queue after explicit approval to stop a current item."""
        if not self._model.items:
            return QueueEditOutcome.NO_CHANGE
        if self._model.current_item_id is not None and not stop_current:
            return QueueEditOutcome.CURRENT_CONFIRMATION_REQUIRED
        before = self._capture()
        self._push("Clear queue", before, QueueSnapshot((), None, ()))
        return QueueEditOutcome.APPLIED

    def move_item(self, source_row: int, destination_row: int) -> None:
        """Move one item through the same exact-state undo stack."""
        if source_row == destination_row:
            return
        before = self._capture()
        moved_items = list(before.items)
        moved_items.insert(destination_row, moved_items.pop(source_row))
        after = QueueSnapshot(
            tuple(moved_items),
            before.current_item_id,
            before.selected_item_ids,
        )
        self._push("Move queue item", before, after)

    def _capture(self) -> QueueSnapshot:
        return QueueSnapshot(
            self._model.items,
            self._model.current_item_id,
            self._view.selected_item_ids,
        )

    def _push(
        self,
        text: str,
        before: QueueSnapshot,
        after: QueueSnapshot,
    ) -> None:
        self.undo_stack.push(_RestoreQueueCommand(self, text, before, after))

    def _restore(self, snapshot: QueueSnapshot) -> None:
        self._model.replace_items(snapshot.items, snapshot.current_item_id)
        self._view.select_item_ids(snapshot.selected_item_ids)


class _RestoreQueueCommand(QUndoCommand):
    def __init__(
        self,
        controller: QueueUndoController,
        text: str,
        before: QueueSnapshot,
        after: QueueSnapshot,
    ) -> None:
        super().__init__(text)
        self._controller = controller
        self._before = before
        self._after = after

    def undo(self) -> None:
        self._controller._restore(self._before)

    def redo(self) -> None:
        self._controller._restore(self._after)
