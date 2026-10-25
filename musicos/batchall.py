"""The preview of every artist folder: what `batch` would do for each one.

This only decides and formats. It reads and writes nothing.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from musicos.batch import BatchPlan
from musicos.dupes import Release
from musicos.text import printable

READY = "ready"
NEEDS_YOU = "needs you"
NOTHING = "nothing to import"
ERROR = "error"

MULTI_DISC_NAME = re.compile(r"^(cd|disc|disk)\s*\d+", re.IGNORECASE)


def is_multi_disc(release: Release) -> bool:
    """A disc folder such as `CD2`, or a disc tag above 1. beets gets such a
    folder as an album of its own, so `ingest` on the parent folder is the way in."""
    return release.disc != "1" or bool(MULTI_DISC_NAME.match(release.folder.name))


@dataclass
class ArtistPlan:
    folder: Path
    already: int = 0  # folders beets already holds
    plan: BatchPlan = field(default_factory=BatchPlan)
    pretend: list[str] = field(default_factory=list)  # beets --pretend output lines
    error: str = ""

    @property
    def name(self) -> str:
        return self.folder.name

    @property
    def multi_disc(self) -> list[Release]:
        return [r for r in self.plan.kept if is_multi_disc(r)]

    @property
    def status(self) -> str:
        plan = self.plan
        if self.error:
            return ERROR
        if plan.undecided or plan.to_split or plan.review or self.multi_disc:
            return NEEDS_YOU
        return READY if plan.kept else NOTHING


GIB = 1073741824


def gib(size: int) -> str:
    return f"{size / GIB:.1f} GiB"


def _kept(artist: ArtistPlan) -> list[str]:
    plan = artist.plan
    return [
        f"- {printable(str(r.folder))} ({gib(r.size)})"
        for r in plan.kept
        if r not in artist.multi_disc
    ]


def _questions(artist: ArtistPlan) -> list[str]:
    plan = artist.plan
    lines = []
    for group in plan.undecided:
        lines.append("- choose one, then run batch again:")
        lines += [f"  - {printable(str(r.folder))}" for r in group]
    lines += [
        f"- split first (musicos split): {printable(str(r.folder))}"
        for r in plan.to_split
    ]
    lines += [f"- review: {printable(str(r.folder))}" for r in plan.review]
    lines += [
        f"- multi-disc, run ingest on the parent folder: {printable(str(r.folder))}"
        for r in artist.multi_disc
    ]
    return lines


def render_batch_all_report(
    artists: list[ArtistPlan],
    root: Path,
    when: datetime,
    loose: list[Path],
    command: Callable[[Path], str],
) -> str:
    """`command` gives the `batch` command line for an artist folder."""
    by_status = {
        s: [a for a in artists if a.status == s]
        for s in (READY, NEEDS_YOU, NOTHING, ERROR)
    }
    counts = ", ".join(f"{s} {len(by_status[s])}" for s in by_status)
    kept = [r for a in artists for r in a.plan.kept]
    out = [
        "# Batch preview",
        "",
        f"Root: {printable(str(root))}",
        f"Made: {when:%Y-%m-%d %H:%M}",
        "",
        "## Totals",
        "",
        f"- Artists: {len(artists)} ({counts})",
        f"- Folders already in beets: {sum(a.already for a in artists)}",
        f"- Folders to import: {len(kept)}",
        f"- Copy size: {gib(sum(r.size for r in kept))}",
        f"- Deletion candidates left out: {sum(len(a.plan.candidates) for a in artists)}",
    ]
    if loose:
        out.append(f"- Loose audio files at the root: {len(loose)}")
    if by_status[READY]:
        out += ["", "## Ready"]
        for a in by_status[READY]:
            summary = (
                f"{len(a.plan.kept)} folders, {gib(a.plan.size)}, "
                f"{len(a.pretend)} lines of beets pretend output."
            )
            out += [
                "",
                f"### {printable(a.name)}",
                "",
                summary,
                "",
                *_kept(a),
                "",
                f"    {command(a.folder)}",
            ]
    if by_status[NEEDS_YOU]:
        out += ["", "## Needs you"]
        for a in by_status[NEEDS_YOU]:
            out += ["", f"### {printable(a.name)}", "", *_questions(a)]
            ok = _kept(a)
            if ok:
                out += ["", "Would import:", "", *ok]
    if by_status[ERROR]:
        out += ["", "## Errors", ""]
        out += [
            f"- {printable(a.name)}: {printable(a.error)}" for a in by_status[ERROR]
        ]
    if by_status[NOTHING]:
        names = ", ".join(printable(a.name) for a in by_status[NOTHING])
        out += ["", "## Nothing to import", "", names]
    if loose:
        out += ["", "## Loose audio files at the root", ""]
        out += [f"- {printable(str(p))}" for p in loose]
    return "\n".join(out) + "\n"


def plan_to_json(
    artists: list[ArtistPlan], root: Path, when: datetime
) -> dict[str, Any]:
    def folders(releases: list[Release]) -> list[str]:
        return [str(r.folder) for r in releases]

    return {
        "root": str(root),
        "time": when.isoformat(),
        "artists": [
            {
                "name": a.name,
                "folder": str(a.folder),
                "status": a.status,
                "already": a.already,
                "kept": [
                    {"folder": str(r.folder), "size": r.size, "tracks": r.tracks}
                    for r in a.plan.kept
                ],
                "candidates": folders(a.plan.candidates),
                "review": folders(a.plan.review),
                "undecided": [folders(g) for g in a.plan.undecided],
                "to_split": folders(a.plan.to_split),
                "multi_disc": folders(a.multi_disc),
                "pretend": a.pretend,
                "error": a.error,
            }
            for a in artists
        ],
    }
