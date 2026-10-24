from datetime import datetime
from pathlib import Path

from musicos.changelog import read_entries
from musicos.trace import Trace

T0 = datetime(2026, 10, 25, 9, 10, 4)
T1 = datetime(2026, 10, 25, 9, 14, 40)


def clock(*times: datetime):  # type: ignore[no-untyped-def]
    ticks = iter(times)
    return lambda: next(ticks)


def test_start_and_done_are_activity_lines_stamped_when_they_happen(
    tmp_path: Path,
) -> None:
    trace = Trace(tmp_path, clock(T0, T1), "batch", "20261025-0910-isis")

    trace.start("6 folders")
    trace.done("5 albums")

    assert (tmp_path / "musicos-activity.log").read_text() == (
        "2026-10-25 09:10:04 batch 20261025-0910-isis start 6 folders\n"
        "2026-10-25 09:14:40 batch 20261025-0910-isis done 5 albums\n"
    )


def test_a_line_with_no_detail_has_no_trailing_space(tmp_path: Path) -> None:
    trace = Trace(tmp_path, clock(T0), "split", "Deserted")

    trace.start()

    assert (tmp_path / "musicos-activity.log").read_text() == (
        "2026-10-25 09:10:04 split Deserted start\n"
    )


def test_a_failure_is_an_activity_line_and_a_change_log_entry(tmp_path: Path) -> None:
    trace = Trace(tmp_path, clock(T1), "batch", "b1")

    trace.fail("error: disk full")

    assert (tmp_path / "musicos-activity.log").read_text() == (
        "2026-10-25 09:14:40 batch b1 FAIL error: disk full\n"
    )
    (entry,) = read_entries(tmp_path / "changes.jsonl")
    assert entry == {
        "time": "2026-10-25T09:14:40",
        "action": "failed",
        "command": "batch",
        "subject": "b1",
        "error": "error: disk full",
    }


def test_lines_are_appended_after_earlier_ones(tmp_path: Path) -> None:
    (tmp_path / "musicos-activity.log").write_text("earlier\n")

    Trace(tmp_path, clock(T0), "folders", "inbox").start()

    assert (tmp_path / "musicos-activity.log").read_text().startswith("earlier\n")
