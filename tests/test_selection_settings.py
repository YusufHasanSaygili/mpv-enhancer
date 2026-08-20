from pathlib import Path
from uuid import UUID

import pytest

from mpv_enhancer.domain.models import QueueItem
from mpv_enhancer.domain.selection_settings import (
    SelectedSettingState,
    SettingPatch,
    apply_selection_patch,
    inspect_selected_setting,
    reset_all_selection_overrides,
    reset_selection_setting,
)
from mpv_enhancer.domain.settings import PlaybackSettings, SettingKey


def _item(number: int, overrides: PlaybackSettings | None = None) -> QueueItem:
    return QueueItem.create(
        Path(f"synthetic/episode-{number:02}.mkv"),
        overrides=overrides,
    )


def test_one_property_patch_updates_many_items_without_touching_other_fields() -> None:
    items = tuple(
        _item(
            number,
            PlaybackSettings(
                panscan=0.4 if number == 4 else None,
                volume=70.0 if number == 6 else None,
            ),
        )
        for number in range(1, 7)
    )
    selected_ids = (items[1].item_id, items[3].item_id, items[5].item_id)
    original_overrides = tuple(item.overrides for item in items)

    updated = apply_selection_patch(
        items,
        selected_ids,
        SettingPatch(SettingKey.SPEED, 1.2),
    )

    for index, item in enumerate(updated):
        expected_speed = 1.2 if index in {1, 3, 5} else None
        assert item.overrides.speed == expected_speed
        assert item.overrides.panscan == original_overrides[index].panscan
        assert item.overrides.volume == original_overrides[index].volume
    assert tuple(item.overrides for item in items) == original_overrides


@pytest.mark.parametrize(
    ("key", "first", "second"),
    [
        (SettingKey.SPEED, 1.2, 1.5),
        (SettingKey.PANSCAN, 0.2, 0.8),
        (SettingKey.VOLUME, 80.0, 90.0),
        (SettingKey.MUTE, True, False),
        (SettingKey.SUBTITLE_VISIBILITY, True, False),
    ],
)
def test_selection_state_distinguishes_inherited_explicit_and_mixed_values(
    key: SettingKey,
    first: float | bool,
    second: float | bool,
) -> None:
    inherited = (_item(1), _item(2))
    explicit = (
        _item(1, PlaybackSettings(**{key.value: first})),
        _item(2, PlaybackSettings(**{key.value: first})),
    )
    mixed = (
        _item(1, PlaybackSettings(**{key.value: first})),
        _item(2, PlaybackSettings(**{key.value: second})),
    )

    assert (
        inspect_selected_setting(inherited, key).state is SelectedSettingState.INHERITED
    )
    explicit_state = inspect_selected_setting(explicit, key)
    assert explicit_state.state is SelectedSettingState.EXPLICIT
    assert explicit_state.value == first
    assert inspect_selected_setting(mixed, key).state is SelectedSettingState.MIXED
    assert (
        inspect_selected_setting((inherited[0], explicit[0]), key).state
        is SelectedSettingState.MIXED
    )


def test_reset_one_removes_only_that_property_from_selected_items() -> None:
    overrides = PlaybackSettings(speed=1.5, panscan=0.7, mute=True)
    items = (_item(1, overrides), _item(2, overrides), _item(3, overrides))

    updated = reset_selection_setting(
        items,
        (items[0].item_id, items[2].item_id),
        SettingKey.SPEED,
    )

    assert updated[0].overrides == PlaybackSettings(panscan=0.7, mute=True)
    assert updated[1].overrides == overrides
    assert updated[2].overrides == PlaybackSettings(panscan=0.7, mute=True)


def test_reset_all_removes_every_override_from_selected_items_only() -> None:
    overrides = PlaybackSettings(speed=1.5, volume=60.0, subtitle_visibility=False)
    items = (_item(1, overrides), _item(2, overrides), _item(3, overrides))

    updated = reset_all_selection_overrides(items, (items[1].item_id,))

    assert updated[0].overrides == overrides
    assert updated[1].overrides == PlaybackSettings()
    assert updated[2].overrides == overrides


def test_selection_commands_reject_stale_item_identities() -> None:
    items = (_item(1),)

    with pytest.raises(KeyError, match="selection"):
        apply_selection_patch(
            items,
            (UUID("00000000-0000-0000-0000-000000000001"),),
            SettingPatch(SettingKey.VOLUME, 80.0),
        )


def test_setting_patch_rejects_an_unregistered_raw_key() -> None:
    with pytest.raises(KeyError, match="registered"):
        SettingPatch("run", True)  # type: ignore[arg-type]


def test_setting_patch_normalizes_a_registered_serialized_key() -> None:
    patch = SettingPatch("speed", 1.2)  # type: ignore[arg-type]

    assert patch.key is SettingKey.SPEED
