import ctypes
from collections import deque
from collections.abc import Sequence
from threading import Event

import pytest

from mpv_enhancer.infrastructure.mpv import pipe_transport
from mpv_enhancer.infrastructure.mpv.pipe_transport import (
    NamedPipeCallbacks,
    NamedPipeTransport,
    PipeCancelled,
    PipeDisconnected,
    PipeTransportError,
    PipeTransportState,
    Win32NamedPipeConnector,
    create_mpv_pipe_name,
)


class FakeConnection:
    def __init__(self, reads: Sequence[bytes | None | Exception] = ()) -> None:
        self._reads = deque(reads)
        self.cancelled = Event()
        self.closed = False
        self.writes: list[bytes] = []
        self.written = Event()

    def read(self, _timeout_ms: int) -> bytes | None:
        if self._reads:
            result = self._reads.popleft()
            if isinstance(result, Exception):
                raise result
            return result
        self.cancelled.wait(0.01)
        return None

    def write(self, payload: bytes, _cancel: Event) -> None:
        self.writes.append(payload)
        self.written.set()

    def cancel(self) -> None:
        self.cancelled.set()

    def close(self) -> None:
        self.closed = True


class BlockingConnection(FakeConnection):
    def __init__(self) -> None:
        super().__init__()
        self.read_started = Event()

    def read(self, _timeout_ms: int) -> bytes | None:
        self.read_started.set()
        self.cancelled.wait(5)
        raise PipeCancelled("Synthetic cancellation.")


class FakeConnector:
    def __init__(
        self,
        results: Sequence[FakeConnection | None],
    ) -> None:
        self._results = deque(results)
        self.calls: list[str] = []

    def connect(self, pipe_name: str) -> FakeConnection | None:
        self.calls.append(pipe_name)
        if self._results:
            return self._results.popleft()
        return None


def _callbacks(
    *,
    data: list[bytes] | None = None,
    states: list[PipeTransportState] | None = None,
    errors: list[str] | None = None,
    connected: Event | None = None,
    disconnected: Event | None = None,
) -> NamedPipeCallbacks:
    def receive(payload: bytes) -> None:
        if data is not None:
            data.append(payload)

    def change_state(state: PipeTransportState) -> None:
        if states is not None:
            states.append(state)
        if state is PipeTransportState.CONNECTED and connected is not None:
            connected.set()
        if state is PipeTransportState.DISCONNECTED and disconnected is not None:
            disconnected.set()

    def fail(message: str) -> None:
        if errors is not None:
            errors.append(message)

    return NamedPipeCallbacks(
        data_received=receive,
        state_changed=change_state,
        error=fail,
    )


def test_pipe_names_are_random_local_and_do_not_include_user_identity() -> None:
    first = create_mpv_pipe_name()
    second = create_mpv_pipe_name()

    assert first.startswith(r"\\.\pipe\mpv-enhancer-")
    assert first != second
    assert len(first.rsplit("-", 1)[-1]) == 32
    assert "user" not in first.casefold()


def test_connect_retries_until_the_pipe_becomes_available() -> None:
    connection = FakeConnection()
    connector = FakeConnector((None, None, connection))
    connected = Event()
    transport = NamedPipeTransport(
        connector=connector,
        callbacks=_callbacks(connected=connected),
        connect_retry_ms=1,
        connect_timeout_ms=500,
    )

    transport.start()
    assert connected.wait(1)
    assert transport.stop(1_000)

    assert len(connector.calls) == 3
    assert len(set(connector.calls)) == 1
    assert connection.closed


def test_fragmented_unicode_bytes_are_delivered_and_disconnect_is_reported() -> None:
    encoded = '{"event":"file-loaded","title":"Kardan Adam ☃"}\n'.encode()
    connection = FakeConnection(
        (
            encoded[:7],
            encoded[7:31],
            encoded[31:],
            PipeDisconnected("Synthetic peer close."),
        )
    )
    connector = FakeConnector((connection,))
    chunks: list[bytes] = []
    states: list[PipeTransportState] = []
    errors: list[str] = []
    disconnected = Event()
    transport = NamedPipeTransport(
        connector=connector,
        callbacks=_callbacks(
            data=chunks,
            states=states,
            errors=errors,
            disconnected=disconnected,
        ),
        connect_retry_ms=5,
        connect_timeout_ms=500,
    )

    transport.start()
    assert disconnected.wait(1)
    assert transport.stop(1_000)

    assert b"".join(chunks) == encoded
    assert PipeTransportState.CONNECTED in states
    assert PipeTransportState.DISCONNECTED in states
    assert errors == []


def test_duplex_worker_writes_unicode_json_while_a_read_is_pending() -> None:
    connection = FakeConnection()
    connector = FakeConnector((connection,))
    connected = Event()
    transport = NamedPipeTransport(
        connector=connector,
        callbacks=_callbacks(connected=connected),
        connect_retry_ms=1,
        connect_timeout_ms=500,
    )
    payload = '{"command":["set_property","sub-text","Merhaba 世界"]}\n'.encode()

    transport.start()
    assert connected.wait(1)
    transport.send(payload)
    assert connection.written.wait(1)
    assert transport.stop(1_000)

    assert connection.writes == [payload]


