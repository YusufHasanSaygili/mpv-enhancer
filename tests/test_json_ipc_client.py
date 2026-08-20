import json
from collections.abc import Callable

import pytest

from mpv_enhancer.infrastructure.mpv.json_ipc import (
    JsonValue,
    MpvIpcCallbacks,
    MpvIpcClient,
    MpvIpcClosed,
    MpvIpcCommandError,
    MpvIpcEvent,
    MpvIpcTimeout,
)


class FakeDeadline:
    def __init__(self, callback: Callable[[], None]) -> None:
        self._callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        if not self.cancelled:
            self._callback()


class FakeScheduler:
    def __init__(self) -> None:
        self.delays: list[float] = []
        self.deadlines: list[FakeDeadline] = []

    def __call__(
        self,
        delay_seconds: float,
        callback: Callable[[], None],
    ) -> FakeDeadline:
        self.delays.append(delay_seconds)
        deadline = FakeDeadline(callback)
        self.deadlines.append(deadline)
        return deadline


def _decode_request(payload: bytes) -> dict[str, JsonValue]:
    assert payload.endswith(b"\n")
    decoded = json.loads(payload)
    assert isinstance(decoded, dict)
    return decoded


def test_partial_and_multiple_frames_resolve_the_matching_requests() -> None:
    sent: list[bytes] = []
    scheduler = FakeScheduler()
    client = MpvIpcClient(send=sent.append, scheduler=scheduler)
    first = client.request(("get_property", "pause"))
    second = client.request(("get_property", "media-title"))

    first_reply = json.dumps(
        {"request_id": first.request_id, "error": "success", "data": False}
    ).encode()
    second_reply = json.dumps(
        {
            "request_id": second.request_id,
            "error": "success",
            "data": "Kardan Adam ☃",
        },
        ensure_ascii=False,
    ).encode()
    client.feed_data(first_reply[:13])
    client.feed_data(first_reply[13:] + b"\n" + second_reply + b"\n")

    assert first.future.result() is False
    assert second.future.result() == "Kardan Adam ☃"
    assert [_decode_request(payload)["request_id"] for payload in sent] == [1, 2]
    assert all(deadline.cancelled for deadline in scheduler.deadlines)


def test_error_reply_fails_only_its_pending_request() -> None:
    sent: list[bytes] = []
    client = MpvIpcClient(send=sent.append, scheduler=FakeScheduler())
    request = client.request(("get_property", "missing-property"))

    client.feed_data(
        json.dumps(
            {
                "request_id": request.request_id,
                "error": "property unavailable",
            }
        ).encode()
        + b"\n"
    )

    with pytest.raises(MpvIpcCommandError, match="property unavailable"):
        request.future.result()


def test_timeout_removes_pending_request_and_late_reply_is_ignored() -> None:
    sent: list[bytes] = []
    late_replies: list[int] = []
    scheduler = FakeScheduler()
    client = MpvIpcClient(
        send=sent.append,
        scheduler=scheduler,
        callbacks=MpvIpcCallbacks(late_reply=late_replies.append),
    )
    request = client.request(("get_property", "duration"), timeout_seconds=0.25)

    scheduler.deadlines[0].fire()
    with pytest.raises(MpvIpcTimeout, match="timed out"):
        request.future.result()

    client.feed_data(
        json.dumps(
            {"request_id": request.request_id, "error": "success", "data": 12.5}
        ).encode()
        + b"\n"
    )

    assert scheduler.delays == [0.25]
    assert late_replies == [request.request_id]


def test_malformed_json_does_not_poison_the_following_event_frame() -> None:
    events: list[MpvIpcEvent] = []
    protocol_errors: list[str] = []
    client = MpvIpcClient(
        send=lambda _payload: None,
        scheduler=FakeScheduler(),
        callbacks=MpvIpcCallbacks(
            event_received=events.append,
            protocol_error=protocol_errors.append,
        ),
    )
    valid_event = json.dumps({"event": "file-loaded", "playlist_entry_id": 9}).encode()

    client.feed_data(b'{"broken":\n' + valid_event + b"\n")

    assert len(protocol_errors) == 1
    assert "valid JSON" in protocol_errors[0]
    assert [event.name for event in events] == ["file-loaded"]


def test_property_observation_routes_values_by_observer_id() -> None:
    sent: list[bytes] = []
    observed: list[tuple[str, JsonValue]] = []
    events: list[MpvIpcEvent] = []
    client = MpvIpcClient(
        send=sent.append,
        scheduler=FakeScheduler(),
        callbacks=MpvIpcCallbacks(event_received=events.append),
    )

    observation = client.observe_property(
        "pause",
        lambda name, value: observed.append((name, value)),
    )
    request_payload = _decode_request(sent[0])
    client.feed_data(
        json.dumps(
            {
                "request_id": observation.request.request_id,
                "error": "success",
            }
        ).encode()
        + b"\n"
    )
    client.feed_data(
        json.dumps(
            {
                "event": "property-change",
                "id": observation.observer_id,
                "name": "pause",
                "data": True,
            }
        ).encode()
        + b"\n"
    )

    assert request_payload["command"] == [
        "observe_property",
        observation.observer_id,
        "pause",
    ]
    assert observation.request.future.result() is None
    assert observed == [("pause", True)]
    assert [event.name for event in events] == ["property-change"]


def test_close_fails_pending_requests_and_cancels_their_deadlines() -> None:
    scheduler = FakeScheduler()
    client = MpvIpcClient(send=lambda _payload: None, scheduler=scheduler)
    request = client.request(("get_property", "time-pos"))

    client.close()

    with pytest.raises(MpvIpcClosed, match="closed"):
        request.future.result()
    assert client.pending_count == 0
    assert scheduler.deadlines[0].cancelled


def test_send_failure_rolls_back_the_pending_request() -> None:
    scheduler = FakeScheduler()

    def fail_send(_payload: bytes) -> None:
        raise OSError("synthetic transport failure")

    client = MpvIpcClient(send=fail_send, scheduler=scheduler)

    with pytest.raises(OSError, match="synthetic transport failure"):
        client.request(("get_property", "pause"))

    assert client.pending_count == 0
    assert scheduler.deadlines[0].cancelled


def test_invalid_and_oversized_frames_are_isolated_without_payload_echo() -> None:
    errors: list[str] = []
    client = MpvIpcClient(
        send=lambda _payload: None,
        scheduler=FakeScheduler(),
        maximum_frame_bytes=8,
        callbacks=MpvIpcCallbacks(protocol_error=errors.append),
    )

    client.feed_data(b"")
    client.feed_data(b"\xff\n[]\n{}\n")
    client.feed_data(b"123456789")

    assert len(errors) == 4
    assert all("123456789" not in error for error in errors)


def test_request_validation_rejects_invalid_commands_before_sending() -> None:
    sent: list[bytes] = []
    client = MpvIpcClient(send=sent.append, scheduler=FakeScheduler())

    with pytest.raises(ValueError, match="cannot be empty"):
        client.request(())
    with pytest.raises(ValueError, match="timeout"):
        client.request(("get_property", "pause"), timeout_seconds=0)
    with pytest.raises(ValueError, match="valid JSON"):
        client.request(("set_property", "volume", float("nan")))

    assert sent == []


def test_default_deadline_scheduler_expires_a_request() -> None:
    client = MpvIpcClient(send=lambda _payload: None)
    request = client.request(("get_property", "duration"), timeout_seconds=0.01)

    with pytest.raises(MpvIpcTimeout, match="timed out"):
        request.future.result(timeout=1)
