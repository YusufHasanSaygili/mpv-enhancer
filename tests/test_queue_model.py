from pathlib import Path

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtTest import QAbstractItemModelTester, QSignalSpy

from mpv_enhancer.domain.models import Playlist, QueueItem
from mpv_enhancer.ui.queue_model import QueueListModel, QueueRole


def _item(name: str) -> QueueItem:
    return QueueItem.create(Path("synthetic") / name)


def test_model_exposes_queue_roles_without_invalid_index_warnings(qtbot) -> None:
    item = _item("episode-01.mkv")
    model = QueueListModel(Playlist([item]))
    tester = QAbstractItemModelTester(
        model,
        QAbstractItemModelTester.FailureReportingMode.Warning,
    )

    index = model.index(0, 0)

    assert tester.model() is model
    assert model.rowCount() == 1
    assert model.rowCount(index) == 0
    assert model.data(index, Qt.ItemDataRole.DisplayRole) == "episode-01"
    assert model.data(index, QueueRole.ItemId) == str(item.item_id)
    assert model.data(index, QueueRole.SourcePath) == str(item.source_path)
    assert model.data(index, QueueRole.DisplayTitle) == item.display_title
    assert model.data(index, QueueRole.IsCurrent) is False
    assert model.data(QModelIndex(), Qt.ItemDataRole.DisplayRole) is None
    qtbot.wait(0)


def test_insert_remove_and_move_emit_structural_notifications(qtbot) -> None:
    first = _item("episode-01.mkv")
    second = _item("episode-02.mkv")
    third = _item("episode-03.mkv")
    model = QueueListModel(Playlist([first, third]))
    tester = QAbstractItemModelTester(model)
    inserted = QSignalSpy(model.rowsInserted)
    moved = QSignalSpy(model.rowsMoved)
    removed = QSignalSpy(model.rowsRemoved)

    model.insert_item(1, second)
    model.move_item(0, 2)
    removed_item = model.remove_item(third.item_id)

    assert tester.model() is model
    assert inserted.count() == 1
    assert moved.count() == 1
    assert removed.count() == 1
    assert removed_item is third
    assert model.items == (second, first)
    qtbot.wait(0)


def test_current_item_role_updates_only_affected_rows(qtbot) -> None:
    first = _item("episode-01.mkv")
    second = _item("episode-02.mkv")
    model = QueueListModel(Playlist([first, second]))
    changed = QSignalSpy(model.dataChanged)

    model.set_current_item(first.item_id)
    model.set_current_item(second.item_id)

    assert model.current_item_id == second.item_id
    assert model.data(model.index(0, 0), QueueRole.IsCurrent) is False
    assert model.data(model.index(1, 0), QueueRole.IsCurrent) is True
    assert changed.count() == 3
    for emission_index in range(changed.count()):
        assert changed.at(emission_index)[2] == [int(QueueRole.IsCurrent)]
    qtbot.wait(0)


def test_flags_are_enabled_and_selectable_for_valid_rows() -> None:
    model = QueueListModel(Playlist([_item("episode.mkv")]))

    flags = model.flags(model.index(0, 0))

    assert flags & Qt.ItemFlag.ItemIsEnabled
    assert flags & Qt.ItemFlag.ItemIsSelectable
    assert model.flags(QModelIndex()) == Qt.ItemFlag.NoItemFlags
