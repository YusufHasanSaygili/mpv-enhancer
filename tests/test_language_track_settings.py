from dataclasses import FrozenInstanceError

import pytest

from mpv_enhancer.domain.settings import (
    DETERMINISTIC_BASELINE,
    SETTING_SPEC_REGISTRY,
    EffectiveSettingsResolver,
    LanguagePreferences,
    PlaybackSettings,
    SettingKey,
    SettingValueType,
    TrackSelection,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("tr,tur,en", ("tr", "tur", "en")),
        (" es, spa, ES, en, spa ", ("es", "spa", "en")),
        ("pt-BR, zh-Hant, en", ("pt-br", "zh-hant", "en")),
        ("tr,, ,en,", ("tr", "en")),
        ("  ,  ", ()),
    ],
)
def test_language_parser_preserves_fallback_order_and_normalizes_entries(
    text: str,
    expected: tuple[str, ...],
) -> None:
    preferences = LanguagePreferences.parse(text)

    assert preferences.tags == expected
    assert preferences.to_mpv_value() == ",".join(expected)


@pytest.mark.parametrize(
    "text",
    [
        "e",
        "english language",
        "en_US",
        "tr;en",
        "toolongtag",
        "en-",
        "-en",
        "en-verylongtag",
    ],
)
def test_language_parser_rejects_invalid_text(text: str) -> None:
    with pytest.raises(ValueError, match="language tag"):
        LanguagePreferences.parse(text)


def test_language_preferences_are_immutable() -> None:
    preferences = LanguagePreferences.parse("tr,en")

    with pytest.raises(FrozenInstanceError):
        preferences.tags = ("es",)  # type: ignore[misc]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("auto", TrackSelection.auto()),
        ("AUTO", TrackSelection.auto()),
        ("off", TrackSelection.off()),
        ("7", TrackSelection.specific(7)),
    ],
)
def test_track_selection_parser_accepts_only_auto_off_or_positive_ids(
    text: str,
    expected: TrackSelection,
) -> None:
    assert TrackSelection.parse(text) == expected


@pytest.mark.parametrize("text", ["", "0", "-1", "1.5", "none", "tur"])
def test_track_selection_parser_rejects_invalid_text(text: str) -> None:
    with pytest.raises(ValueError, match="track selection"):
        TrackSelection.parse(text)


def test_language_track_and_delay_specs_are_typed_and_allowlisted() -> None:
    expected = {
        SettingKey.SUBTITLE_LANGUAGES: (
            "slang",
            SettingValueType.LANGUAGE_PREFERENCES,
            LanguagePreferences(()),
            False,
        ),
        SettingKey.AUDIO_LANGUAGES: (
            "alang",
            SettingValueType.LANGUAGE_PREFERENCES,
            LanguagePreferences(()),
            False,
        ),
        SettingKey.SUBTITLE_TRACK: (
            "sid",
            SettingValueType.TRACK_SELECTION,
            TrackSelection.auto(),
            True,
        ),
        SettingKey.AUDIO_TRACK: (
            "aid",
            SettingValueType.TRACK_SELECTION,
            TrackSelection.auto(),
            True,
        ),
        SettingKey.SUBTITLE_DELAY: (
            "sub-delay",
            SettingValueType.NUMBER,
            0.0,
            True,
        ),
        SettingKey.AUDIO_DELAY: (
            "audio-delay",
            SettingValueType.NUMBER,
            0.0,
            True,
        ),
    }

    for key, (property_name, value_type, reset_value, apply_live) in expected.items():
        spec = SETTING_SPEC_REGISTRY.require(key)
        assert (
            spec.mpv_property,
            spec.value_type,
            spec.reset_value,
            spec.apply_live,
        ) == (property_name, value_type, reset_value, apply_live)

    for key in (SettingKey.SUBTITLE_DELAY, SettingKey.AUDIO_DELAY):
        assert SETTING_SPEC_REGISTRY.validate(key, -100.0) == -100.0
        assert SETTING_SPEC_REGISTRY.validate(key, 100.0) == 100.0
        with pytest.raises(ValueError, match="between"):
            SETTING_SPEC_REGISTRY.validate(key, 100.01)


def test_new_fields_resolve_independently_and_preserve_visibility() -> None:
    playlist_defaults = PlaybackSettings(
        subtitle_languages=LanguagePreferences.parse("tr,tur,en"),
        audio_languages=LanguagePreferences.parse("es,spa,en"),
        subtitle_visibility=True,
    )
    item_overrides = PlaybackSettings(
        subtitle_track=TrackSelection.specific(4),
        audio_track=TrackSelection.off(),
        subtitle_delay=1.25,
        audio_delay=-0.5,
        subtitle_visibility=False,
    )

    effective = EffectiveSettingsResolver().resolve(
        playlist_defaults=playlist_defaults,
        item_overrides=item_overrides,
    )

    assert effective.subtitle_languages.tags == ("tr", "tur", "en")
    assert effective.audio_languages.tags == ("es", "spa", "en")
    assert effective.subtitle_track == TrackSelection.specific(4)
    assert effective.audio_track == TrackSelection.off()
    assert effective.subtitle_delay == 1.25
    assert effective.audio_delay == -0.5
    assert effective.subtitle_visibility is False
    assert DETERMINISTIC_BASELINE.subtitle_track == TrackSelection.auto()
    assert DETERMINISTIC_BASELINE.audio_track == TrackSelection.auto()


def test_typed_field_updates_and_resets_preserve_unrelated_overrides() -> None:
    original = PlaybackSettings(speed=1.2, mute=True)
    preferences = LanguagePreferences.parse("tr,tur,en")

    updated = original.with_value(SettingKey.SUBTITLE_LANGUAGES, preferences)
    updated = updated.with_value(
        SettingKey.SUBTITLE_TRACK,
        TrackSelection.specific(7),
    )
    updated = updated.with_value(SettingKey.SUBTITLE_DELAY, 0.75)

    assert updated == PlaybackSettings(
        speed=1.2,
        mute=True,
        subtitle_languages=preferences,
        subtitle_track=TrackSelection.specific(7),
        subtitle_delay=0.75,
    )
    assert updated.without_value(SettingKey.SUBTITLE_TRACK) == PlaybackSettings(
        speed=1.2,
        mute=True,
        subtitle_languages=preferences,
        subtitle_delay=0.75,
    )


@pytest.mark.parametrize(
    ("key", "invalid"),
    [
        (SettingKey.SUBTITLE_LANGUAGES, "tr,en"),
        (SettingKey.AUDIO_LANGUAGES, ("es", "en")),
        (SettingKey.SUBTITLE_TRACK, 7),
        (SettingKey.AUDIO_TRACK, "off"),
    ],
)
def test_registry_rejects_untyped_language_and_track_values(
    key: SettingKey,
    invalid: object,
) -> None:
    with pytest.raises(ValueError, match="typed"):
        SETTING_SPEC_REGISTRY.validate(key, invalid)
