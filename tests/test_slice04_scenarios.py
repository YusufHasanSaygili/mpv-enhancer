from pathlib import Path

from PySide6.QtWidgets import QDoubleSpinBox

from mpv_enhancer.domain.models import QueueItem
from mpv_enhancer.domain.selection_settings import SelectedSettingState
from mpv_enhancer.domain.settings import PlaybackSettings, SettingKey
from mpv_enhancer.ui.main_window import MainWindow
from mpv_enhancer.ui.queue_model import QueueRole


def test_episodes_two_four_six_receive_only_the_intended_settings(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    items = [
        QueueItem.create(
            Path("synthetic") / f"episode-{number:02}.mkv",
            overrides=(PlaybackSettings(volume=80.0) if number == 4 else None),
        )
        for number in range(1, 7)
    ]
    for row, item in enumerate(items):
        window.queue_model.insert_item(row, item)
    selected = (items[1].item_id, items[3].item_id, items[5].item_id)
    window.queue_view.select_item_ids(selected)
    speed = window.settings_panel.findChild(QDoubleSpinBox, "speedControl")
    panscan = window.settings_panel.findChild(QDoubleSpinBox, "panscanControl")
    assert speed is not None
    assert panscan is not None

    speed.setValue(1.2)
    window.queue_view.select_item_ids((items[3].item_id,))
    panscan.setValue(0.75)

    assert [item.overrides for item in window.queue_model.items] == [
        PlaybackSettings(),
        PlaybackSettings(speed=1.2),
        PlaybackSettings(),
        PlaybackSettings(speed=1.2, panscan=0.75, volume=80.0),
        PlaybackSettings(),
        PlaybackSettings(speed=1.2),
    ]
    assert [
        window.queue_model.data(
            window.queue_model.index(row, 0),
            QueueRole.OverrideSummary,
        )
        for row in range(6)
    ] == [
        "No overrides",
        "1.2×",
        "No overrides",
        "1.2× · Pan 0.75 · 80%",
        "No overrides",
        "1.2×",
    ]

    window.queue_view.select_item_ids(selected)

    speed_state = window.settings_panel.state_for(SettingKey.SPEED)
    panscan_state = window.settings_panel.state_for(SettingKey.PANSCAN)
    assert speed_state.state is SelectedSettingState.EXPLICIT
    assert speed_state.value == 1.2
    assert panscan_state.state is SelectedSettingState.MIXED
    assert window.queue_view.selected_item_ids == selected
