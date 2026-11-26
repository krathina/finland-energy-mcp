"""Skill evals: a real AI assistant (headless Claude Code) answers scenarios using the skill and
the frozen MCP server, and we check what it did. Each scenario runs several times, because the
AI doesn't answer exactly the same way every time; the report shows a pass rate per check.

Uses model credits, so run it on purpose (not in CI):

    uv run python evals/run_skill_evals.py                     # all scenarios, 3 runs each
    uv run python evals/run_skill_evals.py --scenario sauna --runs 1
    uv run python evals/run_skill_evals.py --model haiku       # a smaller model
    uv run python evals/run_skill_evals.py --no-skill          # baseline: same, without the skill
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = ROOT / "skills" / "finland-electricity"
RESULTS = ROOT / "evals" / "results"
HELSINKI = ZoneInfo("Europe/Helsinki")
SERVER = "finland-energy"
TOOLS = ["get_price_now", "get_prices", "find_cheapest_time"]


# --- what happened in one run ------------------------------------------------------------------


@dataclass
class ToolCall:
    name: str  # without the mcp__finland-energy__ prefix
    input: dict[str, Any]
    result: dict[str, Any] | None = None  # the tool's JSON answer, None if it failed


@dataclass
class Transcript:
    skill_used: bool = False
    calls: list[ToolCall] = field(default_factory=list)
    answers: list[str] = field(default_factory=list)  # the assistant's text, one per user turn
    cost_usd: float = 0.0

    def last_call(self, tool: str) -> ToolCall | None:
        return next((c for c in reversed(self.calls) if c.name == tool), None)


def parse_events(lines: list[str]) -> Transcript:
    """Read Claude Code's stream-json events (one JSON object per line)."""
    transcript, by_id, text = Transcript(), {}, []
    for line in lines:
        event = json.loads(line)
        if event["type"] == "assistant":
            for block in event["message"]["content"]:
                if block["type"] == "text":
                    text.append(block["text"])
                elif block["type"] == "tool_use":
                    if block["name"] == "Skill" and block["input"].get("skill") == SKILL_DIR.name:
                        transcript.skill_used = True
                    prefix = f"mcp__{SERVER}__"
                    if block["name"].startswith(prefix):
                        call = ToolCall(block["name"].removeprefix(prefix), block["input"])
                        transcript.calls.append(call)
                        by_id[block["id"]] = call
        elif event["type"] == "user":
            for block in event["message"].get("content", []):
                if isinstance(block, dict) and block.get("tool_use_id") in by_id:
                    by_id[block["tool_use_id"]].result = _json_result(block)
        elif event["type"] == "result":  # end of one user turn
            transcript.answers.append("\n".join(text))
            transcript.cost_usd += event.get("total_cost_usd") or 0.0
            text = []
    return transcript


def _json_result(block: dict[str, Any]) -> dict[str, Any] | None:
    if block.get("is_error"):
        return None
    content = block.get("content") or ""
    raw = content if isinstance(content, str) else "".join(c.get("text", "") for c in content)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


# --- checks: each returns None if fine, or a short reason if not --------------------------------

Check = Callable[[Transcript], str | None]


def skill_used() -> Check:
    return lambda t: None if t.skill_used else "skill not loaded"


def called(tool: str) -> Check:
    return lambda t: None if t.last_call(tool) else f"{tool} not called"


def arg_between(tool: str, key: str, low: float, high: float) -> Check:
    def check(t: Transcript) -> str | None:
        call = t.last_call(tool)
        value = call.input.get(key) if call else None
        if isinstance(value, int | float) and low <= value <= high:
            return None
        return f"{key}={value}, expected {low}-{high}"

    return check


def whole_quarter_hours(tool: str) -> Check:
    def check(t: Transcript) -> str | None:
        call = t.last_call(tool)
        minutes = call.input.get("duration_minutes") if call else None
        return None if isinstance(minutes, int) and minutes % 15 == 0 else f"duration={minutes}"

    return check


