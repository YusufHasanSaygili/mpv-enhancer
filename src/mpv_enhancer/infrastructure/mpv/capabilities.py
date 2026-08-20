"""Typed, cached capability probing over mpv's reviewed property surface."""

from collections.abc import Sequence
from concurrent.futures import Future
from dataclasses import dataclass
from functools import partial
from threading import Lock
from typing import Protocol

from mpv_enhancer.infrastructure.mpv.json_ipc import (
    JsonValue,
    MpvIpcRequest,
)

_CAPABILITY_PROPERTIES = ("mpv-version", "property-list", "command-list")


class MpvCapabilityError(RuntimeError):
    """The capability response could not be normalized safely."""


@dataclass(frozen=True, slots=True)
class MpvCapabilities:
    """Immutable support snapshot for one trusted mpv executable."""

    version: str
    properties: frozenset[str]
    commands: frozenset[str]

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("An mpv capability snapshot requires a version.")
        for label, names in (
            ("property", self.properties),
            ("command", self.commands),
        ):
            if any(not name.strip() for name in names):
                raise ValueError(f"An mpv {label} name cannot be empty.")

    def supports_property(self, name: str) -> bool:
        """Return whether mpv reported one exact property name."""
        return name in self.properties

    def supports_command(self, name: str) -> bool:
        """Return whether mpv reported one exact command name."""
        return name in self.commands


class CapabilityIpcClient(Protocol):
    """Narrow IPC surface required by the capability probe."""

    def request(self, command: Sequence[JsonValue]) -> MpvIpcRequest: ...


class MpvCapabilityProbe:
    """Read and cache version, property, and command support once per session."""

    def __init__(self, client: CapabilityIpcClient) -> None:
        self._client = client
        self._lock = Lock()
        self._cached: MpvCapabilities | None = None
        self._pending: Future[MpvCapabilities] | None = None

    def probe(self) -> Future[MpvCapabilities]:
        """Return one shared probe or a completed future for the cached result."""
        with self._lock:
            if self._cached is not None:
                completed: Future[MpvCapabilities] = Future()
                completed.set_result(self._cached)
                return completed
            if self._pending is not None:
                return self._pending
            aggregate: Future[MpvCapabilities] = Future()
            self._pending = aggregate

        try:
            requests = {
                name: self._client.request(("get_property", name)).future
                for name in _CAPABILITY_PROPERTIES
            }
        except Exception as error:
            with self._lock:
                self._pending = None
            aggregate.set_exception(error)
            return aggregate

        values: dict[str, JsonValue] = {}
        state = {"settled": False}
        for name, future in requests.items():
            future.add_done_callback(
                partial(
                    self._request_completed,
                    aggregate,
                    values,
                    state,
                    name,
                )
            )
        return aggregate

    def _request_completed(
        self,
        aggregate: Future[MpvCapabilities],
        values: dict[str, JsonValue],
        state: dict[str, bool],
        name: str,
        finished: Future[JsonValue],
    ) -> None:
        try:
            value = finished.result()
        except Exception as request_error:
            self._finish_with_error(aggregate, state, request_error)
            return

        capabilities: MpvCapabilities | None = None
        normalization_error: Exception | None = None
        with self._lock:
            if state["settled"]:
                return
            values[name] = value
            if len(values) == len(_CAPABILITY_PROPERTIES):
                try:
                    capabilities = _normalize_capabilities(values)
                except Exception as caught:
                    normalization_error = caught
                else:
                    self._cached = capabilities
                state["settled"] = True
                self._pending = None
        if normalization_error is not None:
            aggregate.set_exception(normalization_error)
        elif capabilities is not None:
            aggregate.set_result(capabilities)

    def _finish_with_error(
        self,
        aggregate: Future[MpvCapabilities],
        state: dict[str, bool],
        error: Exception,
    ) -> None:
        with self._lock:
            if state["settled"]:
                return
            state["settled"] = True
            self._pending = None
        aggregate.set_exception(error)


def _normalize_capabilities(values: dict[str, JsonValue]) -> MpvCapabilities:
    version = values.get("mpv-version")
    if not isinstance(version, str) or not version.strip():
        raise MpvCapabilityError("mpv returned an invalid version capability.")
    normalized_version = version.strip()
    if normalized_version.casefold().startswith("mpv "):
        normalized_version = normalized_version[4:].strip()
    return MpvCapabilities(
        version=normalized_version,
        properties=_normalize_property_list(values.get("property-list")),
        commands=_normalize_command_list(values.get("command-list")),
    )


def _normalize_property_list(value: JsonValue | None) -> frozenset[str]:
    if not isinstance(value, list) or any(
        not isinstance(name, str) or not name.strip() for name in value
    ):
        raise MpvCapabilityError("mpv returned an invalid property list.")
    return frozenset(name.strip() for name in value if isinstance(name, str))


def _normalize_command_list(value: JsonValue | None) -> frozenset[str]:
    if not isinstance(value, list):
        raise MpvCapabilityError("mpv returned an invalid command list.")
    names: set[str] = set()
    for command in value:
        if not isinstance(command, dict):
            raise MpvCapabilityError("mpv returned an invalid command list.")
        name = command.get("name")
        if not isinstance(name, str) or not name.strip():
            raise MpvCapabilityError("mpv returned an invalid command list.")
        names.add(name.strip())
    return frozenset(names)
