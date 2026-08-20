"""Allowlisted effective-setting application over mpv JSON IPC."""

from collections.abc import Sequence
from typing import Protocol

from mpv_enhancer.domain.settings import (
    SETTING_SPEC_REGISTRY,
    AspectRatio,
    EffectivePlaybackSettings,
    LanguagePreferences,
    SettingKey,
    SettingSpecRegistry,
    SettingValue,
    TrackSelection,
)
from mpv_enhancer.infrastructure.mpv.json_ipc import JsonValue
from mpv_enhancer.infrastructure.mpv.tracks import (
    MpvTrack,
    TrackAvailability,
    resolve_track_availability,
)


class SettingsIpcClient(Protocol):
    """Narrow JSON IPC boundary required by managed settings."""

    def request(self, command: Sequence[JsonValue]) -> object: ...


class MpvSettingsAdapter:
    """Reset and apply only typed properties declared in the settings registry."""

    def __init__(
        self,
        client: SettingsIpcClient,
        registry: SettingSpecRegistry = SETTING_SPEC_REGISTRY,
    ) -> None:
        self._client = client
        self._registry = registry

    def reset_managed_properties(self) -> None:
        """Restore every managed mpv property to its deterministic reset value."""
        for spec in self._registry.specs:
            self._set_property(spec.mpv_property, spec.reset_value)

    def apply(self, settings: EffectivePlaybackSettings) -> None:
        """Reset prior state, then apply one complete effective settings value."""
        self.reset_managed_properties()
        for spec in self._registry.specs:
            self._set_property(
                spec.mpv_property,
                _effective_value(settings, spec.key),
            )

    def apply_resolved_tracks(
        self,
        settings: EffectivePlaybackSettings,
        tracks: tuple[MpvTrack, ...],
    ) -> TrackAvailability:
        """Apply deterministic IDs after mpv reports the current file's tracks."""
        availability = resolve_track_availability(settings, tracks)
        self._set_property(
            self._registry.require(SettingKey.SUBTITLE_TRACK).mpv_property,
            availability.subtitle.selection,
        )
        self._set_property(
            self._registry.require(SettingKey.AUDIO_TRACK).mpv_property,
            availability.audio.selection,
        )
        return availability

    def _set_property(self, name: str, value: SettingValue) -> None:
        self._client.request(("set_property", name, _mpv_value(value)))


def _effective_value(
    settings: EffectivePlaybackSettings,
    key: SettingKey,
) -> SettingValue:
    return settings.value_for(key)


def _mpv_value(value: SettingValue) -> JsonValue:
    if isinstance(value, AspectRatio):
        return value.to_mpv_value()
    if isinstance(value, LanguagePreferences):
        return value.to_mpv_value()
    if isinstance(value, TrackSelection):
        return value.to_mpv_value()
    return value
