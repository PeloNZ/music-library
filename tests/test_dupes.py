import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from musicos.dupereport import activity_line, render_report
from musicos.dupes import (
    Release,
    Tags,
    audio_folders,
    cue_header,
    describe,
    find_duplicates,
    normalize,
    read_tags,
)
from musicos.rules import Decision, decide, rank

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
    read = tags_by_name({"Isis - Celestial.flac": flac("", 3000.0, artist="")})

    release = describe(folder, read)

    assert (release.artist, release.album) == ("Isis", "Celestial")
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
    **kw: Any,
) -> Release:
    base = {
        "folder": Path(folder),
        "artist": artist,
        "album": album,
        "disc": disc,
        "tracks": tracks,
        "seconds": 3000.0,
        "fmt": "FLAC 16/44.1",
        "size": 300 * 1048576,
        "cue": False,
        "unreadable": 0,
    }
    return Release(**{**base, **kw})


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


def test_a_folder_with_no_artist_is_in_no_group_when_several_artists_share_the_album() -> (
    None
):
    queen = [rel(f"/lib/q{n}", album="Greatest Hits", artist="Queen") for n in (1, 2)]
    abba = [rel(f"/lib/a{n}", album="Greatest Hits", artist="ABBA") for n in (1, 2)]
    unknown = rel("/lib/x", album="Greatest Hits", artist="")

    groups = find_duplicates([*queen, *abba, unknown])

    assert groups == [abba, queen]


def test_folders_with_no_artist_group_with_each_other_when_several_artists_share_the_album() -> (
    None
):
    queen = [rel(f"/lib/q{n}", album="Greatest Hits", artist="Queen") for n in (1, 2)]
    abba = [rel(f"/lib/a{n}", album="Greatest Hits", artist="ABBA") for n in (1, 2)]
    unknown = [rel(f"/lib/x{n}", album="Greatest Hits", artist="") for n in (1, 2)]

    groups = find_duplicates([*queen, *abba, *unknown])

    assert unknown in groups
    assert len(groups) == 3


def test_groups_come_out_in_artist_and_album_order() -> None:
    z = [rel("/z1", album="Zed", artist="Isis"), rel("/z2", album="Zed", artist="Isis")]
    a = [
        rel("/a1", album="Alpha", artist="Isis"),
        rel("/a2", album="Alpha", artist="Isis"),
    ]

    assert find_duplicates([*z, *a]) == [a, z]


WHEN = datetime(2026, 10, 24, 23, 40, 0)


def decided(*groups: list[Release]) -> list[list[Decision]]:
    return [decide(g) for g in groups]


def test_report_shows_each_group_as_a_table_with_relative_folders_and_actions() -> None:
    rip = rel("/lib/Isis/Isis - Celestial (2000) [EAC-FLAC]", tracks=11, cue=True)
    copy = rel("/lib/Isis/Disc/(2000) Celestial", size=120 * 1048576, fmt="FLAC 24/48")

    report = render_report(decided([rip, copy]), 9, Path("/lib/Isis"), WHEN)

    assert report.startswith("# Duplicate albums\n")
    assert "2026-10-24 23:40:00" in report
    assert "9 folders checked" in report and "1 group" in report
    assert "## Isis - Celestial (disc 1)" in report
    assert (
        "| Isis - Celestial (2000) [EAC-FLAC] | 11 | 50.0 | FLAC 16/44.1 | 300 MiB "
        "| cue rip | deletion candidate |"
    ) in report
    assert (
        "| Disc/(2000) Celestial | 11 | 50.0 | FLAC 24/48 | 120 MiB |  | keep |"
        in report
    )


def test_report_gives_the_reason_for_every_copy_that_is_not_kept() -> None:
    rip = rel("/lib/Isis/rip", cue=True, tracks=11)
    copy = rel("/lib/Isis/split", tracks=11)

    report = render_report(decided([rip, copy]), 2, Path("/lib/Isis"), WHEN)

    assert (
        "- rip: FLAC + cue file is lower priority than FLAC tracks already split"
        in report
    )
    assert "- split:" not in report


def test_report_summarises_the_deletion_candidates() -> None:
    rip = rel("/lib/rip", cue=True, size=300 * 1048576)
    split = rel("/lib/split")
    other = rel("/lib/o1", album="Other")
    other_mp3 = rel("/lib/o2", album="Other", kind="lossy", size=100 * 1048576)

    report = render_report(
        decided([rip, split], [other, other_mp3]), 4, Path("/lib"), WHEN
    )

    assert "2 deletion candidates (400 MiB)" in report


