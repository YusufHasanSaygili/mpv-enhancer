from collections.abc import Sequence
from pathlib import Path

from mpv_enhancer.infrastructure.mpv.process import (
    MpvProcessCallbacks,
    MpvProcessExitStatus,
    MpvProcessState,
    MpvProcessSupervisor,
)


class FakeProcess:
    def __init__(
        self,
        callbacks: MpvProcessCallbacks,
        *,
        starts_successfully: Sequence[bool] = (True,),
        finishes_after: Sequence[bool] = (True,),
    ) -> None:
        self.callbacks = callbacks
        self.starts_successfully = list(starts_successfully)
        self.finishes_after = list(finishes_after)
        self.start_calls: list[tuple[str, tuple[str, ...]]] = []
        self.wait_for_started_calls: list[int] = []
        self.wait_for_finished_calls: list[int] = []
        self.terminate_calls = 0
        self.kill_calls = 0

    def start(self, program: str, arguments: Sequence[str]) -> None:
        self.start_calls.append((program, tuple(arguments)))

    def wait_for_started(self, timeout_ms: int) -> bool:
        self.wait_for_started_calls.append(timeout_ms)
        return self.starts_successfully.pop(0)

    def terminate(self) -> None:
        self.terminate_calls += 1

    def kill(self) -> None:
        self.kill_calls += 1

    def wait_for_finished(self, timeout_ms: int) -> bool:
        self.wait_for_finished_calls.append(timeout_ms)
        return self.finishes_after.pop(0)

    def error_string(self) -> str:
        return "synthetic process error"

    def emit_stdout(self, output: bytes) -> None:
        self.callbacks.stdout(output)

    def emit_stderr(self, output: bytes) -> None:
        self.callbacks.stderr(output)

    def finish(
        self,
        exit_code: int,
        exit_status: MpvProcessExitStatus,
    ) -> None:
        self.callbacks.finished(exit_code, exit_status)


def _supervisor(
    *,
    starts_successfully: Sequence[bool] = (True,),
    finishes_after: Sequence[bool] = (True,),
) -> tuple[MpvProcessSupervisor, FakeProcess]:
    process: FakeProcess | None = None

    def create_process(callbacks: MpvProcessCallbacks) -> FakeProcess:
        nonlocal process
        process = FakeProcess(
            callbacks,
            starts_successfully=starts_successfully,
            finishes_after=finishes_after,
        )
        return process

    supervisor = MpvProcessSupervisor(
        process_factory=create_process,
        start_timeout_ms=125,
        shutdown_timeout_ms=250,
    )
    assert process is not None
    return supervisor, process


def test_normal_close_preserves_structured_arguments_and_captured_output() -> None:
    supervisor, process = _supervisor()
    executable = Path("C:/Program Files/mpv/mpv.exe")
    arguments = ("--no-config", "--wid=123", "--", "- synthetic media.mkv")

    assert supervisor.start(executable, arguments)
    process.emit_stdout(b"ready\n")
    process.emit_stderr(b"warning: synthetic\xff\n")
    process.finish(0, MpvProcessExitStatus.NORMAL)

    assert process.start_calls == [(str(executable), arguments)]
    assert process.wait_for_started_calls == [125]
    assert supervisor.state is MpvProcessState.STOPPED
    assert supervisor.stdout == "ready\n"
    assert supervisor.stderr == "warning: synthetic\ufffd\n"
    assert supervisor.restart_count == 0


def test_failed_start_reports_a_bounded_failure_without_restart() -> None:
    supervisor, process = _supervisor(starts_successfully=(False,))

    assert not supervisor.start(Path("mpv.exe"), ("--no-config",))

    assert supervisor.state is MpvProcessState.FAILED
    assert supervisor.last_error == "synthetic process error"
    assert supervisor.restart_count == 0
    assert len(process.start_calls) == 1


def test_crash_restarts_once_and_a_second_crash_stays_failed() -> None:
    supervisor, process = _supervisor(starts_successfully=(True, True))
    assert supervisor.start(Path("mpv.exe"), ("--no-config", "--idle=yes"))

    process.finish(2, MpvProcessExitStatus.CRASHED)

    assert supervisor.state is MpvProcessState.RUNNING
    assert supervisor.restart_count == 1
    assert len(process.start_calls) == 2

    process.finish(3, MpvProcessExitStatus.CRASHED)

    assert supervisor.state is MpvProcessState.FAILED
    assert supervisor.restart_count == 1
    assert len(process.start_calls) == 2
    assert supervisor.last_error == "mpv exited unexpectedly with code 3."


def test_shutdown_forces_only_the_owned_child_after_the_timeout() -> None:
    supervisor, process = _supervisor(finishes_after=(False, True))
    assert supervisor.start(Path("mpv.exe"), ("--no-config",))

    assert supervisor.stop()

    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert process.wait_for_finished_calls == [250, 250]
    assert supervisor.last_shutdown_was_forced
    assert supervisor.state is MpvProcessState.STOPPED
