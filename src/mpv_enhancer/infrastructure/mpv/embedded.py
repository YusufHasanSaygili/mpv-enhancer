"""Composition of the embedded mpv process, pipe transport, and JSON client."""

import ctypes
from collections.abc import Callable, Sequence
from concurrent.futures import Future
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QObject, Signal

from mpv_enhancer.infrastructure.mpv.json_ipc import (
    JsonValue,
    MpvIpcCallbacks,
    MpvIpcClient,
    MpvIpcEvent,
)
from mpv_enhancer.infrastructure.mpv.pipe_transport import (
    NamedPipeCallbacks,
    NamedPipeTransport,
    PipeTransportState,
)
from mpv_enhancer.infrastructure.mpv.playback import (
    MpvJsonPlaybackAdapter,
    PlaybackAdapter,
)
from mpv_enhancer.infrastructure.mpv.process import (
    MpvProcessState,
    MpvProcessSupervisor,
)


class ProcessSupervisor(Protocol):
    """Owned process surface consumed by an embedded session."""

    def start(self, executable: Path, arguments: Sequence[str]) -> bool: ...

    def stop(self) -> bool: ...


class PipeTransport(Protocol):
    """Duplex transport surface consumed by an embedded session."""

    @property
    def pipe_name(self) -> str: ...

    def start(self) -> None: ...

    def send(self, payload: bytes) -> None: ...

    def stop(self, timeout_ms: int = 3_000) -> bool: ...


PipeTransportFactory = Callable[[NamedPipeCallbacks], PipeTransport]


def build_embedded_mpv_arguments(host_hwnd: int, pipe_name: str) -> tuple[str, ...]:
    """Build mpv's shell-free idle embedding and IPC startup arguments."""
    if not pipe_name.startswith(r"\\.\pipe\mpv-enhancer-") or "\0" in pipe_name:
        raise ValueError("The embedded mpv pipe name is invalid.")
    wid = ctypes.c_uint32(host_hwnd).value
    if wid == 0:
        raise ValueError("The embedded video host handle must be non-zero.")
    return (
        "--no-config",
        "--idle=yes",
        "--force-window=yes",
        "--input-vo-keyboard=no",
        "--input-default-bindings=no",
        "--osc=no",
        "--terminal=no",
        "--msg-level=all=warn",
        f"--wid={wid}",
        f"--input-ipc-server={pipe_name}",
    )


