"""Typed playback commands and property observation over mpv JSON IPC."""

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QObject, Signal

from mpv_enhancer.infrastructure.mpv.json_ipc import JsonValue

PlaybackPropertyListener = Callable[[str, JsonValue], None]


class JsonIpcClient(Protocol):
    """JSON IPC operations required by the playback adapter."""

    def request(self, command: Sequence[JsonValue]) -> object: ...

    def observe_property(
        self,
        name: str,
        listener: PlaybackPropertyListener,
    ) -> object: ...


class PlaybackAdapter(Protocol):
    """Playback surface consumed by the application controller."""

    def begin_observing(self, listener: PlaybackPropertyListener) -> None: ...

    def load_file(self, path: Path) -> None: ...

    def set_paused(self, paused: bool) -> None: ...

    def seek_absolute(self, seconds: float) -> None: ...

    def stop(self) -> None: ...


class MpvJsonPlaybackAdapter(QObject):
    """Issue a fixed allowlist of playback commands through JSON IPC."""

    propertyChanged = Signal(str, object)

    def __init__(self, client: JsonIpcClient) -> None:
        super().__init__()
        self._client = client
        self._observing = False

    def begin_observing(self, listener: PlaybackPropertyListener) -> None:
        if self._observing:
            raise RuntimeError("Playback properties are already being observed.")
        self._observing = True
        self.propertyChanged.connect(listener)
        for name in ("duration", "time-pos", "pause"):
            self._client.observe_property(name, self._property_changed)

    def load_file(self, path: Path) -> None:
        """Load one local path as a JSON value, never as shell syntax."""
        self._client.request(("loadfile", str(path), "replace"))

    def set_paused(self, paused: bool) -> None:
        self._client.request(("set_property", "pause", paused))

    def seek_absolute(self, seconds: float) -> None:
        self._client.request(("seek", seconds, "absolute+exact"))

    def stop(self) -> None:
        self._client.request(("stop",))

    def _property_changed(self, name: str, value: JsonValue) -> None:
        self.propertyChanged.emit(name, value)
