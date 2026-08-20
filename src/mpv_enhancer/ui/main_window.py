"""Main application window and three-region desktop layout."""

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from mpv_enhancer.infrastructure.mpv.discovery import (
    MpvDiagnostics,
    MpvDiscoverer,
)
from mpv_enhancer.infrastructure.mpv.embedded import EmbeddedMpvSession
from mpv_enhancer.infrastructure.mpv.playback import PlaybackAdapter
from mpv_enhancer.infrastructure.preferences import MpvPreferenceStore
from mpv_enhancer.ui.playback_controller import PlaybackController, PlaybackState
from mpv_enhancer.ui.playback_failure import PlaybackFailurePanel
from mpv_enhancer.ui.preferences_dialog import PreferencesDialog
from mpv_enhancer.ui.queue_controller import QueueEditOutcome, QueueUndoController
from mpv_enhancer.ui.queue_model import QueueListModel
from mpv_enhancer.ui.queue_view import QueueDropListView
from mpv_enhancer.ui.transport_controls import TransportControls
from mpv_enhancer.ui.video_host import VideoHost


class PlaybackSession(Protocol):
    """Embedded playback lifecycle owned by the main window."""

    def start(self, executable: Path) -> bool: ...

    def shutdown(self) -> bool: ...

    @property
    def playback_adapter(self) -> PlaybackAdapter: ...

    def set_failure_listener(self, listener: Callable[[str], None]) -> None: ...

    def set_recovered_listener(self, listener: Callable[[], None]) -> None: ...


PlaybackSessionFactory = Callable[[int], PlaybackSession]