class EmbeddedMpvSession(QObject):
    """Own one complete embedded mpv runtime tied to a stable host handle."""

    failureOccurred = Signal(str)
    runtimeRecovered = Signal()

    def __init__(
        self,
        host_hwnd: int,
        *,
        process_supervisor: ProcessSupervisor | None = None,
        transport_factory: PipeTransportFactory | None = None,
    ) -> None:
        super().__init__()
        self._host_hwnd = ctypes.c_uint32(host_hwnd).value
        if self._host_hwnd == 0:
            raise ValueError("The embedded video host handle must be non-zero.")
        self._process = (
            MpvProcessSupervisor(state_listener=self._process_state_changed)
            if process_supervisor is None
            else process_supervisor
        )
        factory = _create_transport if transport_factory is None else transport_factory
        self._last_error: str | None = None
        self._transport_state = PipeTransportState.STOPPED
        self._process_state = MpvProcessState.STOPPED
        self._has_run = False
        self._connected_once = False
        self._failure_notified = False
        self._recovery_token = 0
        self._client: MpvIpcClient | None = None
        callbacks = NamedPipeCallbacks(
            data_received=self._receive_data,
            state_changed=self._transport_state_changed,
            error=self._transport_failed,
        )
        self._transport = factory(callbacks)
        self._client = MpvIpcClient(
            send=self._transport.send,
            callbacks=MpvIpcCallbacks(
                event_received=self._playback_event,
                protocol_error=self._protocol_failed,
            ),
        )
        self._playback_adapter = MpvJsonPlaybackAdapter(self._client)
        self._started = False

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def transport_state(self) -> PipeTransportState:
        return self._transport_state

    @property
    def process_state(self) -> MpvProcessState:
        return self._process_state

    @property
    def client(self) -> MpvIpcClient:
        if self._client is None:
            raise RuntimeError("The embedded mpv IPC client is unavailable.")
        return self._client

    @property
    def playback_adapter(self) -> PlaybackAdapter:
        return self._playback_adapter

    def set_failure_listener(self, listener: Callable[[str], None]) -> None:
        self.failureOccurred.connect(listener)

    def set_recovered_listener(self, listener: Callable[[], None]) -> None:
        self.runtimeRecovered.connect(listener)

    def start(self, executable: Path) -> bool:
        """Start the child first, then connect its named-pipe transport."""
        if self._started:
            raise RuntimeError("The embedded mpv session is already running.")
        arguments = build_embedded_mpv_arguments(
            self._host_hwnd,
            self._transport.pipe_name,
        )
        if not self._process.start(executable, arguments):
            self._last_error = "mpv could not start."
            return False
        if self._process_state is MpvProcessState.STOPPED:
            self._process_state = MpvProcessState.RUNNING
            self._has_run = True
        try:
            self._transport.start()
        except Exception:
            self._process.stop()
            self._last_error = "The mpv IPC transport could not start."
            return False
        self._started = True
        return True

    def shutdown(self) -> bool:
        """Stop IPC before the exact child process owned by this session."""
        if self._client is not None:
            self._client.close()
        transport_stopped = self._transport.stop(3_000)
        process_stopped = self._process.stop()
        self._started = False
        return transport_stopped and process_stopped

    def _receive_data(self, chunk: bytes) -> None:
        if self._client is not None:
            self._client.feed_data(chunk)

    def _transport_state_changed(self, state: PipeTransportState) -> None:
        self._transport_state = state
        if state is PipeTransportState.CONNECTED:
            if self._connected_once:
                self._playback_adapter.reset_runtime()
                self._start_recovery_probe()
            self._connected_once = True
        elif state is PipeTransportState.DISCONNECTED and self._connected_once:
            self._recovery_token += 1
            self._notify_failure(
                "Playback connection was lost. Retry or stop playback."
            )

    def _transport_failed(self, _message: str) -> None:
        self._last_error = "The mpv IPC transport failed."
        self._notify_failure("Playback connection failed. Retry or stop playback.")

    def _protocol_failed(self, _message: str) -> None:
        self._last_error = "mpv returned invalid IPC data."
        self._notify_failure(
            "mpv returned invalid playback data. Retry or stop playback."
        )

    def _playback_event(self, event: MpvIpcEvent) -> None:
        self._playback_adapter.handle_event(event)

    def _process_state_changed(self, state: MpvProcessState) -> None:
        previous = self._process_state
        self._process_state = state
        if state is MpvProcessState.STARTING and self._has_run:
            self._notify_failure(
                "mpv stopped unexpectedly and restarted. "
                "Retry the current item or stop playback."
            )
        elif state is MpvProcessState.RUNNING:
            self._has_run = True
        elif state is MpvProcessState.FAILED and previous is not MpvProcessState.FAILED:
            self._notify_failure(
                "mpv stopped and could not recover. "
                "Stop playback and check Preferences."
            )

    def _notify_failure(self, message: str) -> None:
        if self._failure_notified:
            return
        self._failure_notified = True
        self.failureOccurred.emit(message)

    def _start_recovery_probe(self) -> None:
        if self._client is None:
            return
        self._recovery_token += 1
        token = self._recovery_token
        request = self._client.request(
            ("get_property", "mpv-version"),
            timeout_seconds=1.0,
        )
        request.future.add_done_callback(
            lambda completed: self._recovery_probe_completed(token, completed)
        )

    def _recovery_probe_completed(
        self,
        token: int,
        completed: Future[JsonValue],
    ) -> None:
        if (
            token != self._recovery_token
            or self._transport_state is not PipeTransportState.CONNECTED
        ):
            return
        try:
            completed.result()
        except Exception:
            return
        self._failure_notified = False
        self.runtimeRecovered.emit()


def _create_transport(callbacks: NamedPipeCallbacks) -> PipeTransport:
    return NamedPipeTransport(callbacks=callbacks)
