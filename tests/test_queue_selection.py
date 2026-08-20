from pathlib import Path

from PySide6.QtCore import QPoint, Qt

from mpv_enhancer.domain.models import QueueItem
from mpv_enhancer.ui.main_window import MainWindow


def _window_with_items(qtbot, count: int = 5) -> tuple[MainWindow, list[QueueItem]]:
    window = MainWindow()
    qtbot.addWidget(window)
    items = [
        QueueItem.create(Path("synthetic") / f"episode-{number:02}.mkv")
        for number in range(1, count + 1)
    ]
    for row, item in enumerate(items):
        window.queue_model.insert_item(row, item)
    window.show()
    qtbot.wait(0)
    return window, items


def _click_row(qtbot, window: MainWindow, row: int, modifier=None) -> None:
    rect = window.queue_view.visualRect(window.queue_model.index(row, 0))
    qtbot.mouseClick(
        window.queue_view.viewport(),
        Qt.MouseButton.LeftButton,
        modifier or Qt.KeyboardModifier.NoModifier,
        rect.center() + QPoint(12, 0),
    )


def test_ctrl_selects_non_adjacent_rows_and_updates_summary(qtbot) -> None:
    window, items = _window_with_items(qtbot)

    _click_row(qtbot, window, 0)
    _click_row(qtbot, window, 2, Qt.KeyboardModifier.ControlModifier)

    assert window.queue_view.selected_item_ids == (
        items[0].item_id,
        items[2].item_id,
    )
    assert window.selection_summary_label.text() == "2 queue items selected"
    assert window.queue_view.focusPolicy() == Qt.FocusPolicy.StrongFocus


def test_shift_selects_a_contiguous_range(qtbot) -> None:
    window, items = _window_with_items(qtbot)

    _click_row(qtbot, window, 1)
    _click_row(qtbot, window, 4, Qt.KeyboardModifier.ShiftModifier)

    assert window.queue_view.selected_item_ids == tuple(
        item.item_id for item in items[1:]
    )
    assert window.selection_summary_label.text() == "4 queue items selected"


def test_ctrl_a_selects_every_row_and_keeps_queue_focus(qtbot) -> None:
    window, items = _window_with_items(qtbot)
    window.queue_view.setFocus()

    qtbot.keyClick(
        window.queue_view,
        Qt.Key.Key_A,
        Qt.KeyboardModifier.ControlModifier,
    )

    assert window.queue_view.selected_item_ids == tuple(item.item_id for item in items)
    assert window.selection_summary_label.text() == "5 queue items selected"
    assert window.queue_view.focusPolicy() == Qt.FocusPolicy.StrongFocus


def test_selection_follows_uuid_after_reorder(qtbot) -> None:
    window, items = _window_with_items(qtbot, 3)

    _click_row(qtbot, window, 0)
    _click_row(qtbot, window, 2, Qt.KeyboardModifier.ControlModifier)
    window.queue_model.move_item(2, 1)

    assert window.queue_view.selected_item_ids == (
        items[0].item_id,
        items[2].item_id,
    )
    assert window.selection_summary_label.text() == "2 queue items selected"