class MainWindow(QMainWindow):
    """Top-level window containing the planned three-region workspace."""

    def __init__(
        self,
        *,
        playback_session_factory: PlaybackSessionFactory | None = None,
    ) -> None:
        super().__init__()
        self.setObjectName("mainWindow")
        self.setWindowTitle("MPV Enhancer")
        self.resize(1200, 720)
        self.setMinimumSize(900, 560)
        self._preference_store: MpvPreferenceStore | None = None
        self._mpv_discovery: MpvDiscoverer | None = None
        self._mpv_diagnostics: MpvDiagnostics | None = None
        self._preferences_dialog: PreferencesDialog | None = None
        self._playback_session_factory = (
            _create_playback_session
            if playback_session_factory is None
            else playback_session_factory
        )
        self._playback_session: PlaybackSession | None = None
        self._playback_controller: PlaybackController | None = None

        settings_menu = self.menuBar().addMenu("Settings")
        preferences_action = QAction("Preferences...", self)
        preferences_action.setObjectName("preferencesAction")
        preferences_action.triggered.connect(self.open_preferences)
        settings_menu.addAction(preferences_action)

        view_menu = self.menuBar().addMenu("View")
        full_screen_action = QAction("Full Screen", self)
        full_screen_action.setObjectName("fullScreenAction")
        full_screen_action.setShortcut("F11")
        full_screen_action.triggered.connect(self.toggle_full_screen)
        view_menu.addAction(full_screen_action)

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
        video_content = QWidget(self)
        video_layout = QVBoxLayout(video_content)
        video_layout.setContentsMargins(0, 0, 0, 0)
        video_layout.setSpacing(8)
        self.video_host = VideoHost(video_content)
        self.playback_failure_panel = PlaybackFailurePanel(video_content)
        self.transport_controls = TransportControls(video_content)
        self.transport_controls.set_playback_available(False)
        video_layout.addWidget(self.video_host, 1)
        video_layout.addWidget(self.playback_failure_panel)
        video_layout.addWidget(self.transport_controls)
        video = self._create_region(
            "videoRegion",
            "Video and Transport",
            "Embedded video output",
            video_content,
        )
        self.queue_model = QueueListModel()
        self.queue_view = QueueDropListView(self.queue_model)
        self.queue_controller = QueueUndoController(self.queue_model, self.queue_view)
        self.queue_view.dropMessage.connect(self.statusBar().showMessage)
        self.queue_view.doubleClicked.connect(self._load_queue_index)
        self.transport_controls.playPauseRequested.connect(self._request_play_pause)
        self.transport_controls.previousRequested.connect(self._request_previous)
        self.transport_controls.nextRequested.connect(self._request_next)
        self.transport_controls.stopRequested.connect(self._request_stop)
        self.transport_controls.seekRequested.connect(self._request_seek)
        self.playback_failure_panel.retryRequested.connect(self._retry_failed_playback)
        self.playback_failure_panel.stopRequested.connect(self._stop_failed_playback)
        selection_summary_label = settings.findChild(
            QLabel,
            "settingsRegionDescription",
        )
        if selection_summary_label is None:
            raise RuntimeError("The selection summary label could not be created.")
        self.selection_summary_label = selection_summary_label
        self.selection_summary_label.setAccessibleName("Selection summary")
        self.selection_summary_label.setText(self.queue_view.selection_summary)
        self.queue_view.selectionSummaryChanged.connect(
            self.selection_summary_label.setText
        )

        queue_menu = self.menuBar().addMenu("Queue")
        remove_action = QAction("Remove Selected", self)
        remove_action.setObjectName("removeSelectedQueueItemsAction")
        remove_action.setShortcut("Delete")
        remove_action.setStatusTip("Remove the selected queue items")
        remove_action.triggered.connect(self.request_remove_selected)
        self.queue_view.removeRequested.connect(self.request_remove_selected)
        queue_menu.addAction(remove_action)
        clear_action = QAction("Clear Queue...", self)
        clear_action.setObjectName("clearQueueAction")
        clear_action.setStatusTip("Clear every item after confirmation")
        clear_action.triggered.connect(self.request_clear_queue)
        queue_menu.addAction(clear_action)
        queue_menu.addSeparator()
        undo_action = self.queue_controller.undo_stack.createUndoAction(self)
        undo_action.setObjectName("undoQueueAction")
        undo_action.setShortcuts(QKeySequence.StandardKey.Undo)
        queue_menu.addAction(undo_action)
        redo_action = self.queue_controller.undo_stack.createRedoAction(self)
        redo_action.setObjectName("redoQueueAction")
        redo_action.setShortcuts(QKeySequence.StandardKey.Redo)
        queue_menu.addAction(redo_action)
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

    def request_remove_selected(self) -> None:
        """Remove selected rows, explicitly confirming current-item removal."""
        outcome = self.queue_controller.remove_selected()
        if outcome is QueueEditOutcome.CURRENT_CONFIRMATION_REQUIRED:
            answer = QMessageBox.question(
                self,
                "Remove Current Item",
                (
                    "The selection includes the current item. "
                    "Stop it and remove the selected items?"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer is QMessageBox.StandardButton.Yes:
                if self._playback_controller is not None:
                    self._playback_controller.stop()
                outcome = self.queue_controller.remove_selected(stop_current=True)
        if outcome is QueueEditOutcome.NO_CHANGE:
            self.statusBar().showMessage("Select queue items to remove.")

    def request_clear_queue(self) -> None:
        """Clear the queue only after an explicit destructive confirmation."""
        if not self.queue_model.items:
            self.statusBar().showMessage("The queue is already empty.")
            return
        answer = QMessageBox.question(
            self,
            "Clear Queue",
            "Clear all queue items? This also stops the current item.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer is QMessageBox.StandardButton.Yes:
            if self._playback_controller is not None:
                self._playback_controller.stop()
            self.queue_controller.clear_queue(stop_current=True)

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
        self._configure_playback(diagnostics)

    def toggle_full_screen(self) -> None:
        """Toggle the complete workspace while preserving the video HWND."""
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

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
        self._configure_playback(diagnostics)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Shut down only the playback session owned by this window."""
        self._shutdown_playback()
        super().closeEvent(event)

    def _show_mpv_status(self, diagnostics: MpvDiagnostics) -> None:
        if diagnostics.is_available:
            self.statusBar().showMessage(f"mpv {diagnostics.version} is ready")
        else:
            self.statusBar().showMessage("mpv setup is required")

    def _configure_playback(self, diagnostics: MpvDiagnostics) -> None:
        self._shutdown_playback()
        if not diagnostics.is_available or diagnostics.executable is None:
            return
        session = self._playback_session_factory(self.video_host.native_handle)
        session.set_failure_listener(self._show_playback_failure)
        session.set_recovered_listener(self._playback_runtime_recovered)
        if session.start(diagnostics.executable):
            self._playback_session = session
            controller = PlaybackController(
                self.queue_model,
                session.playback_adapter,
                self,
            )
            controller.stateChanged.connect(self.transport_controls.apply_state)
            controller.failureOccurred.connect(self._show_playback_failure)
            self._playback_controller = controller
            self.transport_controls.set_playback_available(True)
            return
        session.shutdown()
        self.statusBar().showMessage("mpv could not start")

    def _shutdown_playback(self) -> None:
        self._playback_controller = None
        self.playback_failure_panel.clear_failure()
        self.transport_controls.apply_state(PlaybackState())
        self.transport_controls.set_playback_available(False)
        session = self._playback_session
        self._playback_session = None
        if session is not None:
            session.shutdown()

    def _load_queue_index(self, index: QModelIndex) -> None:
        controller = self._playback_controller
        if controller is not None:
            controller.load_row(index.row())

    def _request_play_pause(self) -> None:
        controller = self._playback_controller
        if controller is None:
            return
        current_index = self.queue_view.currentIndex()
        preferred_row = current_index.row() if current_index.isValid() else None
        controller.toggle_play_pause(preferred_row)

    def _request_previous(self) -> None:
        if self._playback_controller is not None:
            self._playback_controller.previous()

    def _request_next(self) -> None:
        if self._playback_controller is not None:
            self._playback_controller.next()

    def _request_stop(self) -> None:
        if self._playback_controller is not None:
            self._playback_controller.stop()

    def _request_seek(self, seconds: float) -> None:
        if self._playback_controller is not None:
            self._playback_controller.seek_absolute(seconds)

    def _show_playback_failure(self, message: str) -> None:
        self.playback_failure_panel.show_failure(message)
        self.statusBar().showMessage("Playback needs attention")

    def _playback_runtime_recovered(self) -> None:
        self.statusBar().showMessage("mpv restarted; retry the current item")

    def _retry_failed_playback(self) -> None:
        controller = self._playback_controller
        if controller is not None and controller.retry_current():
            self.playback_failure_panel.clear_failure()
            self.statusBar().showMessage("Retrying playback")

    def _stop_failed_playback(self) -> None:
        controller = self._playback_controller
        if controller is not None:
            controller.stop()
        self.playback_failure_panel.clear_failure()
        self.statusBar().showMessage("Playback stopped")

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


def _create_playback_session(host_hwnd: int) -> PlaybackSession:
    return EmbeddedMpvSession(host_hwnd)
