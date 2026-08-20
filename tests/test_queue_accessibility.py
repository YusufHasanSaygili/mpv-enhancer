from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction

from mpv_enhancer.domain.models import QueueItem
from mpv_enhancer.ui.main_window import MainWindow
from mpv_enhancer.ui.queue_model import QueueRole
from mpv_enhancer.ui.queue_view import QueueDragHandleDelegate


def _item(number: int, title: str | None = None) -> QueueItem:
    return QueueItem.create(
        Path("synthetic") / f"episode-{number:02}.mkv",
        display_title=title,
    )


def test_empty_state_and_accessible_labels_follow_queue_content(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(0)

    assert window.queue_view.empty_state_label.isVisible()
    assert window.queue_view.empty_state_label.text() == (
        "Drop supported media files here to build the queue."
    )
    assert window.queue_view.accessibleName() == "Playback queue"
    assert window.queue_view.accessibleDescription()
    assert window.queue_view.empty_state_label.accessibleName() == (
        "Empty queue instructions"
    )
    assert window.selection_summary_label.accessibleName() == "Selection summary"

    item = _item(1)
    window.queue_model.insert_item(0, item)
    qtbot.wait(0)

    assert not window.queue_view.empty_state_label.isVisible()

    window.queue_model.remove_item(item.item_id)
    qtbot.wait(0)

    assert window.queue_view.empty_state_label.isVisible()


def test_delegate_elides_long_titles_and_exposes_override_placeholder(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    long_title = "A very long episode title that cannot fit in a compact queue row"
    window.queue_model.insert_item(0, _item(1, long_title))
    delegate = window.queue_view.itemDelegate()

    assert isinstance(delegate, QueueDragHandleDelegate)
    elided = delegate.elided_title(long_title, window.queue_view.font(), 90)
    assert elided != long_title
    assert elided.endswith("…")
    assert (
        window.queue_model.data(
            window.queue_model.index(0, 0),
            QueueRole.OverrideSummary,
        )
        == "No overrides"
    )


def test_keyboard_only_select_remove_undo_and_reorder(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    items = [_item(1), _item(2), _item(3)]
    for row, item in enumerate(items):
        window.queue_model.insert_item(row, item)
    window.show()
    window.queue_view.setFocus()

    qtbot.keyClick(
        window.queue_view,
        Qt.Key.Key_A,
        Qt.KeyboardModifier.ControlModifier,
    )
    qtbot.keyClick(window.queue_view, Qt.Key.Key_Delete)

    assert window.queue_model.items == ()

    undo_action = window.findChild(QAction, "undoQueueAction")
    assert undo_action is not None
    undo_action.trigger()

    assert window.queue_model.items == tuple(items)
    assert window.queue_view.selected_item_ids == tuple(item.item_id for item in items)

    window.queue_view.setCurrentIndex(window.queue_model.index(0, 0))
    move_down = window.findChild(QAction, "moveQueueItemDownAction")
    assert move_down is not None
    move_down.trigger()

    assert window.queue_model.items == (items[1], items[0], items[2])
