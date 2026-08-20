from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
)

from mpv_enhancer.domain.models import QueueItem
from mpv_enhancer.domain.selection_settings import SelectedSettingState, SettingPatch
from mpv_enhancer.domain.settings import PlaybackSettings, SettingKey
from mpv_enhancer.ui.settings_panel import SelectedItemsSettingsPanel


def _item(number: int, overrides: PlaybackSettings | None = None) -> QueueItem:
    return QueueItem.create(
        Path(f"synthetic/episode-{number:02}.mkv"),
        overrides=overrides,
    )


def test_settings_panel_has_grouped_scroll_area_and_apply_reset_actions(qtbot) -> None:
    panel = SelectedItemsSettingsPanel()
    qtbot.addWidget(panel)

    assert panel.findChild(QScrollArea, "settingsScrollArea") is not None
    assert _group_title(panel, "playbackSettingsGroup") == "Playback"
    assert _group_title(panel, "trackSettingsGroup") == "Tracks"
    assert _group_title(panel, "videoSettingsGroup") == "Video"
    assert _button(panel, "applySettingsButton").text() == "Apply"
    assert _button(panel, "resetAllSettingsButton").text() == "Reset All"


def test_zero_selection_disables_the_settings_workspace(qtbot) -> None:
    panel = SelectedItemsSettingsPanel()
    qtbot.addWidget(panel)

    panel.set_selected_items(())

    assert panel.selection_summary_label.text() == "No queue items selected"
    assert not panel.settings_content.isEnabled()
    assert not _button(panel, "applySettingsButton").isEnabled()
    assert not _button(panel, "resetAllSettingsButton").isEnabled()


def test_one_selection_enables_inherited_field_adapters(qtbot) -> None:
    panel = SelectedItemsSettingsPanel()
    qtbot.addWidget(panel)

    panel.set_selected_items((_item(1),))

    assert panel.selection_summary_label.text() == "1 queue item selected"
    assert panel.settings_content.isEnabled()
    assert all(
        panel.state_for(key).state is SelectedSettingState.INHERITED
        for key in SettingKey
    )


def test_same_value_multi_selection_is_explicit(qtbot) -> None:
    panel = SelectedItemsSettingsPanel()
    qtbot.addWidget(panel)
    shared = PlaybackSettings(speed=1.2)

    panel.set_selected_items((_item(1, shared), _item(2, shared)))

    state = panel.state_for(SettingKey.SPEED)
    assert panel.selection_summary_label.text() == "2 queue items selected"
    assert state.state is SelectedSettingState.EXPLICIT
    assert state.value == 1.2


def test_different_value_multi_selection_is_mixed(qtbot) -> None:
    panel = SelectedItemsSettingsPanel()
    qtbot.addWidget(panel)

    panel.set_selected_items(
        (
            _item(1, PlaybackSettings(speed=1.2)),
            _item(2, PlaybackSettings(speed=1.5)),
        )
    )

    assert panel.state_for(SettingKey.SPEED).state is SelectedSettingState.MIXED


@pytest.mark.parametrize(
    ("key", "name", "minimum", "maximum", "default"),
    [
        (SettingKey.SPEED, "speedControl", 0.25, 4.0, 1.0),
        (SettingKey.PANSCAN, "panscanControl", 0.0, 1.0, 0.0),
        (SettingKey.VOLUME, "volumeControl", 0.0, 130.0, 100.0),
    ],
)
def test_numeric_controls_emit_validated_patches_at_limits_and_default(
    qtbot,
    key: SettingKey,
    name: str,
    minimum: float,
    maximum: float,
    default: float,
) -> None:
    panel = SelectedItemsSettingsPanel()
    qtbot.addWidget(panel)
    panel.set_selected_items((_item(1),))
    control_type = QSpinBox if key is SettingKey.VOLUME else QDoubleSpinBox
    control = panel.findChild(control_type, name)
    assert control is not None
    patches = []
    panel.patchRequested.connect(patches.append)

    for value in (minimum, maximum, default):
        control.setValue(maximum if value == minimum else minimum)
        patches.clear()
        control.setValue(value)
        assert patches == [SettingPatch(key, value)]
    assert control.toolTip()


@pytest.mark.parametrize(
    ("key", "name"),
    [
        (SettingKey.MUTE, "muteControl"),
        (SettingKey.SUBTITLE_VISIBILITY, "subtitleVisibilityControl"),
    ],
)
def test_boolean_controls_support_inherited_on_off_and_mixed_states(
    qtbot,
    key: SettingKey,
    name: str,
) -> None:
    panel = SelectedItemsSettingsPanel()
    qtbot.addWidget(panel)
    panel.set_selected_items((_item(1),))
    control = panel.findChild(QComboBox, name)
    assert control is not None
    patches = []
    resets = []
    panel.patchRequested.connect(patches.append)
    panel.resetSettingRequested.connect(resets.append)

    control.setCurrentIndex(1)
    control.setCurrentIndex(2)
    control.setCurrentIndex(0)

    assert patches == [SettingPatch(key, True), SettingPatch(key, False)]
    assert resets == [key]
    assert control.toolTip()

    panel.set_selected_items(
        (
            _item(1, PlaybackSettings(**{key.value: True})),
            _item(2, PlaybackSettings(**{key.value: False})),
        )
    )
    assert control.currentText() == "Mixed"
    state_label = panel.findChild(QLabel, f"{key.value}StateLabel")
    assert state_label is not None
    assert state_label.text() == "Mixed"


def test_numeric_control_binds_explicit_and_mixed_states_and_can_reset(qtbot) -> None:
    panel = SelectedItemsSettingsPanel()
    qtbot.addWidget(panel)
    control = panel.findChild(QDoubleSpinBox, "speedControl")
    state_label = panel.findChild(QLabel, "speedStateLabel")
    assert control is not None
    assert state_label is not None

    panel.set_selected_items(
        (
            _item(1, PlaybackSettings(speed=1.2)),
            _item(2, PlaybackSettings(speed=1.2)),
        )
    )
    assert control.value() == 1.2
    assert state_label.text() == "Explicit"

    panel.set_selected_items(
        (
            _item(1, PlaybackSettings(speed=1.2)),
            _item(2, PlaybackSettings(speed=1.5)),
        )
    )
    assert state_label.text() == "Mixed"

    resets = []
    panel.resetSettingRequested.connect(resets.append)
    qtbot.mouseClick(_button(panel, "speedResetButton"), Qt.MouseButton.LeftButton)
    assert resets == [SettingKey.SPEED]


def _group_title(panel: SelectedItemsSettingsPanel, name: str) -> str:
    group = panel.findChild(QGroupBox, name)
    assert group is not None
    return group.title()


def _button(panel: SelectedItemsSettingsPanel, name: str) -> QPushButton:
    button = panel.findChild(QPushButton, name)
    assert button is not None
    return button
