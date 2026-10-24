from datetime import datetime
from pathlib import Path

from musicos.candidates import list_candidates, record_candidates, status_of
from musicos.changelog import read_entries
from musicos.rules import decide
from tests.test_dupes import rel

WHEN = datetime(2026, 10, 24, 23, 50, 0)


def make(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A split copy (kept), a cue rip and an mp3 copy (candidates), on disk."""
    split = tmp_path / "Isis" / "(2000) Celestial"
    rip = tmp_path / "Isis" / "Isis - Celestial (2000) [EAC-FLAC]"
    mp3 = tmp_path / "Isis" / "Celestial [MP3]"
    for folder in (split, rip, mp3):
        folder.mkdir(parents=True)
        (folder / "a.flac").write_bytes(b"x")
    return split, rip, mp3


def decisions(split: Path, rip: Path, mp3: Path):  # type: ignore[no-untyped-def]
    return decide(
        [
            rel(str(split), tracks=11, kind="flac", cue=False),
            rel(str(rip), tracks=11, kind="flac", cue=True, size=323 * 1048576),
            rel(str(mp3), tracks=11, kind="lossy", cue=False, fmt="MP3 320k"),
        ]
    )


def test_only_candidates_are_recorded_with_what_outranks_them(tmp_path: Path) -> None:
    split, rip, mp3 = make(tmp_path)
    log = tmp_path / "logs" / "deletion-candidates.jsonl"

    added = record_candidates(log, decisions(split, rip, mp3), tmp_path / "Isis", WHEN)

    entries = read_entries(log)
    assert added == 2
    assert [e["folder"] for e in entries] == [str(rip), str(mp3)]
    first = entries[0]
    assert first["action"] == "candidate"
    assert first["time"] == "2026-10-24T23:50:00"
    assert first["album"] == "Isis - Celestial"
    assert first["kept_by"] == [str(split)]
    assert "FLAC + cue file" in first["rule"]
    assert first["tracks"] == 11
    assert first["fmt"] == "FLAC 16/44.1"
    assert first["size"] == 323 * 1048576
    assert first["root"] == str(tmp_path / "Isis")


def test_running_again_adds_nothing_for_a_folder_already_listed(tmp_path: Path) -> None:
    split, rip, mp3 = make(tmp_path)
    log = tmp_path / "logs" / "deletion-candidates.jsonl"
    record_candidates(log, decisions(split, rip, mp3), tmp_path, WHEN)

    again = record_candidates(log, decisions(split, rip, mp3), tmp_path, WHEN)

    assert again == 0
    assert len(read_entries(log)) == 2


def test_a_group_with_no_candidates_records_nothing_and_makes_no_file(
    tmp_path: Path,
) -> None:
    log = tmp_path / "logs" / "deletion-candidates.jsonl"
    tie = decide([rel("/a", kind="flac", cue=False), rel("/b", kind="flac", cue=False)])

    assert record_candidates(log, tie, tmp_path, WHEN) == 0
    assert not log.exists()


def test_a_candidate_is_open_while_it_and_what_outranks_it_exist(
    tmp_path: Path,
) -> None:
    split, rip, mp3 = make(tmp_path)
    log = tmp_path / "logs" / "deletion-candidates.jsonl"
    record_candidates(log, decisions(split, rip, mp3), tmp_path, WHEN)

    assert [status_of(e) for e in read_entries(log)] == ["open", "open"]


def test_a_candidate_is_done_when_its_folder_is_gone(tmp_path: Path) -> None:
    split, rip, mp3 = make(tmp_path)
    log = tmp_path / "logs" / "deletion-candidates.jsonl"
    record_candidates(log, decisions(split, rip, mp3), tmp_path, WHEN)
    (rip / "a.flac").unlink()
    rip.rmdir()

    assert [status_of(e) for e in read_entries(log)] == ["done", "open"]


def test_a_candidate_is_stale_when_the_copy_that_outranked_it_is_gone(
    tmp_path: Path,
) -> None:
    split, rip, mp3 = make(tmp_path)
    log = tmp_path / "logs" / "deletion-candidates.jsonl"
    record_candidates(log, decisions(split, rip, mp3), tmp_path, WHEN)
    (split / "a.flac").unlink()
    split.rmdir()

    assert [status_of(e) for e in read_entries(log)] == ["stale", "stale"]


def test_list_candidates_hides_done_ones_unless_asked(tmp_path: Path) -> None:
    split, rip, mp3 = make(tmp_path)
    log = tmp_path / "logs" / "deletion-candidates.jsonl"
    record_candidates(log, decisions(split, rip, mp3), tmp_path, WHEN)
    (mp3 / "a.flac").unlink()
    mp3.rmdir()

    open_now = list_candidates(log)
    everything = list_candidates(log, include_done=True)

    assert [(e["folder"], s) for e, s in open_now] == [(str(rip), "open")]
    assert [s for _, s in everything] == ["open", "done"]


def test_list_candidates_of_a_missing_log_is_empty(tmp_path: Path) -> None:
    assert list_candidates(tmp_path / "none.jsonl") == []
