"""Opt-in tests that require a trusted local mpv executable."""

import os
from collections.abc import Callable
from pathlib import Path
from threading import Event

import pytest
from PySide6.QtWidgets import QMainWindow

from mpv_enhancer.domain.models import Playlist, QueueItem
from mpv_enhancer.infrastructure.mpv.embedded import EmbeddedMpvSession
from mpv_enhancer.infrastructure.mpv.pipe_transport import PipeTransportState
from mpv_enhancer.infrastructure.mpv.process import MpvProcessState
from mpv_enhancer.ui.playback_controller import PlaybackController, PlaybackPhase
from mpv_enhancer.ui.queue_model import QueueListModel
from mpv_enhancer.ui.video_host import VideoHost

_OPT_IN = os.environ.get("MPV_ENHANCER_RUN_REAL_MPV_TESTS") == "1"
_MPV_PATH = os.environ.get("MPV_ENHANCER_REAL_MPV_PATH")


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


def _wait_until(qtbot, predicate: Callable[[], bool]) -> None:
    qtbot.waitUntil(predicate, timeout=10_000)
