"""The deletion candidates log, for the user to work through by hand.

`beetsdir/logs/deletion-candidates.jsonl` lists copies that a higher priority
copy makes redundant. Nothing here deletes anything. Each entry's status is
worked out from the disk when the log is read:

- open: the folder exists and at least one copy that outranked it exists.
- stale: the folder exists but every copy that outranked it is gone. It is no
  longer safe to delete.
- done: the folder is gone.
- unknown: the share the folder is on is not mounted, so the disk says nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from musicos.changelog import Entry, read_entries, record
from musicos.rules import Decision


def _album(release_artist: str, release_album: str, folder: Path) -> str:
    return f"{release_artist or '?'} - {release_album or folder.name}"


def record_candidates(
    path: Path, decisions: list[Decision], root: Path, when: datetime
) -> int:
    """Append each deletion candidate not already listed. Returns how many."""
    known = {e["folder"] for e in read_entries(path)}
    new = [
        d
        for d in decisions
        if d.action == "candidate" and str(d.release.folder) not in known
    ]
    for d in new:
        r = d.release
        record(
            path,
            "candidate",
            when,
            root=str(root),
            album=_album(r.artist, r.album, r.folder),
            folder=str(r.folder),
            rule=d.reason,
            kept_by=[str(p) for p in d.kept_by],
            tracks=r.tracks,
            fmt=r.fmt,
            size=r.size,
        )
    return len(new)


Mounted = Callable[[str], bool]


def status_of(entry: Entry, mounted: Mounted) -> str:
    if not mounted(entry["root"]):
        return "unknown"
    if not Path(entry["folder"]).exists():
        return "done"
    if all(not Path(p).exists() for p in entry["kept_by"]):
        return "stale"
    return "open"


def list_candidates(
    path: Path, mounted: Mounted, include_done: bool = False
) -> list[tuple[Entry, str]]:
    """Every entry with its status, in log order. Done ones only on request."""
    entries = [(e, status_of(e, mounted)) for e in read_entries(path)]
    return [(e, s) for e, s in entries if include_done or s != "done"]
