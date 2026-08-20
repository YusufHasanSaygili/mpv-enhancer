"""Normalize untrusted mpv track-list values into typed track metadata."""

from dataclasses import dataclass
from enum import StrEnum

from mpv_enhancer.domain.settings import (
    EffectivePlaybackSettings,
    LanguagePreferences,
    TrackSelection,
    TrackSelectionMode,
)
from mpv_enhancer.infrastructure.mpv.json_ipc import JsonValue


class MpvTrackType(StrEnum):
    """Stable application names for the track types reported by mpv."""

    VIDEO = "video"
    AUDIO = "audio"
    SUBTITLE = "subtitle"


@dataclass(frozen=True, slots=True)
class MpvTrack:
    """One immutable, normalized track-list entry."""

    track_type: MpvTrackType
    track_id: int
    language: str | None = None
    title: str | None = None
    is_default: bool = False
    is_forced: bool = False
    is_external: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.track_type, MpvTrackType):
            raise ValueError("A track requires a supported type.")
        if (
            isinstance(self.track_id, bool)
            or not isinstance(self.track_id, int)
            or self.track_id <= 0
        ):
            raise ValueError("A track ID must be a positive integer.")
        if self.language is not None:
            normalized_language = _normalize_language(self.language)
            if normalized_language is None:
                raise ValueError("A track language must be one valid language tag.")
            object.__setattr__(self, "language", normalized_language)
        if self.title is not None:
            if not isinstance(self.title, str):
                raise ValueError("A track title must be text.")
            object.__setattr__(self, "title", _normalize_title(self.title))
        for flag in (self.is_default, self.is_forced, self.is_external):
            if not isinstance(flag, bool):
                raise ValueError("Track flags must be boolean.")


class TrackResolutionReason(StrEnum):
    """Why one deterministic track selection was chosen."""

    OFF = "off"
    EXPLICIT = "explicit"
    LANGUAGE = "language"
    DEFAULT = "default"
    FORCED = "forced"
    FIRST = "first"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class TrackResolution:
    """A resolved selection plus information needed for fallback UX."""

    selection: TrackSelection
    reason: TrackResolutionReason
    matched_language: str | None = None
    used_fallback: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.selection, TrackSelection):
            raise ValueError("A track resolution requires a typed selection.")
        if not isinstance(self.reason, TrackResolutionReason):
            raise ValueError("A track resolution requires a known reason.")
        if self.matched_language is not None:
            normalized_language = _normalize_language(self.matched_language)
            if normalized_language is None:
                raise ValueError("A matched language must be one valid tag.")
            object.__setattr__(self, "matched_language", normalized_language)
        if not isinstance(self.used_fallback, bool):
            raise ValueError("Track fallback metadata must be boolean.")


@dataclass(frozen=True, slots=True)
class TrackAvailability:
    """Current normalized tracks and their independent selection results."""

    tracks: tuple[MpvTrack, ...]
    subtitle: TrackResolution
    audio: TrackResolution


_TRACK_TYPES = {
    "video": MpvTrackType.VIDEO,
    "audio": MpvTrackType.AUDIO,
    "sub": MpvTrackType.SUBTITLE,
}


def normalize_mpv_track_list(value: JsonValue) -> tuple[MpvTrack, ...]:
    """Return valid tracks in mpv order, preserving same-language entries."""
    if not isinstance(value, list):
        return ()
    tracks: list[MpvTrack] = []
    for raw_track in value:
        normalized = _normalize_track(raw_track)
        if normalized is not None:
            tracks.append(normalized)
    return tuple(tracks)


