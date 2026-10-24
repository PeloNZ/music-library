"""Bring new music into the library with beet import."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from musicos.runner import Run

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


EXPORT_FIELDS = "id,album,albumartist,year,mb_albumid,albumtypes"


@dataclass(frozen=True)
class BatchSummary:
    albums: int
    flagged: list[dict[str, object]]


def summarize_batch(run: Run, batch: str) -> BatchSummary:
    """Read an import batch back from beets. An album with no MusicBrainz id
    was imported as-is or never matched, so it needs a closer look."""
    out = run(
        [
            "beet",
            "export",
            "-a",
            "-f",
            "json",
            "-i",
            EXPORT_FIELDS,
            f"musicos_batch:{batch}",
        ]
    )
    albums = json.loads(out.stdout) if out.stdout.strip() else []
    return BatchSummary(len(albums), [a for a in albums if not a.get("mb_albumid")])
