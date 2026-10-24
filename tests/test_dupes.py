from datetime import datetime
from pathlib import Path

from musicos.dupes import (
    Release,
    Tags,
    activity_line,
    audio_folders,
    describe,
    find_duplicates,
    normalize,
    render_report,
)

CUE = """\
REM GENRE "Post-Metal"
REM DATE 2000
PERFORMER "Isis"
TITLE "Celestial"
FILE "Isis - Celestial.flac" WAVE
  TRACK 01 AUDIO
    TITLE "Celestial (The Tower)"
    INDEX 01 00:00:00
  TRACK 02 AUDIO
    TITLE "SGNL>05"
    INDEX 01 07:00:00
"""


def touch(root: Path, *names: str, data: bytes = b"x") -> None:
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def tags_by_name(table: dict[str, Tags]):  # type: ignore[no-untyped-def]
    def read(path: Path) -> Tags | None:
        return table.get(path.name)

    return read


def flac(album: str, length: float = 300.0, artist: str = "Isis", **kw: object) -> Tags:
    base = {
        "album": album,
        "artist": artist,
        "year": "2002",
        "disc": "1",
        "length": length,
        "fmt": "FLAC 16/44.1",
    }
    return Tags(**{**base, **kw})  # type: ignore[arg-type]


def test_audio_folders_lists_every_folder_with_audio_directly_inside(
    tmp_path: Path,
) -> None:
    touch(tmp_path, "A/(2000) Celestial/01.flac", "A/(2000) Celestial/02.flac")
    touch(tmp_path, "A/(2002) Oceanic/01.mp3", "B/cover.jpg", "B/notes.txt")

    assert audio_folders(tmp_path) == [
        tmp_path / "A" / "(2000) Celestial",
        tmp_path / "A" / "(2002) Oceanic",
    ]


def test_audio_folders_ignores_macos_resource_files(tmp_path: Path) -> None:
    touch(tmp_path, "A/._01.flac", "A/readme.txt")

    assert audio_folders(tmp_path) == []


def test_describe_summarises_a_folder_of_tracks(tmp_path: Path) -> None:
    folder = tmp_path / "Oceanic"
    touch(folder, "01.flac", "02.flac", "03.flac", data=b"12345")
    read = tags_by_name(
        {
            "01.flac": flac("Oceanic", 300.0),
            "02.flac": flac("Oceanic", 240.5),
            "03.flac": flac("Oceanic", 59.5),
        }
    )

    release = describe(folder, read)

    assert release == Release(
        folder=folder,
        artist="Isis",
        album="Oceanic",
        year="2002",
        disc="1",
        tracks=3,
        seconds=600.0,
        fmt="FLAC 16/44.1",
        size=15,
        cue=False,
        unreadable=0,
    )


def test_describe_takes_the_most_common_album_tag(tmp_path: Path) -> None:
    folder = tmp_path / "x"
    touch(folder, "1.flac", "2.flac", "3.flac")
    read = tags_by_name(
        {
            "1.flac": flac("Panopticon"),
            "2.flac": flac("Panopticon"),
            "3.flac": flac("Odd"),
        }
    )

    assert describe(folder, read).album == "Panopticon"


def test_describe_counts_files_it_cannot_read(tmp_path: Path) -> None:
    folder = tmp_path / "x"
    touch(folder, "1.flac", "2.flac")
    read = tags_by_name({"1.flac": flac("Oceanic")})

    release = describe(folder, read)

    assert release.tracks == 2
    assert release.unreadable == 1


