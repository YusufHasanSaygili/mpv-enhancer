from pathlib import Path

from PySide6.QtWidgets import QGroupBox, QPushButton, QScrollArea

from mpv_enhancer.domain.models import QueueItem
from mpv_enhancer.domain.selection_settings import SelectedSettingState
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


def _group_title(panel: SelectedItemsSettingsPanel, name: str) -> str:
    group = panel.findChild(QGroupBox, name)
    assert group is not None
    return group.title()


def _button(panel: SelectedItemsSettingsPanel, name: str) -> QPushButton:
    button = panel.findChild(QPushButton, name)
    assert button is not None
    return button