def resolve_track_selection(
    *,
    track_type: MpvTrackType,
    requested: TrackSelection,
    languages: LanguagePreferences,
    tracks: tuple[MpvTrack, ...],
) -> TrackResolution:
    """Resolve explicit, language, and fallback rules in stable source order."""
    if track_type not in {MpvTrackType.AUDIO, MpvTrackType.SUBTITLE}:
        raise ValueError("Only audio and subtitle tracks can be selected.")
    candidates = tuple(track for track in tracks if track.track_type is track_type)
    if requested.mode is TrackSelectionMode.OFF:
        return TrackResolution(TrackSelection.off(), TrackResolutionReason.OFF)

    explicit_missing = False
    if requested.mode is TrackSelectionMode.SPECIFIC:
        explicit = next(
            (track for track in candidates if track.track_id == requested.track_id),
            None,
        )
        if explicit is not None:
            return TrackResolution(requested, TrackResolutionReason.EXPLICIT)
        explicit_missing = True

    for language in languages.tags:
        matching = tuple(track for track in candidates if track.language == language)
        if matching:
            chosen = _preferred_track(matching)
            return TrackResolution(
                TrackSelection.specific(chosen.track_id),
                TrackResolutionReason.LANGUAGE,
                matched_language=language,
                used_fallback=explicit_missing,
            )

    used_fallback = explicit_missing or bool(languages.tags)
    default = next((track for track in candidates if track.is_default), None)
    if default is not None:
        return TrackResolution(
            TrackSelection.specific(default.track_id),
            TrackResolutionReason.DEFAULT,
            used_fallback=used_fallback,
        )
    if track_type is MpvTrackType.SUBTITLE:
        forced = next((track for track in candidates if track.is_forced), None)
        if forced is not None:
            return TrackResolution(
                TrackSelection.specific(forced.track_id),
                TrackResolutionReason.FORCED,
                used_fallback=used_fallback,
            )
    if candidates:
        return TrackResolution(
            TrackSelection.specific(candidates[0].track_id),
            TrackResolutionReason.FIRST,
            used_fallback=used_fallback,
        )
    unavailable = (
        TrackSelection.off()
        if track_type is MpvTrackType.SUBTITLE
        else TrackSelection.auto()
    )
    return TrackResolution(
        unavailable,
        TrackResolutionReason.UNAVAILABLE,
        used_fallback=used_fallback,
    )


def resolve_track_availability(
    settings: EffectivePlaybackSettings,
    tracks: tuple[MpvTrack, ...],
) -> TrackAvailability:
    """Resolve both selectable track types from one current-file snapshot."""
    return TrackAvailability(
        tracks=tracks,
        subtitle=resolve_track_selection(
            track_type=MpvTrackType.SUBTITLE,
            requested=settings.subtitle_track,
            languages=settings.subtitle_languages,
            tracks=tracks,
        ),
        audio=resolve_track_selection(
            track_type=MpvTrackType.AUDIO,
            requested=settings.audio_track,
            languages=settings.audio_languages,
            tracks=tracks,
        ),
    )


def _preferred_track(tracks: tuple[MpvTrack, ...]) -> MpvTrack:
    return min(
        enumerate(tracks),
        key=lambda pair: (
            not pair[1].is_default,
            not pair[1].is_forced,
            pair[0],
        ),
    )[1]


def _normalize_track(value: JsonValue) -> MpvTrack | None:
    if not isinstance(value, dict):
        return None
    raw_type = value.get("type")
    raw_id = value.get("id")
    if not isinstance(raw_type, str):
        return None
    track_type = _TRACK_TYPES.get(raw_type.strip().lower())
    if (
        track_type is None
        or isinstance(raw_id, bool)
        or not isinstance(raw_id, int)
        or raw_id <= 0
    ):
        return None
    return MpvTrack(
        track_type=track_type,
        track_id=raw_id,
        language=_normalize_language(value.get("lang")),
        title=_normalize_title(value.get("title")),
        is_default=value.get("default") is True,
        is_forced=value.get("forced") is True,
        is_external=value.get("external") is True,
    )


def _normalize_language(value: JsonValue) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        preferences = LanguagePreferences((value,))
    except ValueError:
        return None
    return preferences.tags[0] if len(preferences.tags) == 1 else None


def _normalize_title(value: JsonValue) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized or None
