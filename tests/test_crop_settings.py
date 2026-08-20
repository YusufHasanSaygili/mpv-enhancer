from collections.abc import Sequence
from concurrent.futures import Future
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QLabel, QPushButton

from mpv_enhancer.domain.models import Playlist, QueueItem
from mpv_enhancer.domain.selection_settings import SelectedSettingState, SettingPatch
from mpv_enhancer.domain.settings import (
    PlaybackSettings,
    SettingKey,
    VideoCrop,
    VideoCropMode,
    VideoDimensions,
)
from mpv_enhancer.infrastructure.mpv.json_ipc import (
    JsonValue,
    MpvIpcEvent,
    MpvIpcRequest,
)
from mpv_enhancer.infrastructure.mpv.playback import MpvJsonPlaybackAdapter
from mpv_enhancer.infrastructure.mpv.settings_adapter import (
    MpvSettingsAdapter,
    normalize_video_dimensions,
)
from mpv_enhancer.ui.playback_controller import PlaybackController
from mpv_enhancer.ui.queue_model import QueueListModel
from mpv_enhancer.ui.settings_panel import SelectedItemsSettingsPanel


class RecordingIpcClient:
    def __init__(self) -> None:
        self.commands: list[tuple[JsonValue, ...]] = []

    def request(self, command: Sequence[JsonValue]) -> object:
        self.commands.append(tuple(command))
        return object()


class PlaybackIpcClient:
    def __init__(self) -> None:
        self.commands: list[tuple[JsonValue, ...]] = []
        self.dimension_futures: list[Future[JsonValue]] = []
        self._next_request_id = 1

    def request(self, command: Sequence[JsonValue]) -> MpvIpcRequest:
        normalized = tuple(command)
        self.commands.append(normalized)
        future: Future[JsonValue] = Future()
        if normalized == ("get_property", "video-dec-params"):
            self.dimension_futures.append(future)
        elif normalized != ("get_property", "track-list"):
            future.set_result(None)
        request = MpvIpcRequest(self._next_request_id, future)
        self._next_request_id += 1
        return request

    def observe_property(self, _name: str, _listener) -> object:
        return object()


def _item(number: int, overrides: PlaybackSettings | None = None) -> QueueItem:
    return QueueItem.create(
        Path(f"synthetic/episode-{number:02}.mkv"),
        overrides=overrides,
    )


@pytest.mark.parametrize(
    ("text", "mode", "mpv_value"),
    [
        ("off", VideoCropMode.OFF, ""),
        (" 1920 X 800 ", VideoCropMode.CENTERED, "1920x800"),
        ("1280x720+100+50", VideoCropMode.CUSTOM, "1280x720+100+50"),
    ],
)
def test_video_crop_valid_forms_round_trip(
    text: str,
    mode: VideoCropMode,
    mpv_value: str,
) -> None:
    crop = VideoCrop.parse(text)

    assert crop.mode is mode
    assert crop.to_mpv_value() == mpv_value
    assert VideoCrop.parse(crop.display_value) == crop


@pytest.mark.parametrize(
    "text",
    [
        "",
        "none",
        "1920",
        "1920:800",
        "0x800",
        "1920x0",
        "-1x720",
        "640x480+-1+0",
        "640x480+0",
    ],
)
def test_video_crop_rejects_invalid_forms(text: str) -> None:
    with pytest.raises(ValueError, match="[Vv]ideo crop"):
        VideoCrop.parse(text)


def test_video_crop_validates_against_decoded_source_dimensions() -> None:
    source = VideoDimensions(1920, 1080)

    assert (
        VideoCrop.parse("1920x800").validated_for(source).mode is VideoCropMode.CENTERED
    )
    assert (
        VideoCrop.parse("1280x720+320+180").validated_for(source).mode
        is VideoCropMode.CUSTOM
    )

    for invalid in (
        VideoCrop.parse("1921x800"),
        VideoCrop.parse("1280x1081"),
        VideoCrop.parse("1280x720+641+0"),
        VideoCrop.parse("1280x720+0+361"),
    ):
        with pytest.raises(ValueError, match="outside the 1920x1080 source"):
            invalid.validated_for(source)


def test_adapter_blocks_out_of_frame_crop_before_ipc_and_maps_valid_crop() -> None:
    client = RecordingIpcClient()
    adapter = MpvSettingsAdapter(client)
    source = VideoDimensions(1920, 1080)

    with pytest.raises(ValueError, match="outside"):
        adapter.apply_validated_crop(
            VideoCrop.parse("1280x720+641+0"),
            source,
        )
    assert client.commands == []

    adapter.apply_validated_crop(VideoCrop.parse("1280x720+320+180"), source)
    adapter.apply_validated_crop(VideoCrop.off(), source)

    assert client.commands == [
        ("set_property", "video-crop", "1280x720+320+180"),
        ("set_property", "video-crop", ""),
    ]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"w": 1920, "h": 1080}, VideoDimensions(1920, 1080)),
        ({"w": 0, "h": 1080}, None),
        ({"w": True, "h": 1080}, None),
        ({"w": "1920", "h": 1080}, None),
        (None, None),
    ],
)
def test_decoded_video_dimensions_normalize_only_positive_integer_maps(
    value: JsonValue,
    expected: VideoDimensions | None,
) -> None:
    assert normalize_video_dimensions(value) == expected


