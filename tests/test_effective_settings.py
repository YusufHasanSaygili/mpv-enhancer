from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from mpv_enhancer.domain.models import Playlist, QueueItem
from mpv_enhancer.domain.settings import (
    DETERMINISTIC_BASELINE,
    EffectivePlaybackSettings,
    EffectiveSettingsResolver,
    LanguagePreferences,
    PlaybackSettings,
    SettingKey,
    SettingValue,
    TrackSelection,
)

_PRECEDENCE_VALUES: dict[
    SettingKey,
    tuple[SettingValue, SettingValue, SettingValue, SettingValue],
] = {
    SettingKey.SPEED: (1.0, 1.25, 1.5, 2.0),
    SettingKey.PANSCAN: (0.0, 0.25, 0.5, 1.0),
    SettingKey.VOLUME: (100.0, 90.0, 80.0, 70.0),
    SettingKey.MUTE: (False, True, False, True),
    SettingKey.SUBTITLE_VISIBILITY: (True, False, True, False),
    SettingKey.SUBTITLE_LANGUAGES: (
        LanguagePreferences(()),
        LanguagePreferences.parse("en"),
        LanguagePreferences.parse("tr,en"),
        LanguagePreferences.parse("es,en"),
    ),
    SettingKey.AUDIO_LANGUAGES: (
        LanguagePreferences(()),
        LanguagePreferences.parse("en"),
        LanguagePreferences.parse("es,en"),
        LanguagePreferences.parse("tr,en"),
    ),
    SettingKey.SUBTITLE_TRACK: (
        TrackSelection.auto(),
        TrackSelection.specific(1),
        TrackSelection.off(),
        TrackSelection.specific(4),
    ),
    SettingKey.AUDIO_TRACK: (
        TrackSelection.auto(),
        TrackSelection.specific(2),
        TrackSelection.off(),
        TrackSelection.specific(5),
    ),
    SettingKey.SUBTITLE_DELAY: (0.0, 0.25, -0.5, 1.25),
    SettingKey.AUDIO_DELAY: (0.0, -0.25, 0.5, -1.25),
}


def _layer(key: SettingKey, value: SettingValue) -> PlaybackSettings:
    return PlaybackSettings(**{key.value: value})


@pytest.mark.parametrize("key", list(SettingKey))
def test_resolver_applies_every_precedence_level_for_each_core_field(
    key: SettingKey,
) -> None:
    baseline, app_value, playlist_value, item_value = _PRECEDENCE_VALUES[key]
    resolver = EffectiveSettingsResolver()
    app_defaults = _layer(key, app_value)
    playlist_defaults = _layer(key, playlist_value)
    item_overrides = _layer(key, item_value)

    assert getattr(resolver.resolve(), key.value) == baseline
    assert getattr(resolver.resolve(app_defaults=app_defaults), key.value) == app_value
    assert (
        getattr(
            resolver.resolve(
                app_defaults=app_defaults,
                playlist_defaults=playlist_defaults,
            ),
            key.value,
        )
        == playlist_value
    )
    assert (
        getattr(
            resolver.resolve(
                app_defaults=app_defaults,
                playlist_defaults=playlist_defaults,
                item_overrides=item_overrides,
            ),
            key.value,
        )
        == item_value
    )


def test_resolver_is_pure_and_returns_a_complete_immutable_value() -> None:
    resolver = EffectiveSettingsResolver()
    app_defaults = PlaybackSettings(speed=1.25, mute=True)
    playlist_defaults = PlaybackSettings(speed=1.5, panscan=0.4)
    item_overrides = PlaybackSettings(volume=75.0, subtitle_visibility=False)
    inputs_before = (app_defaults, playlist_defaults, item_overrides)

    result = resolver.resolve(
        app_defaults=app_defaults,
        playlist_defaults=playlist_defaults,
        item_overrides=item_overrides,
    )

    assert result == EffectivePlaybackSettings(
        speed=1.5,
        panscan=0.4,
        volume=75.0,
        mute=True,
        subtitle_visibility=False,
    )
    assert (app_defaults, playlist_defaults, item_overrides) == inputs_before
    with pytest.raises(FrozenInstanceError):
        result.speed = 2.0  # type: ignore[misc]


def test_queue_items_own_independent_overrides_and_playlist_owns_defaults() -> None:
    first_overrides = PlaybackSettings(speed=1.2)
    first = QueueItem.create(
        Path("synthetic/repeated.mkv"),
        overrides=first_overrides,
    )
    second = QueueItem.create(Path("synthetic/repeated.mkv"))
    playlist_defaults = PlaybackSettings(volume=85.0)
    playlist = Playlist([first, second], defaults=playlist_defaults)

    assert playlist.defaults is playlist_defaults
    assert playlist.items[0].overrides is first_overrides
    assert playlist.items[1].overrides == PlaybackSettings()
    assert playlist.items[0].item_id != playlist.items[1].item_id


def test_deterministic_baseline_contains_every_core_reset_value() -> None:
    assert DETERMINISTIC_BASELINE == PlaybackSettings(
        speed=1.0,
        panscan=0.0,
        volume=100.0,
        mute=False,
        subtitle_visibility=True,
        subtitle_languages=LanguagePreferences(()),
        audio_languages=LanguagePreferences(()),
        subtitle_track=TrackSelection.auto(),
        audio_track=TrackSelection.auto(),
        subtitle_delay=0.0,
        audio_delay=0.0,
    )
