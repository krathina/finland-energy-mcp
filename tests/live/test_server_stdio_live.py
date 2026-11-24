"""End to end: start the real server as a subprocess over stdio, like Claude Code does, and ask
it for the current price (one real request to spot-hinta.fi). Run with: uv run pytest -m live
"""

import pytest
from mcp import Client, StdioServerParameters

pytestmark = [pytest.mark.live, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_real_server_over_stdio_answers_price_now() -> None:
    server = StdioServerParameters(command="uv", args=["run", "finland-energy-mcp"])
    async with Client(server) as client:
        names = {t.name for t in (await client.list_tools()).tools}
        assert names == {"get_price_now", "get_prices", "find_cheapest_time"}
        result = await client.call_tool("get_price_now", {})
    assert not result.is_error, result.content
    assert isinstance(result.structured_content, dict)
    assert result.structured_content["assumptions"]["source"] == "spot-hinta.fi"
    assert result.structured_content["breakdown_c_per_kwh"]["total"] > 0
