"""Bounded ownership and recovery for the application's mpv child process."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QProcess

_OUTPUT_LIMIT = 65_536


class MpvProcessState(StrEnum):
    """Lifecycle states exposed by the mpv process supervisor."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"


class MpvProcessExitStatus(StrEnum):
    """Backend-independent child-process exit status."""

    NORMAL = "normal"
    CRASHED = "crashed"


@dataclass(frozen=True, slots=True)
class MpvProcessCallbacks:
    """Callbacks emitted by a process backend."""

    stdout: Callable[[bytes], None]
    stderr: Callable[[bytes], None]
    finished: Callable[[int, MpvProcessExitStatus], None]
    error: Callable[[str], None]


class MpvProcessBackend(Protocol):
    """Minimal process surface used by the supervisor and fake tests."""

    def start(self, program: str, arguments: Sequence[str]) -> None: ...

    def wait_for_started(self, timeout_ms: int) -> bool: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait_for_finished(self, timeout_ms: int) -> bool: ...

    def error_string(self) -> str: ...


MpvProcessFactory = Callable[[MpvProcessCallbacks], MpvProcessBackend]
StateListener = Callable[[MpvProcessState], None]


class MpvProcessSupervisor:
    """Start, observe, restart, and stop exactly one owned mpv process."""

    def __init__(
        self,
        *,
        process_factory: MpvProcessFactory | None = None,
        start_timeout_ms: int = 5_000,
        shutdown_timeout_ms: int = 3_000,
        maximum_restarts: int = 1,
        state_listener: StateListener | None = None,
    ) -> None:
        if start_timeout_ms <= 0 or shutdown_timeout_ms <= 0:
            raise ValueError("Process timeouts must be positive.")
        if maximum_restarts < 0:
            raise ValueError("Maximum restarts cannot be negative.")

        self._start_timeout_ms = start_timeout_ms
        self._shutdown_timeout_ms = shutdown_timeout_ms
        self._maximum_restarts = maximum_restarts
        self._state_listener = state_listener
        self._state = MpvProcessState.STOPPED
        self._launch: tuple[str, tuple[str, ...]] | None = None
        self._restart_count = 0
        self._stdout = ""
        self._stderr = ""
        self._last_error: str | None = None
        self._last_shutdown_was_forced = False
        self._stopping = False

        callbacks = MpvProcessCallbacks(
            stdout=self._capture_stdout,
            stderr=self._capture_stderr,
            finished=self._handle_finished,
            error=self._handle_error,
        )
        factory = QtProcessBackend if process_factory is None else process_factory
        self._process = factory(callbacks)

    @property
    def state(self) -> MpvProcessState:
        return self._state

    @property
    def restart_count(self) -> int:
        return self._restart_count

    @property
    def stdout(self) -> str:
        """Return bounded, in-memory stdout captured from the owned child."""
        return self._stdout

    @property
    def stderr(self) -> str:
        """Return bounded, in-memory stderr captured from the owned child."""
        return self._stderr

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def last_shutdown_was_forced(self) -> bool:
        return self._last_shutdown_was_forced

    def start(self, executable: Path, arguments: Sequence[str]) -> bool:
        """Start mpv with a shell-free program and argument array."""
        if self._state in {
            MpvProcessState.STARTING,
            MpvProcessState.RUNNING,
            MpvProcessState.STOPPING,
        }:
            raise RuntimeError("The owned mpv process is already active.")

        program = str(executable)
        argument_array = tuple(arguments)
        if "\0" in program or any("\0" in argument for argument in argument_array):
            raise ValueError("Process arguments cannot contain null bytes.")

        self._launch = program, argument_array
        self._restart_count = 0
        self._stdout = ""
        self._stderr = ""
        self._last_error = None
        self._last_shutdown_was_forced = False
        return self._start_current_launch()

    def stop(self) -> bool:
        """Stop the owned child, escalating to kill after a bounded timeout."""
        if self._state in {MpvProcessState.STOPPED, MpvProcessState.FAILED}:
            self._set_state(MpvProcessState.STOPPED)
            return True

        self._stopping = True
        self._set_state(MpvProcessState.STOPPING)
        try:
            self._process.terminate()
            if self._process.wait_for_finished(self._shutdown_timeout_ms):
                self._set_state(MpvProcessState.STOPPED)
                return True

            self._last_shutdown_was_forced = True
            self._process.kill()
            if self._process.wait_for_finished(self._shutdown_timeout_ms):
                self._set_state(MpvProcessState.STOPPED)
                return True

            self._last_error = "mpv did not stop within the shutdown timeout."
            self._set_state(MpvProcessState.FAILED)
            return False
        finally:
            self._stopping = False

    def _start_current_launch(self) -> bool:
        if self._launch is None:
            raise RuntimeError("No mpv launch has been configured.")
        program, arguments = self._launch
        self._set_state(MpvProcessState.STARTING)
        self._process.start(program, arguments)
        if self._process.wait_for_started(self._start_timeout_ms):
            self._set_state(MpvProcessState.RUNNING)
            return True

        self._last_error = self._last_error or self._process.error_string()
        self._set_state(MpvProcessState.FAILED)
        return False

    def _handle_finished(
        self,
        exit_code: int,
        exit_status: MpvProcessExitStatus,
    ) -> None:
        if self._state not in {
            MpvProcessState.STARTING,
            MpvProcessState.RUNNING,
            MpvProcessState.STOPPING,
        }:
            return
        if self._stopping:
            self._set_state(MpvProcessState.STOPPED)
            return
        if exit_status is MpvProcessExitStatus.NORMAL and exit_code == 0:
            self._set_state(MpvProcessState.STOPPED)
            return

        self._last_error = f"mpv exited unexpectedly with code {exit_code}."
        if self._restart_count < self._maximum_restarts:
            self._restart_count += 1
            self._start_current_launch()
            return
        self._set_state(MpvProcessState.FAILED)

    def _handle_error(self, message: str) -> None:
        if message:
            self._last_error = message

    def _capture_stdout(self, output: bytes) -> None:
        self._stdout = _append_bounded(self._stdout, output)

    def _capture_stderr(self, output: bytes) -> None:
        self._stderr = _append_bounded(self._stderr, output)

    def _set_state(self, state: MpvProcessState) -> None:
        if state is self._state:
            return
        self._state = state
        if self._state_listener is not None:
            self._state_listener(state)


