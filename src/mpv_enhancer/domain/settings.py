"""Typed allowlist metadata for settings that MPV Enhancer may manage."""

import math
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType


class SettingKey(StrEnum):
    """Stable application keys for the settings supported in Slice 04."""

    SPEED = "speed"
    PANSCAN = "panscan"
    VOLUME = "volume"
    MUTE = "mute"
    SUBTITLE_VISIBILITY = "subtitle_visibility"


class SettingValueType(StrEnum):
    """Runtime value categories accepted by setting specifications."""

    NUMBER = "number"
    BOOLEAN = "boolean"


type SettingValue = float | bool


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
            raise ValueError("Boolean settings cannot declare numeric limits.")
        self.validate(self.reset_value)

    def validate(self, value: object) -> SettingValue:
        """Return a normalized value or reject input outside this specification."""
        if self.value_type is SettingValueType.BOOLEAN:
            if not isinstance(value, bool):
                raise ValueError(f"{self.key.value} requires a boolean value.")
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
        return value if isinstance(value, (bool, float)) else None


@dataclass(frozen=True, slots=True)
class EffectivePlaybackSettings:
    """A complete immutable value after all inheritance has been resolved."""

    speed: float
    panscan: float
    volume: float
    mute: bool
    subtitle_visibility: bool

    def __post_init__(self) -> None:
        for key in SettingKey:
            value = SETTING_SPEC_REGISTRY.validate(key, getattr(self, key.value))
            object.__setattr__(self, key.value, value)


def _reset_number(key: SettingKey) -> float:
    value = SETTING_SPEC_REGISTRY.require(key).reset_value
    if isinstance(value, bool):
        raise RuntimeError(f"{key.value} reset metadata is not numeric.")
    return value


def _reset_boolean(key: SettingKey) -> bool:
    value = SETTING_SPEC_REGISTRY.require(key).reset_value
    if not isinstance(value, bool):
        raise RuntimeError(f"{key.value} reset metadata is not boolean.")
    return value


EMPTY_PLAYBACK_SETTINGS = PlaybackSettings()
DETERMINISTIC_BASELINE = PlaybackSettings(
    speed=_reset_number(SettingKey.SPEED),
    panscan=_reset_number(SettingKey.PANSCAN),
    volume=_reset_number(SettingKey.VOLUME),
    mute=_reset_boolean(SettingKey.MUTE),
    subtitle_visibility=_reset_boolean(SettingKey.SUBTITLE_VISIBILITY),
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
        )

    def _resolve_number(
        self,
        key: SettingKey,
        layers: tuple[PlaybackSettings, ...],
    ) -> float:
        value = self._resolve_value(key, layers)
        if isinstance(value, bool):
            raise RuntimeError(f"{key.value} resolved to the wrong value type.")
        return value

    def _resolve_boolean(
        self,
        key: SettingKey,
        layers: tuple[PlaybackSettings, ...],
    ) -> bool:
        value = self._resolve_value(key, layers)
        if not isinstance(value, bool):
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
