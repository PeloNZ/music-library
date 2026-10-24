"""Report albums with missing metadata. Reports only: it never guesses a value.

beets' query language cannot match a NULL field, so the albums are exported
and each field is tested here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from musicos.runner import Run

Album = dict[str, Any]

GAP_FIELDS = [
    ("no album artist", "albumartist"),
    ("no year", "year"),
    ("no genre", "genres"),
    ("no art", "artpath"),
]
EXPORT_FIELDS = "id,albumartist,album,year,genres,artpath,path"


@dataclass(frozen=True)
class GapResult:
    name: str
    albums: list[Album] = field(default_factory=list)


def _missing(value: object) -> bool:
    """beets exports a missing field as an empty string, and a missing year as 0."""
    return value is None or str(value).strip() in ("", "0")


def find_gaps(albums: list[Album]) -> list[GapResult]:
    return [
        GapResult(name, [a for a in albums if _missing(a.get(key))])
        for name, key in GAP_FIELDS
    ]


def export_albums(run: Run) -> list[Album]:
    out = run(["beet", "export", "-a", "-f", "json", "-i", EXPORT_FIELDS])
    if out.code != 0:
        message = out.stderr.strip().splitlines()[:1] or [f"exit code {out.code}"]
        raise RuntimeError(message[0])
    albums: list[Album] = json.loads(out.stdout) if out.stdout.strip() else []
    return albums


def _when(when: datetime) -> str:
    return when.strftime("%Y-%m-%d %H:%M:%S")


def _label(album: Album) -> str:
    artist = album.get("albumartist") or "?"
    title = album.get("album") or "?"
    return f"{artist} - {title} | {album.get('path', '')}"


def render_report(results: list[GapResult], checked: int, when: datetime) -> str:
    lines = [
        "# Metadata gaps",
        "",
        f"Run at {_when(when)}. {checked} albums checked.",
        "",
        "| Gap | Albums |",
        "|---|---|",
    ]
    lines += [f"| {r.name} | {len(r.albums)} |" for r in results]
    for r in results:
        lines += ["", f"## {r.name} ({len(r.albums)})", ""]
        lines += [f"- {_label(a)}" for a in r.albums]
    return "\n".join(lines) + "\n"


def activity_line(results: list[GapResult], checked: int, when: datetime) -> str:
    with_gaps = {id(a) for r in results for a in r.albums}
    gaps = sum(len(r.albums) for r in results)
    return (
        f"{_when(when)} gaps {checked} albums checked, "
        f"{len(with_gaps)} with gaps, {gaps} gaps"
    )
