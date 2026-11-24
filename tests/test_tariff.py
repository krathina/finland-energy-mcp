"""Tests for dated tax rates and household contracts."""

from datetime import date
from decimal import Decimal

import pytest

from finland_energy_mcp.core.tariff import (
    FixedContract,
    SpotContract,
    electricity_tax_c_per_kwh,
    vat_rate,
)

# --- dated rates -------------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "rate"),
    [
        (date(2024, 8, 31), Decimal("0.24")),  # last day at 24 %
        (date(2024, 9, 1), Decimal("0.255")),  # first day at 25.5 %
        (date(2026, 11, 24), Decimal("0.255")),
    ],
)
def test_vat_rate_follows_its_valid_from_dates(day: date, rate: Decimal) -> None:
    assert vat_rate(day) == rate


@pytest.mark.parametrize(
    ("day", "excl_vat"),
    [
        (date(2026, 3, 31), Decimal("2.253")),  # before the stockpile fee rise
        (date(2026, 4, 1), Decimal("2.325")),  # 2.24 tax + 0.085 stockpile fee
    ],
)
def test_electricity_tax_changes_on_1_april_2026(day: date, excl_vat: Decimal) -> None:
    assert electricity_tax_c_per_kwh(day, include_vat=False) == excl_vat


def test_electricity_tax_including_vat_matches_published_figure() -> None:
    # Finnish network companies publish 2.917875 c/kWh incl. VAT from 1.4.2026.
    assert electricity_tax_c_per_kwh(date(2026, 4, 1)) == Decimal("2.917875")


def test_rates_before_the_known_table_are_refused_not_guessed() -> None:
    with pytest.raises(LookupError):
        vat_rate(date(2000, 1, 1))
    with pytest.raises(LookupError):
        electricity_tax_c_per_kwh(date(2000, 1, 1))


# --- contracts ---------------------------------------------------------------


def test_spot_contract_holds_consumer_prices_including_vat() -> None:
    c = SpotContract(
        margin_c_per_kwh=Decimal("0.49"),
        transfer_c_per_kwh=Decimal("3.5"),
        monthly_fees_eur=Decimal("8.90"),
    )
    assert c.margin_c_per_kwh == Decimal("0.49")


def test_contracts_reject_negative_fees() -> None:
    with pytest.raises(ValueError):
        SpotContract(
            margin_c_per_kwh=Decimal("-1"),
            transfer_c_per_kwh=Decimal("3.5"),
            monthly_fees_eur=Decimal("0"),
        )
    with pytest.raises(ValueError):
        FixedContract(
            energy_c_per_kwh=Decimal("8.5"),
            transfer_c_per_kwh=Decimal("3.5"),
            monthly_fees_eur=Decimal("-0.01"),
        )
