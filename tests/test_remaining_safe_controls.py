from collections.abc import Sequence
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QPushButton, QSpinBox

from mpv_enhancer.domain.models import QueueItem
from mpv_enhancer.domain.selection_settings import SettingPatch
from mpv_enhancer.domain.settings import (
    SETTING_SPEC_REGISTRY,
    EffectivePlaybackSettings,
    PlaybackSettings,
    SettingKey,
    SettingValue,
    SettingValueType,
    VideoRotation,
)
from mpv_enhancer.infrastructure.mpv.json_ipc import JsonValue
from mpv_enhancer.infrastructure.mpv.settings_adapter import MpvSettingsAdapter
from mpv_enhancer.ui.queue_model import override_summary
from mpv_enhancer.ui.settings_panel import SelectedItemsSettingsPanel


class RecordingIpcClient:
    def __init__(self) -> None:
        self.commands: list[tuple[JsonValue, ...]] = []

    def request(self, command: Sequence[JsonValue]) -> object:
        self.commands.append(tuple(command))
        return object()


def _item(overrides: PlaybackSettings | None = None) -> QueueItem:
    return QueueItem.create(
        Path("synthetic/episode-01.mkv"),
        overrides=overrides,
    )


@pytest.mark.parametrize(
    ("key", "property_name", "value_type", "minimum", "maximum", "reset"),
    [
        (
            SettingKey.VIDEO_ROTATION,
            "video-rotate",
            SettingValueType.VIDEO_ROTATION,
            None,
            None,
            VideoRotation.AUTO,
        ),
        (
            SettingKey.DEINTERLACE,
            "deinterlace",
            SettingValueType.BOOLEAN,
            None,
            None,
            False,
        ),
        (
            SettingKey.BRIGHTNESS,
            "brightness",
            SettingValueType.NUMBER,
            -100.0,
            100.0,
            0.0,
        ),
        (
            SettingKey.CONTRAST,
            "contrast",
            SettingValueType.NUMBER,
            -100.0,
            100.0,
            0.0,
        ),
        (
            SettingKey.GAMMA,
            "gamma",
            SettingValueType.NUMBER,
            -100.0,
            100.0,
            0.0,
        ),
        (
            SettingKey.SATURATION,
            "saturation",
            SettingValueType.NUMBER,
            -100.0,
            100.0,
            0.0,
        ),
        (
            SettingKey.AUDIO_DELAY,
            "audio-delay",
            SettingValueType.NUMBER,
            -100.0,
            100.0,
            0.0,
        ),
    ],
)
def test_every_remaining_control_has_reviewed_spec_metadata(
    key: SettingKey,
    property_name: str,
    value_type: SettingValueType,
    minimum: float | None,
    maximum: float | None,
    reset: object,
) -> None:
    spec = SETTING_SPEC_REGISTRY.require(key)

    assert (
        spec.mpv_property,
        spec.value_type,
        spec.minimum,
        spec.maximum,
        spec.reset_value,
        spec.apply_live,
    ) == (property_name, value_type, minimum, maximum, reset, True)


@pytest.mark.parametrize(
    ("key", "name"),
    [
        (SettingKey.BRIGHTNESS, "brightnessControl"),
        (SettingKey.CONTRAST, "contrastControl"),
        (SettingKey.GAMMA, "gammaControl"),
        (SettingKey.SATURATION, "saturationControl"),
    ],
)
def test_image_editors_apply_inclusive_boundaries_and_reset(
    qtbot,
    key: SettingKey,
    name: str,
) -> None:
    panel = SelectedItemsSettingsPanel()
    qtbot.addWidget(panel)
    panel.set_selected_items((_item(PlaybackSettings().with_value(key, 25.0)),))
    control = panel.findChild(QSpinBox, name)
    reset = panel.findChild(QPushButton, f"{key.value}ResetButton")
    assert control is not None
    assert reset is not None
    assert (control.minimum(), control.maximum()) == (-100, 100)
    patches: list[SettingPatch] = []
    resets: list[SettingKey] = []
    panel.patchRequested.connect(patches.append)
    panel.resetSettingRequested.connect(resets.append)

    for value in (-100, 100, 0):
        control.setValue(1 if value == 0 else 0)
        patches.clear()
        control.setValue(value)
        assert patches == [SettingPatch(key, float(value))]
    qtbot.mouseClick(reset, Qt.MouseButton.LeftButton)
    assert resets == [key]


