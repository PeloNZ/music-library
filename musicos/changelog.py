"""Change log: one JSON line per action that changed files or tags.

`beetsdir/logs/changes.jsonl` records what changed, with enough detail to
find the old state. `musicos-activity.log` records what ran and when: one
line per event.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from musicos.text import printable

Entry = dict[str, Any]

ACTIVITY_LOG = "musicos-activity.log"
CHANGES_LOG = "changes.jsonl"


def append_activity(logs: Path, line: str) -> None:
    logs.mkdir(parents=True, exist_ok=True)
    with (logs / ACTIVITY_LOG).open("a") as log:
        log.write(printable(line) + "\n")


def record(path: Path, action: str, when: datetime, **fields: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    entry: Entry = {"time": when.isoformat(timespec="seconds"), "action": action}
    entry.update(fields)
    with path.open("a", encoding="utf-8") as log:
        log.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_entries(path: Path) -> list[Entry]:
    """All entries, oldest first. A corrupt line raises ValueError."""
    if not path.exists():
        return []
    entries: list[Entry] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: line {number} is not valid JSON") from exc
    return entries


def filter_entries(
    entries: list[Entry],
    batch: str | None = None,
    action: str | None = None,
    since: datetime | None = None,
    last: int | None = None,
) -> list[Entry]:
    """Keep entries that match every given filter, then the newest `last`."""
    kept = [
        e
        for e in entries
        if (batch is None or e.get("batch") == batch)
        and (action is None or e["action"] == action)
        and (since is None or datetime.fromisoformat(e["time"]) >= since)
    ]
    if last is None:
        return kept
    return kept[max(len(kept) - last, 0) :]


def format_entry(entry: Entry) -> str:
    """One line: time, action, then each field. A list shows as its length."""
    parts = [entry["time"], entry["action"]]
    for key, value in entry.items():
        if key in ("time", "action"):
            continue
        parts.append(f"{key}={len(value) if isinstance(value, list) else value}")
    return " ".join(parts)


def stamp(when: datetime) -> str:
    return when.strftime("%Y-%m-%d %H:%M:%S")
