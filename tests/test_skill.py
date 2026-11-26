"""Guard tests for skills/finland-electricity/SKILL.md: it must match the real server.

A skill is plain text, so nothing else notices when a tool or parameter is renamed. These tests do.
"""

import re
from pathlib import Path
from typing import Any

import pytest

from tests.server.support import FakeSource, client_for

ROOT = Path(__file__).parent.parent
SKILL_DIR = ROOT / "skills" / "finland-electricity"
SKILL = (SKILL_DIR / "SKILL.md").read_text()
README = (ROOT / "README.md").read_text()


def frontmatter() -> dict[str, str]:
    """The `name: value` lines between the two `---` lines at the top."""
    match = re.match(r"---\n(.*?)\n---\n", SKILL, re.DOTALL)
    assert match, "SKILL.md must start with a --- frontmatter block"
    pairs = (line.split(":", 1) for line in match.group(1).splitlines())
    return {key.strip(): value.strip() for key, value in pairs}


def test_name_follows_the_skill_rules_and_matches_the_folder() -> None:
    name = frontmatter()["name"]
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) and len(name) <= 64
    assert name == SKILL_DIR.name


def test_description_says_when_to_use_it_and_fits_the_limit() -> None:
    description = frontmatter()["description"]
    assert 0 < len(description) <= 1024
    assert "Use when" in description


def property_names(schema: Any) -> set[str]:
    """Every property name anywhere in a JSON schema (nested objects and $defs too)."""
    names: set[str] = set()
    if isinstance(schema, dict):
        names |= set(schema.get("properties", {}))
        for value in schema.values():
            names |= property_names(value)
    elif isinstance(schema, list):
        for item in schema:
            names |= property_names(item)
    return names


@pytest.mark.anyio
async def test_every_tool_and_field_the_skill_names_exists() -> None:
    async with client_for(FakeSource()) as client:
        tools = (await client.list_tools()).tools
    known = {tool.name for tool in tools}
    for tool in tools:
        known |= property_names(tool.input_schema) | property_names(tool.output_schema)
    # `snake_case` words in backticks are tool, parameter or field names
    named = set(re.findall(r"`([a-z]+(?:_[a-z]+)+)`", SKILL))
    assert named, "expected the skill to name tools and parameters"
    assert named - known == set(), "SKILL.md names things the server doesn't have"


def test_install_command_is_the_same_as_in_the_readme() -> None:
    command = "claude mcp add finland-energy -s user -- uvx finland-energy-mcp"
    assert command in SKILL
    assert command in README


def test_typical_durations_are_whole_quarter_hours() -> None:
    # Table rows like "| Sauna ... | 120 | 8–12 | ... |" or "| ... | 240–300 | ..."
    rows = [line for line in SKILL.splitlines() if line.startswith("| ") and "kWh" not in line]
    durations = [
        int(number)
        for row in rows
        for cell in row.split("|")[2:3]
        for number in re.findall(r"\d+", cell)
    ]
    assert durations, "expected durations in the jobs table"
    assert all(minutes % 15 == 0 for minutes in durations)