def test_report_marks_a_tie_and_a_review() -> None:
    a, b = rel("/lib/a"), rel("/lib/b")
    wav = rel("/lib/c", album="Z", kind="lossless", fmt="WAV 16/44.1")
    z2 = rel("/lib/d", album="Z")

    report = render_report(decided([a, b], [wav, z2]), 4, Path("/lib"), WHEN)

    assert "| tie: choose one |" in report
    assert "| review |" in report
    assert "WAV 16/44.1 is not in the ranking" in report


def test_report_notes_files_that_could_not_be_read() -> None:
    a = rel("/lib/a", unreadable=2)
    b = rel("/lib/b")

    assert "2 unreadable" in render_report(decided([a, b]), 2, Path("/lib"), WHEN)


def test_report_with_no_duplicates_says_so() -> None:
    report = render_report([], 5, Path("/lib"), WHEN)

    assert "No duplicate albums found." in report
    assert "0 groups" in report


def test_activity_line_counts_folders_groups_and_candidates() -> None:
    first = decided([rel("/a", cue=True), rel("/b")])
    second = decided(
        [
            rel("/c", album="X"),
            rel("/d", album="X", kind="lossy"),
            rel("/e", album="X", kind="lossy"),
        ]
    )

    assert activity_line(first + second, 12, WHEN) == (
        "2026-10-24 23:40:00 dupes 12 folders checked, 2 groups, 5 folders in groups, "
        "3 deletion candidates"
    )


needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def make_audio(path: Path, *extra: str) -> None:
    """One second of silence with the given ffmpeg options, as a real file."""
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=stereo",
        ]
        + ["-t", "1", *extra, str(path)],
        check=True,
    )


@needs_ffmpeg
def test_read_tags_reads_a_real_flac(tmp_path: Path) -> None:
    flac_file = tmp_path / "01.flac"
    make_audio(
        flac_file,
        "-metadata", "album=Oceanic",
        "-metadata", "artist=Isis",
        "-metadata", "date=2002-09-24",
        "-metadata", "discnumber=1/2",
    )  # fmt: skip

    tags = read_tags(flac_file)

    assert tags is not None
    assert (tags.album, tags.artist, tags.disc) == ("Oceanic", "Isis", "1")
    assert tags.fmt == "FLAC 16/44.1"
    assert 0.9 < tags.length < 1.1


@needs_ffmpeg
def test_read_tags_prefers_the_album_artist_and_names_an_mp3_by_bitrate(
    tmp_path: Path,
) -> None:
    mp3 = tmp_path / "01.mp3"
    make_audio(
        mp3, "-b:a", "128k",
        "-metadata", "album=Greatest Hits",
        "-metadata", "artist=Queen",
        "-metadata", "album_artist=Various Artists",
    )  # fmt: skip

    tags = read_tags(mp3)

    assert tags is not None
    assert tags.artist == "Various Artists"
    assert tags.fmt == "MP3 128k"


@needs_ffmpeg
def test_read_tags_of_an_untagged_file_has_empty_names(tmp_path: Path) -> None:
    flac_file = tmp_path / "01.flac"
    make_audio(flac_file)

    tags = read_tags(flac_file)

    assert tags is not None
    assert (tags.album, tags.artist) == ("", "")
    assert tags.disc == "1"


def test_read_tags_of_a_file_that_is_not_audio_is_none(tmp_path: Path) -> None:
    broken = tmp_path / "01.flac"
    broken.write_bytes(b"this is not a flac file")

    assert read_tags(broken) is None


def test_read_tags_of_a_missing_file_is_none(tmp_path: Path) -> None:
    assert read_tags(tmp_path / "missing.flac") is None


@needs_ffmpeg
@pytest.mark.parametrize("tag", ["0", "0/0", "00"])
def test_a_disc_number_of_zero_means_not_set_and_reads_as_disc_one(
    tmp_path: Path, tag: str
) -> None:
    flac_file = tmp_path / "01.flac"
    make_audio(flac_file, "-metadata", f"discnumber={tag}")

    tags = read_tags(flac_file)

    assert tags is not None
    assert tags.disc == "1"


