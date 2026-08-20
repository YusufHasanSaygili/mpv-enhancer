from pathlib import Path

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragMoveEvent, QDropEvent
from PySide6.QtTest import QSignalSpy

from mpv_enhancer.domain.models import QueueItem
from mpv_enhancer.ui.file_drop import parse_external_file_drop
from mpv_enhancer.ui.main_window import MainWindow


def _mime_data(paths: list[Path]) -> QMimeData:
    mime_data = QMimeData()
    mime_data.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
    return mime_data


def test_file_drop_parser_preserves_supported_files_and_counts_rejections(
    tmp_path: Path,
) -> None:
    first = tmp_path / "episode-01.MKV"
    unsupported = tmp_path / "notes.txt"
    second = tmp_path / "episode-02.mp4"
    folder = tmp_path / "season"
    first.touch()
    unsupported.touch()
    second.touch()
    folder.mkdir()

    mime_data = _mime_data([first, unsupported, second, folder])
    mime_data.setUrls(
        [*mime_data.urls(), QUrl("https://example.invalid/episode-03.mkv")]
    )

    result = parse_external_file_drop(mime_data)

    assert result.accepted_paths == (first, second)
    assert result.rejected_count == 3


def test_non_url_mime_data_is_not_an_external_file_drop() -> None:
    mime_data = QMimeData()
    mime_data.setText("episode-01.mkv")

    result = parse_external_file_drop(mime_data)

    assert result.accepted_paths == ()
    assert result.rejected_count == 0


def test_mixed_external_drop_inserts_every_valid_file_in_order(
    qtbot,
    tmp_path: Path,
) -> None:
    before = QueueItem.create(Path("synthetic") / "before.mkv")
    after = QueueItem.create(Path("synthetic") / "after.mkv")
    window = MainWindow()
    qtbot.addWidget(window)
    model = window.queue_model
    model.insert_item(0, before)
    model.insert_item(1, after)
    view = window.queue_view
    window.show()
    qtbot.wait(0)

    first = tmp_path / "episode-01.mkv"
    unsupported = tmp_path / "cover.jpg"
    second = tmp_path / "episode-02.MP4"
    first.touch()
    unsupported.touch()
    second.touch()
    mime_data = _mime_data([first, unsupported, second])
    messages = QSignalSpy(view.dropMessage)

    second_row = view.visualRect(model.index(1, 0))
    position = second_row.topLeft() + QPoint(2, 2)
    move_event = QDragMoveEvent(
        position,
        Qt.DropAction.CopyAction,
        mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    view.dragMoveEvent(move_event)

    assert move_event.isAccepted()
    assert view.insertion_row == 1

    drop_event = QDropEvent(
        QPointF(position),
        Qt.DropAction.CopyAction,
        mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    view.dropEvent(drop_event)

    assert drop_event.isAccepted()
    assert [item.source_path for item in model.items] == [
        before.source_path,
        first,
        second,
        after.source_path,
    ]
    assert messages.count() == 1
    assert messages.at(0)[0] == (
        "Added 2 media files; skipped 1 unsupported or invalid item."
    )
    assert window.statusBar().currentMessage() == messages.at(0)[0]
    assert view.insertion_row is None
