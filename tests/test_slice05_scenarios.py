from collections.abc import Sequence

from mpv_enhancer.domain.settings import (
    EffectivePlaybackSettings,
    LanguagePreferences,
)
from mpv_enhancer.infrastructure.mpv.json_ipc import JsonValue
from mpv_enhancer.infrastructure.mpv.settings_adapter import MpvSettingsAdapter
from mpv_enhancer.infrastructure.mpv.tracks import normalize_mpv_track_list


class _RecordingClient:
    def __init__(self) -> None:
        self.commands: list[tuple[JsonValue, ...]] = []

    def request(self, command: Sequence[JsonValue]) -> object:
        self.commands.append(tuple(command))
        return object()


def _settings(
    subtitle_languages: str,
    *,
    visible: bool,
    delay: float,
) -> EffectivePlaybackSettings:
    return EffectivePlaybackSettings(
        speed=1.0,
        panscan=0.0,
        volume=100.0,
        mute=False,
        subtitle_visibility=visible,
        subtitle_languages=LanguagePreferences.parse(subtitle_languages),
        subtitle_delay=delay,
    )


def test_episode_six_turkish_and_episode_seven_spanish_are_independent() -> None:
    episode_six_tracks = normalize_mpv_track_list(
        [
            {"type": "audio", "id": 1, "lang": "eng", "default": True},
            {"type": "sub", "id": 2, "lang": "eng", "default": True},
            {"type": "sub", "id": 6, "lang": "tur", "title": "Turkish"},
        ]
    )
    episode_seven_tracks = normalize_mpv_track_list(
        [
            {"type": "audio", "id": 4, "lang": "eng", "default": True},
            {"type": "sub", "id": 3, "lang": "eng", "default": True},
            {"type": "sub", "id": 7, "lang": "spa", "title": "Spanish"},
        ]
    )
    episode_six = _settings("tr,tur,en", visible=True, delay=-0.25)
    episode_seven = _settings("es,spa,en", visible=False, delay=1.5)
    client = _RecordingClient()
    adapter = MpvSettingsAdapter(client)

    six = adapter.apply_resolved_tracks(episode_six, episode_six_tracks)
    seven_start = len(client.commands)
    seven = adapter.apply_resolved_tracks(episode_seven, episode_seven_tracks)

    assert six.subtitle.selection.track_id == 6
    assert six.subtitle.matched_language == "tur"
    assert seven.subtitle.selection.track_id == 7
    assert seven.subtitle.matched_language == "spa"
    assert episode_six.subtitle_languages.tags == ("tr", "tur", "en")
    assert episode_seven.subtitle_languages.tags == ("es", "spa", "en")
    assert episode_six.subtitle_visibility
    assert not episode_seven.subtitle_visibility
    assert episode_six.subtitle_delay == -0.25
    assert episode_seven.subtitle_delay == 1.5
    assert ("set_property", "sid", 6) not in client.commands[seven_start:]
    assert client.commands[seven_start:] == [
        ("set_property", "sid", 7),
        ("set_property", "aid", 4),
    ]
