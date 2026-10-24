from pathlib import Path
from typing import Any

from musicos.dupes import Release
from musicos.rules import PRIORITY, decide, rank
from tests.test_dupes import rel


def tracks(folder: str, n: int = 11, **kw: Any) -> Release:
    return rel(folder, tracks=n, kind="flac", cue=False, **kw)


def cue_rip(folder: str, n: int = 11, **kw: Any) -> Release:
    return rel(folder, tracks=n, kind="flac", cue=True, **kw)


def lossy(folder: str, n: int = 11, **kw: Any) -> Release:
    return rel(folder, tracks=n, kind="lossy", cue=False, fmt="MP3 320k", **kw)


def actions(decisions) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {d.release.folder.name: d.action for d in decisions}


def test_the_priority_order_is_split_flac_then_flac_cue_then_lossy() -> None:
    assert PRIORITY == {
        1: "FLAC tracks already split",
        2: "FLAC + cue file",
        3: "lossy tracks",
    }


def test_rank_follows_the_priority_order() -> None:
    assert rank(tracks("a")) == 1
    assert rank(cue_rip("a")) == 2
    assert rank(lossy("a")) == 3


def test_rank_of_a_lossless_format_that_is_not_flac_is_none() -> None:
    assert rank(rel("/a", kind="lossless", fmt="WAV 16/44.1")) is None


def test_split_flac_beats_flac_with_cue() -> None:
    rip, split = cue_rip("rip"), tracks("split")

    result = decide([rip, split])

    assert actions(result) == {"rip": "candidate", "split": "keep"}


def test_flac_with_cue_beats_lossy() -> None:
    result = decide([lossy("mp3"), cue_rip("rip")])

    assert actions(result) == {"mp3": "candidate", "rip": "keep"}


def test_split_flac_beats_lossy() -> None:
    result = decide([lossy("mp3"), tracks("split")])

    assert actions(result) == {"mp3": "candidate", "split": "keep"}


def test_both_lower_priorities_become_candidates() -> None:
    result = decide([lossy("mp3"), tracks("split"), cue_rip("rip")])

    assert actions(result) == {"mp3": "candidate", "split": "keep", "rip": "candidate"}


def test_a_candidate_names_what_it_lost_to_and_why() -> None:
    result = decide([cue_rip("rip"), tracks("/lib/split")])

    candidate = next(d for d in result if d.action == "candidate")
    assert candidate.kept_by == (Path("/lib/split"),)
    assert "FLAC + cue file" in candidate.reason
    assert "FLAC tracks already split" in candidate.reason


def test_two_copies_at_the_same_top_priority_are_a_tie_and_neither_is_a_candidate() -> (
    None
):
    result = decide([tracks("a"), tracks("b")])

    assert actions(result) == {"a": "tie", "b": "tie"}


def test_a_tie_does_not_stop_a_lower_priority_copy_being_a_candidate() -> None:
    result = decide([tracks("a"), tracks("b"), lossy("mp3")])

    assert actions(result) == {"a": "tie", "b": "tie", "mp3": "candidate"}
    mp3 = next(d for d in result if d.release.folder.name == "mp3")
    assert mp3.kept_by == (Path("a"), Path("b"))


def test_a_lower_priority_copy_with_more_tracks_is_reviewed_not_marked() -> None:
    result = decide([tracks("flac", 7), lossy("mp3", 9)])

    assert actions(result) == {"flac": "keep", "mp3": "review"}
    reason = next(d.reason for d in result if d.action == "review")
    assert "7" in reason and "9" in reason


def test_a_lower_priority_copy_with_equal_tracks_is_a_candidate() -> None:
    result = decide([tracks("flac", 7), lossy("mp3", 7)])

    assert actions(result)["mp3"] == "candidate"


def test_a_group_with_an_unranked_format_is_reviewed_and_nothing_is_marked() -> None:
    wav = rel("/wav", kind="lossless", fmt="WAV 16/44.1")

    result = decide([tracks("split"), wav, lossy("mp3")])

    assert set(actions(result).values()) == {"review"}
    wav_reason = next(d.reason for d in result if d.release.folder.name == "wav")
    assert "WAV 16/44.1" in wav_reason


def test_exactly_one_copy_is_kept_when_the_ranks_differ() -> None:
    result = decide([lossy("a"), cue_rip("b"), tracks("c")])

    assert [d.action for d in result].count("keep") == 1
    assert all(d.action != "candidate" for d in result if d.release.folder.name == "c")


def test_decisions_come_back_in_the_order_of_the_group() -> None:
    group = [lossy("z"), tracks("y"), cue_rip("x")]

    assert [d.release for d in decide(group)] == group
