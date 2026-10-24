"""Run a command and return everything it printed."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Output:
    stdout: str
    stderr: str
    code: int


Run = Callable[[list[str]], Output]


def run_command(cmd: list[str]) -> Output:
    done = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return Output(done.stdout, done.stderr, done.returncode)
