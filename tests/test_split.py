from pathlib import Path

from musicos.split import Rip, cue_track_count, read_cue, scan

CUE = """\
REM GENRE "Death Metal"
PERFORMER "Gatecreeper"
TITLE "Deserted"
FILE "Gatecreeper - Deserted.flac" WAVE
  TRACK 01 AUDIO
    TITLE "Deserted"
    INDEX 01 00:00:00
  TRACK 02 AUDIO
    TITLE "Puncture Wounds"
    INDEX 01 05:20:56
  TRACK 03 AUDIO
    TITLE "From The Ashes"
    INDEX 01 08:08:32
"""


def test_track_count_is_the_number_of_audio_tracks() -> None:
    assert cue_track_count(CUE) == 3


def test_track_count_ignores_data_tracks_and_titles_that_say_track() -> None:
    cue = CUE + '  TRACK 04 MODE1/2352\n    TITLE "TRACK 05 AUDIO"\n'

    assert cue_track_count(cue) == 3


def test_track_count_of_text_with_no_tracks_is_zero() -> None:
    assert cue_track_count('PERFORMER "x"\n') == 0


def test_read_cue_decodes_utf8_with_a_byte_order_mark(tmp_path: Path) -> None:
    cue = tmp_path / "a.cue"
    cue.write_bytes(b'\xef\xbb\xbfTITLE "Mot\xc3\xb6rhead"\n')

    assert read_cue(cue) == 'TITLE "Motörhead"\n'


def test_read_cue_falls_back_to_windows_1252(tmp_path: Path) -> None:
    cue = tmp_path / "a.cue"
    cue.write_bytes(b'TITLE "Mot\xf6rhead"\n')

    assert read_cue(cue) == 'TITLE "Motörhead"\n'


def touch(root: Path, *names: str) -> Path:
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    return root


def test_scan_finds_a_folder_with_one_flac_and_one_cue(tmp_path: Path) -> None:
    touch(tmp_path, "Opeth/Heritage/a.flac", "Opeth/Heritage/a.cue")

    result = scan(tmp_path)

    folder = tmp_path / "Opeth" / "Heritage"
    assert result.rips == [Rip(folder, folder / "a.flac", folder / "a.cue")]
    assert result.ambiguous == []


def test_scan_matches_suffixes_in_any_case(tmp_path: Path) -> None:
    touch(tmp_path, "Chevelle/Point 1/Point.FLAC", "Chevelle/Point 1/Point #1.CUE")

    assert len(scan(tmp_path).rips) == 1


def test_scan_skips_folders_with_one_flac_per_track(tmp_path: Path) -> None:
    touch(tmp_path, "A/1.flac", "A/2.flac", "A/3.flac", "A/a.cue")

    result = scan(tmp_path)

    assert result.rips == []
    assert result.ambiguous == []


def test_scan_skips_a_flac_with_no_cue(tmp_path: Path) -> None:
    touch(tmp_path, "A/a.flac", "A/cover.jpg")

    assert scan(tmp_path).rips == []


def test_scan_reports_one_flac_with_several_cues_as_ambiguous(
    tmp_path: Path,
) -> None:
    touch(tmp_path, "H/h.flac", "H/h.cue", "H/h_utf.cue")

    result = scan(tmp_path)

    assert result.rips == []
    assert result.ambiguous == [tmp_path / "H"]


def test_scan_ignores_macos_resource_files(tmp_path: Path) -> None:
    touch(tmp_path, "A/a.flac", "A/a.cue", "A/._a.flac", "A/._a.cue")

    assert len(scan(tmp_path).rips) == 1


def test_scan_lists_rips_in_path_order(tmp_path: Path) -> None:
    touch(tmp_path, "B/b.flac", "B/b.cue", "A/a.flac", "A/a.cue")

    assert [r.folder.name for r in scan(tmp_path).rips] == ["A", "B"]
