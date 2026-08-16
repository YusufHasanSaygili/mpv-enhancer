from PySide6.QtWidgets import QLabel, QWidget

from mpv_enhancer import __version__
from mpv_enhancer.app import create_application
from mpv_enhancer.ui.main_window import MainWindow


def test_application_has_public_metadata(qapp) -> None:
    app = create_application([])

    assert app is qapp
    assert app.applicationName() == "MPV Enhancer"
    assert app.applicationDisplayName() == "MPV Enhancer"
    assert app.applicationVersion() == __version__
    assert app.organizationName() == "MPV Enhancer"
    assert not app.windowIcon().isNull()


def test_main_window_has_three_english_regions(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.windowTitle() == "MPV Enhancer"
    assert _region_title(window, "settingsRegion") == "Selected Item Settings"
    assert _region_title(window, "videoRegion") == "Video and Transport"
    assert _region_title(window, "queueRegion") == "Queue"


def test_main_window_launches_and_closes_cleanly(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    window.show()
    assert window.isVisible()

    window.close()
    assert not window.isVisible()


def _region_title(window: MainWindow, object_name: str) -> str:
    region = window.findChild(QWidget, object_name)
    assert region is not None

    title = region.findChild(QLabel, f"{object_name}Title")
    assert title is not None
    return title.text()