@needs_ffmpeg
@pytest.mark.parametrize(
    ("name", "options", "kind"),
    [
        ("t.flac", ["-c:a", "flac"], "flac"),
        ("t.mp3", ["-c:a", "libmp3lame"], "lossy"),
        ("t.opus", ["-c:a", "libopus"], "lossy"),
        ("aac.m4a", ["-c:a", "aac"], "lossy"),
        ("alac.m4a", ["-c:a", "alac"], "lossless"),
        ("t.wav", [], "lossless"),
        ("t.aiff", [], "lossless"),
        ("t.tta", ["-c:a", "tta"], "lossless"),
    ],
)
def test_read_tags_tells_flac_other_lossless_and_lossy_apart(
    tmp_path: Path, name: str, options: list[str], kind: str
) -> None:
    path = tmp_path / name
    make_audio(path, *options)

    tags = read_tags(path)

    assert tags is not None
    assert tags.kind == kind


@needs_ffmpeg
def test_an_aac_file_is_named_by_bitrate_not_by_bit_depth(tmp_path: Path) -> None:
    path = tmp_path / "aac.m4a"
    make_audio(path, "-c:a", "aac", "-b:a", "128k")

    tags = read_tags(path)

    assert tags is not None
    assert tags.fmt.startswith("M4A ") and tags.fmt.endswith("k")
    assert "/" not in tags.fmt


def test_a_release_takes_the_most_common_kind_of_its_files(tmp_path: Path) -> None:
    folder = tmp_path / "x"
    touch(folder, "1.mp3", "2.mp3", "3.flac")
    read = tags_by_name(
        {
            "1.mp3": flac("A", kind="lossy"),
            "2.mp3": flac("A", kind="lossy"),
            "3.flac": flac("A", kind="flac"),
        }
    )

    assert describe(folder, read).kind == "lossy"


def test_a_macos_shadow_of_the_cue_sheet_is_not_the_cue_sheet(tmp_path: Path) -> None:
    folder = tmp_path / "Isis - Celestial (2000) [EAC-FLAC]"
    touch(folder, "Isis - Celestial.flac", data=b"big")
    (folder / "Isis - Celestial.cue").write_text(CUE)
    touch(folder, "._Isis - Celestial.cue", data=b"\x00\x05\x16\x07\x81")
    read = tags_by_name({"Isis - Celestial.flac": flac("", 3000.0, artist="")})

    release = describe(folder, read)

    assert (release.tracks, release.album) == (2, "Celestial")


def test_a_single_flac_with_two_cue_sheets_is_marked_ambiguous(tmp_path: Path) -> None:
    folder = tmp_path / "Isis - Celestial [EAC-FLAC]"
    touch(folder, "Isis - Celestial.flac", data=b"big")
    (folder / "a.cue").write_text(CUE)
    (folder / "b.cue").write_text(CUE)
    read = tags_by_name({"Isis - Celestial.flac": flac("Celestial", 3000.0)})

    release = describe(folder, read)

    assert release.ambiguous is True
    assert release.cue is False
    assert release.tracks == 1


def test_a_folder_with_no_readable_file_is_not_ranked_as_lossy(tmp_path: Path) -> None:
    folder = tmp_path / "x"
    touch(folder, "1.flac")

    release = describe(folder, lambda path: None)

    assert rank(release) is None
    reason = decide([release, rel("/other", kind="lossy", cue=False)])[0].reason
    assert reason == "no readable file is not in the ranking"


def test_cue_header_replaces_control_characters_in_names() -> None:
    text = 'PERFORMER "Isis\x1b[31m"\nTITLE "Cele\x07stial"\nTRACK 01 AUDIO\n'

    assert cue_header(text) == {"artist": "Isis?[31m", "album": "Cele?stial"}


@needs_ffmpeg
def test_read_tags_replaces_control_characters_in_names(tmp_path: Path) -> None:
    flac_file = tmp_path / "01.flac"
    make_audio(
        flac_file,
        "-metadata", "album=Oce\x1b[2Janic",
        "-metadata", "artist=Isis",
    )  # fmt: skip

    tags = read_tags(flac_file)

    assert tags is not None
    assert tags.album == "Oce?[2Janic"


def test_audio_folders_fails_when_the_root_is_gone(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        audio_folders(tmp_path / "gone")


def test_audio_folders_fails_when_a_folder_cannot_be_listed(tmp_path: Path) -> None:
    album = tmp_path / "Isis" / "Oceanic"
    album.mkdir(parents=True)
    (album / "01.flac").write_bytes(b"x")
    album.parent.chmod(0)
    try:
        with pytest.raises(PermissionError):
            audio_folders(tmp_path)
    finally:
        album.parent.chmod(0o755)
