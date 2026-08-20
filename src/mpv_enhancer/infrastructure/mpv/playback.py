"""Typed playback commands and property observation over mpv JSON IPC."""

from collections import deque
from collections.abc import Callable, Sequence
from concurrent.futures import Future
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QObject, Signal

from mpv_enhancer.domain.settings import EffectivePlaybackSettings, VideoDimensions
from mpv_enhancer.infrastructure.mpv.capabilities import MpvCapabilities
from mpv_enhancer.infrastructure.mpv.json_ipc import (
    JsonValue,
    MpvIpcEvent,
    MpvIpcRequest,
)
from mpv_enhancer.infrastructure.mpv.settings_adapter import (
    MpvSettingsAdapter,
    normalize_video_dimensions,
)
from mpv_enhancer.infrastructure.mpv.tracks import normalize_mpv_track_list

type PlaybackPropertyValue = JsonValue | VideoDimensions
PlaybackPropertyListener = Callable[[str, PlaybackPropertyValue], None]
JsonIpcPropertyListener = Callable[[str, JsonValue], None]


class PlaybackEventType(StrEnum):
    """Playback lifecycle events relevant to the state machine."""

    FILE_LOADED = "file_loaded"
    END_FILE = "end_file"


class PlaybackEndKind(StrEnum):
    """Safe classification of mpv's end-file reason."""

    EOF = "eof"
    ERROR = "error"
    STOPPED = "stopped"
    REPLACED = "replaced"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PlaybackEvent:
    """A lifecycle event tagged with its originating load generation."""

    event_type: PlaybackEventType
    generation: int
    end_kind: PlaybackEndKind | None = None


PlaybackEventListener = Callable[[PlaybackEvent], None]


class JsonIpcClient(Protocol):
    """JSON IPC operations required by the playback adapter."""

    def request(self, command: Sequence[JsonValue]) -> MpvIpcRequest: ...

    def observe_property(
        self,
        name: str,
        listener: JsonIpcPropertyListener,
    ) -> object: ...


class PlaybackAdapter(Protocol):
    """Playback surface consumed by the application controller."""

    def begin_observing(
        self,
        listener: PlaybackPropertyListener,
        event_listener: PlaybackEventListener,
    ) -> None: ...

    def load_file(self, path: Path, generation: int) -> None: ...

    def apply_settings(
        self,
        settings: EffectivePlaybackSettings,
        source_dimensions: VideoDimensions | None = None,
    ) -> None: ...

    def set_paused(self, paused: bool) -> None: ...

    def seek_absolute(self, seconds: float) -> None: ...

    def stop(self) -> None: ...


