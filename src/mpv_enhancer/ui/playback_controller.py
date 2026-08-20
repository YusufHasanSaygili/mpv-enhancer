"""Queue-aware playback commands and presentation state."""

import math
from dataclasses import dataclass
from enum import StrEnum

from PySide6.QtCore import QObject, Signal

from mpv_enhancer.infrastructure.mpv.json_ipc import JsonValue
from mpv_enhancer.infrastructure.mpv.playback import (
    PlaybackAdapter,
    PlaybackEndKind,
    PlaybackEvent,
    PlaybackEventType,
)
from mpv_enhancer.ui.queue_model import QueueListModel


class PlaybackPhase(StrEnum):
    """Explicit lifecycle states for one current playback generation."""

    IDLE = "idle"
    LOADING = "loading"
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"
    ENDED = "ended"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class PlaybackState:
    """UI-safe transport state derived from observed mpv properties."""

    phase: PlaybackPhase = PlaybackPhase.IDLE
    generation: int = 0
    paused: bool = False
    position_seconds: float = 0.0
    duration_seconds: float = 0.0


class PlaybackController(QObject):
    """Coordinate a stable queue identity with the fixed playback adapter."""

    stateChanged = Signal(object)

    def __init__(
        self,
        model: QueueListModel,
        adapter: PlaybackAdapter,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._model = model
        self._adapter = adapter
        self._state = PlaybackState()
        self._generation = 0
        self._adapter.begin_observing(
            self._property_changed,
            self._playback_event,
        )

    @property
    def state(self) -> PlaybackState:
        return self._state

    def load_row(self, row: int) -> bool:
        """Load one exact queue row without resolving or rewriting its path."""
        if not 0 <= row < len(self._model.items):
            return False
        item = self._model.items[row]
        self._generation += 1
        self._adapter.load_file(item.source_path, self._generation)
        self._model.set_current_item(item.item_id)
        self._set_state(
            PlaybackState(
                phase=PlaybackPhase.LOADING,
                generation=self._generation,
            )
        )
        return True

    def toggle_play_pause(self, preferred_row: int | None = None) -> bool:
        """Toggle pause, loading a preferred or first row when idle."""
        if self._model.current_item_id is None:
            row = 0 if preferred_row is None else preferred_row
            return self.load_row(row)
        self._adapter.set_paused(not self._state.paused)
        return True

    def seek_absolute(self, seconds: float) -> bool:
        if self._model.current_item_id is None or not math.isfinite(seconds):
            return False
        upper = self._state.duration_seconds
        target = max(0.0, seconds)
        if upper > 0:
            target = min(target, upper)
        self._adapter.seek_absolute(target)
        return True

    def stop(self) -> bool:
        if self._model.current_item_id is None:
            return False
        self._adapter.stop()
        self._generation += 1
        self._model.set_current_item(None)
        self._set_state(
            PlaybackState(
                phase=PlaybackPhase.STOPPED,
                generation=self._generation,
            )
        )
        return True

    def next(self) -> bool:
        return self._load_relative(1)

    def previous(self) -> bool:
        return self._load_relative(-1)

    def _load_relative(self, offset: int) -> bool:
        items = self._model.items
        if not items:
            return False
        current_id = self._model.current_item_id
        if current_id is None:
            return self.load_row(0)
        current_row = next(
            index for index, item in enumerate(items) if item.item_id == current_id
        )
        return self.load_row(current_row + offset)

    def _property_changed(self, name: str, value: JsonValue) -> None:
        if self._state.phase not in {PlaybackPhase.PLAYING, PlaybackPhase.PAUSED}:
            return
        if name == "pause" and isinstance(value, bool):
            self._set_state(
                PlaybackState(
                    phase=(PlaybackPhase.PAUSED if value else PlaybackPhase.PLAYING),
                    generation=self._state.generation,
                    paused=value,
                    position_seconds=self._state.position_seconds,
                    duration_seconds=self._state.duration_seconds,
                )
            )
            return
        number = _finite_non_negative_number(value)
        if number is None:
            return
        if name == "duration":
            self._set_state(
                PlaybackState(
                    phase=self._state.phase,
                    generation=self._state.generation,
                    paused=self._state.paused,
                    position_seconds=min(self._state.position_seconds, number),
                    duration_seconds=number,
                )
            )
        elif name == "time-pos":
            self._set_state(
                PlaybackState(
                    phase=self._state.phase,
                    generation=self._state.generation,
                    paused=self._state.paused,
                    position_seconds=number,
                    duration_seconds=self._state.duration_seconds,
                )
            )

    def _playback_event(self, event: PlaybackEvent) -> None:
        if event.generation != self._state.generation:
            return
        if event.event_type is PlaybackEventType.FILE_LOADED:
            self._set_state(
                PlaybackState(
                    phase=(
                        PlaybackPhase.PAUSED
                        if self._state.paused
                        else PlaybackPhase.PLAYING
                    ),
                    generation=self._state.generation,
                    paused=self._state.paused,
                    position_seconds=self._state.position_seconds,
                    duration_seconds=self._state.duration_seconds,
                )
            )
            return
        if event.event_type is not PlaybackEventType.END_FILE:
            return
        if event.end_kind is PlaybackEndKind.EOF:
            self._set_state(
                PlaybackState(
                    phase=PlaybackPhase.ENDED,
                    generation=self._state.generation,
                    duration_seconds=self._state.duration_seconds,
                    position_seconds=self._state.position_seconds,
                )
            )
            self.next()
        elif event.end_kind is PlaybackEndKind.ERROR:
            self._set_state(
                PlaybackState(
                    phase=PlaybackPhase.ERROR,
                    generation=self._state.generation,
                    duration_seconds=self._state.duration_seconds,
                    position_seconds=self._state.position_seconds,
                )
            )
        elif event.end_kind is PlaybackEndKind.STOPPED:
            self._set_state(
                PlaybackState(
                    phase=PlaybackPhase.STOPPED,
                    generation=self._state.generation,
                )
            )

    def _set_state(self, state: PlaybackState) -> None:
        if state == self._state:
            return
        if (
            state.phase is not self._state.phase
            and state.phase not in _ALLOWED_TRANSITIONS[self._state.phase]
        ):
            raise RuntimeError(
                f"Invalid playback transition: {self._state.phase} -> {state.phase}."
            )
        self._state = state
        self.stateChanged.emit(state)


def _finite_non_negative_number(value: JsonValue) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else None


_ALLOWED_TRANSITIONS: dict[PlaybackPhase, frozenset[PlaybackPhase]] = {
    PlaybackPhase.IDLE: frozenset({PlaybackPhase.LOADING}),
    PlaybackPhase.LOADING: frozenset(
        {
            PlaybackPhase.PLAYING,
            PlaybackPhase.PAUSED,
            PlaybackPhase.STOPPED,
            PlaybackPhase.ERROR,
        }
    ),
    PlaybackPhase.PLAYING: frozenset(
        {
            PlaybackPhase.LOADING,
            PlaybackPhase.PAUSED,
            PlaybackPhase.STOPPED,
            PlaybackPhase.ENDED,
            PlaybackPhase.ERROR,
        }
    ),
    PlaybackPhase.PAUSED: frozenset(
        {
            PlaybackPhase.LOADING,
            PlaybackPhase.PLAYING,
            PlaybackPhase.STOPPED,
            PlaybackPhase.ENDED,
            PlaybackPhase.ERROR,
        }
    ),
    PlaybackPhase.STOPPED: frozenset({PlaybackPhase.LOADING}),
    PlaybackPhase.ENDED: frozenset({PlaybackPhase.LOADING, PlaybackPhase.STOPPED}),
    PlaybackPhase.ERROR: frozenset({PlaybackPhase.LOADING, PlaybackPhase.STOPPED}),
}
