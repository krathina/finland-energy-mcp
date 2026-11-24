"""Tests for find_cheapest_time, through a real MCP client (in memory)."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from mcp import Client
from mcp.types import CallToolResult, TextContent

from finland_energy_mcp.core.pricing import breakdown_series
from finland_energy_mcp.server.settings import Settings
from tests.server.support import EVENING, HELSINKI, SAVED

pytestmark = pytest.mark.anyio

QUARTER = timedelta(minutes=15)


async def call(client: Client, args: dict[str, Any]) -> CallToolResult:
    return await client.call_tool("find_cheapest_time", args)


def ok(result: CallToolResult) -> dict[str, Any]:
    assert not result.is_error, result.content
    assert isinstance(result.structured_content, dict)
    return result.structured_content


def text_of(result: CallToolResult) -> str:
    first = result.content[0]
    assert isinstance(first, TextContent)
    return first.text


def brute_force_cheapest_start(
    earliest: datetime, finish_by: datetime, duration: timedelta
) -> datetime:
    """Independent oracle: try every start, average its quarter-hours, keep the lowest."""
    prices = breakdown_series(SAVED, Settings().contract)
    best: tuple[Decimal, datetime] | None = None
    start = earliest
    while start + duration <= finish_by:
        window = [p.total_c_per_kwh for p in prices if start <= p.start < start + duration]
        average = sum(window, Decimal(0)) / len(window)
        if best is None or average < best[0]:
            best = (average, start)
        start += QUARTER
    assert best is not None
    return best[1]


# --- finding the window -------------------------------------------------------------


async def test_finds_the_same_window_as_a_brute_force_search(client: Client) -> None:
    out = ok(await call(client, {"duration_minutes": 120}))
    first_full_quarter = datetime(2026, 11, 24, 18, 15, tzinfo=HELSINKI)  # now is 18:05
    expected = brute_force_cheapest_start(first_full_quarter, SAVED.end, timedelta(minutes=120))
    assert datetime.fromisoformat(out["start"]) == expected
    assert datetime.fromisoformat(out["end"]) == expected + timedelta(minutes=120)
    assert out["duration_minutes"] == 120


async def test_never_starts_in_the_past(client: Client) -> None:
    out = ok(await call(client, {"duration_minutes": 60, "earliest_start": "2026-11-24T06:00"}))
    assert datetime.fromisoformat(out["start"]) >= EVENING


async def test_respects_earliest_start_and_finish_by_in_finnish_time(client: Client) -> None:
    out = ok(
        await call(
            client,
            {
                "duration_minutes": 60,
                "earliest_start": "2026-11-25T07:00",  # no offset: read as Finnish time
                "finish_by": "2026-11-25T12:00",
            },
        )
    )
    start = datetime.fromisoformat(out["start"])
    end = datetime.fromisoformat(out["end"])
    assert start >= datetime(2026, 11, 25, 7, 0, tzinfo=HELSINKI)
    assert end <= datetime(2026, 11, 25, 12, 0, tzinfo=HELSINKI)
    assert start == brute_force_cheapest_start(
        datetime(2026, 11, 25, 7, 0, tzinfo=HELSINKI),
        datetime(2026, 11, 25, 12, 0, tzinfo=HELSINKI),
        timedelta(minutes=60),
    )


# --- cost and the "start now" comparison ----------------------------------------------


async def test_gives_the_cost_when_energy_is_known(client: Client) -> None:
    out = ok(await call(client, {"duration_minutes": 120, "energy_kwh": 9}))
    assert out["cost_eur"] == pytest.approx(out["average_total_c_per_kwh"] * 9 / 100, abs=0.01)


async def test_leaves_cost_out_when_energy_is_unknown(client: Client) -> None:
    out = ok(await call(client, {"duration_minutes": 120}))
    assert out["cost_eur"] is None


async def test_compares_with_starting_now(client: Client) -> None:
    out = ok(await call(client, {"duration_minutes": 120, "energy_kwh": 9}))
    now = out["if_started_now"]
    assert datetime.fromisoformat(now["start"]) == datetime(2026, 11, 24, 18, 0, tzinfo=HELSINKI)
    assert now["average_total_c_per_kwh"] >= out["average_total_c_per_kwh"]
    assert now["extra_cost_eur"] == pytest.approx(now["cost_eur"] - out["cost_eur"], abs=0.01)
    assert now["extra_cost_eur"] >= 0


# --- clear refusals ----------------------------------------------------------------------


async def test_explains_when_no_window_fits(client: Client) -> None:
    result = await call(client, {"duration_minutes": 60, "finish_by": "2026-11-24T18:30"})
    assert result.is_error
    assert "No 60-minute window" in text_of(result)


async def test_explains_when_the_job_needs_prices_not_known_yet(client: Client) -> None:
    result = await call(client, {"duration_minutes": 60, "earliest_start": "2026-11-26T08:00"})
    assert result.is_error
    assert "known until" in text_of(result)


async def test_finish_by_must_be_after_earliest_start(client: Client) -> None:
    result = await call(
        client,
        {
            "duration_minutes": 60,
            "earliest_start": "2026-11-25T10:00",
            "finish_by": "2026-11-25T09:00",
        },
    )
    assert result.is_error
    assert "after" in text_of(result)


@pytest.mark.parametrize("minutes", [0, 50, 1500])
async def test_rejects_durations_outside_the_schema(client: Client, minutes: int) -> None:
    result = await call(client, {"duration_minutes": minutes})
    assert result.is_error
    assert "duration_minutes" in text_of(result)  # rejected by validation, not for another reason


async def test_schema_tells_the_ai_about_the_15_minute_steps(client: Client) -> None:
    tools = {t.name: t for t in (await client.list_tools()).tools}
    duration = tools["find_cheapest_time"].input_schema["properties"]["duration_minutes"]
    assert duration["multipleOf"] == 15
    assert duration["minimum"] == 15
