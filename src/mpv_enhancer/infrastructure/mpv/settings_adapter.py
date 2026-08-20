"""Allowlisted effective-setting application over mpv JSON IPC."""

from collections.abc import Sequence
from typing import Protocol

from mpv_enhancer.domain.settings import (
    SETTING_SPEC_REGISTRY,
    EffectivePlaybackSettings,
    SettingKey,
    SettingSpecRegistry,
    SettingValue,
)
from mpv_enhancer.infrastructure.mpv.json_ipc import JsonValue


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

    def _set_property(self, name: str, value: SettingValue) -> None:
        self._client.request(("set_property", name, value))


def _effective_value(
    settings: EffectivePlaybackSettings,
    key: SettingKey,
) -> SettingValue:
    if key is SettingKey.SPEED:
        return settings.speed
    if key is SettingKey.PANSCAN:
        return settings.panscan
    if key is SettingKey.VOLUME:
        return settings.volume
    if key is SettingKey.MUTE:
        return settings.mute
    return settings.subtitle_visibility
