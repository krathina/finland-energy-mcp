"""Tests for turning a spot-hinta.fi response into a PriceSeries."""

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from finland_energy_mcp.sources.errors import SourceFormatError
from finland_energy_mcp.sources.spot_hinta import parse_spot_hinta

HELSINKI = ZoneInfo("Europe/Helsinki")
FIXTURE = Path(__file__).parent / "fixtures" / "spot_hinta_today_and_day_forward_2026-11-24.json"


def as_text(*rows: tuple[str, str]) -> str:
    """JSON text like the API's: one object per (DateTime, PriceNoTax) row, prices as numbers."""
    items = ", ".join(
        f'{{"Rank": 1, "DateTime": "{when}", "PriceNoTax": {price}, "PriceWithTax": {price}}}'
        for when, price in rows
    )
    return f"[{items}]"


# --- the real saved response -------------------------------------------------


def test_parses_the_real_response() -> None:
    series = parse_spot_hinta(FIXTURE.read_text())
    assert len(series) == 192  # today + tomorrow, 96 quarter-hours each
    assert series.start == datetime(2026, 11, 24, 0, 0, tzinfo=HELSINKI)
    assert series.end == datetime(2026, 11, 26, 0, 0, tzinfo=HELSINKI)
    assert series[0].duration == timedelta(minutes=15)


def test_converts_eur_per_kwh_without_vat_to_eur_per_mwh_exactly() -> None:
    series = parse_spot_hinta(FIXTURE.read_text())
    # First entry in the file: "PriceNoTax": 0.01706 EUR/kWh = 17.06 EUR/MWh (no float rounding).
    assert series[0].spot_eur_per_mwh == Decimal("17.06")
    assert series[-1].spot_eur_per_mwh == Decimal("69.09")


# --- small hand-made inputs ----------------------------------------------------


def test_sorts_entries_by_time() -> None:
    text = as_text(
        ("2026-11-24T00:15:00+02:00", "0.02"),
        ("2026-11-24T00:00:00+02:00", "0.01"),
    )
    series = parse_spot_hinta(text)
    assert [p.spot_eur_per_mwh for p in series] == [Decimal("10"), Decimal("20")]


def test_keeps_negative_prices() -> None:
    series = parse_spot_hinta(as_text(("2026-11-24T03:00:00+02:00", "-0.00123")))
    assert series[0].spot_eur_per_mwh == Decimal("-1.23")


def test_handles_the_spring_clock_change() -> None:
    # 29 March 2026: 02:45 (+02:00) is followed by 04:00 (+03:00), 15 real minutes later.
    series = parse_spot_hinta(
        as_text(
            ("2026-03-29T02:45:00+02:00", "0.01"),
            ("2026-03-29T04:00:00+03:00", "0.01"),
        )
    )
    assert len(series) == 2
    assert series.end - series.start == timedelta(minutes=30)


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("not json", "JSON"),
        ('{"prices": []}', "list"),
        ("[]", "empty"),
        ('[{"DateTime": "2026-11-24T00:00:00+02:00"}]', "PriceNoTax"),
        ('[{"DateTime": "yesterday", "PriceNoTax": 0.01}]', "DateTime"),
        ('[{"DateTime": "2026-11-24T00:00:00", "PriceNoTax": 0.01}]', "timezone"),
        ('[{"DateTime": "2026-11-24T00:00:00+02:00", "PriceNoTax": "cheap"}]', "PriceNoTax"),
    ],
)
def test_rejects_unexpected_data_with_a_clear_error(text: str, reason: str) -> None:
    with pytest.raises(SourceFormatError, match=reason):
        parse_spot_hinta(text)


def test_rejects_gaps_in_the_data() -> None:
    text = as_text(
        ("2026-11-24T00:00:00+02:00", "0.01"),
        ("2026-11-24T00:30:00+02:00", "0.01"),  # 00:15 missing
        ("2026-11-24T00:45:00+02:00", "0.01"),
    )
    with pytest.raises(SourceFormatError, match="gap"):
        parse_spot_hinta(text)