class MpvJsonPlaybackAdapter(QObject):
    """Issue a fixed allowlist of playback commands through JSON IPC."""

    propertyChanged = Signal(str, object)
    playbackEvent = Signal(object)

    def __init__(self, client: JsonIpcClient) -> None:
        super().__init__()
        self._client = client
        self._observing = False
        self._pending_generations: deque[int] = deque()
        self._entry_generations: dict[int, int] = {}
        self._loading_entries: deque[int] = deque()
        self._settings_adapter = MpvSettingsAdapter(client)
        self._active_settings: EffectivePlaybackSettings | None = None
        self._active_generation: int | None = None

    def set_capabilities(self, capabilities: MpvCapabilities) -> None:
        """Gate managed writes without changing basic playback availability."""
        self._settings_adapter.set_capabilities(capabilities)

    def begin_observing(
        self,
        listener: PlaybackPropertyListener,
        event_listener: PlaybackEventListener,
    ) -> None:
        if self._observing:
            raise RuntimeError("Playback properties are already being observed.")
        self._observing = True
        self.propertyChanged.connect(listener)
        self.playbackEvent.connect(event_listener)
        self._observe_properties()

    def reset_runtime(self) -> None:
        """Discard old entry mappings and restore observations after restart."""
        self._pending_generations.clear()
        self._entry_generations.clear()
        self._loading_entries.clear()
        self._active_generation = None
        if self._observing:
            self._observe_properties()

    def _observe_properties(self) -> None:
        for name in ("duration", "time-pos", "pause", "track-list"):
            self._client.observe_property(name, self._property_changed)

    def load_file(self, path: Path, generation: int) -> None:
        """Load one local path as a JSON value, never as shell syntax."""
        if generation <= 0:
            raise ValueError("A playback load generation must be positive.")
        self._pending_generations.append(generation)
        self._active_generation = generation
        try:
            self._client.request(("loadfile", str(path), "replace"))
        except Exception:
            if (
                self._pending_generations
                and self._pending_generations[-1] == generation
            ):
                self._pending_generations.pop()
            if self._active_generation == generation:
                self._active_generation = None
            raise

    def apply_settings(
        self,
        settings: EffectivePlaybackSettings,
        source_dimensions: VideoDimensions | None = None,
    ) -> None:
        """Apply safe settings, deferring crop until source dimensions are known."""
        self._active_settings = settings
        self._settings_adapter.apply(settings)
        if source_dimensions is not None:
            try:
                self._settings_adapter.apply_validated_crop(
                    settings.video_crop,
                    source_dimensions,
                )
            except ValueError as error:
                self.propertyChanged.emit("video-crop-error", str(error))

    def set_paused(self, paused: bool) -> None:
        self._client.request(("set_property", "pause", paused))

    def seek_absolute(self, seconds: float) -> None:
        self._client.request(("seek", seconds, "absolute+exact"))

    def stop(self) -> None:
        self._active_generation = None
        self._client.request(("stop",))

    def handle_event(self, event: MpvIpcEvent) -> None:
        """Map mpv playlist entry IDs back to app load generations."""
        entry_id = event.payload.get("playlist_entry_id")
        if event.name == "start-file":
            if (
                isinstance(entry_id, int)
                and not isinstance(entry_id, bool)
                and self._pending_generations
            ):
                self._entry_generations[entry_id] = self._pending_generations.popleft()
                self._loading_entries.append(entry_id)
            return
        if event.name == "file-loaded" and (
            not isinstance(entry_id, int) or isinstance(entry_id, bool)
        ):
            entry_id = self._next_loading_entry()
        if not isinstance(entry_id, int) or isinstance(entry_id, bool):
            return
        generation = self._entry_generations.get(entry_id)
        if generation is None:
            return
        if event.name == "file-loaded":
            _discard_entry(self._loading_entries, entry_id)
            self._read_loaded_tracks(generation)
            self._read_loaded_video_dimensions(generation)
            self.playbackEvent.emit(
                PlaybackEvent(PlaybackEventType.FILE_LOADED, generation)
            )
        elif event.name == "end-file":
            _discard_entry(self._loading_entries, entry_id)
            self._entry_generations.pop(entry_id, None)
            self.playbackEvent.emit(
                PlaybackEvent(
                    PlaybackEventType.END_FILE,
                    generation,
                    _classify_end_reason(event.payload.get("reason")),
                )
            )

    def _property_changed(self, name: str, value: JsonValue) -> None:
        if name == "track-list":
            return
        self.propertyChanged.emit(name, value)

    def _read_loaded_tracks(self, generation: int) -> None:
        if generation != self._active_generation or self._active_settings is None:
            return
        request = self._client.request(("get_property", "track-list"))
        request.future.add_done_callback(
            lambda completed: self._loaded_tracks_received(generation, completed)
        )

    def _read_loaded_video_dimensions(self, generation: int) -> None:
        if generation != self._active_generation or self._active_settings is None:
            return
        request = self._client.request(("get_property", "video-dec-params"))
        request.future.add_done_callback(
            lambda completed: self._loaded_video_dimensions_received(
                generation,
                completed,
            )
        )

    def _loaded_tracks_received(
        self,
        generation: int,
        completed: Future[JsonValue],
    ) -> None:
        if generation != self._active_generation or completed.cancelled():
            return
        try:
            value = completed.result()
        except Exception:
            return
        settings = self._active_settings
        if settings is None or generation != self._active_generation:
            return
        self._settings_adapter.apply_resolved_tracks(
            settings,
            normalize_mpv_track_list(value),
        )
        self.propertyChanged.emit("track-list", value)

    def _loaded_video_dimensions_received(
        self,
        generation: int,
        completed: Future[JsonValue],
    ) -> None:
        if generation != self._active_generation or completed.cancelled():
            return
        try:
            value = completed.result()
        except Exception:
            return
        dimensions = normalize_video_dimensions(value)
        settings = self._active_settings
        if (
            dimensions is None
            or settings is None
            or generation != self._active_generation
        ):
            return
        self.propertyChanged.emit("video-dimensions", dimensions)
        try:
            self._settings_adapter.apply_validated_crop(
                settings.video_crop,
                dimensions,
            )
        except ValueError as error:
            self.propertyChanged.emit("video-crop-error", str(error))

    def _next_loading_entry(self) -> int | None:
        while self._loading_entries:
            entry_id = self._loading_entries.popleft()
            if entry_id in self._entry_generations:
                return entry_id
        return None


def _classify_end_reason(reason: JsonValue) -> PlaybackEndKind:
    if reason == "eof":
        return PlaybackEndKind.EOF
    if reason == "error":
        return PlaybackEndKind.ERROR
    if isinstance(reason, str) and reason in {"stop", "quit"}:
        return PlaybackEndKind.STOPPED
    if reason == "redirect":
        return PlaybackEndKind.REPLACED
    return PlaybackEndKind.UNKNOWN


def _discard_entry(entries: deque[int], entry_id: int) -> None:
    try:
        entries.remove(entry_id)
    except ValueError:
        pass
