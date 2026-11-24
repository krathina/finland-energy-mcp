"""Tests for get_price_now and get_prices, called through a real MCP client (in memory)."""

from datetime import datetime
from typing import Any

import pytest
from mcp import Client
from mcp.types import CallToolResult, TextContent

from finland_energy_mcp.sources.errors import SourceUnavailableError
from tests.server.support import HELSINKI, FakeSource, client_for

pytestmark = pytest.mark.anyio  # every test here is async


async def call(client: Client, tool: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Call a tool that should succeed; return its structured (JSON) answer."""
    result = await client.call_tool(tool, args or {})
    assert not result.is_error, result.content
    assert isinstance(result.structured_content, dict)
    return result.structured_content


def text_of(result: CallToolResult) -> str:
    """The text the AI sees (content can also be images etc., so check it is text)."""
    first = result.content[0]
    assert isinstance(first, TextContent)
    return first.text


# --- discovery: what the AI sees -------------------------------------------------------


async def test_lists_the_tools_with_descriptions_and_read_only_hints(client: Client) -> None:
    tools = {t.name: t for t in (await client.list_tools()).tools}
    assert {"get_price_now", "get_prices"} <= tools.keys()
    for tool in tools.values():
        assert tool.description and len(tool.description) > 40, f"{tool.name} needs a description"
        assert tool.annotations is not None and tool.annotations.read_only_hint


# --- get_price_now ---------------------------------------------------------------------


async def test_price_now_gives_the_household_price_with_its_parts(client: Client) -> None:
    out = await call(client, "get_price_now")
    assert datetime.fromisoformat(out["period_start"]) == datetime(
        2026, 11, 24, 18, 0, tzinfo=HELSINKI
    )
    assert out["price_c_per_kwh"] == {
        "spot": 15.75,  # 125.53 EUR/MWh = 12.553 c, x 1.255 VAT
        "margin": 0.49,
        "transfer": 3.5,
        "electricity_tax": 2.92,
        "total": 22.66,
    }


async def test_price_now_puts_the_price_in_context_of_the_day(client: Client) -> None:
    out = await call(client, "get_price_now")
    day = out["today_c_per_kwh"]
    assert day["min"] < out["price_c_per_kwh"]["total"] < day["max"]


async def test_every_answer_states_its_assumptions(client: Client) -> None:
    out = await call(client, "get_price_now")
    a = out["assumptions"]
    assert a["source"] == "fake source"
    assert a["vat_percent"] == 25.5
    assert a["margin_c_per_kwh"] == 0.49 and a["transfer_c_per_kwh"] == 3.5
    assert "FINLAND_ENERGY_" in a["note"]  # tells the user how to set their own contract


# --- get_prices ------------------------------------------------------------------------


async def test_prices_today_hourly_by_default(client: Client) -> None:
    out = await call(client, "get_prices")
    assert out["day"] == "2026-11-24"
    assert out["resolution"] == "hour"
    assert len(out["periods"]) == 24
    six_pm = out["periods"][18]
    assert datetime.fromisoformat(six_pm["start"]).hour == 18
    assert six_pm["total_c_per_kwh"] == 25.10  # average of the four quarter-hours


async def test_prices_in_15_minute_resolution(client: Client) -> None:
    out = await call(client, "get_prices", {"day": "today", "resolution": "15min"})
    assert len(out["periods"]) == 96


async def test_prices_tomorrow(client: Client) -> None:
    out = await call(client, "get_prices", {"day": "tomorrow"})
    assert out["day"] == "2026-11-25"
    assert len(out["periods"]) == 24


async def test_prices_summary_points_to_cheapest_and_most_expensive(client: Client) -> None:
    out = await call(client, "get_prices")
    totals = [p["total_c_per_kwh"] for p in out["periods"]]
    assert out["summary"]["min_c_per_kwh"] == min(totals)
    assert out["summary"]["max_c_per_kwh"] == max(totals)
    cheapest = next(p for p in out["periods"] if p["total_c_per_kwh"] == min(totals))
    assert out["summary"]["cheapest_start"] == cheapest["start"]


# --- clear errors for the AI ------------------------------------------------------------


async def test_says_clearly_when_tomorrow_is_not_published_yet() -> None:
    morning = datetime(2026, 11, 25, 9, 0, tzinfo=HELSINKI)  # data ends 25 Nov: no 26 Nov yet
    async with client_for(FakeSource(), now=morning) as c:
        result = await c.call_tool("get_prices", {"day": "tomorrow"})
    assert result.is_error
    assert "not published yet" in text_of(result)
    assert "14:00" in text_of(result)


async def test_source_failure_is_explained_not_hidden() -> None:
    down = FakeSource(error=SourceUnavailableError("spot-hinta.fi timed out"))
    async with client_for(down) as c:
        result = await c.call_tool("get_price_now", {})
    assert result.is_error
    assert "timed out" in text_of(result)


async def test_rejects_an_unknown_day() -> None:
    async with client_for(FakeSource()) as c:
        result = await c.call_tool("get_prices", {"day": "yesterday"})
    assert result.is_error
