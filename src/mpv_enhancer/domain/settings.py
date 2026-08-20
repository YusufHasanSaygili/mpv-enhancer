"""Typed allowlist metadata for settings that MPV Enhancer may manage."""

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType

_LANGUAGE_TAG_PATTERN = re.compile(
    r"[a-z]{2,8}(?:-[a-z0-9]{1,8})*",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class LanguagePreferences:
    """Ordered, deduplicated IETF/ISO language fallback tags."""

    tags: tuple[str, ...]

    def __post_init__(self) -> None:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_tag in self.tags:
            if not isinstance(raw_tag, str):
                raise ValueError("Each language tag must be text.")
            tag = raw_tag.strip().lower()
            if not tag:
                continue
            if _LANGUAGE_TAG_PATTERN.fullmatch(tag) is None:
                raise ValueError(f"Invalid language tag: {raw_tag!r}.")
            if tag not in seen:
                normalized.append(tag)
                seen.add(tag)
        object.__setattr__(self, "tags", tuple(normalized))

    @classmethod
    def parse(cls, text: str) -> "LanguagePreferences":
        """Parse a comma-separated fallback list while preserving first order."""
        if not isinstance(text, str):
            raise ValueError("Language preferences must be text.")
        return cls(tuple(text.split(",")))

    def to_mpv_value(self) -> str:
        """Return mpv's comma-separated language preference syntax."""
        return ",".join(self.tags)


class TrackSelectionMode(StrEnum):
    """Safe track-selection modes accepted by the application model."""

    AUTO = "auto"
    OFF = "off"
    SPECIFIC = "specific"


@dataclass(frozen=True, slots=True)
class TrackSelection:
    """An automatic, disabled, or positive explicit mpv track identity."""

    mode: TrackSelectionMode
    track_id: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.mode, TrackSelectionMode):
            raise ValueError("A track selection requires a valid mode.")
        if self.mode is TrackSelectionMode.SPECIFIC:
            if (
                isinstance(self.track_id, bool)
                or not isinstance(self.track_id, int)
                or self.track_id <= 0
            ):
                raise ValueError("A specific track selection requires a positive ID.")
        elif self.track_id is not None:
            raise ValueError("Only a specific track selection may contain an ID.")

    @classmethod
    def auto(cls) -> "TrackSelection":
        return cls(TrackSelectionMode.AUTO)

    @classmethod
    def off(cls) -> "TrackSelection":
        return cls(TrackSelectionMode.OFF)

    @classmethod
    def specific(cls, track_id: int) -> "TrackSelection":
        return cls(TrackSelectionMode.SPECIFIC, track_id)

    @classmethod
    def parse(cls, text: str) -> "TrackSelection":
        """Parse only auto, off, or a positive decimal track identity."""
        if not isinstance(text, str):
            raise ValueError("A track selection must be text.")
        normalized = text.strip().lower()
        if normalized == "auto":
            return cls.auto()
        if normalized == "off":
            return cls.off()
        if normalized.isdecimal() and int(normalized) > 0:
            return cls.specific(int(normalized))
        raise ValueError("Invalid track selection; use auto, off, or a positive ID.")

    def to_mpv_value(self) -> str | int:
        """Return the reviewed mpv property value for this selection."""
        if self.mode is TrackSelectionMode.AUTO:
            return "auto"
        if self.mode is TrackSelectionMode.OFF:
            return "no"
        if self.track_id is None:
            raise RuntimeError("A specific track selection has no ID.")
        return self.track_id


class SettingKey(StrEnum):
    """Stable application keys for reviewed per-item settings."""

    SPEED = "speed"
    PANSCAN = "panscan"
    VOLUME = "volume"
    MUTE = "mute"
    SUBTITLE_VISIBILITY = "subtitle_visibility"
    SUBTITLE_LANGUAGES = "subtitle_languages"
    AUDIO_LANGUAGES = "audio_languages"
    SUBTITLE_TRACK = "subtitle_track"
    AUDIO_TRACK = "audio_track"
    SUBTITLE_DELAY = "subtitle_delay"
    AUDIO_DELAY = "audio_delay"


class SettingValueType(StrEnum):
    """Runtime value categories accepted by setting specifications."""

    NUMBER = "number"
    BOOLEAN = "boolean"
    LANGUAGE_PREFERENCES = "language_preferences"
    TRACK_SELECTION = "track_selection"


type SettingValue = float | bool | LanguagePreferences | TrackSelection