def test_rotation_editor_exposes_only_reviewed_choices_and_reset(qtbot) -> None:
    panel = SelectedItemsSettingsPanel()
    qtbot.addWidget(panel)
    panel.set_selected_items((_item(),))
    control = panel.findChild(QComboBox, "videoRotationControl")
    reset = panel.findChild(QPushButton, "video_rotationResetButton")
    assert control is not None
    assert reset is not None
    assert [control.itemText(index) for index in range(control.count())] == [
        "Inherited",
        "Auto",
        "0°",
        "90°",
        "180°",
        "270°",
        "Mixed",
    ]
    patches: list[SettingPatch] = []
    resets: list[SettingKey] = []
    panel.patchRequested.connect(patches.append)
    panel.resetSettingRequested.connect(resets.append)

    control.setCurrentIndex(control.findData(VideoRotation.DEG_90))
    assert patches == [SettingPatch(SettingKey.VIDEO_ROTATION, VideoRotation.DEG_90)]
    qtbot.mouseClick(reset, Qt.MouseButton.LeftButton)
    assert resets == [SettingKey.VIDEO_ROTATION]


def test_deinterlace_editor_uses_inherited_on_off_and_reset(qtbot) -> None:
    panel = SelectedItemsSettingsPanel()
    qtbot.addWidget(panel)
    panel.set_selected_items((_item(),))
    control = panel.findChild(QComboBox, "deinterlaceControl")
    reset = panel.findChild(QPushButton, "deinterlaceResetButton")
    assert control is not None
    assert reset is not None
    patches: list[SettingPatch] = []
    resets: list[SettingKey] = []
    panel.patchRequested.connect(patches.append)
    panel.resetSettingRequested.connect(resets.append)

    control.setCurrentIndex(1)
    control.setCurrentIndex(2)
    assert patches == [
        SettingPatch(SettingKey.DEINTERLACE, True),
        SettingPatch(SettingKey.DEINTERLACE, False),
    ]
    qtbot.mouseClick(reset, Qt.MouseButton.LeftButton)
    assert resets == [SettingKey.DEINTERLACE]


@pytest.mark.parametrize(
    ("key", "invalid"),
    [
        (SettingKey.BRIGHTNESS, -100.001),
        (SettingKey.CONTRAST, 100.001),
        (SettingKey.GAMMA, float("nan")),
        (SettingKey.SATURATION, float("inf")),
        (SettingKey.DEINTERLACE, 1),
        (SettingKey.VIDEO_ROTATION, 90),
        (SettingKey.AUDIO_DELAY, -100.001),
    ],
)
def test_remaining_controls_reject_unreviewed_or_out_of_range_values(
    key: SettingKey,
    invalid: object,
) -> None:
    with pytest.raises(ValueError):
        PlaybackSettings().with_value(key, invalid)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("key", "value"),
    [
        (SettingKey.VIDEO_ROTATION, VideoRotation.DEG_180),
        (SettingKey.DEINTERLACE, True),
        (SettingKey.BRIGHTNESS, -25.0),
        (SettingKey.CONTRAST, 50.0),
        (SettingKey.GAMMA, 10.0),
        (SettingKey.SATURATION, 75.0),
        (SettingKey.AUDIO_DELAY, -1.25),
    ],
)
def test_every_remaining_control_can_reset_to_inherited(
    key: SettingKey,
    value: SettingValue,
) -> None:
    settings = PlaybackSettings().with_value(key, value)

    assert settings.without_value(key) == PlaybackSettings()


def test_adapter_resets_and_maps_every_remaining_control_live() -> None:
    client = RecordingIpcClient()
    MpvSettingsAdapter(client).apply(
        EffectivePlaybackSettings(
            speed=1.0,
            panscan=0.0,
            volume=100.0,
            mute=False,
            subtitle_visibility=True,
            video_rotation=VideoRotation.DEG_270,
            deinterlace=True,
            brightness=-25.0,
            contrast=50.0,
            gamma=10.0,
            saturation=75.0,
            audio_delay=-1.25,
        )
    )

    properties = {
        "video-rotate",
        "deinterlace",
        "brightness",
        "contrast",
        "gamma",
        "saturation",
        "audio-delay",
    }
    assert [command for command in client.commands if command[1] in properties] == [
        ("set_property", "video-rotate", "no"),
        ("set_property", "deinterlace", False),
        ("set_property", "brightness", 0.0),
        ("set_property", "contrast", 0.0),
        ("set_property", "gamma", 0.0),
        ("set_property", "saturation", 0.0),
        ("set_property", "audio-delay", 0.0),
        ("set_property", "video-rotate", 270),
        ("set_property", "deinterlace", True),
        ("set_property", "brightness", -25.0),
        ("set_property", "contrast", 50.0),
        ("set_property", "gamma", 10.0),
        ("set_property", "saturation", 75.0),
        ("set_property", "audio-delay", -1.25),
    ]


def test_remaining_control_badges_follow_reviewed_display_order() -> None:
    settings = PlaybackSettings(
        video_rotation=VideoRotation.DEG_90,
        deinterlace=True,
        brightness=-25.0,
        contrast=50.0,
        gamma=10.0,
        saturation=75.0,
        audio_delay=-1.25,
    )

    assert override_summary(settings) == (
        "Rotate 90° · Deinterlace On · Bright -25 · Contrast +50 · "
        "Gamma +10 · Saturation +75 · Audio -1.25s"
    )
