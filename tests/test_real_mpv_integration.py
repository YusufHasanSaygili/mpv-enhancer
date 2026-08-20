"""Opt-in tests that require a trusted local mpv executable."""

import os
from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path
from threading import Event

import pytest
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QMainWindow

from mpv_enhancer.domain.models import Playlist, QueueItem
from mpv_enhancer.domain.settings import EffectivePlaybackSettings
from mpv_enhancer.infrastructure.mpv.capabilities import MpvCapabilities
from mpv_enhancer.infrastructure.mpv.embedded import EmbeddedMpvSession
from mpv_enhancer.infrastructure.mpv.json_ipc import JsonValue
from mpv_enhancer.infrastructure.mpv.pipe_transport import PipeTransportState
from mpv_enhancer.infrastructure.mpv.process import MpvProcessState
from mpv_enhancer.infrastructure.mpv.settings_adapter import MpvSettingsAdapter
from mpv_enhancer.ui.playback_controller import PlaybackController, PlaybackPhase
from mpv_enhancer.ui.queue_model import QueueListModel
from mpv_enhancer.ui.video_host import VideoHost

_OPT_IN = os.environ.get("MPV_ENHANCER_RUN_REAL_MPV_TESTS") == "1"
_MPV_PATH = os.environ.get("MPV_ENHANCER_REAL_MPV_PATH")
_VISUAL_OPT_IN = (
    _OPT_IN and bool(_MPV_PATH) and os.environ.get("QT_QPA_PLATFORM") == "windows"
)


@pytest.mark.skipif(
    not _OPT_IN or not _MPV_PATH,
    reason=(
        "Set MPV_ENHANCER_RUN_REAL_MPV_TESTS=1 and "
        "MPV_ENHANCER_REAL_MPV_PATH to run the real-mpv integration test."
    ),
)
def test_real_mpv_error_restart_retry_and_shutdown(
    qtbot,
    tmp_path: Path,
) -> None:
    executable = Path(_MPV_PATH or "")
    corrupt_media = tmp_path / "synthetic-corrupt.mkv"
    corrupt_media.write_bytes(b"not a media file")
    window = QMainWindow()
    host = VideoHost()
    window.setCentralWidget(host)
    qtbot.addWidget(window)
    window.show()
    session = EmbeddedMpvSession(host.native_handle)
    failed = Event()
    recovered = Event()
    session.set_failure_listener(lambda _message: failed.set())
    session.set_recovered_listener(recovered.set)
    model = QueueListModel(Playlist((QueueItem.create(corrupt_media),)))

    try:
        assert session.start(executable)
        _wait_until(
            qtbot,
            lambda: session.transport_state is PipeTransportState.CONNECTED,
        )
        controller = PlaybackController(model, session.playback_adapter)
        assert controller.load_row(0)
        _wait_until(qtbot, lambda: controller.state.phase is PlaybackPhase.ERROR)

        session.client.request(("quit", 7))
        _wait_until(qtbot, failed.is_set)
        _wait_until(qtbot, recovered.is_set)
        assert controller.retry_current()
        _wait_until(qtbot, lambda: controller.state.phase is PlaybackPhase.ERROR)
        assert controller.stop()
    finally:
        assert session.shutdown()
        window.close()

    assert session.process_state is MpvProcessState.STOPPED


@pytest.mark.skipif(
    not _VISUAL_OPT_IN,
    reason=(
        "Set QT_QPA_PLATFORM=windows, MPV_ENHANCER_RUN_REAL_MPV_TESTS=1, and "
        "MPV_ENHANCER_REAL_MPV_PATH to run the real-mpv visual test."
    ),
)
def test_real_mpv_zoom_pan_visual_smoke(qtbot, tmp_path: Path) -> None:
    executable = Path(_MPV_PATH or "")
    source = "av://lavfi:testsrc2=duration=30:size=640x360:rate=30"
    baseline_path = tmp_path / "baseline.png"
    transformed_path = tmp_path / "zoom-pan.png"
    window = QMainWindow()
    window.resize(640, 360)
    host = VideoHost()
    window.setCentralWidget(host)
    qtbot.addWidget(window)
    window.show()
    session = EmbeddedMpvSession(host.native_handle)
    video_ready = Event()
    capabilities: list[MpvCapabilities] = []
    session.set_capabilities_listener(capabilities.append)

    try:
        assert session.start(executable)
        _wait_until(
            qtbot,
            lambda: session.transport_state is PipeTransportState.CONNECTED,
        )
        _wait_until(qtbot, lambda: bool(capabilities))
        assert capabilities[0].supports_property("video-zoom")
        assert capabilities[0].supports_command("loadfile")
        assert capabilities[0].supports_command("set")
        observation = session.client.observe_property(
            "video-params",
            lambda _name, value: video_ready.set() if isinstance(value, dict) else None,
        )
        _request_result(qtbot, observation.request.future)
        _request_result(
            qtbot,
            session.client.request(("loadfile", source, "replace")).future,
        )
        _wait_until(qtbot, video_ready.is_set)
        _request_result(
            qtbot,
            session.client.request(("set_property", "pause", True)).future,
        )
        qtbot.wait(250)
        _request_result(
            qtbot,
            session.client.request(
                ("screenshot-to-file", str(baseline_path), "window")
            ).future,
        )

        MpvSettingsAdapter(session.client).apply(
            EffectivePlaybackSettings(
                speed=1.0,
                panscan=0.0,
                volume=100.0,
                mute=False,
                subtitle_visibility=True,
                video_zoom=1.0,
                video_pan_x=0.25,
                video_pan_y=-0.25,
            )
        )
        _wait_until(qtbot, lambda: session.client.pending_count == 0)
        qtbot.wait(250)
        _request_result(
            qtbot,
            session.client.request(
                ("screenshot-to-file", str(transformed_path), "window")
            ).future,
        )

        assert _request_result(
            qtbot,
            session.client.request(("get_property", "video-zoom")).future,
        ) == pytest.approx(1.0)
        assert _request_result(
            qtbot,
            session.client.request(("get_property", "video-pan-x")).future,
        ) == pytest.approx(0.25)
        assert _request_result(
            qtbot,
            session.client.request(("get_property", "video-pan-y")).future,
        ) == pytest.approx(-0.25)
    finally:
        assert session.shutdown()
        window.close()

    baseline = QImage(str(baseline_path))
    transformed = QImage(str(transformed_path))
    assert not baseline.isNull()
    assert not transformed.isNull()
    assert baseline.size() == transformed.size()
    assert baseline != transformed


def _wait_until(qtbot, predicate: Callable[[], bool]) -> None:
    qtbot.waitUntil(predicate, timeout=10_000)


def _request_result(qtbot, future: Future[JsonValue]) -> JsonValue:
    _wait_until(qtbot, future.done)
    return future.result()