def finishes_at(tool: str, days_from_today: int, hour: int) -> Check:
    def check(t: Transcript) -> str | None:
        call = t.last_call(tool)
        raw = call.input.get("finish_by") if call else None
        expected = datetime.combine(
            today() + timedelta(days=days_from_today), datetime.min.time(), HELSINKI
        ).replace(hour=hour)
        return None if raw and finnish(raw) == expected else f"finish_by={raw}, expected {expected}"

    return check


def answer_gives_start_time(tool: str) -> Check:
    """The final answer mentions the start time the tool returned (20:00 or 20.00)."""

    def check(t: Transcript) -> str | None:
        call = t.last_call(tool)
        if not call or not call.result:
            return "no tool result"
        start = finnish(call.result["start"])
        pattern = rf"\b{start.hour:02d}[:.]{start.minute:02d}\b"
        return None if re.search(pattern, t.answers[-1]) else f"answer lacks {start:%H:%M}"

    return check


def every_call_has(key: str, value: float) -> Check:
    def check(t: Transcript) -> str | None:
        wrong = [c.name for c in t.calls if c.input.get(key) != value]
        return None if t.calls and not wrong else f"{key} != {value} in {wrong or 'no calls'}"

    return check


def last_answer_lacks(pattern: str) -> Check:
    def check(t: Transcript) -> str | None:
        found = re.search(pattern, t.answers[-1], re.IGNORECASE) if t.answers else None
        return f"answer says {found.group(0)!r}" if found else None

    return check


def answer_mentions(pattern: str) -> Check:
    def check(t: Transcript) -> str | None:
        text = "\n".join(t.answers)
        return None if re.search(pattern, text, re.IGNORECASE) else f"no match for {pattern!r}"

    return check


def today() -> date:
    return datetime.now(HELSINKI).date()


def finnish(raw: str) -> datetime:
    """A time from a tool call or result; without an offset it is Finnish time."""
    moment = datetime.fromisoformat(raw)
    return moment.replace(tzinfo=HELSINKI) if moment.tzinfo is None else moment.astimezone(HELSINKI)


# --- scenarios ---------------------------------------------------------------------------------


@dataclass
class Scenario:
    name: str
    messages: list[str]  # one per user turn
    checks: dict[str, Check]


SCENARIOS = [
    Scenario(
        "sauna",
        ["When should I heat the sauna tonight? We want to finish bathing by 22."],
        {
            "uses the skill": skill_used(),
            "plans with find_cheapest_time": called("find_cheapest_time"),
            "2 hours (skill's sauna row)": arg_between(
                "find_cheapest_time", "duration_minutes", 120, 120
            ),
            "8-12 kWh": arg_between("find_cheapest_time", "energy_kwh", 8, 12),
            "finishes by 22:00 today": finishes_at("find_cheapest_time", 0, 22),
            "answer gives the start time": answer_gives_start_time("find_cheapest_time"),
            "says values are examples": answer_mentions(r"example|assum|typical"),
        },
    ),
    Scenario(
        "ev",
        ["I need 150 km of range by 7 tomorrow morning. My charger is 11 kW."],
        {
            "uses the skill": skill_used(),
            "plans with find_cheapest_time": called("find_cheapest_time"),
            "~30 kWh (150 km x 0.18 + 10 %)": arg_between(
                "find_cheapest_time", "energy_kwh", 27, 33
            ),
            "2.5-3 h at 11 kW": arg_between("find_cheapest_time", "duration_minutes", 150, 180),
            "whole quarter-hours": whole_quarter_hours("find_cheapest_time"),
            "finishes by 07:00 tomorrow": finishes_at("find_cheapest_time", 1, 7),
            "answer gives the start time": answer_gives_start_time("find_cheapest_time"),
        },
    ),
    Scenario(
        "contract",
        [
            "My margin is 0.39 c/kWh and my transfer fee (siirtomaksu) is 4.1 c/kWh. "
            "What does electricity cost right now?",
            "When is the cheapest 2-hour slot for laundry before midnight?",
        ],
        {
            "checks the price now": called("get_price_now"),
            "plans the laundry": called("find_cheapest_time"),
            "margin 0.39 in every call": every_call_has("margin_c_per_kwh", 0.39),
            "transfer 4.1 in every call": every_call_has("transfer_c_per_kwh", 4.1),
            "doesn't call them example values": last_answer_lacks(r"example values?"),
        },
    ),
]


