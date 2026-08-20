"""Typed allowlist metadata for settings that MPV Enhancer may manage."""

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from enum import Enum, StrEnum
from types import MappingProxyType

_LANGUAGE_TAG_PATTERN = re.compile(
    r"[a-z]{2,8}(?:-[a-z0-9]{1,8})*",
    re.IGNORECASE,
)
_ASPECT_RATIO_PATTERN = re.compile(
    r"\s*(\d+(?:\.\d*)?|\.\d+)\s*:\s*(\d+(?:\.\d*)?|\.\d+)\s*"
)
_VIDEO_CROP_PATTERN = re.compile(
    r"\s*(\d+)\s*[xX]\s*(\d+)(?:\s*\+\s*(\d+)\s*\+\s*(\d+))?\s*"
)
_COMMON_ASPECT_RATIOS = ("16:9", "21:9", "4:3")


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


class AspectRatioMode(StrEnum):
    """Reviewed automatic, common, and custom aspect-ratio modes."""

    AUTO = "auto"
    COMMON = "common"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class AspectRatio:
    """A safe automatic or positive width-to-height video aspect ratio."""

    mode: AspectRatioMode
    ratio: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.mode, AspectRatioMode):
            raise ValueError("An aspect ratio requires a valid mode.")
        if self.mode is AspectRatioMode.AUTO:
            if self.ratio is not None:
                raise ValueError("An automatic aspect ratio cannot contain a ratio.")
            return
        if not isinstance(self.ratio, str):
            raise ValueError("A non-automatic aspect ratio requires ratio text.")
        normalized = _normalize_aspect_ratio(self.ratio)
        is_common = normalized in _COMMON_ASPECT_RATIOS
        if self.mode is AspectRatioMode.COMMON and not is_common:
            raise ValueError("A common aspect ratio must use a reviewed common value.")
        if self.mode is AspectRatioMode.CUSTOM and is_common:
            raise ValueError("A reviewed common aspect ratio must use common mode.")
        object.__setattr__(self, "ratio", normalized)

    @classmethod
    def auto(cls) -> "AspectRatio":
        """Use the media's normal aspect-ratio metadata."""
        return cls(AspectRatioMode.AUTO)

    @classmethod
    def parse(cls, text: str) -> "AspectRatio":
        """Parse ``auto`` or a positive ``width:height`` ratio."""
        if not isinstance(text, str):
            raise ValueError("A video aspect ratio must be text.")
        if text.strip().casefold() == "auto":
            return cls.auto()
        normalized = _normalize_aspect_ratio(text)
        mode = (
            AspectRatioMode.COMMON
            if normalized in _COMMON_ASPECT_RATIOS
            else AspectRatioMode.CUSTOM
        )
        return cls(mode, normalized)

    @property
    def display_value(self) -> str:
        """Return the normalized value shown in the settings editor."""
        return "Auto" if self.mode is AspectRatioMode.AUTO else self._require_ratio()

    def to_mpv_value(self) -> str:
        """Map automatic mode to mpv's documented reset value."""
        return "no" if self.mode is AspectRatioMode.AUTO else self._require_ratio()

    def _require_ratio(self) -> str:
        if self.ratio is None:
            raise RuntimeError("A non-automatic aspect ratio has no ratio text.")
        return self.ratio


def _normalize_aspect_ratio(text: str) -> str:
    if len(text) > 64:
        raise ValueError("Invalid video aspect ratio; use positive width:height.")
    match = _ASPECT_RATIO_PATTERN.fullmatch(text)
    if match is None:
        raise ValueError("Invalid video aspect ratio; use positive width:height.")
    components: list[str] = []
    for raw_component in match.groups():
        try:
            component = Decimal(raw_component)
        except InvalidOperation as error:
            raise ValueError(
                "Invalid video aspect ratio; use positive width:height."
            ) from error
        if not component.is_finite() or component <= 0:
            raise ValueError("Invalid video aspect ratio; use positive width:height.")
        whole, separator, fraction = format(component, "f").partition(".")
        whole = whole.lstrip("0") or "0"
        fraction = fraction.rstrip("0")
        normalized = whole + (f".{fraction}" if separator and fraction else "")
        components.append(normalized)
    return ":".join(components)


