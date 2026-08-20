"""Selection-aware framework for the left settings workspace."""

from dataclasses import dataclass, field
from functools import partial

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from mpv_enhancer.domain.models import QueueItem
from mpv_enhancer.domain.presets import STARTER_PRESETS, SettingsPreset
from mpv_enhancer.domain.selection_settings import (
    SelectedSettingState,
    SelectedSettingValue,
    SettingPatch,
    inspect_selected_setting,
)
from mpv_enhancer.domain.settings import (
    SETTING_SPEC_REGISTRY,
    LanguagePreferences,
    SettingKey,
)

type SettingControl = QDoubleSpinBox | QSpinBox | QComboBox | QLineEdit

_LANGUAGE_PRESETS: tuple[tuple[str, LanguagePreferences | None], ...] = (
    ("Custom", None),
    ("English", LanguagePreferences.parse("en,eng")),
    ("Turkish", LanguagePreferences.parse("tr,tur,en")),
    ("Spanish", LanguagePreferences.parse("es,spa,en")),
)


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
    patchRequested = Signal(object)
    resetSettingRequested = Signal(object)
    presetRequested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("selectedItemsSettingsPanel")
        self._adapters = {key: MixedValueAdapter(key) for key in SettingKey}
        self._controls: dict[SettingKey, SettingControl] = {}
        self._state_labels: dict[SettingKey, QLabel] = {}
        self._language_preset_controls: dict[SettingKey, QComboBox] = {}

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
        preset_group = _settings_group("Presets", "presetSettingsGroup")
        preset_layout = QVBoxLayout(preset_group)
        self.preset_control = QComboBox(preset_group)
        self.preset_control.setObjectName("presetControl")
        self.preset_control.setAccessibleName("Settings preset")
        self.preset_control.setToolTip(
            "Choose a reviewed preset and inspect every change before applying it."
        )
        self.preset_control.addItems(tuple(preset.label for preset in STARTER_PRESETS))
        preset_layout.addWidget(self.preset_control)
        self.preset_preview_label = QLabel(preset_group)
        self.preset_preview_label.setObjectName("presetPreviewLabel")
        self.preset_preview_label.setAccessibleName("Preset preview")
        self.preset_preview_label.setWordWrap(True)
        preset_layout.addWidget(self.preset_preview_label)
        self.apply_preset_button = QPushButton("Apply Preset", preset_group)
        self.apply_preset_button.setObjectName("applyPresetButton")
        self.apply_preset_button.setToolTip("Apply every change shown in the preview.")
        preset_layout.addWidget(self.apply_preset_button)
        self.preset_control.currentIndexChanged.connect(self._preset_changed)
        self.apply_preset_button.clicked.connect(self._request_preset)
        self._preset_changed(0)

        playback_group = _settings_group("Playback", "playbackSettingsGroup")
        playback_layout = QFormLayout(playback_group)
        self._add_numeric_setting(
            playback_layout,
            SettingKey.SPEED,
            "Speed",
            "speedControl",
            "Set playback speed from 0.25× to 4.00×.",
            decimals=2,
            step=0.05,
            suffix="×",
        )
        self._add_numeric_setting(
            playback_layout,
            SettingKey.VOLUME,
            "Volume",
            "volumeControl",
            "Set playback volume from 0% to 130%.",
            decimals=None,
            step=1.0,
            suffix="%",
        )
        self._add_boolean_setting(
            playback_layout,
            SettingKey.MUTE,
            "Mute",
            "muteControl",
            "Choose whether audio mute is inherited, on, or off.",
        )

        track_group = _settings_group("Tracks", "trackSettingsGroup")
        track_layout = QFormLayout(track_group)
        language_help = QLabel(
            (
                "Enter comma-separated language tags in priority order. "
                "MPV tries them from left to right; for example tr,tur,en. "
                "Reset restores the inherited preference."
            ),
            track_group,
        )
        language_help.setObjectName("languagePreferenceHelpLabel")
        language_help.setAccessibleName("Language preference help")
        language_help.setWordWrap(True)
        track_layout.addRow(language_help)
        self._add_language_setting(
            track_layout,
            SettingKey.SUBTITLE_LANGUAGES,
            "Subtitle Languages",
            "subtitleLanguageControl",
            "subtitleLanguagePresetControl",
        )
        self._add_language_setting(
            track_layout,
            SettingKey.AUDIO_LANGUAGES,
            "Audio Languages",
            "audioLanguageControl",
            "audioLanguagePresetControl",
        )
        self._add_boolean_setting(
            track_layout,
            SettingKey.SUBTITLE_VISIBILITY,
            "Subtitles",
            "subtitleVisibilityControl",
            "Choose whether subtitle visibility is inherited, on, or off.",
        )

        video_group = _settings_group("Video", "videoSettingsGroup")
        video_layout = QFormLayout(video_group)
        self._add_numeric_setting(
            video_layout,
            SettingKey.PANSCAN,
            "Pan and Scan",
            "panscanControl",
            "Set video pan-and-scan from 0.00 to 1.00.",
            decimals=2,
            step=0.05,
        )
        content_layout.addWidget(preset_group)
        content_layout.addWidget(playback_group)
        content_layout.addWidget(track_group)
        content_layout.addWidget(video_group)
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

    def _add_numeric_setting(
        self,
        layout: QFormLayout,
        key: SettingKey,
        label: str,
        object_name: str,
        tooltip: str,
        *,
        decimals: int | None,
        step: float,
        suffix: str = "",
    ) -> None:
        spec = SETTING_SPEC_REGISTRY.require(key)
        if spec.minimum is None or spec.maximum is None:
            raise RuntimeError(f"{key.value} is not a numeric setting.")
        if decimals is None:
            control: QDoubleSpinBox | QSpinBox = QSpinBox(self)
            control.setRange(int(spec.minimum), int(spec.maximum))
            control.setSingleStep(int(step))
        else:
            control = QDoubleSpinBox(self)
            control.setDecimals(decimals)
            control.setRange(spec.minimum, spec.maximum)
            control.setSingleStep(step)
        control.setObjectName(object_name)
        control.setToolTip(tooltip)
        control.setAccessibleName(label)
        control.setSuffix(suffix)
        control.valueChanged.connect(partial(self._numeric_value_changed, key))
        layout.addRow(label, self._editor_row(key, control))
        self._controls[key] = control

    def _add_language_setting(
        self,
        layout: QFormLayout,
        key: SettingKey,
        label: str,
        object_name: str,
        preset_object_name: str,
    ) -> None:
        control = QLineEdit(self)
        control.setObjectName(object_name)
        control.setAccessibleName(label)
        control.setToolTip("Enter ordered comma-separated IETF or ISO language tags.")
        control.editingFinished.connect(partial(self._language_edit_finished, key))

        preset_control = QComboBox(self)
        preset_control.setObjectName(preset_object_name)
        preset_control.setAccessibleName(f"{label} preset")
        preset_control.setToolTip("Choose a common ordered language preference.")
        preset_control.addItems(tuple(label for label, _value in _LANGUAGE_PRESETS))
        preset_control.currentIndexChanged.connect(
            partial(self._language_preset_changed, key)
        )

        row = QWidget(self)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(control, 2)
        row_layout.addWidget(preset_control, 1)
        self._add_state_and_reset_widgets(row_layout, row, key)
        layout.addRow(label, row)
        self._controls[key] = control
        self._language_preset_controls[key] = preset_control

    def _add_boolean_setting(
        self,
        layout: QFormLayout,
        key: SettingKey,
        label: str,
        object_name: str,
        tooltip: str,
    ) -> None:
        control = QComboBox(self)
        control.setObjectName(object_name)
        control.setToolTip(tooltip)
        control.setAccessibleName(label)
        control.addItems(("Inherited", "On", "Off", "Mixed"))
        control.currentIndexChanged.connect(partial(self._boolean_index_changed, key))
        layout.addRow(label, self._editor_row(key, control))
        self._controls[key] = control

    def _editor_row(self, key: SettingKey, control: SettingControl) -> QWidget:
        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(control, 1)
        self._add_state_and_reset_widgets(layout, row, key)
        return row

    def _add_state_and_reset_widgets(
        self,
        layout: QHBoxLayout,
        row: QWidget,
        key: SettingKey,
    ) -> None:
        state_label = QLabel("Inherited", row)
        state_label.setObjectName(f"{key.value}StateLabel")
        state_label.setAccessibleName(f"{key.value} selection state")
        layout.addWidget(state_label)
        reset_button = QPushButton("Reset", row)
        reset_button.setObjectName(f"{key.value}ResetButton")
        reset_button.setToolTip(f"Restore {key.value.replace('_', ' ')} to inherited.")
        reset_button.clicked.connect(partial(self._request_setting_reset, key))
        layout.addWidget(reset_button)
        self._state_labels[key] = state_label

    def _numeric_value_changed(self, key: SettingKey, value: float | int) -> None:
        self.patchRequested.emit(SettingPatch(key, value))

    def _boolean_index_changed(self, key: SettingKey, index: int) -> None:
        if index == 0:
            self.resetSettingRequested.emit(key)
        elif index == 1:
            self.patchRequested.emit(SettingPatch(key, True))
        elif index == 2:
            self.patchRequested.emit(SettingPatch(key, False))

    def _language_edit_finished(self, key: SettingKey) -> None:
        control = self._controls[key]
        if not isinstance(control, QLineEdit):
            raise RuntimeError(f"{key.value} is not a language editor.")
        try:
            preferences = LanguagePreferences.parse(control.text())
        except ValueError:
            self._state_labels[key].setText("Invalid")
            return
        preset_control = self._language_preset_controls[key]
        blocker = QSignalBlocker(preset_control)
        preset_control.setCurrentIndex(_language_preset_index(preferences))
        del blocker
        control.setText(preferences.to_mpv_value())
        self.patchRequested.emit(SettingPatch(key, preferences))

    def _language_preset_changed(self, key: SettingKey, index: int) -> None:
        if index == 0:
            return
        try:
            preferences = _LANGUAGE_PRESETS[index][1]
        except IndexError as error:
            raise IndexError("Language preset index is out of range.") from error
        if preferences is None:
            raise RuntimeError("A named language preset requires a value.")
        control = self._controls[key]
        if not isinstance(control, QLineEdit):
            raise RuntimeError(f"{key.value} is not a language editor.")
        blocker = QSignalBlocker(control)
        control.setText(preferences.to_mpv_value())
        del blocker
        self.patchRequested.emit(SettingPatch(key, preferences))

    def _request_setting_reset(self, key: SettingKey, _checked: bool = False) -> None:
        self.resetSettingRequested.emit(key)

    def _preset_changed(self, index: int) -> None:
        preset = _preset_at(index)
        self.preset_preview_label.setText(preset.preview_text)

    def _request_preset(self, _checked: bool = False) -> None:
        self.presetRequested.emit(_preset_at(self.preset_control.currentIndex()))

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
            if adapter.key in self._controls:
                self._bind_control(adapter.key, adapter.state)

    def _bind_control(self, key: SettingKey, state: SelectedSettingValue) -> None:
        control = self._controls[key]
        self._state_labels[key].setText(state.state.value.title())
        blocker = QSignalBlocker(control)
        if isinstance(control, QLineEdit):
            if state.state is SelectedSettingState.EXPLICIT:
                value = state.value
                if not isinstance(value, LanguagePreferences):
                    raise RuntimeError(
                        f"{key.value} resolved to the wrong control type."
                    )
                control.setText(value.to_mpv_value())
                control.setPlaceholderText("")
                preset_index = _language_preset_index(value)
            else:
                control.clear()
                control.setPlaceholderText(state.state.value.title())
                preset_index = 0
            preset_control = self._language_preset_controls[key]
            preset_blocker = QSignalBlocker(preset_control)
            preset_control.setCurrentIndex(preset_index)
            del preset_blocker
        elif isinstance(control, QComboBox):
            if state.state is SelectedSettingState.INHERITED:
                control.setCurrentIndex(0)
            elif state.state is SelectedSettingState.MIXED:
                control.setCurrentIndex(3)
            else:
                control.setCurrentIndex(1 if state.value is True else 2)
        else:
            if state.state is SelectedSettingState.EXPLICIT:
                value = state.value
            else:
                value = SETTING_SPEC_REGISTRY.require(key).reset_value
            if not isinstance(value, float):
                raise RuntimeError(f"{key.value} resolved to the wrong control type.")
            if isinstance(control, QSpinBox):
                control.setValue(round(value))
            else:
                control.setValue(value)
        del blocker

    def state_for(self, key: SettingKey) -> SelectedSettingValue:
        """Return the current selection state for a future field editor."""
        return self._adapters[key].state


def _settings_group(title: str, object_name: str) -> QGroupBox:
    group = QGroupBox(title)
    group.setObjectName(object_name)
    return group


def _preset_at(index: int) -> SettingsPreset:
    if not 0 <= index < len(STARTER_PRESETS):
        raise IndexError("Settings preset index is out of range.")
    return STARTER_PRESETS[index]


def _language_preset_index(preferences: LanguagePreferences) -> int:
    for index, (_label, preset) in enumerate(_LANGUAGE_PRESETS):
        if preset == preferences:
            return index
    return 0
