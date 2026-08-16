from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QDialogButtonBox, QLabel, QLineEdit, QPushButton

from mpv_enhancer.infrastructure.mpv.discovery import (
    MpvDiagnostics,
    MpvDiagnosticsStatus,
    MpvDiscoverySource,
)
from mpv_enhancer.infrastructure.preferences import MpvPreferenceStore
from mpv_enhancer.ui.main_window import MainWindow
from mpv_enhancer.ui.preferences_dialog import PreferencesDialog


class FakeDiscoveryService:
    def discover(self, selected_path: Path | None = None) -> MpvDiagnostics:
        if selected_path is None:
            return MpvDiagnostics(
                status=MpvDiagnosticsStatus.NOT_FOUND,
                source=None,
                executable=None,
                version=None,
                message="mpv was not found. Choose mpv.exe in Preferences.",
            )
        return MpvDiagnostics(
            status=MpvDiagnosticsStatus.AVAILABLE,
            source=MpvDiscoverySource.SELECTED,
            executable=selected_path,
            version="0.40.0",
            message="mpv is ready.",
        )


def test_preference_store_round_trips_selected_path(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    store = MpvPreferenceStore(settings)
    executable = tmp_path / "mpv.exe"

    assert store.selected_mpv_path() is None

    store.set_selected_mpv_path(executable)
    settings.sync()
    assert MpvPreferenceStore(settings).selected_mpv_path() == executable.resolve()

    store.clear_selected_mpv_path()
    assert store.selected_mpv_path() is None


def test_preferences_dialog_explains_missing_mpv(qtbot, tmp_path: Path) -> None:
    dialog = PreferencesDialog(
        _store(tmp_path),
        FakeDiscoveryService(),
    )
    qtbot.addWidget(dialog)

    status = dialog.findChild(QLabel, "mpvDiagnosticsMessage")
    browse = dialog.findChild(QPushButton, "browseMpvButton")

    assert dialog.windowTitle() == "MPV Enhancer Preferences"
    assert status is not None
    assert "mpv was not found" in status.text()
    assert browse is not None
    assert browse.text() == "Browse..."


def test_preferences_dialog_validates_and_saves_selected_path(
    qtbot,
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    executable = tmp_path / "tools" / "mpv.exe"
    dialog = PreferencesDialog(store, FakeDiscoveryService())
    qtbot.addWidget(dialog)
    path_edit = dialog.findChild(QLineEdit, "mpvPathEdit")
    validate_button = dialog.findChild(QPushButton, "validateMpvButton")
    buttons = dialog.findChild(QDialogButtonBox, "preferencesButtons")
    assert path_edit is not None
    assert validate_button is not None
    assert buttons is not None

    path_edit.setText(str(executable))
    qtbot.mouseClick(validate_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(
        buttons.button(QDialogButtonBox.StandardButton.Save), Qt.MouseButton.LeftButton
    )

    assert store.selected_mpv_path() == executable.resolve()


def test_main_window_opens_preferences_from_settings_menu(
    qtbot,
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    discovery = FakeDiscoveryService()
    window = MainWindow()
    window.configure_mpv_preferences(store, discovery, discovery.discover())
    qtbot.addWidget(window)
    action = window.findChild(QAction, "preferencesAction")
    assert action is not None

    action.trigger()
    dialog = window.findChild(PreferencesDialog, "preferencesDialog")

    assert dialog is not None
    assert dialog.isVisible()
    dialog.close()


def _store(tmp_path: Path) -> MpvPreferenceStore:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    return MpvPreferenceStore(settings)
