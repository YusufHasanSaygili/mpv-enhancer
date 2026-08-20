from pathlib import Path

import pytest

from mpv_enhancer.domain.models import Playlist, QueueItem
from mpv_enhancer.domain.validation import (
    SupportedExtensionPolicy,
    is_supported_media_path,
)


def _item(path: str) -> QueueItem:
    return QueueItem.create(Path(path))


def test_playlist_inserts_items_at_a_specific_position() -> None:
    first = _item("synthetic/episode-01.mkv")
    third = _item("synthetic/episode-03.mkv")
    second = _item("synthetic/episode-02.mkv")
    playlist = Playlist([first, third])

    playlist.insert(1, second)

    assert playlist.items == (first, second, third)


def test_duplicate_paths_have_distinct_stable_identities() -> None:
    first = _item("synthetic/repeated-episode.mkv")
    second = _item("synthetic/repeated-episode.mkv")
    playlist = Playlist([first, second])

    assert first.source_path == second.source_path
    assert first.item_id != second.item_id
    assert playlist.items == (first, second)


def test_move_preserves_the_item_object_and_uuid() -> None:
    first = _item("synthetic/episode-01.mkv")
    second = _item("synthetic/episode-02.mkv")
    third = _item("synthetic/episode-03.mkv")
    playlist = Playlist([first, second, third])
    original_identity = first.item_id

    playlist.move(0, 2)

    assert playlist.items == (second, third, first)
    assert playlist.item_at(2) is first
    assert playlist.item_at(2).item_id == original_identity


def test_remove_uses_uuid_instead_of_the_source_path() -> None:
    first = _item("synthetic/repeated-episode.mkv")
    second = _item("synthetic/repeated-episode.mkv")
    playlist = Playlist([first, second])

    removed = playlist.remove(first.item_id)

    assert removed is first
    assert playlist.items == (second,)


def test_playlist_rejects_duplicate_uuid_identity() -> None:
    item = _item("synthetic/episode.mkv")

    with pytest.raises(ValueError, match="UUID"):
        Playlist([item, item])


def test_supported_extension_policy_is_case_insensitive_and_configurable() -> None:
    policy = SupportedExtensionPolicy(frozenset({".mkv", ".mp3"}))

    assert policy.supports(Path("synthetic/EPISODE.MKV"))
    assert policy.supports(Path("synthetic/audio.mp3"))
    assert not policy.supports(Path("synthetic/notes.txt"))


@pytest.mark.parametrize(
    "path",
    [
        Path("synthetic/video.mp4"),
        Path("synthetic/video.webm"),
        Path("synthetic/audio.flac"),
        Path("synthetic/audio.m4a"),
    ],
)
def test_default_policy_accepts_common_mpv_media_extensions(path: Path) -> None:
    assert is_supported_media_path(path)


def test_default_policy_rejects_files_without_a_supported_suffix() -> None:
    assert not is_supported_media_path(Path("synthetic/README.txt"))
    assert not is_supported_media_path(Path("synthetic/no-extension"))
