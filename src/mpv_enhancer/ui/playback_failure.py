"""Recoverable playback failure message and actions."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class PlaybackFailurePanel(QWidget):
    """Show a path-free error with explicit Retry and Stop actions."""

    retryRequested = Signal()
    stopRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("playbackFailurePanel")
        self.setAccessibleName("Playback error")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        self.message_label = QLabel(self)
        self.message_label.setObjectName("playbackFailureMessage")
        self.message_label.setWordWrap(True)
        self.message_label.setAccessibleName("Playback error message")
        actions = QHBoxLayout()
        actions.addStretch(1)
        retry_button = QPushButton("Retry", self)
        retry_button.setObjectName("retryPlaybackButton")
        retry_button.clicked.connect(self.retryRequested)
        stop_button = QPushButton("Stop", self)
        stop_button.setObjectName("stopFailedPlaybackButton")
        stop_button.clicked.connect(self.stopRequested)
        actions.addWidget(retry_button)
        actions.addWidget(stop_button)
        layout.addWidget(self.message_label)
        layout.addLayout(actions)
        self.hide()

    def show_failure(self, message: str) -> None:
        self.message_label.setText(message)
        self.show()

    def clear_failure(self) -> None:
        self.message_label.clear()
        self.hide()
