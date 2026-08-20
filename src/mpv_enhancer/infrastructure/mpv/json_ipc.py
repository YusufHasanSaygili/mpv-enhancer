"""Line-framed, request-aware client for mpv's JSON IPC protocol."""

import json
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future
from dataclasses import dataclass
from threading import Lock, Timer
from typing import Protocol, cast

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]

_DEFAULT_TIMEOUT_SECONDS = 3.0
_MAXIMUM_FRAME_BYTES = 1_048_576


class MpvIpcError(RuntimeError):
    """Base class for safe mpv JSON IPC failures."""


class MpvIpcCommandError(MpvIpcError):
    """mpv rejected a command with a protocol error response."""


class MpvIpcTimeout(MpvIpcError):
    """A pending command did not receive a reply before its deadline."""


class MpvIpcProtocolError(MpvIpcError):
    """A received line did not satisfy the expected mpv JSON shape."""


class MpvIpcClosed(MpvIpcError):
    """The IPC client closed while a command was pending."""


class Deadline(Protocol):
    """Cancelable timeout returned by a deadline scheduler."""

    def cancel(self) -> None: ...


DeadlineScheduler = Callable[[float, Callable[[], None]], Deadline]
PropertyListener = Callable[[str, JsonValue], None]


@dataclass(frozen=True, slots=True)
class MpvIpcEvent:
    """One unsolicited mpv event with its validated event name."""

    name: str
    payload: Mapping[str, JsonValue]


@dataclass(frozen=True, slots=True)
class MpvIpcRequest:
    """A numbered request and the future resolved by its reply."""

    request_id: int
    future: Future[JsonValue]


@dataclass(frozen=True, slots=True)
class MpvPropertyObservation:
    """An mpv property observer ID and its registration request."""

    observer_id: int
    request: MpvIpcRequest


def _ignore_event(_event: MpvIpcEvent) -> None:
    pass


def _ignore_message(_message: str) -> None:
    pass


def _ignore_request_id(_request_id: int) -> None:
    pass


@dataclass(frozen=True, slots=True)
class MpvIpcCallbacks:
    """Callbacks invoked on the same thread that feeds transport bytes."""

    event_received: Callable[[MpvIpcEvent], None] = _ignore_event
    protocol_error: Callable[[str], None] = _ignore_message
    late_reply: Callable[[int], None] = _ignore_request_id


@dataclass(slots=True)
class _PendingRequest:
    future: Future[JsonValue]
    deadline: Deadline | None = None


