"""Read-only library health checks. Each check is a stock beet command."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from musicos.runner import Output, Run

EXAMPLE_LIMIT = 10
ANSI = re.compile(r"\x1b\[[0-9;]*m")

DRIFT = "placement drift"

CHECKS: list[tuple[str, list[str]]] = [
    (DRIFT, ["beet", "move", "--pretend"]),
    ("duplicates", ["beet", "duplicates"]),
    ("incomplete albums", ["beet", "missing"]),
    ("unimported files", ["beet", "unimported"]),
    ("singletons", ["beet", "ls", "singleton:true"]),
    ("unmatched imports", ["beet", "ls", "--", "^mb_albumid::."]),
]


@dataclass(frozen=True)
class CheckResult:
    name: str
    count: int
    examples: list[str] = field(default_factory=list)
    error: str | None = None


def _lines(text: str) -> list[str]:
    cleaned = (ANSI.sub("", line).strip() for line in text.splitlines())
    return [line for line in cleaned if line]


def _error(name: str, out: Output) -> CheckResult:
    message = _lines(out.stderr)[:1] or [f"exit code {out.code}"]
    return CheckResult(name, 0, error=message[0])


def _drift(out: Output) -> CheckResult:
    if out.code != 0:
        if "No matching items found" in out.stderr:  # empty library
            return CheckResult(DRIFT, 0)
        return _error(DRIFT, out)
    header = re.search(r"Moving (\d+) item", out.stderr)
    lines = _lines(out.stdout)
    pairs = [f"{old} {new}" for old, new in zip(lines[::2], lines[1::2])]
    return CheckResult(DRIFT, int(header[1]) if header else 0, pairs[:EXAMPLE_LIMIT])


def _lines_as_findings(name: str, out: Output) -> CheckResult:
    if out.code != 0:
        return _error(name, out)
    lines = _lines(out.stdout)
    return CheckResult(name, len(lines), lines[:EXAMPLE_LIMIT])


def run_lint(run: Run) -> list[CheckResult]:
    results = []
    for name, cmd in CHECKS:
        out = run(cmd)
        results.append(_drift(out) if name == DRIFT else _lines_as_findings(name, out))
    return results
