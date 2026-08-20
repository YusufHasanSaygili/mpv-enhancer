from collections.abc import Sequence
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDoubleSpinBox, QPushButton

from mpv_enhancer.domain.models import QueueItem
from mpv_enhancer.domain.selection_settings import SettingPatch
from mpv_enhancer.domain.settings import (
    AspectRatio,
    EffectivePlaybackSettings,
    PlaybackSettings,
    SettingKey,
)
from mpv_enhancer.infrastructure.mpv.json_ipc import JsonValue
from mpv_enhancer.infrastructure.mpv.settings_adapter import MpvSettingsAdapter
from mpv_enhancer.ui.main_window import MainWindow
from mpv_enhancer.ui.queue_model import override_summary
from mpv_enhancer.ui.settings_panel import SelectedItemsSettingsPanel


class RecordingIpcClient:
    def __init__(self) -> None:
        self.commands: list[tuple[JsonValue, ...]] = []

    def request(self, command: Sequence[JsonValue]) -> object:
        self.commands.append(tuple(command))
        return object()


def _item(number: int, overrides: PlaybackSettings | None = None) -> QueueItem:
    return QueueItem.create(
        Path(f"synthetic/episode-{number:02}.mkv"),
        overrides=overrides,
    )


@pytest.mark.parametrize(
    ("key", "name", "minimum", "maximum"),
    [
        (SettingKey.VIDEO_ZOOM, "videoZoomControl", -2.0, 2.0),
        (SettingKey.VIDEO_PAN_X, "videoPanXControl", -1.0, 1.0),
        (SettingKey.VIDEO_PAN_Y, "videoPanYControl", -1.0, 1.0),
    ],
)
def test_zoom_pan_editors_apply_inclusive_safe_boundaries(
    qtbot,
    key: SettingKey,
    name: str,
    minimum: float,
    maximum: float,
) -> None:
    panel = SelectedItemsSettingsPanel()
    qtbot.addWidget(panel)
    panel.set_selected_items((_item(1),))
    control = panel.findChild(QDoubleSpinBox, name)
    assert control is not None
    patches: list[SettingPatch] = []
    panel.patchRequested.connect(patches.append)

    assert control.minimum() == minimum
    assert control.maximum() == maximum
    assert control.value() == 0.0
    for value in (minimum, maximum, 0.0):
        control.setValue(maximum if value == minimum else minimum)
        patches.clear()
        control.setValue(value)
        assert patches == [SettingPatch(key, value)]


@pytest.mark.parametrize(
    ("key", "invalid"),
    [
        (SettingKey.VIDEO_ZOOM, -2.001),
        (SettingKey.VIDEO_ZOOM, 2.001),
        (SettingKey.VIDEO_PAN_X, -1.001),
        (SettingKey.VIDEO_PAN_X, 1.001),
        (SettingKey.VIDEO_PAN_Y, float("inf")),
    ],
)
def test_zoom_pan_domain_rejects_values_outside_safe_bounds(
    key: SettingKey,
    invalid: float,
) -> None:
    with pytest.raises(ValueError, match="valid"):
        PlaybackSettings().with_value(key, invalid)


def test_linked_reset_clears_only_zoom_and_pan_for_selected_items(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    aspect = AspectRatio.parse("16:9")
    item = _item(
        1,
        PlaybackSettings(
            aspect_ratio=aspect,
            video_zoom=1.0,
            video_pan_x=0.5,
            video_pan_y=-0.25,
        ),
    )
    window.queue_model.insert_item(0, item)
    window.queue_view.select_item_ids((item.item_id,))
    reset = window.settings_panel.findChild(QPushButton, "resetZoomPanButton")
    assert reset is not None

    qtbot.mouseClick(reset, Qt.MouseButton.LeftButton)

    assert window.queue_model.items[0].overrides == PlaybackSettings(
        aspect_ratio=aspect
    )


def test_adapter_resets_and_applies_zoom_and_pan_live() -> None:
    client = RecordingIpcClient()
    adapter = MpvSettingsAdapter(client)

    adapter.apply(
        EffectivePlaybackSettings(
            speed=1.0,
            panscan=0.0,
            volume=100.0,
            mute=False,
            subtitle_visibility=True,
            video_zoom=1.0,
            video_pan_x=-0.25,
            video_pan_y=0.5,
        )
    )

    assert [
        command
        for command in client.commands
        if command[1] in {"video-zoom", "video-pan-x", "video-pan-y"}
    ] == [
        ("set_property", "video-zoom", 0.0),
        ("set_property", "video-pan-x", 0.0),
        ("set_property", "video-pan-y", 0.0),
        ("set_property", "video-zoom", 1.0),
        ("set_property", "video-pan-x", -0.25),
        ("set_property", "video-pan-y", 0.5),
    ]


def test_zoom_pan_override_badges_follow_video_setting_order() -> None:
    settings = PlaybackSettings(
        video_zoom=1.0,
        video_pan_x=-0.25,
        video_pan_y=0.5,
    )

    assert override_summary(settings) == "Zoom +1 · Pan X -0.25 · Pan Y +0.5"
