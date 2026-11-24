"""Tests for the household price breakdown."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from finland_energy_mcp.core.models import PricePoint, PriceSeries
from finland_energy_mcp.core.pricing import breakdown, breakdown_series
from finland_energy_mcp.core.tariff import SpotContract

HELSINKI = ZoneInfo("Europe/Helsinki")
QUARTER = timedelta(minutes=15)

# A typical Helsinki spot contract (example data, consumer prices including VAT).
CONTRACT = SpotContract(
    margin_c_per_kwh=Decimal("0.49"),
    transfer_c_per_kwh=Decimal("3.5"),
    monthly_fees_eur=Decimal("8.90"),
)


def point(start: datetime, eur_per_mwh: str) -> PricePoint:
    return PricePoint(start=start, end=start + QUARTER, spot_eur_per_mwh=Decimal(eur_per_mwh))


def test_breakdown_adds_vat_to_spot_and_sums_all_parts() -> None:
    # 100 EUR/MWh = 10 c/kWh excl. VAT -> 12.55 incl. 25.5 % VAT.
    b = breakdown(point(datetime(2026, 11, 24, 18, 0, tzinfo=HELSINKI), "100"), CONTRACT)
    assert b.spot_c_per_kwh == Decimal("12.55")
    assert b.margin_c_per_kwh == Decimal("0.49")
    assert b.transfer_c_per_kwh == Decimal("3.5")
    assert b.electricity_tax_c_per_kwh == Decimal("2.917875")
    assert b.total_c_per_kwh == Decimal("19.457875")  # 12.55 + 0.49 + 3.5 + 2.917875


def test_total_is_always_the_sum_of_its_parts() -> None:
    b = breakdown(point(datetime(2026, 11, 24, 3, 0, tzinfo=HELSINKI), "37.21"), CONTRACT)
    parts = (
        b.spot_c_per_kwh + b.margin_c_per_kwh + b.transfer_c_per_kwh + b.electricity_tax_c_per_kwh
    )
    assert b.total_c_per_kwh == parts


@pytest.mark.parametrize(
    ("start", "tax_incl_vat"),
    [
        # Last quarter-hour of 31 March 2026 in Helsinki: old tax.
        (datetime(2026, 3, 31, 23, 45, tzinfo=HELSINKI), Decimal("2.827515")),
        # Same instant as 1 April 00:00 Helsinki, but given in UTC (summer time, UTC+3): new tax.
        (datetime(2026, 3, 31, 21, 0, tzinfo=UTC), Decimal("2.917875")),
    ],
)
def test_rates_follow_the_finnish_local_date(start: datetime, tax_incl_vat: Decimal) -> None:
    assert breakdown(point(start, "50"), CONTRACT).electricity_tax_c_per_kwh == tax_incl_vat


def test_negative_spot_price_gets_no_vat_by_default() -> None:
    # -20 EUR/MWh = -2 c/kWh. Common Finnish practice: no VAT added to a negative price.
    b = breakdown(point(datetime(2026, 11, 24, 3, 0, tzinfo=HELSINKI), "-20"), CONTRACT)
    assert b.spot_c_per_kwh == Decimal("-2")


def test_negative_spot_price_with_vat_when_the_contract_says_so() -> None:
    b = breakdown(
        point(datetime(2026, 11, 24, 3, 0, tzinfo=HELSINKI), "-20"),
        CONTRACT,
        vat_on_negative=True,
    )
    assert b.spot_c_per_kwh == Decimal("-2.51")


def test_breakdown_keeps_the_period_times() -> None:
    start = datetime(2026, 11, 24, 18, 0, tzinfo=HELSINKI)
    b = breakdown(point(start, "100"), CONTRACT)
    assert (b.start, b.end) == (start, start + QUARTER)


def test_breakdown_series_prices_every_period_in_order() -> None:
    t0 = datetime(2026, 11, 24, 0, 0, tzinfo=HELSINKI)
    series = PriceSeries([point(t0 + i * QUARTER, str(10 * i)) for i in range(4)])
    result = breakdown_series(series, CONTRACT)
    assert [b.start for b in result] == [p.start for p in series]
    assert result[0].total_c_per_kwh < result[3].total_c_per_kwh
