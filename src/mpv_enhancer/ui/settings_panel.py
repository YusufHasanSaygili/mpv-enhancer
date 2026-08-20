"""Selection-aware framework for the left settings workspace."""

from dataclasses import dataclass, field
from functools import partial
from uuid import UUID

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
    AspectRatio,
    LanguagePreferences,
    SettingKey,
    TrackSelection,
    TrackSelectionMode,
    VideoCrop,
    VideoDimensions,
)
from mpv_enhancer.infrastructure.mpv.tracks import (
    MpvTrack,
    MpvTrackType,
    TrackAvailability,
    TrackResolution,
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
    resetSettingsRequested = Signal(object)
    presetRequested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("selectedItemsSettingsPanel")
        self._adapters = {key: MixedValueAdapter(key) for key in SettingKey}
        self._controls: dict[SettingKey, SettingControl] = {}
        self._state_labels: dict[SettingKey, QLabel] = {}
        self._language_preset_controls: dict[SettingKey, QComboBox] = {}
        self._track_availability: TrackAvailability | None = None
        self._selected_items: tuple[QueueItem, ...] = ()
        self._source_dimensions: dict[UUID, VideoDimensions] = {}

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
        self._add_track_setting(
            track_layout,
            SettingKey.SUBTITLE_TRACK,
            "Subtitle Track",
            "subtitleTrackControl",
        )
        self._add_track_setting(
            track_layout,
            SettingKey.AUDIO_TRACK,
            "Audio Track",
            "audioTrackControl",
        )
        self.track_availability_label = QLabel(
            "Play an item to inspect available tracks.",
            track_group,
        )
        self.track_availability_label.setObjectName("trackAvailabilityLabel")
        self.track_availability_label.setAccessibleName("Track availability")
        self.track_availability_label.setWordWrap(True)
        track_layout.addRow(self.track_availability_label)
        self._add_boolean_setting(
            track_layout,
            SettingKey.SUBTITLE_VISIBILITY,
            "Subtitles",
            "subtitleVisibilityControl",
            "Choose whether subtitle visibility is inherited, on, or off.",
        )

        timing_group = _settings_group("Timing", "timingSettingsGroup")
        timing_layout = QFormLayout(timing_group)
        self._add_numeric_setting(
            timing_layout,
            SettingKey.SUBTITLE_DELAY,
            "Subtitle Delay",
            "subtitleDelayControl",
            "Shift subtitles from -100.00 to +100.00 seconds.",
            decimals=2,
            step=0.05,
            suffix=" s",
        )
        self._add_numeric_setting(
            timing_layout,
            SettingKey.AUDIO_DELAY,
            "Audio Delay",
            "audioDelayControl",
            "Shift audio from -100.00 to +100.00 seconds.",
            decimals=2,
            step=0.05,
            suffix=" s",
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
        self._add_aspect_ratio_setting(video_layout)
        self._add_video_crop_setting(video_layout)
        self._add_numeric_setting(
            video_layout,
            SettingKey.VIDEO_ZOOM,
            "Zoom",
            "videoZoomControl",
            "Adjust logarithmic video zoom from ¼× (-2.00) to 4× (+2.00).",
            decimals=2,
            step=0.1,
        )
        self._add_numeric_setting(
            video_layout,
            SettingKey.VIDEO_PAN_X,
            "Pan X",
            "videoPanXControl",
            "Move video horizontally from -1.00 to +1.00 of its scaled width.",
            decimals=2,
            step=0.05,
        )
        self._add_numeric_setting(
            video_layout,
            SettingKey.VIDEO_PAN_Y,
            "Pan Y",
            "videoPanYControl",
            "Move video vertically from -1.00 to +1.00 of its scaled height.",
            decimals=2,
            step=0.05,
        )
        reset_zoom_pan = QPushButton("Reset Zoom and Pan", video_group)
        reset_zoom_pan.setObjectName("resetZoomPanButton")
        reset_zoom_pan.setToolTip(
            "Restore zoom and both pan axes to their inherited values."
        )
        reset_zoom_pan.clicked.connect(self._request_zoom_pan_reset)
        video_layout.addRow(reset_zoom_pan)
        content_layout.addWidget(preset_group)
        content_layout.addWidget(playback_group)
        content_layout.addWidget(track_group)
        content_layout.addWidget(timing_group)
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

    def _add_aspect_ratio_setting(self, layout: QFormLayout) -> None:
        key = SettingKey.ASPECT_RATIO
        control = QComboBox(self)
        control.setObjectName("aspectRatioControl")
        control.setAccessibleName("Aspect Ratio")
        control.setToolTip(
            "Use media metadata automatically, choose a common ratio, or enter "
            "a positive custom width:height ratio."
        )
        control.setEditable(True)
        control.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        control.addItem("Inherited", None)
        control.addItem("Auto", AspectRatio.auto())
        for ratio in ("16:9", "21:9", "4:3"):
            control.addItem(ratio, AspectRatio.parse(ratio))
        control.addItem("Custom", "custom")
        control.addItem("Mixed", "mixed")
        control.currentIndexChanged.connect(
            partial(self._aspect_ratio_index_changed, key)
        )
        line_edit = control.lineEdit()
        if line_edit is None:
            raise RuntimeError("An editable aspect-ratio control requires a line edit.")
        line_edit.editingFinished.connect(
            partial(self._aspect_ratio_edit_finished, key)
        )
        layout.addRow("Aspect Ratio", self._editor_row(key, control))
        self._controls[key] = control

    def _add_video_crop_setting(self, layout: QFormLayout) -> None:
        key = SettingKey.VIDEO_CROP
        control = QComboBox(self)
        control.setObjectName("cropControl")
        control.setAccessibleName("Video Crop")
        control.setToolTip(
            "Use Off, enter centered WxH, or enter a custom WxH+X+Y rectangle. "
            "Every selected source must be inspected before a crop can be applied."
        )
        control.setEditable(True)
        control.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        control.addItem("Inherited", None)
        control.addItem("Off", VideoCrop.off())
        control.addItem("Centered", "centered")
        control.addItem("Custom", "custom")
        control.addItem("Mixed", "mixed")
        control.currentIndexChanged.connect(partial(self._crop_index_changed, key))
        line_edit = control.lineEdit()
        if line_edit is None:
            raise RuntimeError("An editable crop control requires a line edit.")
        line_edit.editingFinished.connect(partial(self._crop_edit_finished, key))
        layout.addRow("Crop", self._editor_row(key, control))
        self._controls[key] = control
        source_label = QLabel("Play every selected item to inspect source dimensions.")
        source_label.setObjectName("cropSourceDimensionsLabel")
        source_label.setAccessibleName("Crop source dimensions")
        source_label.setWordWrap(True)
        layout.addRow(source_label)

    def _add_track_setting(
        self,
        layout: QFormLayout,
        key: SettingKey,
        label: str,
        object_name: str,
    ) -> None:
        control = QComboBox(self)
        control.setObjectName(object_name)
        control.setAccessibleName(label)
        control.setToolTip(
            "Use automatic selection, turn this track type off, or choose a "
            "track reported by the current file."
        )
        control.currentIndexChanged.connect(partial(self._track_index_changed, key))
        layout.addRow(label, self._editor_row(key, control))
        self._controls[key] = control
        self._populate_track_control(
            key,
            SelectedSettingValue(SelectedSettingState.INHERITED),
        )

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

    def _aspect_ratio_index_changed(self, key: SettingKey, index: int) -> None:
        if index < 0:
            return
        control = self._controls[key]
        if not isinstance(control, QComboBox):
            raise RuntimeError(f"{key.value} is not an aspect-ratio editor.")
        value = control.itemData(index)
        if value is None:
            self.resetSettingRequested.emit(key)
        elif isinstance(value, AspectRatio):
            self.patchRequested.emit(SettingPatch(key, value))
        elif value == "custom":
            control.setEditText("")

    def _aspect_ratio_edit_finished(self, key: SettingKey) -> None:
        control = self._controls[key]
        if not isinstance(control, QComboBox):
            raise RuntimeError(f"{key.value} is not an aspect-ratio editor.")
        current_index = control.currentIndex()
        if current_index >= 0 and control.currentText() == control.itemText(
            current_index
        ):
            return
        try:
            ratio = AspectRatio.parse(control.currentText())
        except ValueError:
            self._state_labels[key].setText("Invalid")
            return
        control.setEditText(ratio.display_value)
        self.patchRequested.emit(SettingPatch(key, ratio))

    def _crop_index_changed(self, key: SettingKey, index: int) -> None:
        if index < 0:
            return
        control = self._controls[key]
        if not isinstance(control, QComboBox):
            raise RuntimeError(f"{key.value} is not a crop editor.")
        value = control.itemData(index)
        if value is None:
            self.resetSettingRequested.emit(key)
        elif isinstance(value, VideoCrop):
            self.patchRequested.emit(SettingPatch(key, value))
        elif value in {"centered", "custom"}:
            control.setEditText("")

    def _crop_edit_finished(self, key: SettingKey) -> None:
        control = self._controls[key]
        if not isinstance(control, QComboBox):
            raise RuntimeError(f"{key.value} is not a crop editor.")
        current_index = control.currentIndex()
        if current_index >= 0 and control.currentText() == control.itemText(
            current_index
        ):
            return
        try:
            crop = VideoCrop.parse(control.currentText())
            for item in self._selected_items:
                source = self._source_dimensions.get(item.item_id)
                if source is None:
                    raise ValueError("Source dimensions are unavailable.")
                crop.validated_for(source)
        except ValueError:
            self._state_labels[key].setText("Invalid")
            return
        control.setEditText(crop.display_value)
        self.patchRequested.emit(SettingPatch(key, crop))

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

    def _track_index_changed(self, key: SettingKey, index: int) -> None:
        if index < 0:
            return
        control = self._controls[key]
        if not isinstance(control, QComboBox):
            raise RuntimeError(f"{key.value} is not a track selector.")
        value = control.itemData(index)
        if value is None:
            self.resetSettingRequested.emit(key)
        elif isinstance(value, TrackSelection):
            self.patchRequested.emit(SettingPatch(key, value))

    def _request_setting_reset(self, key: SettingKey, _checked: bool = False) -> None:
        self.resetSettingRequested.emit(key)

    def _request_zoom_pan_reset(self, _checked: bool = False) -> None:
        self.resetSettingsRequested.emit(
            (
                SettingKey.VIDEO_ZOOM,
                SettingKey.VIDEO_PAN_X,
                SettingKey.VIDEO_PAN_Y,
            )
        )

    def _preset_changed(self, index: int) -> None:
        preset = _preset_at(index)
        self.preset_preview_label.setText(preset.preview_text)

    def _request_preset(self, _checked: bool = False) -> None:
        self.presetRequested.emit(_preset_at(self.preset_control.currentIndex()))

    def set_selected_items(self, selected_items: tuple[QueueItem, ...]) -> None:
        """Bind summary, enabled state, and mixed adapters to one selection."""
        self._selected_items = selected_items
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
        self._update_crop_source_label()

    def set_source_dimensions(
        self,
        item_id: UUID,
        dimensions: VideoDimensions | None,
    ) -> None:
        """Record decoded dimensions for safe selected-item crop validation."""
        if dimensions is None:
            self._source_dimensions.pop(item_id, None)
        else:
            self._source_dimensions[item_id] = dimensions
        self._update_crop_source_label()

    def clear_source_dimensions(self) -> None:
        """Discard runtime-only decoded dimensions when playback shuts down."""
        self._source_dimensions.clear()
        self._update_crop_source_label()

    def show_crop_validation_error(self, message: str) -> None:
        """Present a non-fatal decoded-source crop rejection."""
        self._state_labels[SettingKey.VIDEO_CROP].setText("Invalid")
        label = self.findChild(QLabel, "cropSourceDimensionsLabel")
        if label is not None:
            label.setText(message)

    def set_track_availability(
        self,
        availability: TrackAvailability | None,
    ) -> None:
        """Refresh current-file track choices without mutating item preferences."""
        self._track_availability = availability
        for key in (SettingKey.SUBTITLE_TRACK, SettingKey.AUDIO_TRACK):
            self._populate_track_control(key, self._adapters[key].state)
        self.track_availability_label.setText(_track_explanation(availability))

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
        elif isinstance(control, QComboBox) and key in {
            SettingKey.SUBTITLE_TRACK,
            SettingKey.AUDIO_TRACK,
        }:
            self._populate_track_control(key, state)
        elif isinstance(control, QComboBox) and key is SettingKey.ASPECT_RATIO:
            self._bind_aspect_ratio_control(control, state)
        elif isinstance(control, QComboBox) and key is SettingKey.VIDEO_CROP:
            self._bind_crop_control(control, state)
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

    @staticmethod
    def _bind_aspect_ratio_control(
        control: QComboBox,
        state: SelectedSettingValue,
    ) -> None:
        if state.state is SelectedSettingState.INHERITED:
            control.setCurrentIndex(0)
            return
        if state.state is SelectedSettingState.MIXED:
            control.setCurrentIndex(control.count() - 1)
            return
        value = state.value
        if not isinstance(value, AspectRatio):
            raise RuntimeError("aspect_ratio resolved to the wrong control type.")
        matching_index = next(
            (
                index
                for index in range(control.count())
                if control.itemData(index) == value
            ),
            -1,
        )
        control.setCurrentIndex(matching_index)
        if matching_index < 0:
            control.setEditText(value.display_value)

    @staticmethod
    def _bind_crop_control(
        control: QComboBox,
        state: SelectedSettingValue,
    ) -> None:
        if state.state is SelectedSettingState.INHERITED:
            control.setCurrentIndex(0)
            return
        if state.state is SelectedSettingState.MIXED:
            control.setCurrentIndex(control.count() - 1)
            return
        value = state.value
        if not isinstance(value, VideoCrop):
            raise RuntimeError("video_crop resolved to the wrong control type.")
        matching_index = next(
            (
                index
                for index in range(control.count())
                if control.itemData(index) == value
            ),
            -1,
        )
        control.setCurrentIndex(matching_index)
        if matching_index < 0:
            control.setEditText(value.display_value)

    def _update_crop_source_label(self) -> None:
        label = self.findChild(QLabel, "cropSourceDimensionsLabel")
        if label is None:
            return
        dimensions = tuple(
            self._source_dimensions.get(item.item_id) for item in self._selected_items
        )
        if not dimensions or any(value is None for value in dimensions):
            label.setText("Play every selected item to inspect source dimensions.")
            return
        known = tuple(value for value in dimensions if value is not None)
        unique = {(value.width, value.height) for value in known}
        if len(unique) == 1:
            width, height = next(iter(unique))
            label.setText(f"Selected source dimensions: {width}×{height}.")
        else:
            label.setText("Selected items have different inspected source dimensions.")

    def _populate_track_control(
        self,
        key: SettingKey,
        state: SelectedSettingValue,
    ) -> None:
        control = self._controls[key]
        if not isinstance(control, QComboBox):
            raise RuntimeError(f"{key.value} is not a track selector.")
        track_type = (
            MpvTrackType.SUBTITLE
            if key is SettingKey.SUBTITLE_TRACK
            else MpvTrackType.AUDIO
        )
        available = (
            ()
            if self._track_availability is None
            else tuple(
                track
                for track in self._track_availability.tracks
                if track.track_type is track_type
            )
        )
        blocker = QSignalBlocker(control)
        control.clear()
        control.addItem("Inherited", None)
        control.addItem("Auto", TrackSelection.auto())
        control.addItem("Off", TrackSelection.off())
        for track in available:
            control.addItem(
                _track_label(track),
                TrackSelection.specific(track.track_id),
            )
        explicit = state.value if state.state is SelectedSettingState.EXPLICIT else None
        if (
            isinstance(explicit, TrackSelection)
            and explicit.mode is TrackSelectionMode.SPECIFIC
            and all(track.track_id != explicit.track_id for track in available)
        ):
            control.addItem(
                f"Unavailable track ID {explicit.track_id}",
                explicit,
            )
        control.addItem("Mixed", "mixed")
        if state.state is SelectedSettingState.INHERITED:
            selected_index = 0
        elif state.state is SelectedSettingState.MIXED:
            selected_index = control.count() - 1
        elif isinstance(explicit, TrackSelection):
            selected_index = next(
                (
                    index
                    for index in range(control.count())
                    if control.itemData(index) == explicit
                ),
                0,
            )
        else:
            selected_index = 0
        control.setCurrentIndex(selected_index)
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


def _track_label(track: MpvTrack) -> str:
    description = track.title or track.language or "Untagged"
    if track.title is not None and track.language is not None:
        description = f"{description} ({track.language})"
    flags = []
    if track.is_default:
        flags.append("default")
    if track.is_forced:
        flags.append("forced")
    if track.is_external:
        flags.append("external")
    suffix = f" [{', '.join(flags)}]" if flags else ""
    return f"{track.track_id} — {description}{suffix}"


def _track_explanation(availability: TrackAvailability | None) -> str:
    if availability is None:
        return "Play an item to inspect available tracks."
    if not availability.tracks:
        return "No selectable audio or subtitle tracks were reported."
    messages = []
    for label, resolution in (
        ("Subtitle", availability.subtitle),
        ("Audio", availability.audio),
    ):
        if resolution.used_fallback:
            messages.append(_fallback_explanation(label, resolution))
    return (
        " ".join(messages)
        if messages
        else "Available tracks are from the currently playing item."
    )


def _fallback_explanation(label: str, resolution: TrackResolution) -> str:
    selection = resolution.selection
    if selection.mode is TrackSelectionMode.SPECIFIC:
        return f"{label} preference is unavailable; using track {selection.track_id}."
    if selection.mode is TrackSelectionMode.OFF:
        return f"{label} preference is unavailable; this track type is off."
    return f"{label} preference is unavailable; using automatic selection."