class VideoRotation(Enum):
    """Reviewed automatic and right-angle video rotation choices."""

    AUTO = "auto"
    DEG_0 = "0"
    DEG_90 = "90"
    DEG_180 = "180"
    DEG_270 = "270"

    @property
    def display_value(self) -> str:
        """Return the concise value shown by editors and queue badges."""
        return "Auto" if self is VideoRotation.AUTO else f"{self.value}°"

    def to_mpv_value(self) -> str | int:
        """Map automatic mode to mpv's documented manual-rotation reset."""
        return "no" if self is VideoRotation.AUTO else int(self.value)


@dataclass(frozen=True, slots=True)
class VideoDimensions:
    """Positive decoded source dimensions used to validate video crops."""

    width: int
    height: int

    def __post_init__(self) -> None:
        for name, value in (("width", self.width), ("height", self.height)):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"Video source {name} must be a positive integer.")


class VideoCropMode(StrEnum):
    """Safe disabled, centered, and explicitly positioned crop modes."""

    OFF = "off"
    CENTERED = "centered"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class VideoCrop:
    """A structurally valid crop that still requires source-bound validation."""

    mode: VideoCropMode
    width: int | None = None
    height: int | None = None
    x: int | None = None
    y: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.mode, VideoCropMode):
            raise ValueError("A video crop requires a valid mode.")
        if self.mode is VideoCropMode.OFF:
            if any(
                value is not None for value in (self.width, self.height, self.x, self.y)
            ):
                raise ValueError("An off video crop cannot contain a rectangle.")
            return
        for name, value in (("width", self.width), ("height", self.height)):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"Video crop {name} must be a positive integer.")
        if self.mode is VideoCropMode.CENTERED:
            if self.x is not None or self.y is not None:
                raise ValueError("A centered video crop cannot contain offsets.")
            return
        for name, value in (("x", self.x), ("y", self.y)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"Video crop {name} must be a non-negative integer.")

    @classmethod
    def off(cls) -> "VideoCrop":
        """Disable manual cropping and restore source crop metadata."""
        return cls(VideoCropMode.OFF)

    @classmethod
    def parse(cls, text: str) -> "VideoCrop":
        """Parse ``off``, centered ``WxH``, or custom ``WxH+X+Y`` syntax."""
        if not isinstance(text, str):
            raise ValueError("A video crop must be text.")
        if text.strip().casefold() == "off":
            return cls.off()
        if len(text) > 64:
            raise ValueError("Invalid video crop; use off, WxH, or WxH+X+Y.")
        match = _VIDEO_CROP_PATTERN.fullmatch(text)
        if match is None:
            raise ValueError("Invalid video crop; use off, WxH, or WxH+X+Y.")
        width, height, x, y = (
            int(component) if component is not None else None
            for component in match.groups()
        )
        if x is None and y is None:
            return cls(VideoCropMode.CENTERED, width, height)
        return cls(VideoCropMode.CUSTOM, width, height, x, y)

    @property
    def display_value(self) -> str:
        """Return normalized editor text."""
        return "Off" if self.mode is VideoCropMode.OFF else self._rectangle_text()

    def to_mpv_value(self) -> str:
        """Return only reviewed mpv ``video-crop`` syntax."""
        return "" if self.mode is VideoCropMode.OFF else self._rectangle_text()

    def validated_for(self, source: VideoDimensions) -> "VideoCrop":
        """Reject any rectangle extending beyond decoded source dimensions."""
        if not isinstance(source, VideoDimensions):
            raise ValueError("Video crop validation requires source dimensions.")
        if self.mode is VideoCropMode.OFF:
            return self
        width, height = self._require_size()
        x = 0 if self.x is None else self.x
        y = 0 if self.y is None else self.y
        if width > source.width or height > source.height:
            raise ValueError(
                f"Video crop is outside the {source.width}x{source.height} source."
            )
        if self.mode is VideoCropMode.CUSTOM and (
            x + width > source.width or y + height > source.height
        ):
            raise ValueError(
                f"Video crop is outside the {source.width}x{source.height} source."
            )
        return self

    def _rectangle_text(self) -> str:
        width, height = self._require_size()
        rectangle = f"{width}x{height}"
        if self.mode is VideoCropMode.CUSTOM:
            if self.x is None or self.y is None:
                raise RuntimeError("A custom video crop has incomplete offsets.")
            rectangle += f"+{self.x}+{self.y}"
        return rectangle

    def _require_size(self) -> tuple[int, int]:
        if self.width is None or self.height is None:
            raise RuntimeError("An active video crop has incomplete dimensions.")
        return self.width, self.height


