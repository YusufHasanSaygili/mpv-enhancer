"""Accessible basic playback controls and progress presentation."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QWidget

from mpv_enhancer.ui.playback_controller import PlaybackState


class TransportControls(QWidget):
    """Emit user intent while rendering controller-owned playback state."""

    previousRequested = Signal()
    playPauseRequested = Signal()
    stopRequested = Signal()
    nextRequested = Signal()
    seekRequested = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("transportControls")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.previous_button = _button("Previous", "previousButton", self)
        self.play_pause_button = _button("Pause", "playPauseButton", self)
        self.stop_button = _button("Stop", "stopButton", self)
        self.next_button = _button("Next", "nextButton", self)
        self.progress_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.progress_slider.setObjectName("playbackProgress")
        self.progress_slider.setAccessibleName("Playback position")
        self.progress_slider.setRange(0, 0)
        self.time_label = QLabel("00:00 / 00:00", self)
        self.time_label.setObjectName("playbackTimeLabel")
        self.time_label.setAccessibleName("Playback time")

        layout.addWidget(self.previous_button)
        layout.addWidget(self.play_pause_button)
        layout.addWidget(self.stop_button)
        layout.addWidget(self.next_button)
        layout.addWidget(self.progress_slider, 1)
        layout.addWidget(self.time_label)

        self.previous_button.clicked.connect(self.previousRequested)
        self.play_pause_button.clicked.connect(self.playPauseRequested)
        self.stop_button.clicked.connect(self.stopRequested)
        self.next_button.clicked.connect(self.nextRequested)
        self.progress_slider.sliderReleased.connect(self._seek_released)

    def set_playback_available(self, available: bool) -> None:
        for control in (
            self.previous_button,
            self.play_pause_button,
            self.stop_button,
            self.next_button,
            self.progress_slider,
        ):
            control.setEnabled(available)

    def apply_state(self, state: PlaybackState) -> None:
        """Render one atomic state without generating a seek command."""
        self.play_pause_button.setText("Play" if state.paused else "Pause")
        maximum = max(0, min(round(state.duration_seconds), 2_147_483_647))
        position = max(0, min(round(state.position_seconds), maximum))
        self.progress_slider.setMaximum(maximum)
        if not self.progress_slider.isSliderDown():
            self.progress_slider.setValue(position)
        self.time_label.setText(
            f"{_format_time(state.position_seconds)} / "
            f"{_format_time(state.duration_seconds)}"
        )

    def _seek_released(self) -> None:
        self.seekRequested.emit(float(self.progress_slider.value()))


def _button(text: str, object_name: str, parent: QWidget) -> QPushButton:
    button = QPushButton(text, parent)
    button.setObjectName(object_name)
    button.setAccessibleName(text)
    return button


def _format_time(seconds: float) -> str:
    total_seconds = max(0, round(seconds))
    hours, remainder = divmod(total_seconds, 3_600)
    minutes, remaining_seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{remaining_seconds:02d}"
    return f"{minutes:02d}:{remaining_seconds:02d}"