def test_a_cue_rip_takes_its_track_count_and_names_from_the_cue(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "Isis - Celestial (2000) [EAC-FLAC]"
    touch(folder, "Isis - Celestial.flac", data=b"big")
    (folder / "Isis - Celestial.cue").write_text(CUE)
    read = tags_by_name({"Isis - Celestial.flac": flac("", 3000.0, artist="", year="")})

    release = describe(folder, read)

    assert (release.artist, release.album, release.year) == (
        "Isis",
        "Celestial",
        "2000",
    )
    assert release.tracks == 2  # from the cue, not the single FLAC file
    assert release.seconds == 3000.0
    assert release.cue


def test_describe_falls_back_to_unknown_when_nothing_is_tagged(tmp_path: Path) -> None:
    folder = tmp_path / "x"
    touch(folder, "1.mp3")

    release = describe(folder, lambda path: None)

    assert (release.artist, release.album) == ("", "")
    assert release.unreadable == 1


def rel(
    folder: str,
    album: str = "Celestial",
    artist: str = "Isis",
    disc: str = "1",
    tracks: int = 11,
    **kw: object,
) -> Release:
    base = {
        "folder": Path(folder),
        "artist": artist,
        "album": album,
        "year": "2000",
        "disc": disc,
        "tracks": tracks,
        "seconds": 3000.0,
        "fmt": "FLAC 16/44.1",
        "size": 300 * 1048576,
        "cue": False,
        "unreadable": 0,
    }
    return Release(**{**base, **kw})  # type: ignore[arg-type]


def test_normalize_ignores_case_accents_punctuation_and_bracketed_notes() -> None:
    assert normalize("In the Absence of Truth") == normalize("In The Absence Of Truth!")
    assert normalize("Motörhead") == normalize("motorhead")
    assert normalize("Celestial (Reissue 2016)") == normalize("Celestial")
    assert normalize("Panopticon [EAC-FLAC]") == normalize("Panopticon")
    assert normalize("The Mars Volta") == normalize("Mars Volta")


def test_normalize_keeps_a_title_made_only_of_a_bracket() -> None:
    assert normalize("(Untitled)") != ""


def test_the_same_album_in_two_folders_is_a_group() -> None:
    a = rel("/lib/Isis/Isis - Celestial (2000) [EAC-FLAC]", tracks=11)
    b = rel("/lib/Isis/Disc/(2000) Celestial", album="Celestial (Reissue)")
    c = rel("/lib/Isis/Oceanic", album="Oceanic")

    assert find_duplicates([a, b, c]) == [[a, b]]


def test_different_discs_of_one_album_are_not_duplicates() -> None:
    one = rel("/lib/x/CD1", album="Box", disc="1")
    two = rel("/lib/x/CD2", album="Box", disc="2")

    assert find_duplicates([one, two]) == []


def test_the_same_album_by_different_artists_is_not_a_duplicate() -> None:
    a = rel("/lib/a", album="Greatest Hits", artist="Queen")
    b = rel("/lib/b", album="Greatest Hits", artist="ABBA")

    assert find_duplicates([a, b]) == []


def test_a_folder_with_no_album_tag_is_grouped_by_its_name() -> None:
    tagged = rel("/lib/Isis/(2004) Panopticon", album="Panopticon")
    untagged = rel("/lib/Isis/[2004] Panopticon", album="", artist="")

    assert find_duplicates([tagged, untagged]) == [[tagged, untagged]]


def test_groups_come_out_in_artist_and_album_order() -> None:
    z = [rel("/z1", album="Zed", artist="Isis"), rel("/z2", album="Zed", artist="Isis")]
    a = [
        rel("/a1", album="Alpha", artist="Isis"),
        rel("/a2", album="Alpha", artist="Isis"),
    ]

    assert find_duplicates([*z, *a]) == [a, z]


WHEN = datetime(2026, 10, 24, 23, 40, 0)


def test_report_shows_each_group_as_a_table_with_relative_folders() -> None:
    rip = rel("/lib/Isis/Isis - Celestial (2000) [EAC-FLAC]", tracks=11, cue=True)
    copy = rel("/lib/Isis/Disc/(2000) Celestial", size=120 * 1048576, fmt="FLAC 24/48")

    report = render_report([[rip, copy]], 9, Path("/lib/Isis"), WHEN)

    assert report.startswith("# Duplicate albums\n")
    assert "2026-10-24 23:40:00" in report
    assert "9 folders checked" in report and "1 group" in report
    assert "## Isis - Celestial (disc 1)" in report
    assert (
        "| Isis - Celestial (2000) [EAC-FLAC] | 11 | 50.0 | FLAC 16/44.1 | 300 MiB | cue rip |"
        in report
    )
    assert "| Disc/(2000) Celestial | 11 | 50.0 | FLAC 24/48 | 120 MiB |  |" in report


def test_report_notes_files_that_could_not_be_read() -> None:
    a = rel("/lib/a", unreadable=2)
    b = rel("/lib/b")

    assert "2 unreadable" in render_report([[a, b]], 2, Path("/lib"), WHEN)


def test_report_with_no_duplicates_says_so() -> None:
    report = render_report([], 5, Path("/lib"), WHEN)

    assert "No duplicate albums found." in report
    assert "0 groups" in report


def test_activity_line_counts_folders_groups_and_folders_in_groups() -> None:
    groups = [
        [rel("/a"), rel("/b")],
        [rel("/c", album="X"), rel("/d", album="X"), rel("/e", album="X")],
    ]

    assert (
        activity_line(groups, 12, WHEN)
        == "2026-10-24 23:40:00 dupes 12 folders checked, 2 groups, 5 folders in groups"
    )