class MpvIpcClient:
    """Encode commands and route newline-delimited replies and events."""

    def __init__(
        self,
        *,
        send: Callable[[bytes], None],
        callbacks: MpvIpcCallbacks | None = None,
        scheduler: DeadlineScheduler | None = None,
        maximum_frame_bytes: int = _MAXIMUM_FRAME_BYTES,
    ) -> None:
        if maximum_frame_bytes <= 0:
            raise ValueError("Maximum frame size must be positive.")
        self._send = send
        self._callbacks = MpvIpcCallbacks() if callbacks is None else callbacks
        self._scheduler = _schedule_deadline if scheduler is None else scheduler
        self._maximum_frame_bytes = maximum_frame_bytes
        self._frame_buffer = bytearray()
        self._frame_lock = Lock()
        self._pending: dict[int, _PendingRequest] = {}
        self._pending_lock = Lock()
        self._next_request_id = 1
        self._observers: dict[int, PropertyListener] = {}
        self._observer_lock = Lock()
        self._next_observer_id = 1

    @property
    def pending_count(self) -> int:
        with self._pending_lock:
            return len(self._pending)

    def request(
        self,
        command: Sequence[JsonValue],
        *,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> MpvIpcRequest:
        """Send a numbered command and return its pending reply future."""
        if not command:
            raise ValueError("An mpv command cannot be empty.")
        if timeout_seconds <= 0:
            raise ValueError("An mpv request timeout must be positive.")

        with self._pending_lock:
            request_id = self._next_request_id
            self._next_request_id += 1
        payload = _encode_request(command, request_id)
        future: Future[JsonValue] = Future()
        pending = _PendingRequest(future=future)
        with self._pending_lock:
            self._pending[request_id] = pending

        deadline = self._scheduler(
            timeout_seconds,
            lambda: self._expire_request(request_id),
        )
        with self._pending_lock:
            current = self._pending.get(request_id)
            if current is pending:
                pending.deadline = deadline
            else:
                deadline.cancel()

        try:
            self._send(payload)
        except Exception as error:
            removed = self._take_pending(request_id)
            if removed is not None:
                _cancel_deadline(removed)
                removed.future.set_exception(error)
            raise
        return MpvIpcRequest(request_id=request_id, future=future)

    def observe_property(
        self,
        name: str,
        listener: PropertyListener,
        *,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> MpvPropertyObservation:
        """Register one observer and route matching property-change events."""
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("An observed property requires a name.")
        with self._observer_lock:
            observer_id = self._next_observer_id
            self._next_observer_id += 1
            self._observers[observer_id] = listener
        try:
            request = self.request(
                ("observe_property", observer_id, normalized_name),
                timeout_seconds=timeout_seconds,
            )
        except Exception:
            self._remove_observer(observer_id)
            raise

        request.future.add_done_callback(
            lambda completed: self._discard_failed_observation(observer_id, completed)
        )
        return MpvPropertyObservation(observer_id=observer_id, request=request)

    def unobserve_property(
        self,
        observer_id: int,
        *,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> MpvIpcRequest:
        """Stop local routing and ask mpv to remove an observer."""
        self._remove_observer(observer_id)
        return self.request(
            ("unobserve_property", observer_id),
            timeout_seconds=timeout_seconds,
        )

    def feed_data(self, chunk: bytes) -> None:
        """Consume any fragmented or coalesced UTF-8 line frames."""
        if not chunk:
            return
        frames: list[bytes] = []
        overflow = False
        with self._frame_lock:
            self._frame_buffer.extend(chunk)
            while True:
                separator = self._frame_buffer.find(b"\n")
                if separator < 0:
                    break
                frame = bytes(self._frame_buffer[:separator]).rstrip(b"\r")
                del self._frame_buffer[: separator + 1]
                if frame:
                    frames.append(frame)
            if len(self._frame_buffer) > self._maximum_frame_bytes:
                self._frame_buffer.clear()
                overflow = True
        if overflow:
            self._callbacks.protocol_error("An mpv IPC frame exceeded the size limit.")
        for frame in frames:
            if len(frame) > self._maximum_frame_bytes:
                self._callbacks.protocol_error(
                    "An mpv IPC frame exceeded the size limit."
                )
                continue
            self._consume_frame(frame)

    def close(self) -> None:
        """Fail all pending requests and discard property observers."""
        with self._pending_lock:
            pending = tuple(self._pending.values())
            self._pending.clear()
        for request in pending:
            _cancel_deadline(request)
            request.future.set_exception(MpvIpcClosed("The mpv IPC client closed."))
        with self._observer_lock:
            self._observers.clear()
        with self._frame_lock:
            self._frame_buffer.clear()

    def _consume_frame(self, frame: bytes) -> None:
        try:
            decoded = frame.decode("utf-8", errors="strict")
            parsed: object = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._callbacks.protocol_error(
                "mpv IPC returned a line without valid JSON."
            )
            return
        if not isinstance(parsed, dict) or not all(
            isinstance(key, str) for key in parsed
        ):
            self._callbacks.protocol_error("mpv IPC returned a non-object JSON frame.")
            return

        message = cast(dict[str, JsonValue], parsed)
        request_id = message.get("request_id")
        if isinstance(request_id, int) and not isinstance(request_id, bool):
            self._consume_reply(request_id, message)
            return
        event_name = message.get("event")
        if isinstance(event_name, str) and event_name:
            self._consume_event(event_name, message)
            return
        self._callbacks.protocol_error("mpv IPC returned an unrecognized JSON object.")

    def _consume_reply(
        self,
        request_id: int,
        message: Mapping[str, JsonValue],
    ) -> None:
        pending = self._take_pending(request_id)
        if pending is None:
            self._callbacks.late_reply(request_id)
            return
        _cancel_deadline(pending)
        error = message.get("error")
        if not isinstance(error, str):
            failure = MpvIpcProtocolError(
                "An mpv reply did not include an error field."
            )
            pending.future.set_exception(failure)
            self._callbacks.protocol_error(str(failure))
            return
        if error != "success":
            pending.future.set_exception(MpvIpcCommandError(f"mpv error: {error}"))
            return
        pending.future.set_result(message.get("data"))

    def _consume_event(
        self,
        event_name: str,
        message: dict[str, JsonValue],
    ) -> None:
        event = MpvIpcEvent(name=event_name, payload=dict(message))
        self._callbacks.event_received(event)
        if event_name != "property-change":
            return
        observer_id = message.get("id")
        property_name = message.get("name")
        if (
            not isinstance(observer_id, int)
            or isinstance(observer_id, bool)
            or not isinstance(property_name, str)
        ):
            self._callbacks.protocol_error(
                "An mpv property-change event had invalid observer metadata."
            )
            return
        with self._observer_lock:
            listener = self._observers.get(observer_id)
        if listener is not None:
            listener(property_name, message.get("data"))

    def _expire_request(self, request_id: int) -> None:
        pending = self._take_pending(request_id)
        if pending is None:
            return
        pending.future.set_exception(
            MpvIpcTimeout(f"mpv request {request_id} timed out.")
        )

    def _take_pending(self, request_id: int) -> _PendingRequest | None:
        with self._pending_lock:
            return self._pending.pop(request_id, None)

    def _remove_observer(self, observer_id: int) -> None:
        with self._observer_lock:
            self._observers.pop(observer_id, None)

    def _discard_failed_observation(
        self,
        observer_id: int,
        completed: Future[JsonValue],
    ) -> None:
        if completed.cancelled() or completed.exception() is not None:
            self._remove_observer(observer_id)


def _encode_request(command: Sequence[JsonValue], request_id: int) -> bytes:
    try:
        serialized = json.dumps(
            {"command": list(command), "request_id": request_id},
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise ValueError("The mpv command must contain valid JSON values.") from error
    return serialized.encode("utf-8") + b"\n"


def _schedule_deadline(
    delay_seconds: float,
    callback: Callable[[], None],
) -> Deadline:
    timer = Timer(delay_seconds, callback)
    timer.daemon = True
    timer.start()
    return timer


def _cancel_deadline(pending: _PendingRequest) -> None:
    if pending.deadline is not None:
        pending.deadline.cancel()
