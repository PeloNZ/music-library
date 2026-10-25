from datetime import datetime
from pathlib import Path

from musicos.batch import BatchPlan
from musicos.batchall import (
    ArtistPlan,
    is_multi_disc,
    plan_to_json,
    render_batch_all_report,
)
from tests.test_dupes import rel


def artist(plan: BatchPlan, error: str = "") -> ArtistPlan:
    return ArtistPlan(folder=Path("/m/Isis"), plan=plan, error=error)


def test_a_folder_named_cd1_disc_2_or_disk_3_is_multi_disc() -> None:
    assert is_multi_disc(rel("/m/Isis/Box/CD1"))
    assert is_multi_disc(rel("/m/Isis/Box/disc 2"))
    assert is_multi_disc(rel("/m/Isis/Box/Disk3"))


def test_a_folder_with_a_disc_tag_above_one_is_multi_disc() -> None:
    assert is_multi_disc(rel("/m/Isis/Oceanic", disc="2"))


def test_an_ordinary_album_folder_is_not_multi_disc() -> None:
    assert not is_multi_disc(rel("/m/Isis/Oceanic"))
    assert not is_multi_disc(rel("/m/Isis/Discography"))


def test_an_artist_with_kept_folders_and_no_questions_is_ready() -> None:
    plan = BatchPlan(kept=[rel("/m/Isis/Oceanic")])

    assert artist(plan).status == "ready"


def test_an_artist_with_nothing_kept_and_nothing_to_decide_has_nothing_to_import() -> (
    None
):
    plan = BatchPlan(candidates=[rel("/m/Isis/Oceanic [MP3]")])

    assert artist(plan).status == "nothing to import"


def test_each_open_question_makes_an_artist_need_you() -> None:
    one = rel("/m/Isis/Oceanic")
    for plan in (
        BatchPlan(kept=[one], undecided=[[one, one]]),
        BatchPlan(kept=[one], to_split=[one]),
        BatchPlan(kept=[one], review=[one]),
        BatchPlan(kept=[rel("/m/Isis/Box/CD1")]),
    ):
        assert artist(plan).status == "needs you"


def test_an_error_outranks_every_other_status() -> None:
    plan = BatchPlan(kept=[rel("/m/Isis/Oceanic")], review=[rel("/m/Isis/X")])

    assert artist(plan, error="boom").status == "error"


WHEN = datetime(2026, 10, 25, 12, 0, 0)
GIB = 1073741824


def command(folder: Path) -> str:
    return f"musicos batch {folder} --apply"


def report(artists: list[ArtistPlan], loose: list[Path] | None = None) -> str:
    return render_batch_all_report(artists, Path("/m"), WHEN, loose or [], command)


def sample() -> list[ArtistPlan]:
    oceanic = rel("/m/Isis/Oceanic", size=GIB)
    celestial = rel("/m/Isis/Celestial", size=GIB // 2)
    mp3 = rel("/m/Isis/Oceanic [MP3]")
    return [
        ArtistPlan(
            Path("/m/Isis"),
            already=5,
            plan=BatchPlan(kept=[oceanic, celestial], candidates=[mp3]),
            pretend=["a", "b", "c"],
        ),
        ArtistPlan(
            Path("/m/Cake"),
            plan=BatchPlan(
                undecided=[[rel("/m/Cake/A"), rel("/m/Cake/B")]],
                to_split=[rel("/m/Cake/Rip", cue=True)],
                review=[rel("/m/Cake/Old")],
                kept=[rel("/m/Cake/Box/CD2", size=GIB)],
            ),
        ),
        ArtistPlan(Path("/m/Death"), error="beet exploded"),
        ArtistPlan(Path("/m/Dio"), already=3),
    ]


def test_the_report_totals_every_status_and_the_copy_size() -> None:
    text = report(sample())

    assert "Artists: 4 (ready 1, needs you 1, nothing to import 1, error 1)" in text
    assert "Folders already in beets: 8" in text
    assert "Folders to import: 3" in text
    assert "Copy size: 2.5 GiB" in text
    assert "Deletion candidates left out: 1" in text


def test_the_report_gives_the_batch_command_for_each_ready_artist() -> None:
    text = report(sample())

    assert "musicos batch /m/Isis --apply" in text
    assert "musicos batch /m/Cake --apply" not in text
    assert "- /m/Isis/Oceanic (1.0 GiB)" in text
    assert "3 lines of beets pretend output" in text


def test_the_report_says_what_each_artist_needs_from_the_user() -> None:
    text = report(sample())

    assert "choose one, then run batch again:" in text
    assert "  - /m/Cake/A" in text and "  - /m/Cake/B" in text
    assert "split first (musicos split): /m/Cake/Rip" in text
    assert "review: /m/Cake/Old" in text
    assert "multi-disc, run ingest on the parent folder: /m/Cake/Box/CD2" in text


def test_the_report_lists_errors_and_the_artists_with_nothing_to_import() -> None:
    text = report(sample())

    assert "- Death: beet exploded" in text
    assert "## Nothing to import\n\nDio" in text


def test_the_report_names_loose_audio_files_at_the_root() -> None:
    text = report(sample(), [Path("/m/stray.mp3")])

    assert "Loose audio files at the root: 1" in text
    assert "- /m/stray.mp3" in text


def test_the_report_cleans_control_characters_from_folder_names() -> None:
    odd = ArtistPlan(Path("/m/Bad\x1b[2JName"), error="x\ny")

    text = report([odd])

    assert "\x1b" not in text
    assert "Bad?[2JName: x?y" in text


def test_the_json_plan_holds_every_artist_with_its_status_and_folders() -> None:
    plan = plan_to_json(sample(), Path("/m"), WHEN)

    assert plan["root"] == "/m"
    assert plan["time"] == "2026-10-25T12:00:00"
    isis, cake, death, dio = plan["artists"]
    assert isis["name"] == "Isis" and isis["status"] == "ready"
    assert isis["already"] == 5
    assert isis["kept"] == [
        {"folder": "/m/Isis/Oceanic", "size": GIB, "tracks": 11},
        {"folder": "/m/Isis/Celestial", "size": GIB // 2, "tracks": 11},
    ]
    assert isis["candidates"] == ["/m/Isis/Oceanic [MP3]"]
    assert isis["pretend"] == ["a", "b", "c"]
    assert cake["undecided"] == [["/m/Cake/A", "/m/Cake/B"]]
    assert cake["to_split"] == ["/m/Cake/Rip"]
    assert cake["review"] == ["/m/Cake/Old"]
    assert cake["multi_disc"] == ["/m/Cake/Box/CD2"]
    assert death["status"] == "error" and death["error"] == "beet exploded"
    assert dio["status"] == "nothing to import"
