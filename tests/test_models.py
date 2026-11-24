"""Tests for the market price data types."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from finland_energy_mcp.core.models import PricePoint, PriceSeries, eur_per_mwh_to_c_per_kwh

HELSINKI = ZoneInfo("Europe/Helsinki")
QUARTER = timedelta(minutes=15)


def point(start: datetime, eur_per_mwh: str = "50") -> PricePoint:
    """Test helper: a 15-minute price point starting at `start`."""
    return PricePoint(start=start, end=start + QUARTER, spot_eur_per_mwh=Decimal(eur_per_mwh))


# --- unit conversion -------------------------------------------------------


@pytest.mark.parametrize(
    ("eur_per_mwh", "c_per_kwh"),
    [("100", "10"), ("0", "0"), ("12.34", "1.234"), ("-5", "-0.5")],
)
def test_converts_eur_per_mwh_to_cents_per_kwh(eur_per_mwh: str, c_per_kwh: str) -> None:
    assert eur_per_mwh_to_c_per_kwh(Decimal(eur_per_mwh)) == Decimal(c_per_kwh)


# --- PricePoint --------------------------------------------------------------


def test_price_point_knows_its_duration_and_price_in_cents() -> None:
    p = point(datetime(2026, 11, 24, 18, 0, tzinfo=HELSINKI), "120.5")
    assert p.duration == QUARTER
    assert p.spot_c_per_kwh == Decimal("12.05")


def test_price_point_rejects_times_without_a_timezone() -> None:
    naive = datetime(2026, 11, 24, 18, 0)  # no tzinfo: ambiguous, a classic bug source
    with pytest.raises(ValueError, match="timezone"):
        PricePoint(start=naive, end=naive + QUARTER, spot_eur_per_mwh=Decimal("1"))


def test_price_point_duration_is_real_time_across_the_spring_clock_change() -> None:
    # 29 March 2026 in Finland: clocks jump from 03:00 to 04:00.
    # 02:45 -> 04:00 local looks like 1 h 15 min on the wall, but only 15 minutes pass.
    p = PricePoint(
        start=datetime(2026, 3, 29, 2, 45, tzinfo=HELSINKI),
        end=datetime(2026, 3, 29, 4, 0, tzinfo=HELSINKI),
        spot_eur_per_mwh=Decimal("1"),
    )
    assert p.duration == QUARTER


def test_price_point_stores_times_in_utc() -> None:
    p = point(datetime(2026, 11, 24, 18, 0, tzinfo=HELSINKI))
    assert p.start == datetime(2026, 11, 24, 16, 0, tzinfo=UTC)  # same instant
    assert p.start.tzinfo is UTC


def test_price_point_end_must_be_after_start() -> None:
    t = datetime(2026, 11, 24, 18, 0, tzinfo=HELSINKI)
    with pytest.raises(ValueError, match="after"):
        PricePoint(start=t, end=t, spot_eur_per_mwh=Decimal("1"))


def test_price_point_is_immutable() -> None:
    p = point(datetime(2026, 11, 24, 18, 0, tzinfo=HELSINKI))
    with pytest.raises(AttributeError):
        p.spot_eur_per_mwh = Decimal("999")  # type: ignore[misc]


# --- PriceSeries -------------------------------------------------------------


def test_series_accepts_contiguous_points() -> None:
    t0 = datetime(2026, 11, 24, 0, 0, tzinfo=HELSINKI)
    series = PriceSeries([point(t0 + i * QUARTER) for i in range(96)])  # one normal day
    assert len(series) == 96
    assert series.start == t0
    assert series.end == t0 + timedelta(days=1)


def test_series_rejects_a_gap() -> None:
    t0 = datetime(2026, 11, 24, 0, 0, tzinfo=HELSINKI)
    with pytest.raises(ValueError, match="gap"):
        PriceSeries([point(t0), point(t0 + 2 * QUARTER)])


def test_series_rejects_overlap_or_wrong_order() -> None:
    t0 = datetime(2026, 11, 24, 0, 0, tzinfo=HELSINKI)
    with pytest.raises(ValueError, match="gap or overlap"):
        PriceSeries([point(t0 + QUARTER), point(t0)])


def test_series_must_not_be_empty() -> None:
    with pytest.raises(ValueError, match="empty"):
        PriceSeries([])