@dataclass(frozen=True, slots=True)
class SettingSpec:
    """Validation and application metadata for one allowlisted mpv property."""

    key: SettingKey
    mpv_property: str
    value_type: SettingValueType
    minimum: float | None
    maximum: float | None
    reset_value: SettingValue
    apply_live: bool

    def __post_init__(self) -> None:
        if not self.mpv_property or any(
            not (character.isascii() and (character.isalnum() or character == "-"))
            for character in self.mpv_property
        ):
            raise ValueError("An mpv property must use a safe allowlist name.")
        if not isinstance(self.apply_live, bool):
            raise ValueError("Live-application metadata must be boolean.")
        if self.value_type is SettingValueType.NUMBER:
            if self.minimum is None or self.maximum is None:
                raise ValueError("Numeric settings require minimum and maximum values.")
            if (
                not math.isfinite(self.minimum)
                or not math.isfinite(self.maximum)
                or self.minimum > self.maximum
            ):
                raise ValueError("Numeric setting limits must form a finite range.")
        elif self.minimum is not None or self.maximum is not None:
            raise ValueError("Non-numeric settings cannot declare numeric limits.")
        self.validate(self.reset_value)

    def validate(self, value: object) -> SettingValue:
        """Return a normalized value or reject input outside this specification."""
        if self.value_type is SettingValueType.BOOLEAN:
            if not isinstance(value, bool):
                raise ValueError(f"{self.key.value} requires a boolean value.")
            return value
        if self.value_type is SettingValueType.LANGUAGE_PREFERENCES:
            if not isinstance(value, LanguagePreferences):
                raise ValueError(
                    f"{self.key.value} requires typed language preferences."
                )
            return value
        if self.value_type is SettingValueType.TRACK_SELECTION:
            if not isinstance(value, TrackSelection):
                raise ValueError(f"{self.key.value} requires a typed track selection.")
            return value

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{self.key.value} requires a valid numeric value.")
        normalized = float(value)
        if not math.isfinite(normalized):
            raise ValueError(f"{self.key.value} requires a valid finite value.")
        if self.minimum is None or self.maximum is None:
            raise RuntimeError("Numeric setting metadata is incomplete.")
        if not self.minimum <= normalized <= self.maximum:
            raise ValueError(
                f"{self.key.value} requires a valid value between "
                f"{self.minimum:g} and {self.maximum:g}."
            )
        return normalized


class SettingSpecRegistry:
    """Immutable lookup boundary for reviewed setting specifications."""

    def __init__(self, specs: Iterable[SettingSpec]) -> None:
        by_key: dict[SettingKey, SettingSpec] = {}
        for spec in specs:
            if spec.key in by_key:
                raise ValueError(f"Duplicate setting key: {spec.key.value}.")
            by_key[spec.key] = spec
        if not by_key:
            raise ValueError("A setting registry cannot be empty.")
        self._by_key = MappingProxyType(by_key)

    @property
    def keys(self) -> tuple[SettingKey, ...]:
        """Return registered keys in their reviewed declaration order."""
        return tuple(self._by_key)

    @property
    def specs(self) -> tuple[SettingSpec, ...]:
        """Return immutable specifications in declaration order."""
        return tuple(self._by_key.values())

    def require(self, key: SettingKey | str) -> SettingSpec:
        """Resolve only a registered application key, never a raw mpv property."""
        try:
            normalized = key if isinstance(key, SettingKey) else SettingKey(key)
            return self._by_key[normalized]
        except (KeyError, TypeError, ValueError) as error:
            raise KeyError(f"Setting key {key!r} is not registered.") from error

    def validate(self, key: SettingKey | str, value: object) -> SettingValue:
        """Validate a value through its reviewed setting specification."""
        return self.require(key).validate(value)


