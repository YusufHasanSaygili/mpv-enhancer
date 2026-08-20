"""Typed starter presets built only from validated setting patches."""

from dataclasses import dataclass
from enum import StrEnum

from mpv_enhancer.domain.selection_settings import SettingPatch
from mpv_enhancer.domain.settings import SettingKey


class PresetKey(StrEnum):
    """Stable identities for the starter preset collection."""

    DEFAULT = "default"
    PLAYBACK_1_2X = "playback_1_2x"
    FILL_DISPLAY = "fill_display"
    SUBTITLES_ON = "subtitles_on"
    SUBTITLES_OFF = "subtitles_off"


@dataclass(frozen=True, slots=True)
class SettingsPreset:
    """One reviewed multi-property patch with a generated complete preview."""

    key: PresetKey
    label: str
    patches: tuple[SettingPatch, ...]
    reset_all: bool = False

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError("A settings preset requires an English label.")
        if self.reset_all == bool(self.patches):
            raise ValueError("A preset must either reset all or declare patches.")
        keys = tuple(patch.key for patch in self.patches)
        if len(keys) != len(set(keys)):
            raise ValueError("A preset cannot patch the same setting twice.")

    @property
    def preview_text(self) -> str:
        """Describe every change directly from the preset's typed patch data."""
        if self.reset_all:
            return "All overrides → Inherited"
        return "; ".join(_patch_preview(patch) for patch in self.patches)


def _patch_preview(patch: SettingPatch) -> str:
    if patch.key is SettingKey.SPEED:
        return f"Speed → {patch.value:g}×"
    if patch.key is SettingKey.PANSCAN:
        return f"Pan and Scan → {patch.value:.1f}"
    if patch.key is SettingKey.VOLUME:
        return f"Volume → {patch.value:g}%"
    if patch.key is SettingKey.MUTE:
        return f"Mute → {'On' if patch.value else 'Off'}"
    if patch.key is SettingKey.SUBTITLE_VISIBILITY:
        return f"Subtitles → {'On' if patch.value else 'Off'}"
    raise ValueError(f"No starter preset preview exists for {patch.key.value}.")


STARTER_PRESETS = (
    SettingsPreset(PresetKey.DEFAULT, "Default", (), reset_all=True),
    SettingsPreset(
        PresetKey.PLAYBACK_1_2X,
        "1.2× Playback",
        (SettingPatch(SettingKey.SPEED, 1.2),),
    ),
    SettingsPreset(
        PresetKey.FILL_DISPLAY,
        "Fill Display",
        (SettingPatch(SettingKey.PANSCAN, 1.0),),
    ),
    SettingsPreset(
        PresetKey.SUBTITLES_ON,
        "Subtitles On",
        (SettingPatch(SettingKey.SUBTITLE_VISIBILITY, True),),
    ),
    SettingsPreset(
        PresetKey.SUBTITLES_OFF,
        "Subtitles Off",
        (SettingPatch(SettingKey.SUBTITLE_VISIBILITY, False),),
    ),
)
