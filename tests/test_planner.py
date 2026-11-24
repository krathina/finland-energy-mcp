"""Tests for finding the cheapest time to run something."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from finland_energy_mcp.core.models import PricePoint, PriceSeries
from finland_energy_mcp.core.planner import cheapest_window
from finland_energy_mcp.core.pricing import PriceBreakdown, breakdown_series
from finland_energy_mcp.core.tariff import SpotContract

HELSINKI = ZoneInfo("Europe/Helsinki")
QUARTER = timedelta(minutes=15)
HOUR = timedelta(hours=1)

# No margin, transfer fee or fees, so totals are easy to reason about: spot x 1.255 + tax.
PLAIN = SpotContract(
    margin_c_per_kwh=Decimal("0"),
    transfer_c_per_kwh=Decimal("0"),
    monthly_fees_eur=Decimal("0"),
)


def prices_from(start: datetime, spot_eur_per_mwh: Sequence[int]) -> list[PriceBreakdown]:
    """Household prices for consecutive quarter-hours, built in real (UTC) time."""
    t0 = start.astimezone(UTC)
    series = PriceSeries(
        PricePoint(
            start=t0 + i * QUARTER,
            end=t0 + (i + 1) * QUARTER,
            spot_eur_per_mwh=Decimal(v),
        )
        for i, v in enumerate(spot_eur_per_mwh)
    )
    return breakdown_series(series, PLAIN)


MIDNIGHT = datetime(2026, 11, 24, 0, 0, tzinfo=HELSINKI)
# 6 hours: expensive, then a cheap hour from 02:00 to 03:00, then expensive again.
NIGHT = prices_from(MIDNIGHT, [100] * 8 + [10] * 4 + [100] * 12)


def test_finds_the_cheapest_hour() -> None:
    w = cheapest_window(NIGHT, HOUR)
    assert w.start == MIDNIGHT + 2 * HOUR
    assert w.end == MIDNIGHT + 3 * HOUR


def test_respects_the_deadline() -> None:
    # Must finish by 02:30, so the cheap hour (02:00-03:00) doesn't fit completely.
    w = cheapest_window(NIGHT, HOUR, deadline=MIDNIGHT + timedelta(hours=2, minutes=30))
    assert w.end <= MIDNIGHT + timedelta(hours=2, minutes=30)
    assert w.start == MIDNIGHT + timedelta(hours=1, minutes=30)  # half cheap, half expensive


def test_respects_the_earliest_start() -> None:
    w = cheapest_window(NIGHT, HOUR, earliest=MIDNIGHT + 3 * HOUR)
    assert w.start >= MIDNIGHT + 3 * HOUR


def test_reports_average_price_and_cost() -> None:
    w = cheapest_window(NIGHT, HOUR, energy_kwh=Decimal("2"))
    # 10 EUR/MWh = 1 c -> 1.255 c with VAT, + 2.917875 c tax = 4.172875 c/kWh
    assert w.average_c_per_kwh == Decimal("4.172875")
    assert w.cost_eur == Decimal("0.0834575")  # 2 kWh x 4.172875 c / 100


def test_cost_is_left_out_when_energy_is_not_given() -> None:
    assert cheapest_window(NIGHT, HOUR).cost_eur is None


def test_ties_go_to_the_earliest_window() -> None:
    flat = prices_from(MIDNIGHT, [50] * 8)
    assert cheapest_window(flat, HOUR).start == MIDNIGHT


def test_refuses_when_no_window_fits() -> None:
    with pytest.raises(ValueError, match="no window"):
        cheapest_window(NIGHT, timedelta(hours=7))


def test_refuses_a_duration_that_is_not_whole_periods() -> None:
    with pytest.raises(ValueError, match="multiple"):
        cheapest_window(NIGHT, timedelta(minutes=50))


# --- clock changes -----------------------------------------------------------


def test_spring_forward_day_has_92_periods_and_windows_use_real_time() -> None:
    # 29 March 2026: 03:00 -> 04:00, so the Finnish day lasts 23 hours = 92 quarter-hours.
    day_start = datetime(2026, 3, 29, 0, 0, tzinfo=HELSINKI)
    day_end = datetime(2026, 3, 30, 0, 0, tzinfo=HELSINKI)
    n = int((day_end.astimezone(UTC) - day_start.astimezone(UTC)) / QUARTER)
    assert n == 92
    # Cheapest 2 hours start at 02:00 local (index 8).
    prices = prices_from(day_start, [100] * 8 + [1] * 8 + [100] * (n - 16))
    w = cheapest_window(prices, 2 * HOUR)
    assert w.start == datetime(2026, 3, 29, 2, 0, tzinfo=HELSINKI)
    assert w.end == datetime(2026, 3, 29, 5, 0, tzinfo=HELSINKI)  # 05:00 on the wall...
    assert w.end - w.start == 2 * HOUR  # ...but exactly 2 real hours


def test_fall_back_day_has_100_periods() -> None:
    # 25 October 2026: 04:00 -> 03:00, so the Finnish day lasts 25 hours = 100 quarter-hours.
    day_start = datetime(2026, 10, 25, 0, 0, tzinfo=HELSINKI)
    day_end = datetime(2026, 10, 26, 0, 0, tzinfo=HELSINKI)
    n = int((day_end.astimezone(UTC) - day_start.astimezone(UTC)) / QUARTER)
    assert n == 100
    prices = prices_from(day_start, [100] * (n - 4) + [1] * 4)  # cheapest: last hour of the day
    w = cheapest_window(prices, HOUR)
    assert w.end == day_end
    assert w.end - w.start == HOUR