SETTING_SPEC_REGISTRY = SettingSpecRegistry(
    (
        SettingSpec(
            key=SettingKey.SPEED,
            mpv_property="speed",
            value_type=SettingValueType.NUMBER,
            minimum=0.25,
            maximum=4.0,
            reset_value=1.0,
            apply_live=True,
        ),
        SettingSpec(
            key=SettingKey.PANSCAN,
            mpv_property="panscan",
            value_type=SettingValueType.NUMBER,
            minimum=0.0,
            maximum=1.0,
            reset_value=0.0,
            apply_live=True,
        ),
        SettingSpec(
            key=SettingKey.VOLUME,
            mpv_property="volume",
            value_type=SettingValueType.NUMBER,
            minimum=0.0,
            maximum=130.0,
            reset_value=100.0,
            apply_live=True,
        ),
        SettingSpec(
            key=SettingKey.MUTE,
            mpv_property="mute",
            value_type=SettingValueType.BOOLEAN,
            minimum=None,
            maximum=None,
            reset_value=False,
            apply_live=True,
        ),
        SettingSpec(
            key=SettingKey.SUBTITLE_VISIBILITY,
            mpv_property="sub-visibility",
            value_type=SettingValueType.BOOLEAN,
            minimum=None,
            maximum=None,
            reset_value=True,
            apply_live=True,
        ),
        SettingSpec(
            key=SettingKey.SUBTITLE_LANGUAGES,
            mpv_property="slang",
            value_type=SettingValueType.LANGUAGE_PREFERENCES,
            minimum=None,
            maximum=None,
            reset_value=LanguagePreferences(()),
            apply_live=False,
        ),
        SettingSpec(
            key=SettingKey.AUDIO_LANGUAGES,
            mpv_property="alang",
            value_type=SettingValueType.LANGUAGE_PREFERENCES,
            minimum=None,
            maximum=None,
            reset_value=LanguagePreferences(()),
            apply_live=False,
        ),
        SettingSpec(
            key=SettingKey.SUBTITLE_TRACK,
            mpv_property="sid",
            value_type=SettingValueType.TRACK_SELECTION,
            minimum=None,
            maximum=None,
            reset_value=TrackSelection.auto(),
            apply_live=True,
        ),
        SettingSpec(
            key=SettingKey.AUDIO_TRACK,
            mpv_property="aid",
            value_type=SettingValueType.TRACK_SELECTION,
            minimum=None,
            maximum=None,
            reset_value=TrackSelection.auto(),
            apply_live=True,
        ),
        SettingSpec(
            key=SettingKey.SUBTITLE_DELAY,
            mpv_property="sub-delay",
            value_type=SettingValueType.NUMBER,
            minimum=-100.0,
            maximum=100.0,
            reset_value=0.0,
            apply_live=True,
        ),
        SettingSpec(
            key=SettingKey.AUDIO_DELAY,
            mpv_property="audio-delay",
            value_type=SettingValueType.NUMBER,
            minimum=-100.0,
            maximum=100.0,
            reset_value=0.0,
            apply_live=True,
        ),
    )
)


@dataclass(frozen=True, slots=True)
class PlaybackSettings:
    """One immutable settings layer where ``None`` means inherit."""

    speed: float | None = None
    panscan: float | None = None
    volume: float | None = None
    mute: bool | None = None
    subtitle_visibility: bool | None = None
    subtitle_languages: LanguagePreferences | None = None
    audio_languages: LanguagePreferences | None = None
    subtitle_track: TrackSelection | None = None
    audio_track: TrackSelection | None = None
    subtitle_delay: float | None = None
    audio_delay: float | None = None

    def __post_init__(self) -> None:
        for key in SettingKey:
            value = getattr(self, key.value)
            if value is not None:
                object.__setattr__(
                    self,
                    key.value,
                    SETTING_SPEC_REGISTRY.validate(key, value),
                )

    def value_for(self, key: SettingKey) -> SettingValue | None:
        """Return one typed layer value without applying inheritance."""
        value = getattr(self, key.value)
        return (
            value
            if isinstance(
                value,
                (bool, float, LanguagePreferences, TrackSelection),
            )
            else None
        )

    def with_value(self, key: SettingKey, value: SettingValue) -> "PlaybackSettings":
        """Return a copy with one validated property changed."""
        normalized = SETTING_SPEC_REGISTRY.validate(key, value)
        if key is SettingKey.SPEED:
            return replace(self, speed=_require_number(key, normalized))
        if key is SettingKey.PANSCAN:
            return replace(self, panscan=_require_number(key, normalized))
        if key is SettingKey.VOLUME:
            return replace(self, volume=_require_number(key, normalized))
        if key is SettingKey.MUTE:
            return replace(self, mute=_require_boolean(key, normalized))
        if key is SettingKey.SUBTITLE_VISIBILITY:
            return replace(
                self,
                subtitle_visibility=_require_boolean(key, normalized),
            )
        if key is SettingKey.SUBTITLE_LANGUAGES:
            return replace(
                self,
                subtitle_languages=_require_language_preferences(key, normalized),
            )
        if key is SettingKey.AUDIO_LANGUAGES:
            return replace(
                self,
                audio_languages=_require_language_preferences(key, normalized),
            )
        if key is SettingKey.SUBTITLE_TRACK:
            return replace(
                self,
                subtitle_track=_require_track_selection(key, normalized),
            )
        if key is SettingKey.AUDIO_TRACK:
            return replace(
                self,
                audio_track=_require_track_selection(key, normalized),
            )
        if key is SettingKey.SUBTITLE_DELAY:
            return replace(self, subtitle_delay=_require_number(key, normalized))
        return replace(self, audio_delay=_require_number(key, normalized))

    def without_value(self, key: SettingKey) -> "PlaybackSettings":
        """Return a copy with one property restored to inherited state."""
        if key is SettingKey.SPEED:
            return replace(self, speed=None)
        if key is SettingKey.PANSCAN:
            return replace(self, panscan=None)
        if key is SettingKey.VOLUME:
            return replace(self, volume=None)
        if key is SettingKey.MUTE:
            return replace(self, mute=None)
        if key is SettingKey.SUBTITLE_VISIBILITY:
            return replace(self, subtitle_visibility=None)
        if key is SettingKey.SUBTITLE_LANGUAGES:
            return replace(self, subtitle_languages=None)
        if key is SettingKey.AUDIO_LANGUAGES:
            return replace(self, audio_languages=None)
        if key is SettingKey.SUBTITLE_TRACK:
            return replace(self, subtitle_track=None)
        if key is SettingKey.AUDIO_TRACK:
            return replace(self, audio_track=None)
        if key is SettingKey.SUBTITLE_DELAY:
            return replace(self, subtitle_delay=None)
        return replace(self, audio_delay=None)


