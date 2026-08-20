from pathlib import Path

from PySide6.QtCore import QModelIndex, Qt

from mpv_enhancer.domain.models import Playlist, QueueItem
from mpv_enhancer.ui.queue_model import QueueListModel, QueueRole
from mpv_enhancer.ui.queue_view import QueueDragHandleDelegate, QueueDropListView


def _item(name: str) -> QueueItem:
    return QueueItem.create(Path("synthetic") / name)


def test_internal_move_preserves_uuid_metadata_and_current_identity() -> None:
    first = _item("episode-01.mkv")
    second = _item("episode-02.mkv")
    third = _item("episode-03.mkv")
    model = QueueListModel(Playlist([first, second, third]))
    model.set_current_item(first.item_id)

    mime_data = model.mimeData([model.index(0, 0)])
    moved = model.dropMimeData(
        mime_data,
        Qt.DropAction.MoveAction,
        3,
        0,
        QModelIndex(),
    )

    assert moved is True
    assert model.items == (second, third, first)
    assert model.items[2] is first
    assert model.items[2].item_id == first.item_id
    assert model.items[2].source_path == first.source_path
    assert model.items[2].display_title == first.display_title
    assert model.current_item_id == first.item_id
    assert model.data(model.index(2, 0), QueueRole.IsCurrent) is True


def test_internal_move_contract_rejects_copy_and_foreign_mime_data() -> None:
    model = QueueListModel(Playlist([_item("episode.mkv")]))
    internal_mime = model.mimeData([model.index(0, 0)])

    assert model.supportedDropActions() == Qt.DropAction.MoveAction
    assert model.flags(model.index(0, 0)) & Qt.ItemFlag.ItemIsDragEnabled
    assert model.flags(QModelIndex()) & Qt.ItemFlag.ItemIsDropEnabled
    assert not model.dropMimeData(
        internal_mime,
        Qt.DropAction.CopyAction,
        0,
        0,
        QModelIndex(),
    )


def test_keyboard_actions_move_the_current_row_with_its_identity(qtbot) -> None:
    first = _item("episode-01.mkv")
    second = _item("episode-02.mkv")
    third = _item("episode-03.mkv")
    model = QueueListModel(Playlist([first, second, third]))
    model.set_current_item(second.item_id)
    view = QueueDropListView(model)
    qtbot.addWidget(view)
    view.show()
    view.setCurrentIndex(model.index(1, 0))
    view.setFocus()

    move_up_action, move_down_action = view.actions()
    assert move_up_action.shortcut().toString() == "Alt+Up"
    assert move_down_action.shortcut().toString() == "Alt+Down"
    move_up_action.trigger()

    assert model.items == (second, first, third)
    assert view.currentIndex().row() == 0
    assert model.current_item_id == second.item_id
    assert model.data(view.currentIndex(), QueueRole.ItemId) == str(second.item_id)

    move_down_action.trigger()

    assert model.items == (first, second, third)
    assert view.currentIndex().row() == 1
    assert model.items[1] is second


def test_queue_view_uses_a_visible_drag_handle_delegate(qtbot) -> None:
    view = QueueDropListView(QueueListModel(Playlist([_item("episode.mkv")])))
    qtbot.addWidget(view)

    assert isinstance(view.itemDelegate(), QueueDragHandleDelegate)
    assert view.dragDropMode() == view.DragDropMode.DragDrop
