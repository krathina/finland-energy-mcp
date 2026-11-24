"""MCP server for Finnish household electricity prices.

Run with `uv run finland-energy-mcp`. It speaks MCP over stdio: stdout carries protocol messages
only, so nothing else may print to stdout.
"""

from finland_energy_mcp.server.app import build_server
from finland_energy_mcp.server.settings import Settings
from finland_energy_mcp.sources.spot_hinta import SpotHintaSource


def main() -> None:
    """Start the server with the real price source and settings from the environment."""
    settings = Settings.from_env()
    with SpotHintaSource() as source:  # closes the HTTP connection when the server stops
        build_server(source, settings).run("stdio")
