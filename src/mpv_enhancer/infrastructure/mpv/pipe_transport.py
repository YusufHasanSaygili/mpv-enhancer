"""Cancelable Windows named-pipe byte transport for mpv JSON IPC."""

import ctypes
import sys
import time
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass
from enum import StrEnum
from queue import Empty, Queue
from threading import Event, Lock, Thread
from typing import Any, Protocol, cast
from uuid import uuid4

_PIPE_PREFIX = r"\\.\pipe\mpv-enhancer-"
_READ_CHUNK_SIZE = 65_536
_IO_POLL_MS = 25
_IO_TIMEOUT_MS = 3_000

_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_OPEN_EXISTING = 3
_FILE_FLAG_OVERLAPPED = 0x40000000
_ERROR_FILE_NOT_FOUND = 2
_ERROR_BROKEN_PIPE = 109
_ERROR_NO_DATA = 232
_ERROR_PIPE_BUSY = 231
_ERROR_PIPE_NOT_CONNECTED = 233
_ERROR_OPERATION_ABORTED = 995
_ERROR_IO_PENDING = 997
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 258
_WAIT_FAILED = 0xFFFFFFFF
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class PipeTransportState(StrEnum):
    """Observable named-pipe transport states."""

    STOPPED = "stopped"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    STOPPING = "stopping"


class PipeTransportError(RuntimeError):
    """Base class for local named-pipe transport failures."""


class PipeDisconnected(PipeTransportError):
    """The mpv side closed or lost the named pipe."""


class PipeCancelled(PipeTransportError):
    """Pending pipe I/O was cancelled during shutdown."""


@dataclass(frozen=True, slots=True)
class NamedPipeCallbacks:
    """Thread-safe callbacks consumed by the transport worker."""

    data_received: Callable[[bytes], None]
    state_changed: Callable[[PipeTransportState], None]
    error: Callable[[str], None]


class NamedPipeConnection(Protocol):
    """One connected, full-duplex named-pipe handle."""

    def read(self, timeout_ms: int) -> bytes | None: ...

    def write(self, payload: bytes, cancel: Event) -> None: ...

    def cancel(self) -> None: ...

    def close(self) -> None: ...


class NamedPipeConnector(Protocol):
    """Open the mpv pipe or report that it is not available yet."""

    def connect(self, pipe_name: str) -> NamedPipeConnection | None: ...


def create_mpv_pipe_name() -> str:
    """Create an unguessable local pipe name without user or media identity."""
    return f"{_PIPE_PREFIX}{uuid4().hex}"


