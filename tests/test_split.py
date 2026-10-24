from pathlib import Path

from musicos.split import cue_track_count, read_cue

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
