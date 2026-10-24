import json
from datetime import datetime
from pathlib import Path

import pytest

from musicos.changelog import Entry, filter_entries, read_entries, record

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


ENTRIES: list[Entry] = [
    {"time": "2026-10-22T09:00:00", "action": "import", "batch": "b1"},
    {"time": "2026-10-23T09:00:00", "action": "move", "batch": "b1"},
    {"time": "2026-10-24T09:00:00", "action": "import", "batch": "b2"},
    {"time": "2026-10-24T10:00:00", "action": "split"},
]


def times(entries: list[Entry]) -> list[str]:
    return [e["time"][5:13] for e in entries]


def test_filter_by_batch_drops_entries_without_one() -> None:
    assert times(filter_entries(ENTRIES, batch="b1")) == ["10-22T09", "10-23T09"]


def test_filter_by_action() -> None:
    assert times(filter_entries(ENTRIES, action="import")) == ["10-22T09", "10-24T09"]


def test_filter_since_keeps_entries_from_that_time_on() -> None:
    since = datetime(2026, 10, 24, 9, 0, 0)

    assert times(filter_entries(ENTRIES, since=since)) == ["10-24T09", "10-24T10"]


def test_filter_last_keeps_the_newest_in_order() -> None:
    assert times(filter_entries(ENTRIES, last=2)) == ["10-24T09", "10-24T10"]


def test_filters_combine() -> None:
    result = filter_entries(ENTRIES, action="import", last=1)

    assert times(result) == ["10-24T09"]


def test_no_filters_returns_everything() -> None:
    assert filter_entries(ENTRIES) == ENTRIES


def test_filter_last_zero_keeps_nothing() -> None:
    assert filter_entries(ENTRIES, last=0) == []
