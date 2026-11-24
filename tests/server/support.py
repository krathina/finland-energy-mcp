"""Test helpers for the MCP server: saved real prices, a fake price source, a fixed clock."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from mcp import Client

from finland_energy_mcp.core.models import PriceSeries
from finland_energy_mcp.server.app import build_server
from finland_energy_mcp.server.settings import Settings
from finland_energy_mcp.sources.errors import PriceSourceError
from finland_energy_mcp.sources.spot_hinta import parse_spot_hinta

HELSINKI = ZoneInfo("Europe/Helsinki")
FIXTURE = (
    Path(__file__).parent.parent / "fixtures" / "spot_hinta_today_and_day_forward_2026-11-24.json"
)
SAVED = parse_spot_hinta(FIXTURE.read_text())  # 24 + 25 Nov 2026, 15-minute prices
EVENING = datetime(2026, 11, 24, 18, 5, tzinfo=HELSINKI)


class FakeSource:
    """A PriceSource that returns given prices, or raises a given error."""

    def __init__(self, prices: PriceSeries | None = SAVED, error: PriceSourceError | None = None):
        self._prices = prices
        self._error = error

    @property
    def name(self) -> str:
        return "fake source"

    def latest_prices(self) -> PriceSeries:
        if self._error is not None:
            raise self._error
        assert self._prices is not None
        return self._prices


def client_for(source: FakeSource, now: datetime = EVENING) -> Client:
    """An in-memory MCP client connected to a server built with this source and clock."""
    return Client(build_server(source, Settings(), clock=lambda: now))