def test_shutdown_cancels_pending_io_and_joins_the_worker() -> None:
    connection = BlockingConnection()
    connector = FakeConnector((connection,))
    transport = NamedPipeTransport(
        connector=connector,
        callbacks=_callbacks(),
        connect_retry_ms=1,
        connect_timeout_ms=500,
    )

    transport.start()
    assert connection.read_started.wait(1)

    assert transport.stop(1_000)
    assert connection.cancelled.is_set()
    assert connection.closed
    assert transport.state is PipeTransportState.STOPPED


class FakeKernel32:
    def __init__(self, *, pending: bool = False) -> None:
        self.pending = pending
        self.handle = 700
        self.next_event = 800
        self.read_payload = "parçalı ☃".encode()
        self.writes: list[bytes] = []
        self.closed: list[int] = []
        self.cancelled = 0
        self.wait_results: deque[int] = deque()
        self.transfer_results: deque[int] = deque()

    def CreateFileW(self, *_arguments: object) -> int:
        return self.handle

    def CreateEventW(self, *_arguments: object) -> int:
        event = self.next_event
        self.next_event += 1
        return event

    def ResetEvent(self, _event: int) -> bool:
        return True

    def ReadFile(
        self,
        _handle: int,
        buffer: object,
        _size: int,
        read: object,
        _overlapped: object,
    ) -> bool:
        ctypes.memmove(buffer, self.read_payload, len(self.read_payload))
        if self.pending:
            ctypes.set_last_error(pipe_transport._ERROR_IO_PENDING)
            self.transfer_results.append(len(self.read_payload))
            return False
        read._obj.value = len(self.read_payload)  # type: ignore[attr-defined]
        return True

    def WriteFile(
        self,
        _handle: int,
        buffer: object,
        size: int,
        written: object,
        _overlapped: object,
    ) -> bool:
        self.writes.append(ctypes.string_at(buffer, size))
        if self.pending:
            ctypes.set_last_error(pipe_transport._ERROR_IO_PENDING)
            self.transfer_results.append(size)
            return False
        written._obj.value = size  # type: ignore[attr-defined]
        return True

    def WaitForSingleObject(self, _event: int, _timeout: int) -> int:
        if self.wait_results:
            return self.wait_results.popleft()
        return pipe_transport._WAIT_OBJECT_0

    def GetOverlappedResult(
        self,
        _handle: int,
        _overlapped: object,
        transferred: object,
        _wait: bool,
    ) -> bool:
        transferred._obj.value = self.transfer_results.popleft()  # type: ignore[attr-defined]
        return True

    def CancelIoEx(self, _handle: int, _overlapped: object) -> bool:
        self.cancelled += 1
        return True

    def CloseHandle(self, handle: int) -> bool:
        self.closed.append(handle)
        return True


def test_win32_connection_supports_immediate_duplex_io_and_idempotent_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeKernel32()
    monkeypatch.setattr(pipe_transport, "_load_kernel32", lambda: api)
    connector = Win32NamedPipeConnector()

    connection = connector.connect(create_mpv_pipe_name())
    assert connection is not None
    assert connection.read(25) == api.read_payload
    connection.write(b"outbound\n", Event())
    connection.cancel()
    connection.close()
    connection.close()

    assert api.writes == [b"outbound\n"]
    assert api.cancelled == 2
    assert api.closed == [800, 801, 700]


def test_win32_connection_keeps_pending_overlapped_read_and_write_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeKernel32(pending=True)
    api.wait_results.extend(
        (
            pipe_transport._WAIT_TIMEOUT,
            pipe_transport._WAIT_OBJECT_0,
            pipe_transport._WAIT_OBJECT_0,
        )
    )
    monkeypatch.setattr(pipe_transport, "_load_kernel32", lambda: api)
    connector = Win32NamedPipeConnector()
    connection = connector.connect(create_mpv_pipe_name())
    assert connection is not None

    assert connection.read(1) is None
    assert connection.read(25) == api.read_payload
    connection.write(b"pending outbound\n", Event())
    connection.close()

    assert api.writes == [b"pending outbound\n"]


def test_win32_connector_distinguishes_retryable_and_fatal_open_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeKernel32()

    def unavailable(*_arguments: object) -> int | None:
        ctypes.set_last_error(pipe_transport._ERROR_PIPE_BUSY)
        return pipe_transport._INVALID_HANDLE_VALUE

    api.CreateFileW = unavailable  # type: ignore[method-assign]
    monkeypatch.setattr(pipe_transport, "_load_kernel32", lambda: api)
    connector = Win32NamedPipeConnector()
    assert connector.connect(create_mpv_pipe_name()) is None

    def forbidden(*_arguments: object) -> int | None:
        ctypes.set_last_error(5)
        return pipe_transport._INVALID_HANDLE_VALUE

    api.CreateFileW = forbidden  # type: ignore[method-assign]
    with pytest.raises(PipeTransportError, match="Windows error 5"):
        connector.connect(create_mpv_pipe_name())


def test_win32_connection_reports_a_broken_pipe_without_leaking_a_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeKernel32()

    def disconnected(*_arguments: object) -> bool:
        ctypes.set_last_error(pipe_transport._ERROR_BROKEN_PIPE)
        return False

    api.ReadFile = disconnected  # type: ignore[method-assign]
    monkeypatch.setattr(pipe_transport, "_load_kernel32", lambda: api)
    connector = Win32NamedPipeConnector()
    connection = connector.connect(create_mpv_pipe_name())
    assert connection is not None

    with pytest.raises(PipeDisconnected, match="disconnected") as raised:
        connection.read(25)

    assert "mpv-enhancer-" not in str(raised.value)
    connection.close()
