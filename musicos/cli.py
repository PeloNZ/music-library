"""Command line entry point: `uv run musicos <command>`."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from musicos.preflight import Result, check_beetsdir, check_mount, check_plugins


@dataclass(frozen=True)
class Output:
    stdout: str
    stderr: str
    code: int


Run = Callable[[list[str]], Output]


def run_command(cmd: list[str]) -> Output:
    done = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return Output(done.stdout, done.stderr, done.returncode)


def preflight(env: Mapping[str, str], run: Run) -> list[Result]:
    results = [check_beetsdir(env)]
    if not results[0].ok:
        return results
    config = yaml.safe_load((Path(env["BEETSDIR"]) / "config.yaml").read_text())
    results.append(check_mount(config["directory"], run(["mount"]).stdout))
    plugins = config.get("plugins", "")
    wanted = plugins.split() if isinstance(plugins, str) else list(plugins)
    version = run(["beet", "version"])
    if version.code != 0:
        message = version.stderr.strip().splitlines()[:1] or ["beet version failed"]
        results.append(Result("beet", False, message[0]))
        return results
    results.append(check_plugins(version.stdout, wanted))
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
