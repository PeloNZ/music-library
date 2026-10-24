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
