"""Smoke test: the installed command points at the MCP server's entry point."""

import finland_energy_mcp
from finland_energy_mcp.server import main


def test_package_entry_point_is_the_server() -> None:
    assert finland_energy_mcp.main is main
