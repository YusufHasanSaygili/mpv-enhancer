import math

import pytest

from mpv_enhancer.domain.settings import (
    SETTING_SPEC_REGISTRY,
    SettingKey,
    SettingValueType,
)


def test_core_registry_declares_exact_safe_settings_and_metadata() -> None:
    expected = {
        SettingKey.SPEED: ("speed", SettingValueType.NUMBER, 0.25, 4.0, 1.0, True),
        SettingKey.PANSCAN: (
            "panscan",
            SettingValueType.NUMBER,
            0.0,
            1.0,
            0.0,
            True,
        ),
        SettingKey.VOLUME: (
            "volume",
            SettingValueType.NUMBER,
            0.0,
            130.0,
            100.0,
            True,
        ),
        SettingKey.MUTE: ("mute", SettingValueType.BOOLEAN, None, None, False, True),
        SettingKey.SUBTITLE_VISIBILITY: (
            "sub-visibility",
            SettingValueType.BOOLEAN,
            None,
            None,
            True,
            True,
        ),
    }

    assert set(SETTING_SPEC_REGISTRY.keys) == set(expected)
    for key, metadata in expected.items():
        spec = SETTING_SPEC_REGISTRY.require(key)
        assert (
            spec.mpv_property,
            spec.value_type,
            spec.minimum,
            spec.maximum,
            spec.reset_value,
            spec.apply_live,
        ) == metadata


@pytest.mark.parametrize(
    ("key", "boundary"),
    [
        (SettingKey.SPEED, 0.25),
        (SettingKey.SPEED, 4.0),
        (SettingKey.PANSCAN, 0.0),
        (SettingKey.PANSCAN, 1.0),
        (SettingKey.VOLUME, 0),
        (SettingKey.VOLUME, 130),
    ],
)
def test_numeric_setting_boundaries_are_inclusive(
    key: SettingKey,
    boundary: float,
) -> None:
    assert SETTING_SPEC_REGISTRY.validate(key, boundary) == float(boundary)


@pytest.mark.parametrize(
    ("key", "invalid"),
    [
        (SettingKey.SPEED, 0.249),
        (SettingKey.SPEED, 4.001),
        (SettingKey.PANSCAN, -0.001),
        (SettingKey.PANSCAN, 1.001),
        (SettingKey.VOLUME, -1),
        (SettingKey.VOLUME, 131),
        (SettingKey.SPEED, True),
        (SettingKey.PANSCAN, "0.5"),
        (SettingKey.VOLUME, math.inf),
        (SettingKey.VOLUME, math.nan),
    ],
)
def test_numeric_settings_reject_out_of_range_or_wrong_type_values(
    key: SettingKey,
    invalid: object,
) -> None:
    with pytest.raises(ValueError, match="valid"):
        SETTING_SPEC_REGISTRY.validate(key, invalid)


@pytest.mark.parametrize(
    "key",
    [SettingKey.MUTE, SettingKey.SUBTITLE_VISIBILITY],
)
def test_boolean_settings_accept_only_actual_booleans(key: SettingKey) -> None:
    assert SETTING_SPEC_REGISTRY.validate(key, True) is True
    assert SETTING_SPEC_REGISTRY.validate(key, False) is False

    for invalid in (0, 1, "yes", None):
        with pytest.raises(ValueError, match="boolean"):
            SETTING_SPEC_REGISTRY.validate(key, invalid)


def test_registry_rejects_unknown_keys_instead_of_exposing_raw_mpv_properties() -> None:
    with pytest.raises(KeyError, match="registered"):
        SETTING_SPEC_REGISTRY.require("run")