class SettingKey(StrEnum):
    """Stable application keys for reviewed per-item settings."""

    SPEED = "speed"
    PANSCAN = "panscan"
    ASPECT_RATIO = "aspect_ratio"
    VIDEO_CROP = "video_crop"
    VIDEO_ZOOM = "video_zoom"
    VIDEO_PAN_X = "video_pan_x"
    VIDEO_PAN_Y = "video_pan_y"
    VIDEO_ROTATION = "video_rotation"
    DEINTERLACE = "deinterlace"
    BRIGHTNESS = "brightness"
    CONTRAST = "contrast"
    GAMMA = "gamma"
    SATURATION = "saturation"
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
    ASPECT_RATIO = "aspect_ratio"
    VIDEO_CROP = "video_crop"
    VIDEO_ROTATION = "video_rotation"


type SettingValue = (
    float
    | bool
    | LanguagePreferences
    | TrackSelection
    | AspectRatio
    | VideoCrop
    | VideoRotation
)


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
        if self.value_type is SettingValueType.ASPECT_RATIO:
            if not isinstance(value, AspectRatio):
                raise ValueError(f"{self.key.value} requires a typed aspect ratio.")
            return value
        if self.value_type is SettingValueType.VIDEO_CROP:
            if not isinstance(value, VideoCrop):
                raise ValueError(f"{self.key.value} requires a typed video crop.")
            return value
        if self.value_type is SettingValueType.VIDEO_ROTATION:
            if not isinstance(value, VideoRotation):
                raise ValueError(f"{self.key.value} requires a typed video rotation.")
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
            key=SettingKey.ASPECT_RATIO,
            mpv_property="video-aspect-override",
            value_type=SettingValueType.ASPECT_RATIO,
            minimum=None,
            maximum=None,
            reset_value=AspectRatio.auto(),
            apply_live=True,
        ),
        SettingSpec(
            key=SettingKey.VIDEO_CROP,
            mpv_property="video-crop",
            value_type=SettingValueType.VIDEO_CROP,
            minimum=None,
            maximum=None,
            reset_value=VideoCrop.off(),
            apply_live=True,
        ),
        SettingSpec(
            key=SettingKey.VIDEO_ZOOM,
            mpv_property="video-zoom",
            value_type=SettingValueType.NUMBER,
            minimum=-2.0,
            maximum=2.0,
            reset_value=0.0,
            apply_live=True,
        ),
        SettingSpec(
            key=SettingKey.VIDEO_PAN_X,
            mpv_property="video-pan-x",
            value_type=SettingValueType.NUMBER,
            minimum=-1.0,
            maximum=1.0,
            reset_value=0.0,
            apply_live=True,
        ),
        SettingSpec(
            key=SettingKey.VIDEO_PAN_Y,
            mpv_property="video-pan-y",
            value_type=SettingValueType.NUMBER,
            minimum=-1.0,
            maximum=1.0,
            reset_value=0.0,
            apply_live=True,
        ),
        SettingSpec(
            key=SettingKey.VIDEO_ROTATION,
            mpv_property="video-rotate",
            value_type=SettingValueType.VIDEO_ROTATION,
            minimum=None,
            maximum=None,
            reset_value=VideoRotation.AUTO,
            apply_live=True,
        ),
        SettingSpec(
            key=SettingKey.DEINTERLACE,
            mpv_property="deinterlace",
            value_type=SettingValueType.BOOLEAN,
            minimum=None,
            maximum=None,
            reset_value=False,
            apply_live=True,
        ),
        SettingSpec(
            key=SettingKey.BRIGHTNESS,
            mpv_property="brightness",
            value_type=SettingValueType.NUMBER,
            minimum=-100.0,
            maximum=100.0,
            reset_value=0.0,
            apply_live=True,
        ),
        SettingSpec(
            key=SettingKey.CONTRAST,
            mpv_property="contrast",
            value_type=SettingValueType.NUMBER,
            minimum=-100.0,
            maximum=100.0,
            reset_value=0.0,
            apply_live=True,
        ),
        SettingSpec(
            key=SettingKey.GAMMA,
            mpv_property="gamma",
            value_type=SettingValueType.NUMBER,
            minimum=-100.0,
            maximum=100.0,
            reset_value=0.0,
            apply_live=True,
        ),
        SettingSpec(
            key=SettingKey.SATURATION,
            mpv_property="saturation",
            value_type=SettingValueType.NUMBER,
            minimum=-100.0,
            maximum=100.0,
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
    aspect_ratio: AspectRatio | None = None
    video_crop: VideoCrop | None = None
    video_zoom: float | None = None
    video_pan_x: float | None = None
    video_pan_y: float | None = None
    video_rotation: VideoRotation | None = None
    deinterlace: bool | None = None
    brightness: float | None = None
    contrast: float | None = None
    gamma: float | None = None
    saturation: float | None = None
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
                (
                    bool,
                    float,
                    LanguagePreferences,
                    TrackSelection,
                    AspectRatio,
                    VideoCrop,
                    VideoRotation,
                ),
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
        if key is SettingKey.ASPECT_RATIO:
            return replace(self, aspect_ratio=_require_aspect_ratio(key, normalized))
        if key is SettingKey.VIDEO_CROP:
            return replace(self, video_crop=_require_video_crop(key, normalized))
        if key is SettingKey.VIDEO_ZOOM:
            return replace(self, video_zoom=_require_number(key, normalized))
        if key is SettingKey.VIDEO_PAN_X:
            return replace(self, video_pan_x=_require_number(key, normalized))
        if key is SettingKey.VIDEO_PAN_Y:
            return replace(self, video_pan_y=_require_number(key, normalized))
        if key is SettingKey.VIDEO_ROTATION:
            return replace(
                self,
                video_rotation=_require_video_rotation(key, normalized),
            )
        if key is SettingKey.DEINTERLACE:
            return replace(self, deinterlace=_require_boolean(key, normalized))
        if key is SettingKey.BRIGHTNESS:
            return replace(self, brightness=_require_number(key, normalized))
        if key is SettingKey.CONTRAST:
            return replace(self, contrast=_require_number(key, normalized))
        if key is SettingKey.GAMMA:
            return replace(self, gamma=_require_number(key, normalized))
        if key is SettingKey.SATURATION:
            return replace(self, saturation=_require_number(key, normalized))
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
        if key is SettingKey.ASPECT_RATIO:
            return replace(self, aspect_ratio=None)
        if key is SettingKey.VIDEO_CROP:
            return replace(self, video_crop=None)
        if key is SettingKey.VIDEO_ZOOM:
            return replace(self, video_zoom=None)
        if key is SettingKey.VIDEO_PAN_X:
            return replace(self, video_pan_x=None)
        if key is SettingKey.VIDEO_PAN_Y:
            return replace(self, video_pan_y=None)
        if key is SettingKey.VIDEO_ROTATION:
            return replace(self, video_rotation=None)
        if key is SettingKey.DEINTERLACE:
            return replace(self, deinterlace=None)
        if key is SettingKey.BRIGHTNESS:
            return replace(self, brightness=None)
        if key is SettingKey.CONTRAST:
            return replace(self, contrast=None)
        if key is SettingKey.GAMMA:
            return replace(self, gamma=None)
        if key is SettingKey.SATURATION:
            return replace(self, saturation=None)
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
    aspect_ratio: AspectRatio = AspectRatio.auto()
    video_crop: VideoCrop = VideoCrop.off()
    video_zoom: float = 0.0
    video_pan_x: float = 0.0
    video_pan_y: float = 0.0
    video_rotation: VideoRotation = VideoRotation.AUTO
    deinterlace: bool = False
    brightness: float = 0.0
    contrast: float = 0.0
    gamma: float = 0.0
    saturation: float = 0.0
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
        if isinstance(
            value,
            (
                bool,
                float,
                LanguagePreferences,
                TrackSelection,
                AspectRatio,
                VideoCrop,
                VideoRotation,
            ),
        ):
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


def _require_aspect_ratio(key: SettingKey, value: SettingValue) -> AspectRatio:
    if not isinstance(value, AspectRatio):
        raise RuntimeError(f"{key.value} metadata is not an aspect ratio.")
    return value


def _require_video_crop(key: SettingKey, value: SettingValue) -> VideoCrop:
    if not isinstance(value, VideoCrop):
        raise RuntimeError(f"{key.value} metadata is not a video crop.")
    return value


def _require_video_rotation(key: SettingKey, value: SettingValue) -> VideoRotation:
    if not isinstance(value, VideoRotation):
        raise RuntimeError(f"{key.value} metadata is not a video rotation.")
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


def _reset_aspect_ratio(key: SettingKey) -> AspectRatio:
    return _require_aspect_ratio(key, SETTING_SPEC_REGISTRY.require(key).reset_value)


def _reset_video_crop(key: SettingKey) -> VideoCrop:
    return _require_video_crop(key, SETTING_SPEC_REGISTRY.require(key).reset_value)


def _reset_video_rotation(key: SettingKey) -> VideoRotation:
    return _require_video_rotation(
        key,
        SETTING_SPEC_REGISTRY.require(key).reset_value,
    )


EMPTY_PLAYBACK_SETTINGS = PlaybackSettings()
DETERMINISTIC_BASELINE = PlaybackSettings(
    speed=_reset_number(SettingKey.SPEED),
    panscan=_reset_number(SettingKey.PANSCAN),
    aspect_ratio=_reset_aspect_ratio(SettingKey.ASPECT_RATIO),
    video_crop=_reset_video_crop(SettingKey.VIDEO_CROP),
    video_zoom=_reset_number(SettingKey.VIDEO_ZOOM),
    video_pan_x=_reset_number(SettingKey.VIDEO_PAN_X),
    video_pan_y=_reset_number(SettingKey.VIDEO_PAN_Y),
    video_rotation=_reset_video_rotation(SettingKey.VIDEO_ROTATION),
    deinterlace=_reset_boolean(SettingKey.DEINTERLACE),
    brightness=_reset_number(SettingKey.BRIGHTNESS),
    contrast=_reset_number(SettingKey.CONTRAST),
    gamma=_reset_number(SettingKey.GAMMA),
    saturation=_reset_number(SettingKey.SATURATION),
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
            aspect_ratio=self._resolve_aspect_ratio(SettingKey.ASPECT_RATIO, layers),
            video_crop=self._resolve_video_crop(SettingKey.VIDEO_CROP, layers),
            video_zoom=self._resolve_number(SettingKey.VIDEO_ZOOM, layers),
            video_pan_x=self._resolve_number(SettingKey.VIDEO_PAN_X, layers),
            video_pan_y=self._resolve_number(SettingKey.VIDEO_PAN_Y, layers),
            video_rotation=self._resolve_video_rotation(
                SettingKey.VIDEO_ROTATION,
                layers,
            ),
            deinterlace=self._resolve_boolean(SettingKey.DEINTERLACE, layers),
            brightness=self._resolve_number(SettingKey.BRIGHTNESS, layers),
            contrast=self._resolve_number(SettingKey.CONTRAST, layers),
            gamma=self._resolve_number(SettingKey.GAMMA, layers),
            saturation=self._resolve_number(SettingKey.SATURATION, layers),
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

    def _resolve_video_rotation(
        self,
        key: SettingKey,
        layers: tuple[PlaybackSettings, ...],
    ) -> VideoRotation:
        value = self._resolve_value(key, layers)
        if not isinstance(value, VideoRotation):
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

    def _resolve_aspect_ratio(
        self,
        key: SettingKey,
        layers: tuple[PlaybackSettings, ...],
    ) -> AspectRatio:
        value = self._resolve_value(key, layers)
        if not isinstance(value, AspectRatio):
            raise RuntimeError(f"{key.value} resolved to the wrong value type.")
        return value

    def _resolve_video_crop(
        self,
        key: SettingKey,
        layers: tuple[PlaybackSettings, ...],
    ) -> VideoCrop:
        value = self._resolve_value(key, layers)
        if not isinstance(value, VideoCrop):
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
