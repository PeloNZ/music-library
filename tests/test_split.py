from pathlib import Path

import pytest

from musicos.split import (
    Rip,
    SplitError,
    cue_track_count,
    read_cue,
    scan,
    split_rip,
)
from tests.fakes import Tools

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


def make_rip(tmp_path: Path) -> Rip:
    folder = tmp_path / "src" / "Gatecreeper-2019-Deserted"
    folder.mkdir(parents=True)
    flac, cue = folder / "Deserted.flac", folder / "Deserted.cue"
    flac.write_bytes(b"big")
    cue.write_text(CUE)
    (folder / "rip.log").write_text("log")
    return Rip(folder, flac, cue)


def test_split_puts_tracks_in_the_inbox_and_the_source_in_holding(
    tmp_path: Path,
) -> None:
    rip = make_rip(tmp_path)
    tools = Tools()

    result = split_rip(rip, tmp_path / "inbox", tmp_path / "holding", tools)

    album = tmp_path / "inbox" / "Gatecreeper-2019-Deserted"
    assert result.tracks == [album / f"split-track0{n}.flac" for n in (1, 2, 3)]
    assert result.track_count == 3
    held = tmp_path / "holding" / "Gatecreeper-2019-Deserted"
    assert result.holding == held
    assert sorted(p.name for p in held.iterdir()) == [
        "Deserted.cue",
        "Deserted.flac",
        "rip.log",
    ]
    assert not rip.folder.exists()
    assert [p.name for p in (tmp_path / "inbox").iterdir()] == [album.name]


def test_split_runs_the_three_tools_in_order(tmp_path: Path) -> None:
    rip = make_rip(tmp_path)
    tools = Tools()

    split_rip(rip, tmp_path / "inbox", tmp_path / "holding", tools)

    assert [c[0] for c in tools.commands] == ["cuebreakpoints", "shnsplit", "cuetag.sh"]
    assert tools.commands[0] == ["cuebreakpoints", str(rip.cue)]
    shnsplit = tools.commands[1]
    assert shnsplit[-1] == str(rip.flac)
    assert shnsplit[shnsplit.index("-o") + 1] == "flac"
    cuetag = tools.commands[2]
    assert cuetag[1] == str(rip.cue)
    assert len(cuetag) == 2 + 3


def assert_nothing_changed(rip: Rip, tmp_path: Path) -> None:
    assert rip.flac.read_bytes() == b"big"
    assert rip.cue.exists()
    inbox = tmp_path / "inbox"
    assert not inbox.exists() or list(inbox.iterdir()) == []
    assert not (tmp_path / "holding").exists()


def test_split_with_the_wrong_track_count_changes_nothing(tmp_path: Path) -> None:
    rip = make_rip(tmp_path)

    with pytest.raises(SplitError, match="3 tracks.*made 2"):
        split_rip(rip, tmp_path / "inbox", tmp_path / "holding", Tools(tracks_made=2))

    assert_nothing_changed(rip, tmp_path)


@pytest.mark.parametrize("tool", ["cuebreakpoints", "shnsplit", "cuetag.sh"])
def test_split_with_a_failing_tool_changes_nothing(tmp_path: Path, tool: str) -> None:
    rip = make_rip(tmp_path)

    with pytest.raises(SplitError, match=f"{tool}: boom"):
        split_rip(rip, tmp_path / "inbox", tmp_path / "holding", Tools(fail=tool))

    assert_nothing_changed(rip, tmp_path)


def test_split_of_a_cue_with_no_tracks_changes_nothing(tmp_path: Path) -> None:
    rip = make_rip(tmp_path)
    rip.cue.write_text('PERFORMER "x"\n')
    tools = Tools()

    with pytest.raises(SplitError, match="no audio tracks"):
        split_rip(rip, tmp_path / "inbox", tmp_path / "holding", tools)

    assert tools.commands == []
    assert_nothing_changed(rip, tmp_path)


def test_split_never_overwrites_an_existing_album(tmp_path: Path) -> None:
    rip = make_rip(tmp_path)
    existing = tmp_path / "inbox" / "Gatecreeper-2019-Deserted"
    existing.mkdir(parents=True)
    (existing / "keep.flac").write_bytes(b"keep")

    with pytest.raises(SplitError, match="already exists"):
        split_rip(rip, tmp_path / "inbox", tmp_path / "holding", Tools())

    assert (existing / "keep.flac").read_bytes() == b"keep"
    assert rip.flac.exists()
