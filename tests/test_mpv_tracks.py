from mpv_enhancer.infrastructure.mpv.tracks import (
    MpvTrack,
    MpvTrackType,
    normalize_mpv_track_list,
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
