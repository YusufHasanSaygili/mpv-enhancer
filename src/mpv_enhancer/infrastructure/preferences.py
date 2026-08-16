"""Machine-local application preference storage."""

from pathlib import Path

from PySide6.QtCore import QSettings

_MPV_PATH_KEY = "playback/mpv_path"


class MpvPreferenceStore:
    """Persist only the user-selected mpv executable path in QSettings."""

    def __init__(self, settings: QSettings) -> None:
        self._settings = settings

    def selected_mpv_path(self) -> Path | None:
        value = self._settings.value(_MPV_PATH_KEY, "", type=str).strip()
        return Path(value).expanduser().resolve() if value else None

    def set_selected_mpv_path(self, executable: Path) -> None:
        self._settings.setValue(_MPV_PATH_KEY, str(executable.expanduser().resolve()))
        self._settings.sync()

    def clear_selected_mpv_path(self) -> None:
        self._settings.remove(_MPV_PATH_KEY)
        self._settings.sync()
