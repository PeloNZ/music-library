"""Command line entry point: `uv run musicos <command>`."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path

import yaml

from musicos.lint import activity_line, render_report, run_lint
from musicos.preflight import (
    Result,
    check_beetsdir,
    check_mount,
    check_plugins,
    configured_plugins,
)
from musicos.runner import Run, run_command


def preflight(env: Mapping[str, str], run: Run) -> list[Result]:
    results = [check_beetsdir(env)]
    if not results[0].ok:
        return results
    config = yaml.safe_load((Path(env["BEETSDIR"]) / "config.yaml").read_text())
    results.append(check_mount(config["directory"], run(["mount"]).stdout))
    wanted = configured_plugins(config)
    version = run(["beet", "version"])
    if version.code != 0:
        message = version.stderr.strip().splitlines()[:1] or ["beet version failed"]
        results.append(Result("beet", False, message[0]))
        return results
    results.append(check_plugins(version.stdout, wanted))
    return results


def print_results(results: list[Result]) -> bool:
    for r in results:
        print(f"{'ok  ' if r.ok else 'FAIL'} {r.name}: {r.detail}")
    return all(r.ok for r in results)


def lint(env: Mapping[str, str], run: Run, when: datetime) -> int:
    checks = run_lint(run)
    logs = Path(env["BEETSDIR"]) / "logs"
    logs.mkdir(exist_ok=True)
    report = logs / "last-health-report.md"
    report.write_text(render_report(checks, when))
    with (logs / "musicos-activity.log").open("a") as log:
        log.write(activity_line(checks, when) + "\n")
    for c in checks:
        print(f"{c.name}: {'could not run (' + c.error + ')' if c.error else c.count}")
    print(f"report: {report}")
    return 1 if any(c.error for c in checks) else 0


def main(
    argv: Sequence[str] | None = None,
    env: Mapping[str, str] = os.environ,
    run: Run = run_command,
    now: Callable[[], datetime] = datetime.now,
) -> int:
    parser = argparse.ArgumentParser(prog="musicos")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "preflight", help="check BEETSDIR, the share mount and the plugins"
    )
    commands.add_parser("lint", help="run the read-only health checks")
    args = parser.parse_args(argv)

    if not print_results(preflight(env, run)):
        return 1
    if args.command == "lint":
        return lint(env, run, now())
    return 0


if __name__ == "__main__":
    sys.exit(main())
