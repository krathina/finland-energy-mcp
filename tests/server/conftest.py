"""Shared fixtures for the MCP server tests.

conftest.py is where pytest finds fixtures automatically (like JUnit @BeforeEach helpers).
"""

from collections.abc import AsyncIterator

import pytest
from mcp import Client

from tests.server.support import FakeSource, client_for


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"  # run async tests on asyncio (the default Python event loop)


@pytest.fixture
async def client() -> AsyncIterator[Client]:
    async with client_for(FakeSource()) as c:
        yield c
