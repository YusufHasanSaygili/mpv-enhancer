from mpv_enhancer.domain.settings import LanguagePreferences, TrackSelection
from mpv_enhancer.infrastructure.mpv.tracks import (
    MpvTrack,
    MpvTrackType,
    TrackResolution,
    TrackResolutionReason,
    normalize_mpv_track_list,
    resolve_track_selection,
)


def test_track_list_normalizes_tagged_untagged_duplicate_and_external_tracks() -> None:
    raw_tracks = [
        {
            "type": "sub",
            "id": 3,
            "lang": " TR ",
            "title": " Turkish Signs ",
            "default": True,
            "forced": True,
        },
        {"type": "audio", "id": 1, "title": "Original audio"},
        {"type": "audio", "id": 2, "lang": "ENG", "default": True},
        {"type": "audio", "id": 4, "lang": "eng", "title": "Commentary"},
        {
            "type": "sub",
            "id": 8,
            "lang": "es",
            "title": "External Spanish",
            "external": True,
        },
    ]

    assert normalize_mpv_track_list(raw_tracks) == (
        MpvTrack(
            track_type=MpvTrackType.SUBTITLE,
            track_id=3,
            language="tr",
            title="Turkish Signs",
            is_default=True,
            is_forced=True,
            is_external=False,
        ),
        MpvTrack(
            track_type=MpvTrackType.AUDIO,
            track_id=1,
            language=None,
            title="Original audio",
            is_default=False,
            is_forced=False,
            is_external=False,
        ),
        MpvTrack(
            track_type=MpvTrackType.AUDIO,
            track_id=2,
            language="eng",
            title=None,
            is_default=True,
            is_forced=False,
            is_external=False,
        ),
        MpvTrack(
            track_type=MpvTrackType.AUDIO,
            track_id=4,
            language="eng",
            title="Commentary",
            is_default=False,
            is_forced=False,
            is_external=False,
        ),
        MpvTrack(
            track_type=MpvTrackType.SUBTITLE,
            track_id=8,
            language="es",
            title="External Spanish",
            is_default=False,
            is_forced=False,
            is_external=True,
        ),
    )


def test_track_list_ignores_invalid_entries_without_reordering_valid_tracks() -> None:
    raw_tracks = [
        None,
        {"type": "unknown", "id": 1},
        {"type": "video", "id": True},
        {"type": "audio", "id": 0},
        {"type": "video", "id": 5, "lang": "not a tag"},
        {"type": "sub", "id": 6, "title": 99, "external": "yes"},
    ]

    assert normalize_mpv_track_list(raw_tracks) == (
        MpvTrack(MpvTrackType.VIDEO, 5),
        MpvTrack(MpvTrackType.SUBTITLE, 6),
    )
    assert normalize_mpv_track_list(None) == ()
    assert normalize_mpv_track_list({"type": "audio", "id": 1}) == ()


def test_language_resolution_honors_preference_order_before_track_defaults() -> None:
    tracks = (
        MpvTrack(MpvTrackType.SUBTITLE, 1, "en", is_default=True),
        MpvTrack(MpvTrackType.SUBTITLE, 2, "tur", title="Full"),
        MpvTrack(MpvTrackType.SUBTITLE, 3, "tur", title="Signs", is_forced=True),
        MpvTrack(MpvTrackType.SUBTITLE, 4, "tr"),
    )

    result = resolve_track_selection(
        track_type=MpvTrackType.SUBTITLE,
        requested=TrackSelection.auto(),
        languages=LanguagePreferences.parse("tr,tur,en"),
        tracks=tracks,
    )

    assert result == TrackResolution(
        selection=TrackSelection.specific(4),
        reason=TrackResolutionReason.LANGUAGE,
        matched_language="tr",
    )
    assert resolve_track_selection(
        track_type=MpvTrackType.SUBTITLE,
        requested=TrackSelection.auto(),
        languages=LanguagePreferences.parse("tur,en"),
        tracks=tracks,
    ) == TrackResolution(
        selection=TrackSelection.specific(3),
        reason=TrackResolutionReason.LANGUAGE,
        matched_language="tur",
    )


def test_resolution_handles_explicit_off_and_documented_fallbacks() -> None:
    tracks = (
        MpvTrack(MpvTrackType.AUDIO, 1, "en", is_default=True),
        MpvTrack(MpvTrackType.AUDIO, 2, "es"),
        MpvTrack(MpvTrackType.SUBTITLE, 3, "en", is_forced=True),
        MpvTrack(MpvTrackType.SUBTITLE, 4),
    )

    assert resolve_track_selection(
        track_type=MpvTrackType.AUDIO,
        requested=TrackSelection.specific(2),
        languages=LanguagePreferences(()),
        tracks=tracks,
    ) == TrackResolution(
        TrackSelection.specific(2),
        TrackResolutionReason.EXPLICIT,
    )
    assert resolve_track_selection(
        track_type=MpvTrackType.SUBTITLE,
        requested=TrackSelection.off(),
        languages=LanguagePreferences.parse("tr,tur,en"),
        tracks=tracks,
    ) == TrackResolution(TrackSelection.off(), TrackResolutionReason.OFF)
    assert resolve_track_selection(
        track_type=MpvTrackType.AUDIO,
        requested=TrackSelection.specific(99),
        languages=LanguagePreferences.parse("es,spa,en"),
        tracks=tracks,
    ) == TrackResolution(
        TrackSelection.specific(2),
        TrackResolutionReason.LANGUAGE,
        matched_language="es",
        used_fallback=True,
    )
    assert resolve_track_selection(
        track_type=MpvTrackType.SUBTITLE,
        requested=TrackSelection.auto(),
        languages=LanguagePreferences.parse("tr,tur"),
        tracks=tracks,
    ) == TrackResolution(
        TrackSelection.specific(3),
        TrackResolutionReason.FORCED,
        used_fallback=True,
    )
    assert resolve_track_selection(
        track_type=MpvTrackType.SUBTITLE,
        requested=TrackSelection.auto(),
        languages=LanguagePreferences.parse("tr"),
        tracks=(),
    ) == TrackResolution(
        TrackSelection.off(),
        TrackResolutionReason.UNAVAILABLE,
        used_fallback=True,
    )
    assert resolve_track_selection(
        track_type=MpvTrackType.AUDIO,
        requested=TrackSelection.auto(),
        languages=LanguagePreferences(()),
        tracks=(),
    ) == TrackResolution(
        TrackSelection.auto(),
        TrackResolutionReason.UNAVAILABLE,
    )
