"""Tests for giving your own contract (margin, transfer fee) in the tool call itself."""

from typing import Any

import pytest
from mcp import Client
from mcp.types import CallToolResult

pytestmark = pytest.mark.anyio

TOOLS = ["get_price_now", "get_prices", "find_cheapest_time"]
BASE_ARGS: dict[str, dict[str, Any]] = {
    "get_price_now": {},
    "get_prices": {},
    "find_cheapest_time": {"duration_minutes": 60},
}
MINE = {"margin_c_per_kwh": 0.39, "transfer_c_per_kwh": 4.1}


async def call(client: Client, tool: str, extra: dict[str, Any] | None = None) -> CallToolResult:
    return await client.call_tool(tool, {**BASE_ARGS[tool], **(extra or {})})


def ok(result: CallToolResult) -> dict[str, Any]:
    assert not result.is_error, result.content
    assert isinstance(result.structured_content, dict)
    return result.structured_content


@pytest.mark.parametrize("tool", TOOLS)
async def test_every_tool_accepts_the_users_own_contract(client: Client, tool: str) -> None:
    out = ok(await call(client, tool, MINE))
    a = out["assumptions"]
    assert a["margin_c_per_kwh"] == 0.39
    assert a["transfer_c_per_kwh"] == 4.1
    assert a["contract_from"] == "user"


@pytest.mark.parametrize("tool", TOOLS)
async def test_without_values_the_example_defaults_are_used_and_said_so(
    client: Client, tool: str
) -> None:
    a = ok(await call(client, tool))["assumptions"]
    assert a["contract_from"] == "example defaults"
    assert "ask the user" in a["note"].lower()
    # Point the AI at the parameters, not at configuration (a real session got this wrong).
    assert "margin_c_per_kwh" in a["note"] and "no configuration" in a["note"].lower()


async def test_own_contract_changes_the_total_by_exactly_the_difference(client: Client) -> None:
    default = ok(await call(client, "get_price_now"))["price_c_per_kwh"]
    mine = ok(await call(client, "get_price_now", MINE))["price_c_per_kwh"]
    # 0.39 + 4.1 instead of 0.49 + 3.5: +0.5 c/kWh; spot and tax don't change.
    assert mine["spot"] == default["spot"]
    assert mine["electricity_tax"] == default["electricity_tax"]
    assert mine["total"] == pytest.approx(default["total"] + 0.5, abs=0.01)


async def test_only_one_value_given_keeps_the_default_for_the_other(client: Client) -> None:
    a = ok(await call(client, "get_price_now", {"transfer_c_per_kwh": 4.1}))["assumptions"]
    assert a["transfer_c_per_kwh"] == 4.1
    assert a["margin_c_per_kwh"] == 0.49
    assert a["contract_from"] == "user (partly example defaults)"


@pytest.mark.parametrize("bad", [{"margin_c_per_kwh": -1}, {"transfer_c_per_kwh": 500}])
async def test_impossible_values_are_rejected(client: Client, bad: dict[str, float]) -> None:
    assert (await call(client, "get_price_now", bad)).is_error


async def test_the_ai_is_told_to_reuse_the_users_values(client: Client) -> None:
    instructions = client.instructions  # sent by the server when the client connects
    assert instructions is not None
    assert "assumed" in instructions and "every later call" in instructions
    assert "no configuration" in instructions.lower()
    tools = {t.name: t for t in (await client.list_tools()).tools}
    for name in TOOLS:
        margin = tools[name].input_schema["properties"]["margin_c_per_kwh"]
        assert "user" in margin["description"].lower()
