from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from mpv_enhancer.domain.models import Playlist, QueueItem
from mpv_enhancer.ui.main_window import MainWindow
from mpv_enhancer.ui.queue_controller import QueueEditOutcome, QueueUndoController
from mpv_enhancer.ui.queue_model import QueueListModel
from mpv_enhancer.ui.queue_view import QueueDropListView


def _item(name: str, title: str) -> QueueItem:
    return QueueItem.create(Path("synthetic") / name, display_title=title)


def _controller(
    qtbot,
    items: list[QueueItem],
) -> tuple[QueueListModel, QueueDropListView, QueueUndoController]:
    model = QueueListModel(Playlist(items))
    view = QueueDropListView(model)
    qtbot.addWidget(view)
    controller = QueueUndoController(model, view)
    return model, view, controller


def test_remove_undo_redo_restores_exact_items_order_and_selection(qtbot) -> None:
    first = _item("episode.mkv", "First override")
    second = _item("episode.mkv", "Second override")
    third = _item("episode-03.mkv", "Third override")
    model, view, controller = _controller(qtbot, [first, second, third])
    view.select_item_ids((first.item_id, third.item_id))

    assert controller.remove_selected() is QueueEditOutcome.APPLIED
    assert model.items == (second,)
    assert view.selected_item_ids == ()

    controller.undo_stack.undo()

    assert model.items == (first, second, third)
    assert model.items[0] is first
    assert model.items[1] is second
    assert model.items[2] is third
    assert view.selected_item_ids == (first.item_id, third.item_id)

    controller.undo_stack.redo()

    assert model.items == (second,)
    assert view.selected_item_ids == ()


def test_current_item_requires_confirmation_before_clear_and_is_undoable(qtbot) -> None:
    first = _item("episode-01.mkv", "First")
    second = _item("episode-02.mkv", "Second")
    model, view, controller = _controller(qtbot, [first, second])
    model.set_current_item(second.item_id)
    view.select_item_ids((first.item_id, second.item_id))

    assert controller.clear_queue() is QueueEditOutcome.CURRENT_CONFIRMATION_REQUIRED
    assert model.items == (first, second)
    assert model.current_item_id == second.item_id

    assert controller.clear_queue(stop_current=True) is QueueEditOutcome.APPLIED
    assert model.items == ()
    assert model.current_item_id is None

    controller.undo_stack.undo()

    assert model.items == (first, second)
    assert model.current_item_id == second.item_id
    assert view.selected_item_ids == (first.item_id, second.item_id)


def test_move_undo_redo_preserves_selected_uuid_metadata_and_current_item(
    qtbot,
) -> None:
    first = _item("episode-01.mkv", "First")
    second = _item("episode-02.mkv", "Second")
    third = _item("episode-03.mkv", "Third")
    model, view, controller = _controller(qtbot, [first, second, third])
    model.set_current_item(third.item_id)
    view.select_item_ids((first.item_id, third.item_id))

    controller.move_item(2, 0)

    assert model.items == (third, first, second)
    assert view.selected_item_ids == (third.item_id, first.item_id)
    assert model.current_item_id == third.item_id

    controller.undo_stack.undo()

    assert model.items == (first, second, third)
    assert view.selected_item_ids == (first.item_id, third.item_id)
    assert model.current_item_id == third.item_id
    assert model.items[2] is third

    controller.undo_stack.redo()

    assert model.items == (third, first, second)
    assert model.items[0] is third


def test_main_window_clear_asks_for_confirmation(qtbot, monkeypatch) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.queue_model.insert_item(0, _item("episode.mkv", "Episode"))
    questions: list[str] = []

    def confirm(*_args, **_kwargs):
        questions.append("asked")
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", confirm)

    window.request_clear_queue()

    assert questions == ["asked"]
    assert window.queue_model.rowCount() == 1
