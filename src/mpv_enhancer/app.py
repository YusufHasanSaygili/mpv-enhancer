"""Application creation and command-line entry point."""

import sys
from collections.abc import Sequence
from importlib.resources import files

from PySide6.QtGui import QFont, QIcon, QPixmap
from PySide6.QtWidgets import QApplication

from mpv_enhancer import __version__
from mpv_enhancer.ui.main_window import MainWindow

APPLICATION_NAME = "MPV Enhancer"
ORGANIZATION_NAME = "MPV Enhancer"


def create_application(argv: Sequence[str] | None = None) -> QApplication:
    """Return the process QApplication configured with public metadata."""
    existing = QApplication.instance()
    if existing is None:
        app = QApplication(list(argv) if argv is not None else sys.argv)
    elif isinstance(existing, QApplication):
        app = existing
    else:
        raise RuntimeError("A non-GUI Qt application already exists.")

    app.setApplicationName(APPLICATION_NAME)
    app.setApplicationDisplayName(APPLICATION_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(ORGANIZATION_NAME)
    app.setDesktopFileName("mpv-enhancer")
    if sys.platform == "win32":
        app.setFont(QFont("Segoe UI", 10))
    app.setWindowIcon(load_application_icon())
    return app


def load_application_icon() -> QIcon:
    """Load the redistribution-safe placeholder icon bundled with the app."""
    icon_data = files("mpv_enhancer.assets.icons").joinpath("app-icon.svg").read_bytes()
    pixmap = QPixmap()
    if not pixmap.loadFromData(icon_data, "SVG"):
        raise RuntimeError("The bundled application icon could not be loaded.")
    return QIcon(pixmap)


def main() -> int:
    """Launch the desktop application and return its process exit code."""
    app = create_application()
    window = MainWindow()
    window.show()
    return app.exec()