class QtProcessBackend:
    """QProcess adapter that never creates a command shell."""

    def __init__(self, callbacks: MpvProcessCallbacks) -> None:
        self._callbacks = callbacks
        self._process = QProcess()
        self._process.setProcessChannelMode(
            QProcess.ProcessChannelMode.SeparateChannels
        )
        self._process.readyReadStandardOutput.connect(self._read_stdout)
        self._process.readyReadStandardError.connect(self._read_stderr)
        self._process.finished.connect(self._finished)
        self._process.errorOccurred.connect(self._error)

    def start(self, program: str, arguments: Sequence[str]) -> None:
        self._process.start(program, list(arguments))

    def wait_for_started(self, timeout_ms: int) -> bool:
        return self._process.waitForStarted(timeout_ms)

    def terminate(self) -> None:
        self._process.terminate()

    def kill(self) -> None:
        self._process.kill()

    def wait_for_finished(self, timeout_ms: int) -> bool:
        return self._process.waitForFinished(timeout_ms)

    def error_string(self) -> str:
        return self._process.errorString()

    def _read_stdout(self) -> None:
        self._callbacks.stdout(bytes(self._process.readAllStandardOutput().data()))

    def _read_stderr(self) -> None:
        self._callbacks.stderr(bytes(self._process.readAllStandardError().data()))

    def _finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        self._read_stdout()
        self._read_stderr()
        status = (
            MpvProcessExitStatus.CRASHED
            if exit_status is QProcess.ExitStatus.CrashExit
            else MpvProcessExitStatus.NORMAL
        )
        self._callbacks.finished(exit_code, status)

    def _error(self, _error: QProcess.ProcessError) -> None:
        self._callbacks.error(self._process.errorString())


def _append_bounded(existing: str, output: bytes) -> str:
    decoded = output.decode("utf-8", errors="replace")
    return (existing + decoded)[-_OUTPUT_LIMIT:]
