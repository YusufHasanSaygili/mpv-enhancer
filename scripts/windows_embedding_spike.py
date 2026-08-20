"""Prove that mpv embeds into a native Qt host on interactive Windows."""

import argparse
import ctypes
import json
import platform
import sys
import time
from collections.abc import Callable, Sequence
from ctypes import wintypes
from dataclasses import asdict, dataclass
from pathlib import Path

from PySide6.QtCore import QEventLoop, QProcess, Qt, QThread, qVersion
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from mpv_enhancer.infrastructure.mpv.discovery import validate_mpv_executable

TEST_SOURCE = "av://lavfi:testsrc=size=640x360:rate=30"
PROBE_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class EmbeddingProbeResult:
    """Machine-safe evidence from one real Windows embedding probe."""

    os_name: str
    os_release: str
    os_build: str
    qt_version: str
    mpv_version: str
    host_hwnd_is_uint32: bool
    child_parent_verified: bool
    initial_host_size: tuple[int, int]
    initial_child_size: tuple[int, int]
    resized_host_size: tuple[int, int]
    resized_child_size: tuple[int, int]
    fullscreen_entered: bool
    fullscreen_host_size: tuple[int, int]
    fullscreen_child_size: tuple[int, int]
    returned_to_windowed: bool
    process_running_after_transitions: bool
    clean_shutdown: bool


