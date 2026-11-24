"""Every price in a tool's output must say what it is: total, spot, or one component.

Found in real use: a field named only "today_c_per_kwh" (it held totals) made the AI compare
the spot price against total prices. Names are part of the tool's interface to the AI.
"""

from typing import Any

import pytest
from mcp import Client

pytestmark = pytest.mark.anyio

BASIS = ("total", "spot", "margin", "transfer", "electricity_tax", "breakdown")


def price_field_names(schema: dict[str, Any]) -> set[str]:
    """All property names ending in c_per_kwh, anywhere in a JSON schema (incl. its $defs)."""
    names: set[str] = set()
    stack: list[Any] = [schema]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for name in node.get("properties", {}):
                if name.endswith("c_per_kwh"):
                    names.add(name)
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return names


async def test_every_price_field_names_its_basis(client: Client) -> None:
    for tool in (await client.list_tools()).tools:
        assert tool.output_schema is not None, tool.name
        for name in price_field_names(tool.output_schema):
            assert any(b in name for b in BASIS), f"{tool.name}: '{name}' doesn't say what it is"


async def test_the_guard_finds_price_fields_at_all(client: Client) -> None:
    # Make sure the walker really sees nested fields (otherwise the test above proves nothing).
    tools = {t.name: t for t in (await client.list_tools()).tools}
    names = price_field_names(tools["get_prices"].output_schema or {})
    assert "total_c_per_kwh" in names and "margin_c_per_kwh" in names
