"""Application creation and command-line entry point."""

import sys
from collections.abc import Sequence
from importlib.resources import files

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtGui import QFont, QIcon, QPixmap
from PySide6.QtWidgets import QApplication

from mpv_enhancer import __version__
from mpv_enhancer.infrastructure.logging_config import (
    configure_logging,
    shutdown_logging,
)
from mpv_enhancer.infrastructure.mpv.discovery import MpvDiscoveryService
from mpv_enhancer.infrastructure.paths import AppDataPaths
from mpv_enhancer.infrastructure.preferences import MpvPreferenceStore
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
    logger = configure_logging(AppDataPaths.for_current_user())
    logger.info("application_started version=%s", __version__)
    try:
        preference_store = MpvPreferenceStore(QSettings())
        discovery = MpvDiscoveryService()
        diagnostics = discovery.discover(preference_store.selected_mpv_path())
        logger.info(
            "mpv_discovery status=%s source=%s",
            diagnostics.status.value,
            diagnostics.source.value if diagnostics.source else "none",
        )
        window = MainWindow()
        window.configure_mpv_preferences(
            preference_store,
            discovery,
            diagnostics,
        )
        window.show()
        if not diagnostics.is_available:
            QTimer.singleShot(0, window.open_preferences)
        return app.exec()
    except Exception:
        logger.exception("application_failed")
        raise
    finally:
        logger.info("application_stopped")
        shutdown_logging(logger)
