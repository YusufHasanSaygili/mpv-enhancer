"""Composition of the embedded mpv process, pipe transport, and JSON client."""

import ctypes
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from mpv_enhancer.infrastructure.mpv.json_ipc import MpvIpcCallbacks, MpvIpcClient
from mpv_enhancer.infrastructure.mpv.pipe_transport import (
    NamedPipeCallbacks,
    NamedPipeTransport,
    PipeTransportState,
)
from mpv_enhancer.infrastructure.mpv.playback import (
    MpvJsonPlaybackAdapter,
    PlaybackAdapter,
)
from mpv_enhancer.infrastructure.mpv.process import MpvProcessSupervisor


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
        "--keep-open=yes",
        "--input-vo-keyboard=no",
        "--input-default-bindings=no",
        "--osc=no",
        "--terminal=no",
        "--msg-level=all=warn",
        f"--wid={wid}",
        f"--input-ipc-server={pipe_name}",
    )


class EmbeddedMpvSession:
    """Own one complete embedded mpv runtime tied to a stable host handle."""

    def __init__(
        self,
        host_hwnd: int,
        *,
        process_supervisor: ProcessSupervisor | None = None,
        transport_factory: PipeTransportFactory | None = None,
    ) -> None:
        self._host_hwnd = ctypes.c_uint32(host_hwnd).value
        if self._host_hwnd == 0:
            raise ValueError("The embedded video host handle must be non-zero.")
        self._process = (
            MpvProcessSupervisor() if process_supervisor is None else process_supervisor
        )
        factory = _create_transport if transport_factory is None else transport_factory
        self._last_error: str | None = None
        self._transport_state = PipeTransportState.STOPPED
        self._client: MpvIpcClient | None = None
        callbacks = NamedPipeCallbacks(
            data_received=self._receive_data,
            state_changed=self._transport_state_changed,
            error=self._transport_failed,
        )
        self._transport = factory(callbacks)
        self._client = MpvIpcClient(
            send=self._transport.send,
            callbacks=MpvIpcCallbacks(protocol_error=self._protocol_failed),
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
    def client(self) -> MpvIpcClient:
        if self._client is None:
            raise RuntimeError("The embedded mpv IPC client is unavailable.")
        return self._client

    @property
    def playback_adapter(self) -> PlaybackAdapter:
        return self._playback_adapter

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

    def _transport_failed(self, _message: str) -> None:
        self._last_error = "The mpv IPC transport failed."

    def _protocol_failed(self, _message: str) -> None:
        self._last_error = "mpv returned invalid IPC data."


def _create_transport(callbacks: NamedPipeCallbacks) -> PipeTransport:
    return NamedPipeTransport(callbacks=callbacks)