# --- running -----------------------------------------------------------------------------------


def run_once(scenario: Scenario, model: str | None, with_skill: bool, log: Path) -> Transcript:
    """One headless Claude Code session in an empty folder: only the frozen server, and the
    skill only if asked. User settings, other MCP servers and other skills are not loaded."""
    uv, claude = _require("uv"), _require("claude")
    with tempfile.TemporaryDirectory() as folder:
        work = Path(folder)
        if with_skill:
            (work / ".claude" / "skills").mkdir(parents=True)
            (work / ".claude" / "skills" / SKILL_DIR.name).symlink_to(SKILL_DIR)
        server = {"command": uv, "args": ["run", "--quiet", "--directory", str(ROOT)]}
        server["args"] += ["python", "evals/frozen_server.py"]  # type: ignore[operator]
        config = work / "mcp.json"
        config.write_text(json.dumps({"mcpServers": {SERVER: server}}))
        command = [
            claude, "-p", "--verbose", "--no-session-persistence",
            "--input-format", "stream-json", "--output-format", "stream-json",
            "--setting-sources", "project",  # ignore the user's own settings
            "--strict-mcp-config", "--mcp-config", str(config),  # only the frozen server
            "--tools", "Skill,ToolSearch",  # no web search, files or shell
            "--allowedTools", "Skill", "ToolSearch", *[f"mcp__{SERVER}__{t}" for t in TOOLS],
        ]  # fmt: skip
        if model:
            command += ["--model", model]
        if not with_skill:
            command.append("--disable-slash-commands")
        turns = [
            {"type": "user", "message": {"role": "user", "content": m}} for m in scenario.messages
        ]
        done = subprocess.run(
            command,
            input="".join(json.dumps(turn) + "\n" for turn in turns),
            capture_output=True,
            text=True,
            cwd=work,
            timeout=600,
            env={**os.environ, "PATH": f"{Path(uv).parent}:{os.environ.get('PATH', '')}"},
        )
    log.write_text(done.stdout + (f"\n# stderr\n{done.stderr}" if done.stderr else ""))
    return parse_events([line for line in done.stdout.splitlines() if line.startswith("{")])


def _require(program: str) -> str:
    found = shutil.which(program) or shutil.which(program, path="/opt/homebrew/bin")
    if not found:
        sys.exit(f"{program} not found on PATH")
    return found


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--model", help="e.g. haiku, sonnet, opus (default: Claude Code's default)")
    parser.add_argument("--scenario", choices=[s.name for s in SCENARIOS])
    parser.add_argument("--no-skill", action="store_true", help="baseline without the skill")
    args = parser.parse_args()

    label = "without-skill" if args.no_skill else "with-skill"
    out = RESULTS / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{label}"
    out.mkdir(parents=True)
    scenarios = [s for s in SCENARIOS if args.scenario in (None, s.name)]
    failed, cost = False, 0.0
    for scenario in scenarios:
        passes = dict.fromkeys(scenario.checks, 0)
        reasons: dict[str, list[str]] = {name: [] for name in scenario.checks}
        for run in range(1, args.runs + 1):
            log = out / f"{scenario.name}-{run}.jsonl"
            transcript = run_once(scenario, args.model, not args.no_skill, log)
            cost += transcript.cost_usd
            for name, check in scenario.checks.items():
                reason = check(transcript) if transcript.answers else "no answer (see log)"
                if reason is None:
                    passes[name] += 1
                else:
                    reasons[name].append(f"run {run}: {reason}")
        print(f"\n{scenario.name} ({label}, {args.runs} runs)")
        for name, count in passes.items():
            mark = "PASS" if count == args.runs else "FAIL"
            failed |= mark == "FAIL"
            print(f"  {mark} {count}/{args.runs}  {name}")
            for reason in reasons[name]:
                print(f"         {reason}")
    print(f"\nCost about ${cost:.2f}. Logs: {out}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
