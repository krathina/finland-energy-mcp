"""Tests for the project's identity, which must come from pyproject.toml (not from code)."""

import tomllib
from pathlib import Path

import pytest
from mcp import Client

from finland_energy_mcp import about
from tests.server.support import FakeSource, client_for

PYPROJECT = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text())


def test_name_version_and_home_page_come_from_pyproject() -> None:
    assert about.name() == PYPROJECT["project"]["name"]
    assert about.version() == PYPROJECT["project"]["version"]
    assert about.home_page() == PYPROJECT["project"]["urls"]["Homepage"]


def test_user_agent_identifies_the_project_without_personal_data() -> None:
    ua = about.user_agent()
    assert ua == f"{about.name()}/{about.version()} (+{about.home_page()})"


@pytest.mark.anyio
async def test_mcp_server_introduces_itself_with_the_same_identity() -> None:
    client: Client = client_for(FakeSource())
    async with client:
        info = client.server_info
    assert info is not None
    assert (info.name, info.version) == (about.name(), about.version())
    assert info.website_url == about.home_page()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
