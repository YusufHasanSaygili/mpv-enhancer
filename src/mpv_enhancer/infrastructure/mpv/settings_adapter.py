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
    VideoCrop,
    VideoDimensions,
    VideoRotation,
)
from mpv_enhancer.infrastructure.mpv.capabilities import MpvCapabilities
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
        self._capabilities: MpvCapabilities | None = None

    def set_capabilities(self, capabilities: MpvCapabilities) -> None:
        """Gate future property writes against one normalized mpv snapshot."""
        self._capabilities = capabilities

    def reset_managed_properties(self) -> None:
        """Restore every managed mpv property to its deterministic reset value."""
        for spec in self._registry.specs:
            if not self._is_supported(spec.mpv_property):
                continue
            self._set_property(spec.mpv_property, spec.reset_value)

    def apply(self, settings: EffectivePlaybackSettings) -> None:
        """Reset prior state and apply settings not requiring source metadata."""
        self.reset_managed_properties()
        for spec in self._registry.specs:
            if spec.key is SettingKey.VIDEO_CROP or not self._is_supported(
                spec.mpv_property
            ):
                continue
            self._set_property(
                spec.mpv_property,
                _effective_value(settings, spec.key),
            )

    def apply_validated_crop(
        self,
        crop: VideoCrop,
        source: VideoDimensions,
    ) -> None:
        """Apply a crop only after it fits the decoded source rectangle."""
        validated = crop.validated_for(source)
        property_name = self._registry.require(SettingKey.VIDEO_CROP).mpv_property
        if self._is_supported(property_name):
            self._set_property(property_name, validated)

    def apply_resolved_tracks(
        self,
        settings: EffectivePlaybackSettings,
        tracks: tuple[MpvTrack, ...],
    ) -> TrackAvailability:
        """Apply deterministic IDs after mpv reports the current file's tracks."""
        availability = resolve_track_availability(settings, tracks)
        subtitle_property = self._registry.require(
            SettingKey.SUBTITLE_TRACK
        ).mpv_property
        audio_property = self._registry.require(SettingKey.AUDIO_TRACK).mpv_property
        if self._is_supported(subtitle_property):
            self._set_property(subtitle_property, availability.subtitle.selection)
        if self._is_supported(audio_property):
            self._set_property(audio_property, availability.audio.selection)
        return availability

    def _is_supported(self, property_name: str) -> bool:
        return self._capabilities is None or self._capabilities.supports_property(
            property_name
        )

    def _set_property(self, name: str, value: SettingValue) -> None:
        self._client.request(("set_property", name, _mpv_value(value)))


def _effective_value(
    settings: EffectivePlaybackSettings,
    key: SettingKey,
) -> SettingValue:
    return settings.value_for(key)


def _mpv_value(value: SettingValue) -> JsonValue:
    if isinstance(value, VideoRotation):
        return value.to_mpv_value()
    if isinstance(value, VideoCrop):
        return value.to_mpv_value()
    if isinstance(value, AspectRatio):
        return value.to_mpv_value()
    if isinstance(value, LanguagePreferences):
        return value.to_mpv_value()
    if isinstance(value, TrackSelection):
        return value.to_mpv_value()
    return value


def normalize_video_dimensions(value: JsonValue) -> VideoDimensions | None:
    """Normalize decoded mpv source dimensions without leaking raw JSON."""
    if not isinstance(value, dict):
        return None
    width = value.get("w")
    height = value.get("h")
    if (
        isinstance(width, bool)
        or not isinstance(width, int)
        or isinstance(height, bool)
        or not isinstance(height, int)
    ):
        return None
    try:
        return VideoDimensions(width, height)
    except ValueError:
        return None
