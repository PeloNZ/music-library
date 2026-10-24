from pathlib import Path

from musicos.dupes import Release, Tags, audio_folders, describe

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
