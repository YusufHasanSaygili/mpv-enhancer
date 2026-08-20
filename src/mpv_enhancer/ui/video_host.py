"""Stable native Qt widget used as mpv's embedded video parent."""

import ctypes

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSizePolicy, QWidget


class VideoHost(QWidget):
    """Keep one forced-native Windows handle for the lifetime of playback."""

    native_window_attribute = Qt.WidgetAttribute.WA_NativeWindow

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("videoHost")
        self.setAccessibleName("Embedded video output")
        self.setAttribute(self.native_window_attribute, True)
        self.setAutoFillBackground(True)
        self.setStyleSheet("background-color: black;")
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.setMinimumSize(320, 180)
        self._native_handle: int | None = None

    @property
    def native_handle(self) -> int:
        """Return mpv's uint32 Windows parent ID and reject handle churn."""
        current = ctypes.c_uint32(int(self.winId())).value
        if current == 0:
            raise RuntimeError("The video host did not create a native handle.")
        if self._native_handle is None:
            self._native_handle = current
        elif self._native_handle != current:
            raise RuntimeError("The video host native handle changed during playback.")
        return self._native_handle
