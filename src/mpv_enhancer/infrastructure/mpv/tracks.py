"""Normalize untrusted mpv track-list values into typed track metadata."""

from dataclasses import dataclass
from enum import StrEnum

from mpv_enhancer.domain.settings import LanguagePreferences
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
