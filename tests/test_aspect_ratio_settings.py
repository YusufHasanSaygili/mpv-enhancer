from collections.abc import Sequence
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QLabel, QPushButton

from mpv_enhancer.domain.models import QueueItem
from mpv_enhancer.domain.selection_settings import (
    SelectedSettingState,
    SettingPatch,
)
from mpv_enhancer.domain.settings import (
    AspectRatio,
    AspectRatioMode,
    EffectivePlaybackSettings,
    EffectiveSettingsResolver,
    PlaybackSettings,
    SettingKey,
)
from mpv_enhancer.infrastructure.mpv.json_ipc import JsonValue
from mpv_enhancer.infrastructure.mpv.settings_adapter import MpvSettingsAdapter
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
    ("text", "mode", "mpv_value"),
    [
        ("auto", AspectRatioMode.AUTO, "no"),
        (" 16 : 9 ", AspectRatioMode.COMMON, "16:9"),
        ("21:9", AspectRatioMode.COMMON, "21:9"),
        ("4:3", AspectRatioMode.COMMON, "4:3"),
        ("2.390:1.0", AspectRatioMode.CUSTOM, "2.39:1"),
        ("1920:1080", AspectRatioMode.CUSTOM, "1920:1080"),
    ],
)
def test_aspect_ratio_parser_returns_typed_normalized_values(
    text: str,
    mode: AspectRatioMode,
    mpv_value: str,
) -> None:
    ratio = AspectRatio.parse(text)

    assert ratio.mode is mode
    assert ratio.to_mpv_value() == mpv_value
    assert ratio.display_value == (
        "Auto" if mode is AspectRatioMode.AUTO else mpv_value
    )


@pytest.mark.parametrize(
    "text",
    ["", "no", "16", "16/9", "0:9", "16:0", "-16:9", "nan:1", "1:inf", "1::1"],
)
def test_aspect_ratio_parser_rejects_invalid_or_raw_mpv_values(text: str) -> None:
    with pytest.raises(ValueError, match="aspect ratio"):
        AspectRatio.parse(text)


def test_aspect_ratio_setting_rejects_untyped_text_before_adapter_boundary() -> None:
    with pytest.raises(ValueError, match="typed aspect ratio"):
        PlaybackSettings(aspect_ratio="16:9")  # type: ignore[arg-type]


def test_aspect_ratio_resolves_inheritance_and_resets_to_auto() -> None:
    custom = AspectRatio.parse("2.39:1")
    resolved = EffectiveSettingsResolver().resolve(
        playlist_defaults=PlaybackSettings(aspect_ratio=AspectRatio.parse("16:9")),
        item_overrides=PlaybackSettings(aspect_ratio=custom),
    )

    assert resolved.aspect_ratio == custom
    assert (
        PlaybackSettings(aspect_ratio=custom).without_value(SettingKey.ASPECT_RATIO)
        == PlaybackSettings()
    )
    assert EffectiveSettingsResolver().resolve().aspect_ratio == AspectRatio.auto()


def test_adapter_maps_auto_and_custom_aspect_ratio_to_allowlisted_mpv_property() -> (
    None
):
    client = RecordingIpcClient()
    adapter = MpvSettingsAdapter(client)

    adapter.apply(
        EffectivePlaybackSettings(
            speed=1.0,
            panscan=0.0,
            volume=100.0,
            mute=False,
            subtitle_visibility=True,
            aspect_ratio=AspectRatio.parse("2.39:1"),
        )
    )

    assert [
        command for command in client.commands if "video-aspect-override" in command
    ] == [
        ("set_property", "video-aspect-override", "no"),
        ("set_property", "video-aspect-override", "2.39:1"),
    ]


def test_aspect_editor_supports_inherited_common_custom_mixed_and_reset(qtbot) -> None:
    panel = SelectedItemsSettingsPanel()
    qtbot.addWidget(panel)
    control = panel.findChild(QComboBox, "aspectRatioControl")
    state_label = panel.findChild(QLabel, "aspect_ratioStateLabel")
    reset = panel.findChild(QPushButton, "aspect_ratioResetButton")
    assert control is not None
    assert state_label is not None
    assert reset is not None
    patches: list[SettingPatch] = []
    resets: list[SettingKey] = []
    panel.patchRequested.connect(patches.append)
    panel.resetSettingRequested.connect(resets.append)

    panel.set_selected_items((_item(1),))
    assert control.currentText() == "Inherited"
    assert state_label.text() == "Inherited"
    assert [control.itemText(index) for index in range(control.count())] == [
        "Inherited",
        "Auto",
        "16:9",
        "21:9",
        "4:3",
        "Custom",
        "Mixed",
    ]

    control.setCurrentIndex(control.findText("16:9"))
    assert patches == [SettingPatch(SettingKey.ASPECT_RATIO, AspectRatio.parse("16:9"))]

    patches.clear()
    control.setCurrentIndex(control.findText("Auto"))
    assert patches == [SettingPatch(SettingKey.ASPECT_RATIO, AspectRatio.auto())]

    patches.clear()
    control.setEditText("2.39:1")
    line_edit = control.lineEdit()
    assert line_edit is not None
    line_edit.editingFinished.emit()
    assert patches == [
        SettingPatch(SettingKey.ASPECT_RATIO, AspectRatio.parse("2.39:1"))
    ]

    patches.clear()
    control.setEditText("16/9")
    line_edit.editingFinished.emit()
    assert patches == []
    assert state_label.text() == "Invalid"

    panel.set_selected_items(
        (
            _item(1, PlaybackSettings(aspect_ratio=AspectRatio.parse("16:9"))),
            _item(2, PlaybackSettings(aspect_ratio=AspectRatio.parse("4:3"))),
        )
    )
    assert panel.state_for(SettingKey.ASPECT_RATIO).state is SelectedSettingState.MIXED
    assert control.currentText() == "Mixed"
    assert state_label.text() == "Mixed"

    qtbot.mouseClick(reset, Qt.MouseButton.LeftButton)
    assert resets == [SettingKey.ASPECT_RATIO]
