"""Preferences dialog for selecting and diagnosing mpv."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mpv_enhancer.infrastructure.mpv.discovery import (
    MpvDiagnostics,
    MpvDiscoverer,
    MpvDiscoverySource,
)
from mpv_enhancer.infrastructure.preferences import MpvPreferenceStore

_SOURCE_LABELS = {
    MpvDiscoverySource.SELECTED: "Selected in Preferences",
    MpvDiscoverySource.ENVIRONMENT: "Development environment override",
    MpvDiscoverySource.PATH: "System PATH",
    MpvDiscoverySource.STANDARD: "Standard install location",
}


class PreferencesDialog(QDialog):
    """Select an mpv executable and display safe validation diagnostics."""

    def __init__(
        self,
        preference_store: MpvPreferenceStore,
        discovery: MpvDiscoverer,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._preference_store = preference_store
        self._discovery = discovery
        self._diagnostics: MpvDiagnostics | None = None

        self.setObjectName("preferencesDialog")
        self.setWindowTitle("MPV Enhancer Preferences")
        self.setModal(True)
        self.resize(640, 320)

        root_layout = QVBoxLayout(self)
        intro = QLabel(
            "MPV Enhancer needs mpv.exe before playback can be enabled. "
            "Choose an executable or use automatic discovery.",
            self,
        )
        intro.setWordWrap(True)
        root_layout.addWidget(intro)

        path_row = QHBoxLayout()
        self._path_edit = QLineEdit(self)
        self._path_edit.setObjectName("mpvPathEdit")
        self._path_edit.setPlaceholderText("Automatically detect mpv.exe")
        selected_path = self._preference_store.selected_mpv_path()
        if selected_path is not None:
            self._path_edit.setText(str(selected_path))
        path_row.addWidget(self._path_edit, 1)

        browse_button = QPushButton("Browse...", self)
        browse_button.setObjectName("browseMpvButton")
        browse_button.clicked.connect(self._browse)
        path_row.addWidget(browse_button)

        validate_button = QPushButton("Validate", self)
        validate_button.setObjectName("validateMpvButton")
        validate_button.clicked.connect(self.refresh_diagnostics)
        path_row.addWidget(validate_button)
        root_layout.addLayout(path_row)

        diagnostics_group = QGroupBox("Diagnostics", self)
        diagnostics_layout = QFormLayout(diagnostics_group)
        self._status_value = QLabel(diagnostics_group)
        self._status_value.setObjectName("mpvDiagnosticsStatus")
        self._source_value = QLabel(diagnostics_group)
        self._source_value.setObjectName("mpvDiagnosticsSource")
        self._version_value = QLabel(diagnostics_group)
        self._version_value.setObjectName("mpvDiagnosticsVersion")
        self._message = QLabel(diagnostics_group)
        self._message.setObjectName("mpvDiagnosticsMessage")
        self._message.setWordWrap(True)
        self._message.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        diagnostics_layout.addRow("Status:", self._status_value)
        diagnostics_layout.addRow("Source:", self._source_value)
        diagnostics_layout.addRow("Version:", self._version_value)
        diagnostics_layout.addRow("Result:", self._message)
        root_layout.addWidget(diagnostics_group)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self._buttons.setObjectName("preferencesButtons")
        self._buttons.accepted.connect(self._save)
        self._buttons.rejected.connect(self.reject)
        root_layout.addWidget(self._buttons)

        self.refresh_diagnostics()

    def refresh_diagnostics(self) -> None:
        selected_path = self._entered_path()
        self._diagnostics = self._discovery.discover(selected_path)
        diagnostics = self._diagnostics
        self._status_value.setText(diagnostics.status.value.replace("_", " ").title())
        self._source_value.setText(
            _SOURCE_LABELS.get(diagnostics.source, "Not available")
        )
        self._version_value.setText(diagnostics.version or "Not available")
        self._message.setText(diagnostics.message)

        selected_is_valid = (
            selected_path is None or diagnostics.source is MpvDiscoverySource.SELECTED
        )
        save_button = self._buttons.button(QDialogButtonBox.StandardButton.Save)
        save_button.setEnabled(diagnostics.is_available and selected_is_valid)

    def _browse(self) -> None:
        filename, _filter = QFileDialog.getOpenFileName(
            self,
            "Choose mpv executable",
            self._path_edit.text(),
            "mpv executable (mpv.exe);;All files (*)",
        )
        if filename:
            self._path_edit.setText(filename)
            self.refresh_diagnostics()

    def _save(self) -> None:
        self.refresh_diagnostics()
        if self._diagnostics is None or not self._diagnostics.is_available:
            return
        selected_path = self._entered_path()
        if selected_path is None:
            self._preference_store.clear_selected_mpv_path()
        elif self._diagnostics.source is MpvDiscoverySource.SELECTED:
            self._preference_store.set_selected_mpv_path(selected_path)
        else:
            return
        self.accept()

    def _entered_path(self) -> Path | None:
        value = self._path_edit.text().strip()
        return Path(value) if value else None