def test_playback_applies_crop_only_after_generation_safe_source_validation() -> None:
    item = _item(
        1,
        PlaybackSettings(video_crop=VideoCrop.parse("1280x720+320+180")),
    )
    model = QueueListModel(Playlist((item,)))
    client = PlaybackIpcClient()
    adapter = MpvJsonPlaybackAdapter(client)
    controller = PlaybackController(model, adapter)
    dimensions = []
    controller.videoDimensionsChanged.connect(
        lambda item_id, value: dimensions.append((item_id, value))
    )

    assert controller.load_row(0)
    assert ("set_property", "video-crop", "1280x720+320+180") not in client.commands
    adapter.handle_event(MpvIpcEvent("start-file", {"playlist_entry_id": 41}))
    adapter.handle_event(MpvIpcEvent("file-loaded", {"playlist_entry_id": 41}))
    assert len(client.dimension_futures) == 1

    client.dimension_futures[0].set_result({"w": 1920, "h": 1080})

    assert ("set_property", "video-crop", "1280x720+320+180") in client.commands
    assert dimensions == [
        (item.item_id, None),
        (item.item_id, VideoDimensions(1920, 1080)),
    ]


def test_playback_reports_and_blocks_crop_outside_actual_decoded_source() -> None:
    crop = VideoCrop.parse("1280x720+641+0")
    item = _item(1, PlaybackSettings(video_crop=crop))
    model = QueueListModel(Playlist((item,)))
    client = PlaybackIpcClient()
    adapter = MpvJsonPlaybackAdapter(client)
    controller = PlaybackController(model, adapter)
    errors: list[str] = []
    controller.cropValidationFailed.connect(errors.append)

    assert controller.load_row(0)
    adapter.handle_event(MpvIpcEvent("start-file", {"playlist_entry_id": 42}))
    adapter.handle_event(MpvIpcEvent("file-loaded", {"playlist_entry_id": 42}))
    client.dimension_futures[0].set_result({"w": 1920, "h": 1080})

    assert ("set_property", "video-crop", crop.to_mpv_value()) not in client.commands
    assert errors == ["Video crop is outside the 1920x1080 source."]


def test_crop_editor_requires_every_selected_source_to_validate(qtbot) -> None:
    panel = SelectedItemsSettingsPanel()
    qtbot.addWidget(panel)
    first = _item(1)
    second = _item(2)
    panel.set_selected_items((first, second))
    control = panel.findChild(QComboBox, "cropControl")
    source_label = panel.findChild(QLabel, "cropSourceDimensionsLabel")
    assert control is not None
    assert source_label is not None
    patches: list[SettingPatch] = []
    panel.patchRequested.connect(patches.append)

    assert control.currentText() == "Inherited"
    assert "Play every selected item" in source_label.text()
    panel.set_source_dimensions(first.item_id, VideoDimensions(1920, 1080))
    panel.set_source_dimensions(second.item_id, VideoDimensions(1280, 720))

    control.setEditText("1920x800")
    line_edit = control.lineEdit()
    assert line_edit is not None
    line_edit.editingFinished.emit()
    assert patches == []
    assert panel.findChild(QLabel, "video_cropStateLabel").text() == "Invalid"

    control.setEditText("1280x720")
    line_edit.editingFinished.emit()
    assert patches == [SettingPatch(SettingKey.VIDEO_CROP, VideoCrop.parse("1280x720"))]


def test_crop_editor_supports_off_mixed_and_reset(qtbot) -> None:
    panel = SelectedItemsSettingsPanel()
    qtbot.addWidget(panel)
    first = _item(1, PlaybackSettings(video_crop=VideoCrop.parse("1920x800")))
    second = _item(2, PlaybackSettings(video_crop=VideoCrop.off()))
    panel.set_selected_items((first, second))
    control = panel.findChild(QComboBox, "cropControl")
    reset = panel.findChild(QPushButton, "video_cropResetButton")
    assert control is not None
    assert reset is not None
    patches: list[SettingPatch] = []
    resets: list[SettingKey] = []
    panel.patchRequested.connect(patches.append)
    panel.resetSettingRequested.connect(resets.append)

    assert panel.state_for(SettingKey.VIDEO_CROP).state is SelectedSettingState.MIXED
    assert control.currentText() == "Mixed"

    control.setCurrentIndex(control.findText("Off"))
    assert patches == [SettingPatch(SettingKey.VIDEO_CROP, VideoCrop.off())]

    qtbot.mouseClick(reset, Qt.MouseButton.LeftButton)
    assert resets == [SettingKey.VIDEO_CROP]