@dataclass(frozen=True, slots=True)
class EffectivePlaybackSettings:
    """A complete immutable value after all inheritance has been resolved."""

    speed: float
    panscan: float
    volume: float
    mute: bool
    subtitle_visibility: bool
    subtitle_languages: LanguagePreferences = LanguagePreferences(())
    audio_languages: LanguagePreferences = LanguagePreferences(())
    subtitle_track: TrackSelection = TrackSelection.auto()
    audio_track: TrackSelection = TrackSelection.auto()
    subtitle_delay: float = 0.0
    audio_delay: float = 0.0

    def __post_init__(self) -> None:
        for key in SettingKey:
            value = SETTING_SPEC_REGISTRY.validate(key, getattr(self, key.value))
            object.__setattr__(self, key.value, value)

    def value_for(self, key: SettingKey) -> SettingValue:
        """Return one complete typed effective value."""
        value = getattr(self, key.value)
        if isinstance(value, (bool, float, LanguagePreferences, TrackSelection)):
            return value
        raise RuntimeError(f"{key.value} resolved to an unsupported value type.")


def _require_number(key: SettingKey, value: SettingValue) -> float:
    if isinstance(value, float):
        return value
    raise RuntimeError(f"{key.value} metadata is not numeric.")


def _require_boolean(key: SettingKey, value: SettingValue) -> bool:
    if not isinstance(value, bool):
        raise RuntimeError(f"{key.value} metadata is not boolean.")
    return value


def _require_language_preferences(
    key: SettingKey,
    value: SettingValue,
) -> LanguagePreferences:
    if not isinstance(value, LanguagePreferences):
        raise RuntimeError(f"{key.value} metadata is not a language preference.")
    return value


def _require_track_selection(
    key: SettingKey,
    value: SettingValue,
) -> TrackSelection:
    if not isinstance(value, TrackSelection):
        raise RuntimeError(f"{key.value} metadata is not a track selection.")
    return value


def _reset_number(key: SettingKey) -> float:
    return _require_number(key, SETTING_SPEC_REGISTRY.require(key).reset_value)


def _reset_boolean(key: SettingKey) -> bool:
    return _require_boolean(key, SETTING_SPEC_REGISTRY.require(key).reset_value)


def _reset_language_preferences(key: SettingKey) -> LanguagePreferences:
    return _require_language_preferences(
        key,
        SETTING_SPEC_REGISTRY.require(key).reset_value,
    )


def _reset_track_selection(key: SettingKey) -> TrackSelection:
    return _require_track_selection(
        key,
        SETTING_SPEC_REGISTRY.require(key).reset_value,
    )


