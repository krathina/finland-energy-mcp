"""Contract test against the real spot-hinta.fi API. One request; run with: uv run pytest -m live

Checks the shape of real data, not exact prices (those change every day).
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from finland_energy_mcp.sources.spot_hinta import SpotHintaSource

pytestmark = pytest.mark.live  # applies the "live" tag to every test in this file


def test_real_api_returns_todays_prices_in_the_expected_shape() -> None:
    with SpotHintaSource() as source:
        prices = source.latest_prices()

    now = datetime.now(UTC)
    assert prices.start <= now < prices.end, "today's prices should cover the current moment"
    assert len(prices) in (92, 96, 100, 188, 192, 196, 200), "today (+ tomorrow) in quarter-hours"
    assert all(p.duration == timedelta(minutes=15) for p in prices)
    start_local = prices.start.astimezone(ZoneInfo("Europe/Helsinki"))
    assert (start_local.hour, start_local.minute) == (0, 0), "starts at Finnish midnight"
    # Market limits are about -500 and +4000 EUR/MWh; anything outside means a unit change.
    assert all(Decimal(-500) <= p.spot_eur_per_mwh <= Decimal(4000) for p in prices)
