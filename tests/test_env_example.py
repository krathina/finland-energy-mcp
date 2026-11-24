"""Keeps .env.example in sync with the settings the code actually reads."""

import re
from pathlib import Path

from finland_energy_mcp.server.settings import Settings

ROOT = Path(__file__).parent.parent
SETTINGS_CODE = (ROOT / "src" / "finland_energy_mcp" / "server" / "settings.py").read_text()
EXAMPLE = (ROOT / ".env.example").read_text()


def variables_read_by_code() -> set[str]:
    """Every FINLAND_ENERGY_<KEY> the code reads: from_env passes each KEY as a string literal."""
    from_env = SETTINGS_CODE[SETTINGS_CODE.index("def from_env") : SETTINGS_CODE.index("# ---")]
    return {f"FINLAND_ENERGY_{key}" for key in re.findall(r'env, "([A-Z_]+)"', from_env)}


def variables_in_example() -> dict[str, str]:
    """NAME=value lines (comments and blank lines skipped)."""
    pairs = (line.split("=", 1) for line in EXAMPLE.splitlines() if re.match(r"^[A-Z_]+=", line))
    return {name: value for name, value in pairs}


def test_every_setting_is_documented_and_nothing_extra() -> None:
    assert variables_read_by_code() == set(variables_in_example())


def test_the_example_values_are_the_real_defaults() -> None:
    assert Settings.from_env(variables_in_example()) == Settings()
