"""Main application window and first-slice layout placeholders."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class MainWindow(QMainWindow):
    """Top-level window containing the planned three-region workspace."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("mainWindow")
        self.setWindowTitle("MPV Enhancer")
        self.resize(1200, 720)
        self.setMinimumSize(900, 560)

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
        queue = self._create_region(
            "queueRegion",
            "Queue",
            "Drop media files here to build a playback queue.",
        )

        layout.addWidget(settings, 2)
        layout.addWidget(video, 5)
        layout.addWidget(queue, 3)
        self.setCentralWidget(workspace)
        self.statusBar().showMessage("Ready")

    def _create_region(
        self,
        object_name: str,
        title: str,
        description: str,
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
        layout.addStretch(1)
        layout.addWidget(description_label)
        layout.addStretch(1)
        return region