EMPTY_PLAYBACK_SETTINGS = PlaybackSettings()
DETERMINISTIC_BASELINE = PlaybackSettings(
    speed=_reset_number(SettingKey.SPEED),
    panscan=_reset_number(SettingKey.PANSCAN),
    volume=_reset_number(SettingKey.VOLUME),
    mute=_reset_boolean(SettingKey.MUTE),
    subtitle_visibility=_reset_boolean(SettingKey.SUBTITLE_VISIBILITY),
    subtitle_languages=_reset_language_preferences(SettingKey.SUBTITLE_LANGUAGES),
    audio_languages=_reset_language_preferences(SettingKey.AUDIO_LANGUAGES),
    subtitle_track=_reset_track_selection(SettingKey.SUBTITLE_TRACK),
    audio_track=_reset_track_selection(SettingKey.AUDIO_TRACK),
    subtitle_delay=_reset_number(SettingKey.SUBTITLE_DELAY),
    audio_delay=_reset_number(SettingKey.AUDIO_DELAY),
)


class EffectiveSettingsResolver:
    """Purely resolve baseline, app, playlist, and per-item settings layers."""

    def __init__(self, registry: SettingSpecRegistry = SETTING_SPEC_REGISTRY) -> None:
        self._registry = registry

    def resolve(
        self,
        *,
        baseline: PlaybackSettings = DETERMINISTIC_BASELINE,
        app_defaults: PlaybackSettings = EMPTY_PLAYBACK_SETTINGS,
        playlist_defaults: PlaybackSettings = EMPTY_PLAYBACK_SETTINGS,
        item_overrides: PlaybackSettings = EMPTY_PLAYBACK_SETTINGS,
    ) -> EffectivePlaybackSettings:
        """Return a new complete value without mutating any input layer."""
        layers = (item_overrides, playlist_defaults, app_defaults, baseline)
        return EffectivePlaybackSettings(
            speed=self._resolve_number(SettingKey.SPEED, layers),
            panscan=self._resolve_number(SettingKey.PANSCAN, layers),
            volume=self._resolve_number(SettingKey.VOLUME, layers),
            mute=self._resolve_boolean(SettingKey.MUTE, layers),
            subtitle_visibility=self._resolve_boolean(
                SettingKey.SUBTITLE_VISIBILITY,
                layers,
            ),
            subtitle_languages=self._resolve_language_preferences(
                SettingKey.SUBTITLE_LANGUAGES,
                layers,
            ),
            audio_languages=self._resolve_language_preferences(
                SettingKey.AUDIO_LANGUAGES,
                layers,
            ),
            subtitle_track=self._resolve_track_selection(
                SettingKey.SUBTITLE_TRACK,
                layers,
            ),
            audio_track=self._resolve_track_selection(
                SettingKey.AUDIO_TRACK,
                layers,
            ),
            subtitle_delay=self._resolve_number(SettingKey.SUBTITLE_DELAY, layers),
            audio_delay=self._resolve_number(SettingKey.AUDIO_DELAY, layers),
        )

    def _resolve_number(
        self,
        key: SettingKey,
        layers: tuple[PlaybackSettings, ...],
    ) -> float:
        value = self._resolve_value(key, layers)
        if isinstance(value, float):
            return value
        raise RuntimeError(f"{key.value} resolved to the wrong value type.")

    def _resolve_boolean(
        self,
        key: SettingKey,
        layers: tuple[PlaybackSettings, ...],
    ) -> bool:
        value = self._resolve_value(key, layers)
        if not isinstance(value, bool):
            raise RuntimeError(f"{key.value} resolved to the wrong value type.")
        return value

    def _resolve_language_preferences(
        self,
        key: SettingKey,
        layers: tuple[PlaybackSettings, ...],
    ) -> LanguagePreferences:
        value = self._resolve_value(key, layers)
        if not isinstance(value, LanguagePreferences):
            raise RuntimeError(f"{key.value} resolved to the wrong value type.")
        return value

    def _resolve_track_selection(
        self,
        key: SettingKey,
        layers: tuple[PlaybackSettings, ...],
    ) -> TrackSelection:
        value = self._resolve_value(key, layers)
        if not isinstance(value, TrackSelection):
            raise RuntimeError(f"{key.value} resolved to the wrong value type.")
        return value

    def _resolve_value(
        self,
        key: SettingKey,
        layers: tuple[PlaybackSettings, ...],
    ) -> SettingValue:
        for layer in layers:
            value = layer.value_for(key)
            if value is not None:
                return self._registry.validate(key, value)
        raise ValueError(f"The {key.value} baseline must provide a value.")
