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
    source = SpotHintaSource(
        base_url=settings.spot_hinta_base_url,
        timeout_seconds=settings.request_timeout_seconds,
        cache_for=settings.cache_for,
    )
    with source:  # closes the HTTP connection when the server stops
        build_server(source, settings).run("stdio")
