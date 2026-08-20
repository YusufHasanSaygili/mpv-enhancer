"""Main application window and first-slice layout placeholders."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from mpv_enhancer.infrastructure.mpv.discovery import (
    MpvDiagnostics,
    MpvDiscoverer,
)
from mpv_enhancer.infrastructure.preferences import MpvPreferenceStore
from mpv_enhancer.ui.preferences_dialog import PreferencesDialog
from mpv_enhancer.ui.queue_model import QueueListModel
from mpv_enhancer.ui.queue_view import QueueDropListView


class MainWindow(QMainWindow):
    """Top-level window containing the planned three-region workspace."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("mainWindow")
        self.setWindowTitle("MPV Enhancer")
        self.resize(1200, 720)
        self.setMinimumSize(900, 560)
        self._preference_store: MpvPreferenceStore | None = None
        self._mpv_discovery: MpvDiscoverer | None = None
        self._mpv_diagnostics: MpvDiagnostics | None = None
        self._preferences_dialog: PreferencesDialog | None = None

        settings_menu = self.menuBar().addMenu("Settings")
        preferences_action = QAction("Preferences...", self)
        preferences_action.setObjectName("preferencesAction")
        preferences_action.triggered.connect(self.open_preferences)
        settings_menu.addAction(preferences_action)

        workspace = QWidget(self)
        workspace.setObjectName("workspace")
        layout = QHBoxLayout(workspace)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        settings = self._create_region(
            "settingsRegion",
            "Selected Item Settings",
            "Select queue items to edit their playback settings.",
        )
        video = self._create_region(
            "videoRegion",
            "Video and Transport",
            "Video playback and transport controls will appear here.",
        )
        self.queue_model = QueueListModel()
        self.queue_view = QueueDropListView(self.queue_model)
        self.queue_view.dropMessage.connect(self.statusBar().showMessage)
        queue = self._create_region(
            "queueRegion",
            "Queue",
            "Drop media files here to build a playback queue.",
            self.queue_view,
        )

        layout.addWidget(settings, 2)
        layout.addWidget(video, 5)
        layout.addWidget(queue, 3)
        self.setCentralWidget(workspace)
        self.statusBar().showMessage("Ready")

    def configure_mpv_preferences(
        self,
        preference_store: MpvPreferenceStore,
        discovery: MpvDiscoverer,
        diagnostics: MpvDiagnostics,
    ) -> None:
        """Attach machine-local mpv preferences to the application shell."""
        self._preference_store = preference_store
        self._mpv_discovery = discovery
        self._mpv_diagnostics = diagnostics
        self._show_mpv_status(diagnostics)

    def open_preferences(self) -> None:
        """Open the non-blocking mpv setup and diagnostics dialog."""
        if self._preference_store is None or self._mpv_discovery is None:
            return
        if self._preferences_dialog is not None:
            self._preferences_dialog.raise_()
            self._preferences_dialog.activateWindow()
            return

        dialog = PreferencesDialog(
            self._preference_store,
            self._mpv_discovery,
            self,
        )
        self._preferences_dialog = dialog
        dialog.finished.connect(self._preferences_finished)
        dialog.open()

    def _preferences_finished(self, _result: int) -> None:
        self._preferences_dialog = None
        if self._preference_store is None or self._mpv_discovery is None:
            return
        diagnostics = self._mpv_discovery.discover(
            self._preference_store.selected_mpv_path()
        )
        self._mpv_diagnostics = diagnostics
        self._show_mpv_status(diagnostics)

    def _show_mpv_status(self, diagnostics: MpvDiagnostics) -> None:
        if diagnostics.is_available:
            self.statusBar().showMessage(f"mpv {diagnostics.version} is ready")
        else:
            self.statusBar().showMessage("mpv setup is required")

    def _create_region(
        self,
        object_name: str,
        title: str,
        description: str,
        content: QWidget | None = None,
    ) -> QFrame:
        region = QFrame(self)
        region.setObjectName(object_name)
        region.setAccessibleName(title)
        region.setFrameShape(QFrame.Shape.StyledPanel)
        region.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        layout = QVBoxLayout(region)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title_label = QLabel(title, region)
        title_label.setObjectName(f"{object_name}Title")
        title_label.setProperty("role", "heading")
        title_font = title_label.font()
        title_font.setBold(True)
        title_label.setFont(title_font)

        description_label = QLabel(description, region)
        description_label.setObjectName(f"{object_name}Description")
        description_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        description_label.setWordWrap(True)

        layout.addWidget(title_label)
        if content is None:
            layout.addStretch(1)
            layout.addWidget(description_label)
            layout.addStretch(1)
        else:
            layout.addWidget(description_label)
            layout.addWidget(content, 1)
        return region
