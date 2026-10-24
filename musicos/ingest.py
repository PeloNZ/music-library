"""Bring new music into the library with beet import."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path

SLUG_LIMIT = 40


def make_batch_id(when: datetime, source: Path) -> str:
    """`<YYYYMMDD-HHMM>-<slug of the source folder name>`."""
    ascii_name = (
        unicodedata.normalize("NFKD", source.name)
        .encode("ascii", "ignore")
        .decode()
        .lower()
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")[:SLUG_LIMIT].strip("-")
    return f"{when:%Y%m%d-%H%M}-{slug}"


def dry_run_command(source: Path) -> list[str]:
    """Lists the files beets would import. It does not show matches."""
    return ["beet", "import", "--pretend", str(source)]


def import_command(source: Path, batch: str, logs: Path, unattended: bool) -> list[str]:
    """The real import. `-q` is only ever paired with `--quiet-fallback skip`,
    so a weak match is never applied as-is."""
    cmd = [
        "beet",
        "import",
        "-l",
        str(logs / f"import-{batch}.log"),
        "--set",
        f"musicos_batch={batch}",
    ]
    if unattended:
        cmd += ["-q", "--quiet-fallback", "skip"]
    return cmd + [str(source)]