class NamedPipeTransport:
    """Retry connection and run duplex pipe I/O on one cancellable worker."""

    def __init__(
        self,
        *,
        callbacks: NamedPipeCallbacks,
        connector: NamedPipeConnector | None = None,
        pipe_name: str | None = None,
        connect_retry_ms: int = 50,
        connect_timeout_ms: int = 5_000,
        read_poll_ms: int = _IO_POLL_MS,
    ) -> None:
        if connect_retry_ms <= 0 or connect_timeout_ms <= 0 or read_poll_ms <= 0:
            raise ValueError("Pipe timeouts must be positive.")
        self._callbacks = callbacks
        self._connector = Win32NamedPipeConnector() if connector is None else connector
        self._pipe_name = create_mpv_pipe_name() if pipe_name is None else pipe_name
        self._connect_retry_ms = connect_retry_ms
        self._connect_timeout_ms = connect_timeout_ms
        self._read_poll_ms = read_poll_ms
        self._outgoing: Queue[bytes] = Queue()
        self._stop_requested = Event()
        self._connection_lock = Lock()
        self._connection: NamedPipeConnection | None = None
        self._worker: Thread | None = None
        self._state = PipeTransportState.STOPPED

    @property
    def pipe_name(self) -> str:
        return self._pipe_name

    @property
    def state(self) -> PipeTransportState:
        return self._state

    def start(self) -> None:
        """Start one background connection and I/O worker."""
        if self._worker is not None and self._worker.is_alive():
            raise RuntimeError("The named-pipe transport is already active.")
        self._stop_requested.clear()
        self._set_state(PipeTransportState.CONNECTING)
        self._worker = Thread(
            target=self._run,
            name="mpv-named-pipe-transport",
            daemon=True,
        )
        self._worker.start()

    def send(self, payload: bytes) -> None:
        """Queue bytes for ordered delivery without interpreting JSON."""
        if not payload:
            raise ValueError("Pipe payload cannot be empty.")
        if self._state in {PipeTransportState.STOPPED, PipeTransportState.STOPPING}:
            raise RuntimeError("The named-pipe transport is not active.")
        self._outgoing.put(bytes(payload))

    def stop(self, timeout_ms: int = 3_000) -> bool:
        """Cancel pending Win32 I/O and join the worker within a timeout."""
        if timeout_ms <= 0:
            raise ValueError("Shutdown timeout must be positive.")
        worker = self._worker
        if worker is None or not worker.is_alive():
            self._set_state(PipeTransportState.STOPPED)
            return True

        self._set_state(PipeTransportState.STOPPING)
        self._stop_requested.set()
        with self._connection_lock:
            connection = self._connection
        if connection is not None:
            connection.cancel()
        worker.join(timeout_ms / 1_000)
        if worker.is_alive():
            self._callbacks.error("The named-pipe worker did not stop in time.")
            return False
        self._set_state(PipeTransportState.STOPPED)
        return True

    def _run(self) -> None:
        try:
            while not self._stop_requested.is_set():
                connection = self._connect_with_retry()
                if connection is None:
                    return
                with self._connection_lock:
                    self._connection = connection
                self._set_state(PipeTransportState.CONNECTED)
                try:
                    self._serve(connection)
                except PipeCancelled:
                    if not self._stop_requested.is_set():
                        self._callbacks.error(
                            "Named-pipe I/O was cancelled unexpectedly."
                        )
                except PipeDisconnected:
                    if not self._stop_requested.is_set():
                        self._set_state(PipeTransportState.DISCONNECTED)
                except PipeTransportError as error:
                    if not self._stop_requested.is_set():
                        self._callbacks.error(str(error))
                        self._set_state(PipeTransportState.DISCONNECTED)
                finally:
                    connection.close()
                    with self._connection_lock:
                        if self._connection is connection:
                            self._connection = None
                if not self._stop_requested.is_set():
                    self._set_state(PipeTransportState.CONNECTING)
        finally:
            self._set_state(PipeTransportState.STOPPED)

    def _connect_with_retry(self) -> NamedPipeConnection | None:
        deadline = time.monotonic() + (self._connect_timeout_ms / 1_000)
        while not self._stop_requested.is_set():
            try:
                connection = self._connector.connect(self._pipe_name)
            except PipeTransportError as error:
                self._callbacks.error(str(error))
                return None
            if connection is not None:
                return connection
            if time.monotonic() >= deadline:
                self._callbacks.error("Timed out waiting for the mpv named pipe.")
                return None
            self._stop_requested.wait(self._connect_retry_ms / 1_000)
        return None

    def _serve(self, connection: NamedPipeConnection) -> None:
        while not self._stop_requested.is_set():
            self._flush_outgoing(connection)
            chunk = connection.read(self._read_poll_ms)
            if chunk == b"":
                raise PipeDisconnected("The mpv named pipe was closed.")
            if chunk is not None:
                self._callbacks.data_received(chunk)

    def _flush_outgoing(self, connection: NamedPipeConnection) -> None:
        while not self._stop_requested.is_set():
            try:
                payload = self._outgoing.get_nowait()
            except Empty:
                return
            connection.write(payload, self._stop_requested)

    def _set_state(self, state: PipeTransportState) -> None:
        if state is self._state:
            return
        self._state = state
        self._callbacks.state_changed(state)


