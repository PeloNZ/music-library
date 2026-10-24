"""Checks that must pass before any command that runs beet."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Result:
    name: str
    ok: bool
    detail: str


def check_beetsdir(env: Mapping[str, str]) -> Result:
    """BEETSDIR must point at a folder with config.yaml.

    Without it, beets writes its config and database to ~/.config/beets.
    """
    beetsdir = env.get("BEETSDIR")
    if not beetsdir:
        return Result("beetsdir", False, "BEETSDIR is not set")
    if not (Path(beetsdir) / "config.yaml").is_file():
        return Result("beetsdir", False, f"{beetsdir}/config.yaml does not exist")
    return Result("beetsdir", True, beetsdir)


def check_mount(directory: str, mount_output: str) -> Result:
    """The library folder must sit on a mounted volume, not on the root disk.

    A dropped network mount leaves an empty local folder at the same path.
    """
    for mount_point in re.findall(r" on (.+) \(", mount_output):
        if mount_point != "/" and (
            directory == mount_point or directory.startswith(mount_point + "/")
        ):
            return Result("mount", True, mount_point)
    return Result("mount", False, f"nothing is mounted at {directory}")


def check_plugins(version_output: str, required: list[str]) -> Result:
    """Every required plugin must appear in the `plugins:` line of `beet version`."""
    enabled: set[str] = set()
    for line in version_output.splitlines():
        if line.startswith("plugins:"):
            enabled = {
                name.strip() for name in line.removeprefix("plugins:").split(",")
            }
    missing = [name for name in required if name not in enabled]
    if missing:
        return Result("plugins", False, "not enabled: " + ", ".join(missing))
    return Result("plugins", True, ", ".join(sorted(enabled)))
