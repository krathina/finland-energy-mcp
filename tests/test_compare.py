"""Tests for comparing a fixed-price contract with a spot contract."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from finland_energy_mcp.core.compare import compare_contracts, flat_usage
from finland_energy_mcp.core.models import PricePoint, PriceSeries
from finland_energy_mcp.core.tariff import FixedContract, SpotContract

HELSINKI = ZoneInfo("Europe/Helsinki")
QUARTER = timedelta(minutes=15)
START = datetime(2026, 11, 24, 0, 0, tzinfo=HELSINKI)

SPOT = SpotContract(
    margin_c_per_kwh=Decimal("0.49"),
    transfer_c_per_kwh=Decimal("3.5"),
    monthly_fees_eur=Decimal("4.50"),
)
FIXED = FixedContract(
    energy_c_per_kwh=Decimal("10"),
    transfer_c_per_kwh=Decimal("3.5"),
    monthly_fees_eur=Decimal("3.90"),
)


def series_of(spot_eur_per_mwh: Sequence[int]) -> PriceSeries:
    t0 = START.astimezone(UTC)
    return PriceSeries(
        PricePoint(start=t0 + i * QUARTER, end=t0 + (i + 1) * QUARTER, spot_eur_per_mwh=Decimal(v))
        for i, v in enumerate(spot_eur_per_mwh)
    )


def kwh(*values: str) -> list[Decimal]:
    return [Decimal(v) for v in values]


# --- usage -------------------------------------------------------------------


def test_flat_usage_spreads_the_total_evenly() -> None:
    usage = flat_usage(series_of([50] * 96), Decimal("24"))
    assert len(usage) == 96
    assert set(usage) == {Decimal("0.25")}


def test_usage_must_match_the_number_of_periods() -> None:
    with pytest.raises(ValueError, match="periods"):
        compare_contracts(series_of([50] * 4), kwh("1", "1"), SPOT, FIXED)


def test_usage_must_not_be_negative() -> None:
    with pytest.raises(ValueError, match="negative"):
        compare_contracts(series_of([50] * 2), kwh("1", "-1"), SPOT, FIXED)


def test_usage_must_not_be_all_zero() -> None:
    with pytest.raises(ValueError, match="zero"):
        compare_contracts(series_of([50] * 2), kwh("0", "0"), SPOT, FIXED)


# --- costs -------------------------------------------------------------------


def test_costs_for_a_simple_case() -> None:
    # 100 EUR/MWh all day; 1 kWh in each of 4 quarter-hours = 4 kWh.
    # Spot:  12.55 + 0.49 + 3.5 + 2.917875 = 19.457875 c/kWh -> 4 x 19.457875 / 100 EUR
    # Fixed: 10    + 3.5  + 2.917875       = 16.417875 c/kWh -> 4 x 16.417875 / 100 EUR
    result = compare_contracts(series_of([100] * 4), kwh("1", "1", "1", "1"), SPOT, FIXED)
    assert result.total_kwh == Decimal("4")
    assert result.spot.energy_eur == Decimal("0.778315")
    assert result.fixed.energy_eur == Decimal("0.656715")
    assert result.spot.average_c_per_kwh == Decimal("19.457875")
    assert result.fixed.average_c_per_kwh == Decimal("16.417875")
    assert result.cheaper == "fixed"
    assert result.saving_eur == Decimal("0.1216")


def test_fees_are_added_for_the_given_number_of_months() -> None:
    result = compare_contracts(
        series_of([100] * 4), kwh("1", "1", "1", "1"), SPOT, FIXED, fee_months=Decimal("1")
    )
    assert result.spot.fees_eur == Decimal("4.50")
    assert result.fixed.fees_eur == Decimal("3.90")
    assert result.spot.total_eur == result.spot.energy_eur + Decimal("4.50")


def test_fees_are_left_out_by_default() -> None:
    result = compare_contracts(series_of([100] * 4), kwh("1", "1", "1", "1"), SPOT, FIXED)
    assert result.spot.fees_eur == Decimal("0")


def test_on_spot_the_timing_of_use_changes_the_cost() -> None:
    prices = series_of([200, 200, 0, 0])  # expensive first half, free second half
    early = compare_contracts(prices, kwh("2", "2", "0", "0"), SPOT, FIXED)
    late = compare_contracts(prices, kwh("0", "0", "2", "2"), SPOT, FIXED)
    assert late.spot.total_eur < early.spot.total_eur  # same 4 kWh, cheaper when shifted
    assert late.fixed.total_eur == early.fixed.total_eur  # fixed doesn't care when
    assert early.cheaper == "fixed"
    assert late.cheaper == "spot"


def test_break_even_fixed_price_makes_both_contracts_cost_the_same() -> None:
    prices = series_of([30, 80, 150, 10])
    usage = kwh("0.5", "1.5", "2", "1")
    result = compare_contracts(prices, usage, SPOT, FIXED, fee_months=Decimal("1"))
    equivalent = FixedContract(
        energy_c_per_kwh=result.break_even_fixed_c_per_kwh,
        transfer_c_per_kwh=FIXED.transfer_c_per_kwh,
        monthly_fees_eur=FIXED.monthly_fees_eur,
    )
    again = compare_contracts(prices, usage, SPOT, equivalent, fee_months=Decimal("1"))
    assert again.fixed.total_eur == pytest.approx(again.spot.total_eur, abs=Decimal("1e-9"))
    assert again.cheaper == "same" or abs(again.saving_eur) < Decimal("1e-9")
