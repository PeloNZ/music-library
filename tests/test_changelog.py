import json
from datetime import datetime
from pathlib import Path

import pytest

from musicos.changelog import read_entries, record

WHEN = datetime(2026, 10, 24, 21, 30, 5)


def test_record_appends_one_json_line_per_entry(tmp_path: Path) -> None:
    log = tmp_path / "logs" / "changes.jsonl"

    record(log, "import", WHEN, batch="b1", albums=2)
    record(log, "move", WHEN, batch="b2", moved=[["/a", "/b"]])

    lines = log.read_text().splitlines()
    assert [json.loads(line) for line in lines] == [
        {"time": "2026-10-24T21:30:05", "action": "import", "batch": "b1", "albums": 2},
        {
            "time": "2026-10-24T21:30:05",
            "action": "move",
            "batch": "b2",
            "moved": [["/a", "/b"]],
        },
    ]


def test_record_keeps_non_ascii_names_readable(tmp_path: Path) -> None:
    log = tmp_path / "changes.jsonl"

    record(log, "import", WHEN, album="Motörhead")

    assert "Motörhead" in log.read_text()


def test_read_entries_returns_what_was_recorded(tmp_path: Path) -> None:
    log = tmp_path / "changes.jsonl"
    record(log, "import", WHEN, batch="b1")

    assert read_entries(log) == [
        {"time": "2026-10-24T21:30:05", "action": "import", "batch": "b1"}
    ]


def test_read_entries_of_a_missing_log_is_empty(tmp_path: Path) -> None:
    assert read_entries(tmp_path / "none.jsonl") == []


def test_read_entries_names_the_corrupt_line(tmp_path: Path) -> None:
    log = tmp_path / "changes.jsonl"
    record(log, "import", WHEN)
    with log.open("a") as f:
        f.write("{not json\n")

    with pytest.raises(ValueError, match="line 2"):
        read_entries(log)
