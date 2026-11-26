"""The MCP server with frozen prices and a frozen clock, for repeatable skill evals.

It serves the real prices saved on 24-25 Nov 2026, moved to today's and tomorrow's dates, with
the clock fixed at 16:30 Finnish time today. Every run sees the same prices at the same clock
times, while the dates still match what the AI assistant believes today is.

Run it like the real server (MCP over stdio): `uv run python evals/frozen_server.py`
"""

import dataclasses
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from finland_energy_mcp.core.models import PriceSeries
from finland_energy_mcp.server.app import build_server
from finland_energy_mcp.server.settings import Settings
from finland_energy_mcp.sources.spot_hinta import parse_spot_hinta

HELSINKI = ZoneInfo("Europe/Helsinki")
FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "tests"
    / "fixtures"
    / "spot_hinta_today_and_day_forward_2026-11-24.json"
)
SAVED_DAY = date(2026, 11, 24)  # the first day in the fixture
NOW = time(16, 30)  # tomorrow's prices are already published at this time


class FrozenSource:
    """A PriceSource that always returns the same prices (no network)."""

    def __init__(self, prices: PriceSeries) -> None:
        self._prices = prices

    @property
    def name(self) -> str:
        return "spot-hinta.fi"  # as in real use, so the AI sees nothing test-like

    def latest_prices(self) -> PriceSeries:
        return self._prices


def frozen_prices(today: date) -> PriceSeries:
    """The saved prices, moved by whole days so that the saved first day becomes `today`."""
    if _utc_offset(today) != _utc_offset(SAVED_DAY):
        # Moving winter prices into summer time would shift every price by an hour.
        raise SystemExit(
            f"{today} is in a different UTC offset than {SAVED_DAY}; save a new fixture"
        )
    shift = today - SAVED_DAY
    saved = parse_spot_hinta(FIXTURE.read_text())
    return PriceSeries(
        dataclasses.replace(point, start=point.start + shift, end=point.end + shift)
        for point in saved
    )


def frozen_now(today: date) -> datetime:
    return datetime.combine(today, NOW, HELSINKI)


def _utc_offset(day: date) -> object:
    return datetime.combine(day, time(12), HELSINKI).utcoffset()


def main() -> None:
    today = datetime.now(HELSINKI).date()
    now = frozen_now(today)
    build_server(FrozenSource(frozen_prices(today)), Settings(), clock=lambda: now).run("stdio")


if __name__ == "__main__":
    main()
