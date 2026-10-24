"""Command line entry point: `uv run musicos <command>`."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import yaml

from musicos.preflight import Result, check_beetsdir, check_mount, check_plugins

Run = Callable[[list[str]], str]


def run_command(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout


def preflight(env: Mapping[str, str], run: Run) -> list[Result]:
    results = [check_beetsdir(env)]
    if not results[0].ok:
        return results
    config = yaml.safe_load((Path(env["BEETSDIR"]) / "config.yaml").read_text())
    results.append(check_mount(config["directory"], run(["mount"])))
    plugins = config.get("plugins", "")
    wanted = plugins.split() if isinstance(plugins, str) else list(plugins)
    results.append(check_plugins(run(["beet", "version"]), wanted))
    return results


def main(
    argv: Sequence[str] | None = None,
    env: Mapping[str, str] = os.environ,
    run: Run = run_command,
) -> int:
    parser = argparse.ArgumentParser(prog="musicos")
    parser.add_subparsers(dest="command", required=True).add_parser(
        "preflight", help="check BEETSDIR, the share mount and the plugins"
    )
    parser.parse_args(argv)

    results = preflight(env, run)
    for r in results:
        print(f"{'ok  ' if r.ok else 'FAIL'} {r.name}: {r.detail}")
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
