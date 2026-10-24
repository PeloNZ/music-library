"""Read KEY=value settings from a file, such as the Plex URL and token.

Values are never printed. An error names the line number only, because a
malformed line may hold a secret.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_env_file(path: Path) -> dict[str, str]:
    """`KEY=value` lines. `#` starts a comment line, `export ` is allowed, and
    matching quotes are removed. A `$` is kept as it is. A missing file gives
    no variables."""
    if not path.exists():
        return {}
    variables: dict[str, str] = {}
    for number, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, equals, value = line.removeprefix("export ").partition("=")
        if not equals or not KEY.fullmatch(key.strip()):
            raise ValueError(f"{path}: line {number} is not KEY=value")
        variables[key.strip()] = _unquote(value.strip())
    return variables


def merged_env(path: Path, environ: Mapping[str, str]) -> dict[str, str]:
    """The file's variables, with anything already in the environment on top."""
    return {**parse_env_file(path), **environ}
