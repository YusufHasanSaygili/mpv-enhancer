from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QLabel, QPushButton

from mpv_enhancer.domain.models import QueueItem
from mpv_enhancer.domain.presets import STARTER_PRESETS, PresetKey
from mpv_enhancer.domain.selection_settings import SettingPatch
from mpv_enhancer.domain.settings import PlaybackSettings, SettingKey
from mpv_enhancer.ui.main_window import MainWindow
from mpv_enhancer.ui.queue_model import QueueRole, override_summary
from mpv_enhancer.ui.settings_panel import SelectedItemsSettingsPanel


def _item(number: int) -> QueueItem:
    return QueueItem.create(Path("synthetic") / f"episode-{number:02}.mkv")


def test_starter_preset_previews_match_every_declared_patch() -> None:
    assert [preset.key for preset in STARTER_PRESETS] == [
        PresetKey.DEFAULT,
        PresetKey.PLAYBACK_1_2X,
        PresetKey.FILL_DISPLAY,
        PresetKey.SUBTITLES_ON,
        PresetKey.SUBTITLES_OFF,
    ]
    assert STARTER_PRESETS[0].reset_all
    assert STARTER_PRESETS[0].patches == ()
    assert STARTER_PRESETS[0].preview_text == "All overrides → Inherited"
    assert [preset.preview_text for preset in STARTER_PRESETS[1:]] == [
        "Speed → 1.2×",
        "Pan and Scan → 1.0",
        "Subtitles → On",
        "Subtitles → Off",
    ]
    assert [preset.patches for preset in STARTER_PRESETS[1:]] == [
        (SettingPatch(SettingKey.SPEED, 1.2),),
        (SettingPatch(SettingKey.PANSCAN, 1.0),),
        (SettingPatch(SettingKey.SUBTITLE_VISIBILITY, True),),
        (SettingPatch(SettingKey.SUBTITLE_VISIBILITY, False),),
    ]


def test_preset_picker_shows_preview_and_emits_the_exact_preset(qtbot) -> None:
    panel = SelectedItemsSettingsPanel()
    qtbot.addWidget(panel)
    panel.set_selected_items((_item(1),))
    picker = panel.findChild(QComboBox, "presetControl")
    preview = panel.findChild(QLabel, "presetPreviewLabel")
    apply_button = panel.findChild(QPushButton, "applyPresetButton")
    assert picker is not None
    assert preview is not None
    assert apply_button is not None
    requested = []
    panel.presetRequested.connect(requested.append)

    picker.setCurrentIndex(2)

    assert picker.currentText() == "Fill Display"
    assert preview.text() == "Pan and Scan → 1.0"
    qtbot.mouseClick(apply_button, Qt.MouseButton.LeftButton)
    assert requested == [STARTER_PRESETS[2]]


def test_badges_update_after_preset_apply_and_default_reset(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    item = _item(1)
    window.queue_model.insert_item(0, item)
    window.queue_view.select_item_ids((item.item_id,))
    picker = window.settings_panel.findChild(QComboBox, "presetControl")
    apply_button = window.settings_panel.findChild(QPushButton, "applyPresetButton")
    assert picker is not None
    assert apply_button is not None
    index = window.queue_model.index(0, 0)

    picker.setCurrentIndex(1)
    qtbot.mouseClick(apply_button, Qt.MouseButton.LeftButton)

    assert window.queue_model.items[0].overrides == PlaybackSettings(speed=1.2)
    assert window.queue_model.data(index, QueueRole.OverrideSummary) == "1.2×"

    picker.setCurrentIndex(0)
    qtbot.mouseClick(apply_button, Qt.MouseButton.LeftButton)

    assert window.queue_model.items[0].overrides == PlaybackSettings()
    assert window.queue_model.data(index, QueueRole.OverrideSummary) == "No overrides"


def test_override_summary_is_compact_and_uses_stable_registry_order() -> None:
    settings = PlaybackSettings(
        speed=1.2,
        panscan=1.0,
        volume=80.0,
        mute=True,
        subtitle_visibility=False,
    )

    assert override_summary(settings) == "1.2× · Fill · 80% · Muted · Subs Off"
