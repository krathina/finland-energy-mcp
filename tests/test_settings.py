"""Tests for reading settings from environment variables.

Each test passes its own small dict as the environment, so tests never depend on (or change)
the real environment of the machine running them.
"""

from datetime import timedelta
from decimal import Decimal

import pytest

from finland_energy_mcp.server.settings import Settings


def test_defaults_when_nothing_is_set() -> None:
    s = Settings.from_env({})
    assert s.margin_c_per_kwh == Decimal("0.49")
    assert s.transfer_c_per_kwh == Decimal("3.5")
    assert s.vat_on_negative is False
    assert s.spot_hinta_base_url == "https://api.spot-hinta.fi"
    assert s.request_timeout_seconds == 10.0
    assert s.cache_for == timedelta(minutes=15)


def test_every_setting_can_be_overridden() -> None:
    s = Settings.from_env(
        {
            "FINLAND_ENERGY_MARGIN_C_PER_KWH": "0.6",
            "FINLAND_ENERGY_TRANSFER_C_PER_KWH": "4,2",  # Finnish decimal comma
            "FINLAND_ENERGY_VAT_ON_NEGATIVE": "true",
            "FINLAND_ENERGY_SPOT_HINTA_BASE_URL": "http://localhost:8080",
            "FINLAND_ENERGY_REQUEST_TIMEOUT_SECONDS": "30",
            "FINLAND_ENERGY_CACHE_MINUTES": "5",
        }
    )
    assert s.margin_c_per_kwh == Decimal("0.6")
    assert s.transfer_c_per_kwh == Decimal("4.2")
    assert s.vat_on_negative is True
    assert s.spot_hinta_base_url == "http://localhost:8080"
    assert s.request_timeout_seconds == 30.0
    assert s.cache_for == timedelta(minutes=5)


def test_empty_values_mean_default() -> None:
    s = Settings.from_env({"FINLAND_ENERGY_CACHE_MINUTES": "  "})
    assert s.cache_for == timedelta(minutes=15)


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("FINLAND_ENERGY_MARGIN_C_PER_KWH", "cheap", "must be a number"),
        ("FINLAND_ENERGY_REQUEST_TIMEOUT_SECONDS", "0", "greater than 0"),
        ("FINLAND_ENERGY_CACHE_MINUTES", "0", "at least 1"),
        ("FINLAND_ENERGY_CACHE_MINUTES", "1.5", "whole number"),
        ("FINLAND_ENERGY_SPOT_HINTA_BASE_URL", "api.spot-hinta.fi", "http"),
    ],
)
def test_invalid_values_are_refused_with_the_variable_name(
    key: str, value: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message) as error:
        Settings.from_env({key: value})
    assert key in str(error.value)  # the message names the variable to fix
