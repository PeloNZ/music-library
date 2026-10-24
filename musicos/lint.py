"""Read-only library health checks. Each check is a stock beet command."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime

from musicos.changelog import stamp
from musicos.runner import Output, Run

EXAMPLE_LIMIT = 10
ANSI = re.compile(r"\x1b\[[0-9;]*m")

DRIFT = "placement drift"
UNIMPORTED = "unimported files"
CASE_MISMATCH = "path case mismatches"
DB_PATHS = ["beet", "ls", "-f", "$path"]

CHECKS: list[tuple[str, list[str]]] = [
    (DRIFT, ["beet", "move", "--pretend"]),
    ("duplicates", ["beet", "duplicates"]),
    ("incomplete albums", ["beet", "missing"]),
    (UNIMPORTED, ["beet", "unimported"]),
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


def _same_path(path: str) -> str:
    """Compare paths the way the Mac and Samba file systems do: ignoring case
    and the two ways of writing an accented letter."""
    return unicodedata.normalize("NFC", path).casefold()


def _unimported(out: Output, db_paths: Output) -> list[CheckResult]:
    """Split `beet unimported` in two. beets compares paths exactly, so a file
    whose path differs from the database only in case, such as `Cake/` on disk
    and `CAKE/` in the database, is listed even though beets holds it."""
    for failed in (out, db_paths):
        if failed.code != 0:
            return [_error(UNIMPORTED, failed), _error(CASE_MISMATCH, failed)]
    known = {_same_path(line) for line in _lines(db_paths.stdout)}
    files = _lines(out.stdout)
    mismatched = [f for f in files if _same_path(f) in known]
    missing = [f for f in files if _same_path(f) not in known]
    return [
        CheckResult(UNIMPORTED, len(missing), missing[:EXAMPLE_LIMIT]),
        CheckResult(CASE_MISMATCH, len(mismatched), mismatched[:EXAMPLE_LIMIT]),
    ]


def run_lint(run: Run) -> list[CheckResult]:
    results = []
    for name, cmd in CHECKS:
        out = run(cmd)
        if name == DRIFT:
            results.append(_drift(out))
        elif name == UNIMPORTED:
            results += _unimported(out, run(DB_PATHS))
        else:
            results.append(_lines_as_findings(name, out))
    return results


def render_report(results: list[CheckResult], when: datetime) -> str:
    lines = [
        "# Library health report",
        "",
        f"Run at {stamp(when)}",
        "",
        "| Check | Findings |",
        "|---|---|",
    ]
    for r in results:
        lines.append(f"| {r.name} | {'n/a' if r.error else r.count} |")
    for r in results:
        lines.append("")
        if r.error:
            lines.append(f"## {r.name}: could not run ({r.error})")
            continue
        lines += [f"## {r.name} ({r.count})", ""]
        lines += [f"- {example}" for example in r.examples]
        hidden = r.count - len(r.examples)
        if hidden > 0:
            lines.append(f"- ... {hidden} more not shown")
    return "\n".join(lines) + "\n"


def activity_line(results: list[CheckResult], when: datetime) -> str:
    issues = sum(r.count for r in results)
    categories = sum(1 for r in results if r.count > 0)
    return f"{stamp(when)} lint {issues} issues across {categories} categories"
