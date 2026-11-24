"""Smoke test: proves the tooling works end to end (import the package, run a test)."""

import finland_energy_mcp


def test_package_has_an_entry_point() -> None:
    assert callable(finland_energy_mcp.main)
