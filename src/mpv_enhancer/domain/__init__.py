"""Qt-independent domain models and policies."""

from mpv_enhancer.domain.models import Playlist, QueueItem
from mpv_enhancer.domain.settings import (
    DETERMINISTIC_BASELINE,
    EMPTY_PLAYBACK_SETTINGS,
    SETTING_SPEC_REGISTRY,
    EffectivePlaybackSettings,
    EffectiveSettingsResolver,
    PlaybackSettings,
    SettingKey,
    SettingSpec,
    SettingSpecRegistry,
    SettingValue,
    SettingValueType,
)
from mpv_enhancer.domain.validation import (
    DEFAULT_SUPPORTED_MEDIA_EXTENSIONS,
    SUPPORTED_MEDIA_POLICY,
    SupportedExtensionPolicy,
    is_supported_media_path,
)

__all__ = [
    "DEFAULT_SUPPORTED_MEDIA_EXTENSIONS",
    "DETERMINISTIC_BASELINE",
    "EMPTY_PLAYBACK_SETTINGS",
    "SUPPORTED_MEDIA_POLICY",
    "SETTING_SPEC_REGISTRY",
    "EffectivePlaybackSettings",
    "EffectiveSettingsResolver",
    "Playlist",
    "PlaybackSettings",
    "QueueItem",
    "SettingKey",
    "SettingSpec",
    "SettingSpecRegistry",
    "SettingValue",
    "SettingValueType",
    "SupportedExtensionPolicy",
    "is_supported_media_path",
]
