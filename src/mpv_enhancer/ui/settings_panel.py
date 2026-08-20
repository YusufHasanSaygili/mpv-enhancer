"""Selection-aware framework for the left settings workspace."""

from dataclasses import dataclass, field

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from mpv_enhancer.domain.models import QueueItem
from mpv_enhancer.domain.selection_settings import (
    SelectedSettingState,
    SelectedSettingValue,
    inspect_selected_setting,
)
from mpv_enhancer.domain.settings import SettingKey


@dataclass(slots=True)
class MixedValueAdapter:
    """Hold presentation-neutral selection state for one future editor."""

    key: SettingKey
    state: SelectedSettingValue = field(
        default_factory=lambda: SelectedSettingValue(SelectedSettingState.INHERITED)
    )

    def bind(self, selected_items: tuple[QueueItem, ...]) -> None:
        """Refresh state from selected item overrides."""
        self.state = (
            inspect_selected_setting(selected_items, self.key)
            if selected_items
            else SelectedSettingValue(SelectedSettingState.INHERITED)
        )


class SelectedItemsSettingsPanel(QWidget):
    """Scrollable grouped shell for selection-bound setting editors."""

    applyRequested = Signal()
    resetAllRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("selectedItemsSettingsPanel")
        self._adapters = {key: MixedValueAdapter(key) for key in SettingKey}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.selection_summary_label = QLabel("No queue items selected", self)
        self.selection_summary_label.setObjectName("selectionSummaryLabel")
        self.selection_summary_label.setAccessibleName("Selection summary")
        self.selection_summary_label.setWordWrap(True)
        layout.addWidget(self.selection_summary_label)

        scroll_area = QScrollArea(self)
        scroll_area.setObjectName("settingsScrollArea")
        scroll_area.setWidgetResizable(True)
        self.settings_content = QWidget(scroll_area)
        self.settings_content.setObjectName("settingsContent")
        content_layout = QVBoxLayout(self.settings_content)
        content_layout.setContentsMargins(4, 4, 4, 4)
        content_layout.setSpacing(10)
        content_layout.addWidget(_settings_group("Playback", "playbackSettingsGroup"))
        content_layout.addWidget(_settings_group("Tracks", "trackSettingsGroup"))
        content_layout.addWidget(_settings_group("Video", "videoSettingsGroup"))
        content_layout.addStretch(1)
        scroll_area.setWidget(self.settings_content)
        layout.addWidget(scroll_area, 1)

        actions = QHBoxLayout()
        self.apply_button = QPushButton("Apply", self)
        self.apply_button.setObjectName("applySettingsButton")
        self.apply_button.clicked.connect(self.applyRequested)
        self.reset_all_button = QPushButton("Reset All", self)
        self.reset_all_button.setObjectName("resetAllSettingsButton")
        self.reset_all_button.clicked.connect(self.resetAllRequested)
        actions.addWidget(self.apply_button)
        actions.addWidget(self.reset_all_button)
        layout.addLayout(actions)
        self.set_selected_items(())

    def set_selected_items(self, selected_items: tuple[QueueItem, ...]) -> None:
        """Bind summary, enabled state, and mixed adapters to one selection."""
        count = len(selected_items)
        if count == 0:
            summary = "No queue items selected"
        elif count == 1:
            summary = "1 queue item selected"
        else:
            summary = f"{count} queue items selected"
        self.selection_summary_label.setText(summary)
        enabled = count > 0
        self.settings_content.setEnabled(enabled)
        self.apply_button.setEnabled(enabled)
        self.reset_all_button.setEnabled(enabled)
        for adapter in self._adapters.values():
            adapter.bind(selected_items)

    def state_for(self, key: SettingKey) -> SelectedSettingValue:
        """Return the current selection state for a future field editor."""
        return self._adapters[key].state


def _settings_group(title: str, object_name: str) -> QGroupBox:
    group = QGroupBox(title)
    group.setObjectName(object_name)
    group.setLayout(QVBoxLayout())
    return group
