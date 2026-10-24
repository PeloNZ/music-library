"""Run a command and return everything it printed."""

from __future__ import annotations

import os
import shlex
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Output:
    stdout: str
    stderr: str
    code: int


Run = Callable[[list[str]], Output]


def run_command(cmd: list[str]) -> Output:
    done = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return Output(done.stdout, done.stderr, done.returncode)


Stream = Callable[[list[str], Path], Output]


def stream_command(cmd: list[str], log: Path) -> Output:
    """Run a command and write each line it prints, stdout and stderr in order,
    to `log` and the terminal as it appears, so `tail -f` follows a long run.
    `stderr` of the result holds the last line, which is where errors end up."""
    lines: list[str] = []
    with log.open("a") as out_log:
        out_log.write(f"$ {shlex.join(cmd)}\n")
        out_log.flush()
        child = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        assert child.stdout is not None
        for line in child.stdout:
            lines.append(line)
            out_log.write(line)
            out_log.flush()
            print(line, end="", flush=True)
        code = child.wait()
    last = lines[-1].strip() if lines else ""
    return Output("".join(lines), last, code)


def first_error(out: Output, fallback: str | None = None) -> str:
    """The first line of stderr, else the fallback, else the exit code."""
    lines = out.stderr.strip().splitlines()
    return lines[0] if lines else fallback or f"exit code {out.code}"
