from pathlib import Path

from musicos.batch import BatchPlan, plan_batch
from musicos.dupes import Release, find_duplicates
from tests.test_dupes import rel


def plan(releases: list[Release], status: dict[str, str] | None = None) -> BatchPlan:
    return plan_batch(releases, find_duplicates(releases), status or {})


def test_a_folder_in_no_group_is_kept() -> None:
    oceanic = rel("/Isis/Oceanic", album="Oceanic")

    result = plan([oceanic])

    assert result.kept == [oceanic]


def test_an_open_deletion_candidate_is_left_out() -> None:
    split = rel("/Isis/(2000) Celestial")
    mp3 = rel("/Isis/Celestial [MP3]", kind="lossy")

    result = plan([split, mp3], {"/Isis/Celestial [MP3]": "open"})

    assert result.kept == [split]
    assert result.candidates == [mp3]


def test_a_tie_with_one_copy_chosen_keeps_the_other() -> None:
    chosen = rel("/Isis/[2004] Panopticon", album="Panopticon")
    other = rel("/Isis/D/(2004) Panopticon", album="Panopticon")

    result = plan([chosen, other], {"/Isis/D/(2004) Panopticon": "open"})

    assert result.kept == [chosen]
    assert result.undecided == []


def test_a_group_with_two_copies_left_is_imported_by_neither() -> None:
    a = rel("/Isis/A", album="Panopticon")
    b = rel("/Isis/B", album="Panopticon")

    result = plan([a, b])

    assert result.kept == []
    assert result.undecided == [[a, b]]


def test_a_kept_cue_rip_is_listed_for_splitting_and_not_imported() -> None:
    rip = rel("/Isis/Celestial [EAC-FLAC]", cue=True)

    result = plan([rip])

    assert result.kept == []
    assert result.to_split == [rip]


def test_a_candidate_whose_keeper_is_gone_is_for_review() -> None:
    mp3 = rel("/Isis/Celestial [MP3]", kind="lossy")

    result = plan([mp3], {"/Isis/Celestial [MP3]": "stale"})

    assert result.kept == []
    assert result.review == [mp3]


def test_a_folder_with_several_cue_sheets_is_for_review() -> None:
    odd = rel("/Isis/Odd", ambiguous=True)

    result = plan([odd])

    assert result.kept == []
    assert result.review == [odd]


def test_the_total_size_of_what_is_kept() -> None:
    a = rel("/Isis/A", album="A", size=100)
    b = rel("/Isis/B", album="B", size=250)

    assert plan([a, b]).size == 350


def test_kept_folders_come_in_path_order() -> None:
    b = rel("/Isis/B", album="B")
    a = rel("/Isis/A", album="A")

    assert [r.folder for r in plan([b, a]).kept] == [Path("/Isis/A"), Path("/Isis/B")]
