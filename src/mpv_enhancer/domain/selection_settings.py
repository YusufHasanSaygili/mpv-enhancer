"""Pure multi-item setting inspection and patch commands."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from enum import StrEnum
from uuid import UUID

from mpv_enhancer.domain.models import QueueItem
from mpv_enhancer.domain.settings import (
    SETTING_SPEC_REGISTRY,
    PlaybackSettings,
    SettingKey,
    SettingValue,
)


class SelectedSettingState(StrEnum):
    """Presentation-neutral state for one field across selected items."""

    INHERITED = "inherited"
    EXPLICIT = "explicit"
    MIXED = "mixed"


@dataclass(frozen=True, slots=True)
class SelectedSettingValue:
    """A selection state with a value only when every override is explicit."""

    state: SelectedSettingState
    value: SettingValue | None = None

    def __post_init__(self) -> None:
        if self.state is SelectedSettingState.EXPLICIT and self.value is None:
            raise ValueError("An explicit selection state requires a value.")
        if self.state is not SelectedSettingState.EXPLICIT and self.value is not None:
            raise ValueError("Only an explicit selection state may contain a value.")


@dataclass(frozen=True, slots=True)
class SettingPatch:
    """One validated property update that preserves every unrelated override."""

    key: SettingKey
    value: SettingValue

    def __post_init__(self) -> None:
        normalized_key = SETTING_SPEC_REGISTRY.require(self.key).key
        object.__setattr__(self, "key", normalized_key)
        object.__setattr__(
            self,
            "value",
            SETTING_SPEC_REGISTRY.validate(normalized_key, self.value),
        )


def inspect_selected_setting(
    selected_items: Iterable[QueueItem],
    key: SettingKey,
) -> SelectedSettingValue:
    """Calculate inherited, explicit, or mixed state from raw overrides."""
    values = tuple(item.overrides.value_for(key) for item in selected_items)
    if not values:
        raise ValueError("At least one selected item is required.")
    if all(value is None for value in values):
        return SelectedSettingValue(SelectedSettingState.INHERITED)
    first = values[0]
    if first is not None and all(value == first for value in values):
        return SelectedSettingValue(SelectedSettingState.EXPLICIT, first)
    return SelectedSettingValue(SelectedSettingState.MIXED)


def apply_selection_patch(
    items: Iterable[QueueItem],
    selected_item_ids: Iterable[UUID],
    patch: SettingPatch,
) -> tuple[QueueItem, ...]:
    """Apply one property to selected UUIDs and return a new queue snapshot."""
    return _update_selection(
        items,
        selected_item_ids,
        lambda settings: settings.with_value(patch.key, patch.value),
    )


def reset_selection_setting(
    items: Iterable[QueueItem],
    selected_item_ids: Iterable[UUID],
    key: SettingKey,
) -> tuple[QueueItem, ...]:
    """Remove one selected property while preserving unrelated overrides."""
    return _update_selection(
        items,
        selected_item_ids,
        lambda settings: settings.without_value(key),
    )


def reset_all_selection_overrides(
    items: Iterable[QueueItem],
    selected_item_ids: Iterable[UUID],
) -> tuple[QueueItem, ...]:
    """Remove every override from selected UUIDs only."""
    return _update_selection(
        items,
        selected_item_ids,
        lambda _settings: PlaybackSettings(),
    )


def _update_selection(
    items: Iterable[QueueItem],
    selected_item_ids: Iterable[UUID],
    update: Callable[[PlaybackSettings], PlaybackSettings],
) -> tuple[QueueItem, ...]:
    snapshot = tuple(items)
    selected = frozenset(selected_item_ids)
    known = {item.item_id for item in snapshot}
    missing = selected - known
    if missing:
        raise KeyError(
            "A selected queue identity is not present in the selection source."
        )
    return tuple(
        replace(item, overrides=update(item.overrides))
        if item.item_id in selected
        else item
        for item in snapshot
    )