class _Overlapped(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_size_t),
        ("InternalHigh", ctypes.c_size_t),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


class Win32NamedPipeConnector:
    """Open mpv's pipe for overlapped read and write operations."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Windows named pipes require Windows.")
        self._api = _load_kernel32()

    def connect(self, pipe_name: str) -> NamedPipeConnection | None:
        handle = self._api.CreateFileW(
            pipe_name,
            _GENERIC_READ | _GENERIC_WRITE,
            0,
            None,
            _OPEN_EXISTING,
            _FILE_FLAG_OVERLAPPED,
            None,
        )
        if handle == _INVALID_HANDLE_VALUE:
            error_code = ctypes.get_last_error()
            if error_code in {_ERROR_FILE_NOT_FOUND, _ERROR_PIPE_BUSY}:
                return None
            raise PipeTransportError(_safe_win32_error("open", error_code))
        return Win32NamedPipeConnection(self._api, cast(int, handle))


class Win32NamedPipeConnection:
    """One overlapped Windows pipe handle with independent read/write events."""

    def __init__(self, api: Any, handle: int) -> None:
        self._api = api
        self._handle = handle
        self._closed = False
        self._read_event = self._create_event()
        self._write_event = self._create_event()
        self._read_overlapped: Any = _Overlapped(hEvent=self._read_event)
        self._write_overlapped: Any = _Overlapped(hEvent=self._write_event)
        self._read_buffer: Any = ctypes.create_string_buffer(_READ_CHUNK_SIZE)
        self._read_count = wintypes.DWORD()
        self._read_pending = False

    def read(self, timeout_ms: int) -> bytes | None:
        if not self._read_pending:
            self._api.ResetEvent(self._read_event)
            self._read_count = wintypes.DWORD()
            succeeded = self._api.ReadFile(
                self._handle,
                self._read_buffer,
                _READ_CHUNK_SIZE,
                ctypes.byref(self._read_count),
                ctypes.byref(self._read_overlapped),
            )
            if succeeded:
                return self._read_result(self._read_count.value)
            error_code = ctypes.get_last_error()
            if error_code in _DISCONNECT_ERRORS:
                raise PipeDisconnected("The mpv named pipe disconnected.")
            if error_code != _ERROR_IO_PENDING:
                raise PipeTransportError(_safe_win32_error("read", error_code))
            self._read_pending = True

        try:
            transferred = self._wait_for_operation(
                self._read_event,
                self._read_overlapped,
                timeout_ms,
            )
        except PipeTransportError:
            self._read_pending = False
            raise
        if transferred is None:
            return None
        self._read_pending = False
        return self._read_result(transferred)

    def write(self, payload: bytes, cancel: Event) -> None:
        if self._closed:
            raise PipeDisconnected("The mpv named pipe is closed.")
        self._api.ResetEvent(self._write_event)
        self._write_overlapped = _Overlapped(hEvent=self._write_event)
        buffer: Any = ctypes.create_string_buffer(payload)
        written = wintypes.DWORD()
        succeeded = self._api.WriteFile(
            self._handle,
            buffer,
            len(payload),
            ctypes.byref(written),
            ctypes.byref(self._write_overlapped),
        )
        if succeeded:
            if written.value != len(payload):
                raise PipeTransportError("A named-pipe write was incomplete.")
            return
        error_code = ctypes.get_last_error()
        if error_code in _DISCONNECT_ERRORS:
            raise PipeDisconnected("The mpv named pipe disconnected.")
        if error_code != _ERROR_IO_PENDING:
            raise PipeTransportError(_safe_win32_error("write", error_code))

        deadline = time.monotonic() + (_IO_TIMEOUT_MS / 1_000)
        while not cancel.is_set():
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1_000))
            transferred = self._wait_for_operation(
                self._write_event,
                self._write_overlapped,
                min(_IO_POLL_MS, remaining_ms),
            )
            if transferred is not None:
                if transferred != len(payload):
                    raise PipeTransportError("A named-pipe write was incomplete.")
                return
            if time.monotonic() >= deadline:
                self._api.CancelIoEx(
                    self._handle,
                    ctypes.byref(self._write_overlapped),
                )
                raise PipeTransportError("A named-pipe write timed out.")
        self._api.CancelIoEx(self._handle, ctypes.byref(self._write_overlapped))
        raise PipeCancelled("Named-pipe write cancelled.")

    def cancel(self) -> None:
        if not self._closed:
            self._api.CancelIoEx(self._handle, None)

    def close(self) -> None:
        if self._closed:
            return
        self.cancel()
        self._api.CloseHandle(self._read_event)
        self._api.CloseHandle(self._write_event)
        self._api.CloseHandle(self._handle)
        self._closed = True

    def _create_event(self) -> int:
        event = self._api.CreateEventW(None, True, False, None)
        if not event:
            raise PipeTransportError(
                _safe_win32_error("create an I/O event", ctypes.get_last_error())
            )
        return cast(int, event)

    def _wait_for_operation(
        self,
        event: int,
        overlapped: Any,
        timeout_ms: int,
    ) -> int | None:
        wait_result = self._api.WaitForSingleObject(event, timeout_ms)
        if wait_result == _WAIT_TIMEOUT:
            return None
        if wait_result == _WAIT_FAILED:
            raise PipeTransportError(
                _safe_win32_error("wait for I/O", ctypes.get_last_error())
            )
        if wait_result != _WAIT_OBJECT_0:
            raise PipeTransportError("Named-pipe I/O returned an unknown wait state.")

        transferred = wintypes.DWORD()
        succeeded = self._api.GetOverlappedResult(
            self._handle,
            ctypes.byref(overlapped),
            ctypes.byref(transferred),
            False,
        )
        if succeeded:
            return transferred.value
        error_code = ctypes.get_last_error()
        if error_code == _ERROR_OPERATION_ABORTED:
            raise PipeCancelled("Named-pipe I/O cancelled.")
        if error_code in _DISCONNECT_ERRORS:
            raise PipeDisconnected("The mpv named pipe disconnected.")
        raise PipeTransportError(_safe_win32_error("complete I/O", error_code))

    def _read_result(self, transferred: int) -> bytes:
        if transferred == 0:
            raise PipeDisconnected("The mpv named pipe was closed.")
        return bytes(self._read_buffer.raw[:transferred])


_DISCONNECT_ERRORS = {
    _ERROR_BROKEN_PIPE,
    _ERROR_NO_DATA,
    _ERROR_PIPE_NOT_CONNECTED,
}


def _safe_win32_error(operation: str, error_code: int) -> str:
    return f"Could not {operation} the mpv named pipe (Windows error {error_code})."


def _load_kernel32() -> Any:
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    api.CreateFileW.restype = wintypes.HANDLE
    api.CreateEventW.argtypes = [
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    api.CreateEventW.restype = wintypes.HANDLE
    api.ResetEvent.argtypes = [wintypes.HANDLE]
    api.ResetEvent.restype = wintypes.BOOL
    api.ReadFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.LPVOID,
        ctypes.POINTER(_Overlapped),
    ]
    api.ReadFile.restype = wintypes.BOOL
    api.WriteFile.argtypes = api.ReadFile.argtypes
    api.WriteFile.restype = wintypes.BOOL
    api.GetOverlappedResult.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_Overlapped),
        ctypes.POINTER(wintypes.DWORD),
        wintypes.BOOL,
    ]
    api.GetOverlappedResult.restype = wintypes.BOOL
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.CancelIoEx.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
    api.CancelIoEx.restype = wintypes.BOOL
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    return api