class EmbeddingProbeWindow(QWidget):
    """Minimal top-level window containing one forced-native video host."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MPV Enhancer embedding probe")
        self.resize(800, 520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.video_host = QWidget(self)
        self.video_host.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.video_host.setStyleSheet("background: black;")
        layout.addWidget(self.video_host)


def build_mpv_arguments(host_hwnd: int) -> list[str]:
    """Return the shell-free argument vector for the minimal --wid proof."""
    wid = ctypes.c_uint32(host_hwnd).value
    return [
        "--no-config",
        "--force-window=yes",
        "--keep-open=yes",
        "--loop-file=inf",
        "--no-audio",
        "--input-vo-keyboard=no",
        "--input-default-bindings=no",
        "--osc=no",
        "--osd-level=0",
        "--terminal=no",
        "--msg-level=all=warn",
        f"--wid={wid}",
        TEST_SOURCE,
    ]


def run_embedding_probe(executable: Path) -> EmbeddingProbeResult:
    """Run the real child-window, resize, full-screen, and shutdown proof."""
    if sys.platform != "win32":
        raise RuntimeError("The embedding probe requires interactive Windows.")
    validation = validate_mpv_executable(executable)
    if not validation.is_valid or validation.version is None:
        raise RuntimeError("The supplied executable is not a valid mpv build.")

    app = QApplication.instance()
    if app is None:
        app = QApplication(["mpv-enhancer-embedding-probe"])
    if not isinstance(app, QApplication):
        raise RuntimeError("A non-GUI Qt application already exists.")

    window = EmbeddingProbeWindow()
    process = QProcess(window)
    process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
    clean_shutdown = False
    try:
        window.show()
        _wait_for(app, window.isVisible, "probe window visibility")
        host_hwnd = int(window.video_host.winId())
        uint32_hwnd = ctypes.c_uint32(host_hwnd).value

        process.start(str(executable.resolve()), build_mpv_arguments(host_hwnd))
        if not process.waitForStarted(5_000):
            raise RuntimeError(f"mpv did not start: {process.errorString()}")
        process_id = process.processId()

        child_hwnd = _wait_for_value(
            app,
            lambda: _find_direct_child_for_process(uint32_hwnd, process_id),
            "mpv child window attachment",
        )
        child_parent_verified = _get_parent(child_hwnd) == uint32_hwnd
        initial_host = _client_size(uint32_hwnd)
        _wait_for(
            app,
            lambda: _sizes_match(_client_size(uint32_hwnd), _client_size(child_hwnd)),
            "initial child coverage",
        )
        initial_child = _client_size(child_hwnd)

        window.resize(1100, 680)
        _wait_for(
            app,
            lambda: (
                _sizes_match(_client_size(uint32_hwnd), _client_size(child_hwnd))
                and _client_size(uint32_hwnd) != initial_host
            ),
            "resized child coverage",
        )
        resized_host = _client_size(uint32_hwnd)
        resized_child = _client_size(child_hwnd)

        window.showFullScreen()
        _wait_for(app, window.isFullScreen, "full-screen entry")
        _wait_for(
            app,
            lambda: _sizes_match(_client_size(uint32_hwnd), _client_size(child_hwnd)),
            "full-screen child coverage",
        )
        fullscreen_host = _client_size(uint32_hwnd)
        fullscreen_child = _client_size(child_hwnd)

        window.showNormal()
        _wait_for(app, lambda: not window.isFullScreen(), "windowed restoration")
        _wait_for(
            app,
            lambda: _sizes_match(_client_size(uint32_hwnd), _client_size(child_hwnd)),
            "restored child coverage",
        )
        process_running = process.state() is QProcess.ProcessState.Running

        process.terminate()
        if not process.waitForFinished(3_000):
            process.kill()
            if not process.waitForFinished(3_000):
                raise RuntimeError("mpv did not stop after terminate and kill.")
        clean_shutdown = process.state() is QProcess.ProcessState.NotRunning

        return EmbeddingProbeResult(
            os_name=platform.system(),
            os_release=platform.release(),
            os_build=platform.version(),
            qt_version=qVersion(),
            mpv_version=validation.version,
            host_hwnd_is_uint32=host_hwnd == uint32_hwnd,
            child_parent_verified=child_parent_verified,
            initial_host_size=initial_host,
            initial_child_size=initial_child,
            resized_host_size=resized_host,
            resized_child_size=resized_child,
            fullscreen_entered=True,
            fullscreen_host_size=fullscreen_host,
            fullscreen_child_size=fullscreen_child,
            returned_to_windowed=True,
            process_running_after_transitions=process_running,
            clean_shutdown=clean_shutdown,
        )
    except Exception as error:
        stderr = bytes(process.readAllStandardError().data()).decode(
            "utf-8", errors="replace"
        )
        detail = stderr[-1_000:].strip()
        if detail:
            raise RuntimeError(f"{error}\nmpv stderr:\n{detail}") from error
        raise
    finally:
        if process.state() is not QProcess.ProcessState.NotRunning:
            process.kill()
            process.waitForFinished(3_000)
        window.close()
        app.processEvents()


def _wait_for(
    app: QApplication,
    predicate: Callable[[], bool],
    label: str,
) -> None:
    deadline = time.monotonic() + PROBE_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        if predicate():
            return
        QThread.msleep(25)
    raise RuntimeError(f"Timed out waiting for {label}.")


def _wait_for_value(
    app: QApplication,
    producer: Callable[[], int | None],
    label: str,
) -> int:
    value: int | None = None

    def produced() -> bool:
        nonlocal value
        value = producer()
        return value is not None

    _wait_for(app, produced, label)
    if value is None:
        raise RuntimeError(f"No value produced for {label}.")
    return value


def _find_direct_child_for_process(parent_hwnd: int, process_id: int) -> int | None:
    matches: list[int] = []

    @WNDENUMPROC
    def visit(hwnd: int, _parameter: int) -> bool:
        child_process_id = wintypes.DWORD()
        USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(child_process_id))
        if child_process_id.value == process_id and _get_parent(hwnd) == parent_hwnd:
            matches.append(hwnd)
            return False
        return True

    USER32.EnumChildWindows(parent_hwnd, visit, 0)
    return matches[0] if matches else None


def _get_parent(hwnd: int) -> int:
    parent = USER32.GetParent(hwnd)
    return int(parent) if parent else 0


def _client_size(hwnd: int) -> tuple[int, int]:
    rect = wintypes.RECT()
    if not USER32.GetClientRect(hwnd, ctypes.byref(rect)):
        raise ctypes.WinError(ctypes.get_last_error())
    return rect.right - rect.left, rect.bottom - rect.top


def _sizes_match(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return abs(left[0] - right[0]) <= 2 and abs(left[1] - right[1]) <= 2


def _parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mpv", required=True, type=Path)
    parser.add_argument("--evidence", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the probe and optionally write machine-safe JSON evidence."""
    arguments = _parse_arguments(sys.argv[1:] if argv is None else argv)
    result = run_embedding_probe(arguments.mpv)
    serialized = json.dumps(asdict(result), indent=2)
    print(serialized)
    if arguments.evidence is not None:
        arguments.evidence.parent.mkdir(parents=True, exist_ok=True)
        arguments.evidence.write_text(f"{serialized}\n", encoding="utf-8")
    return 0


if sys.platform == "win32":
    USER32 = ctypes.WinDLL("user32", use_last_error=True)
    WNDENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HWND,
        wintypes.LPARAM,
    )
    USER32.EnumChildWindows.argtypes = [
        wintypes.HWND,
        WNDENUMPROC,
        wintypes.LPARAM,
    ]
    USER32.EnumChildWindows.restype = wintypes.BOOL
    USER32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    USER32.GetWindowThreadProcessId.restype = wintypes.DWORD
    USER32.GetParent.argtypes = [wintypes.HWND]
    USER32.GetParent.restype = wintypes.HWND
    USER32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    USER32.GetClientRect.restype = wintypes.BOOL


if __name__ == "__main__":
    raise SystemExit(main())
