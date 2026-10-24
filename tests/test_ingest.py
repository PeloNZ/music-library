import json
from datetime import datetime
from pathlib import Path

import pytest

from musicos.ingest import (
    LogEntry,
    batch_items,
    dry_run_command,
    has_audio,
    import_command,
    make_batch_id,
    parse_import_log,
    read_import_logs,
    retry_command,
    summarize_batch,
)
from musicos.runner import Output

WHEN = datetime(2026, 10, 24, 21, 40)


def test_batch_id_is_timestamp_and_folder_slug() -> None:
    assert (
        make_batch_id(WHEN, Path("/inbox/Gatecreeper-2019-Deserted"))
        == "20261024-2140-gatecreeper-2019-deserted"
    )


def test_batch_id_slug_drops_accents_and_punctuation() -> None:
    assert make_batch_id(WHEN, Path("/inbox/Motörhead (Live!)")) == (
        "20261024-2140-motorhead-live"
    )


def test_batch_id_slug_is_cut_at_40_characters() -> None:
    folder = Path("/inbox/Red Hot Chili Peppers - What Hits! (1992) {FLAC} vtwin88cube")

    assert make_batch_id(WHEN, folder) == (
        "20261024-2140-red-hot-chili-peppers-what-hits-1992-fla"
    )


SOURCE = Path("/Volumes/music/_inbox/Gatecreeper-2019-Deserted")
BATCH = "20261024-2140-gatecreeper-2019-deserted"
LOGS = Path("/repo/beetsdir/logs")


def test_dry_run_only_lists_files() -> None:
    assert dry_run_command([SOURCE]) == ["beet", "import", "--pretend", str(SOURCE)]


def test_incremental_dry_run_leaves_out_folders_beets_imported_before() -> None:
    assert dry_run_command([SOURCE], incremental=True) == [
        "beet",
        "import",
        "--pretend",
        "-i",
        str(SOURCE),
    ]


def test_dry_run_of_several_folders_lists_each() -> None:
    other = Path("/Volumes/music/_inbox/Other")

    assert dry_run_command([SOURCE, other])[-2:] == [str(SOURCE), str(other)]


def test_assisted_import_logs_and_tags_the_batch() -> None:
    assert import_command([SOURCE], BATCH, LOGS, unattended=False) == [
        "beet",
        "import",
        "-l",
        f"/repo/beetsdir/logs/import-{BATCH}.log",
        "--set",
        f"musicos_batch={BATCH}",
        str(SOURCE),
    ]


def test_an_import_imports_a_folder_again_unless_asked_to_be_incremental() -> None:
    plain = import_command([SOURCE], BATCH, LOGS, unattended=True)
    incremental = import_command(
        [SOURCE], BATCH, LOGS, unattended=True, incremental=True
    )

    assert "-i" not in plain and "-R" not in plain
    assert incremental[2:4] == ["-i", "-R"]


def test_import_of_several_folders_is_one_command() -> None:
    other = Path("/Volumes/music/_inbox/Other")

    cmd = import_command([SOURCE, other], BATCH, LOGS, unattended=True)

    assert cmd.count("beet") == 1
    assert cmd[-2:] == [str(SOURCE), str(other)]


def test_unattended_import_skips_what_it_cannot_match() -> None:
    cmd = import_command([SOURCE], BATCH, LOGS, unattended=True)

    assert cmd[-4:-1] == ["-q", "--quiet-fallback", "skip"]
    assert cmd[-1] == str(SOURCE)
    assert "-l" in cmd
    assert f"musicos_batch={BATCH}" in cmd


def test_retry_command_imports_only_the_skipped_folders_with_prompts() -> None:
    skipped = [Path("/lib/Isis/A"), Path("/lib/Isis/B")]

    cmd = retry_command(skipped, BATCH, LOGS)

    assert "-q" not in cmd
    assert cmd[2:4] == ["-i", "-R"]
    assert cmd[-2:] == ["/lib/Isis/A", "/lib/Isis/B"]
    assert f"musicos_batch={BATCH}" in cmd
    assert cmd[cmd.index("-l") + 1] == f"/repo/beetsdir/logs/import-{BATCH}-retry.log"


def test_a_retry_log_replaces_the_skips_of_the_first_run(tmp_path: Path) -> None:
    (tmp_path / f"import-{BATCH}.log").write_text("skip /a\nskip /b\nasis /c\n")
    (tmp_path / f"import-{BATCH}-retry.log").write_text("skip /b\n")

    entries = read_import_logs(tmp_path, BATCH)

    assert entries == [LogEntry("asis", "/c"), LogEntry("skip", "/b")]


def test_the_first_log_stands_when_nothing_was_retried(tmp_path: Path) -> None:
    (tmp_path / f"import-{BATCH}.log").write_text("skip /a\n")

    assert read_import_logs(tmp_path, BATCH) == [LogEntry("skip", "/a")]


def test_no_log_means_no_entries(tmp_path: Path) -> None:
    assert read_import_logs(tmp_path, BATCH) == []


def album(name: str, mb_albumid: str) -> dict[str, object]:
    return {
        "id": 1,
        "album": name,
        "albumartist": "Gatecreeper",
        "year": 2019,
        "mb_albumid": mb_albumid,
    }


def test_summary_flags_albums_with_no_musicbrainz_id() -> None:
    exported = json.dumps([album("Deserted", "abc-123"), album("Unknown", "")])
    seen: list[list[str]] = []

    def run(cmd: list[str]) -> Output:
        seen.append(cmd)
        return Output(exported, "", 0)

    summary = summarize_batch(run, BATCH)

    assert summary.albums == 2
    assert [a["album"] for a in summary.flagged] == ["Unknown"]
    assert seen[0][:4] == ["beet", "export", "-a", "-f"]
    assert seen[0][-1] == f"musicos_batch:{BATCH}"


def test_summary_of_an_empty_batch() -> None:
    summary = summarize_batch(lambda cmd: Output("", "", 0), BATCH)

    assert summary.albums == 0
    assert summary.flagged == []


def test_has_audio_finds_a_track_in_a_subfolder(tmp_path: Path) -> None:
    (tmp_path / "Disc 1").mkdir()
    (tmp_path / "Disc 1" / "01 Intro.FLAC").write_bytes(b"")

    assert has_audio(tmp_path)


def test_has_audio_ignores_art_and_logs(tmp_path: Path) -> None:
    (tmp_path / "cover.jpg").write_bytes(b"")
    (tmp_path / "rip.log").write_text("")
    (tmp_path / "album.cue").write_text("")

    assert not has_audio(tmp_path)


def test_a_failing_export_is_an_error_not_an_empty_batch() -> None:
    def run(cmd: list[str]) -> Output:
        return Output("", "error: no such field\n", 1)

    with pytest.raises(RuntimeError, match="no such field"):
        summarize_batch(run, BATCH)


def test_batch_items_lists_the_paths_beets_holds_for_a_batch() -> None:
    seen: list[list[str]] = []

    def run(cmd: list[str]) -> Output:
        seen.append(cmd)
        return Output("/lib/a/01.flac\n\n/lib/a/02.flac\n", "", 0)

    assert batch_items(run, BATCH) == ["/lib/a/01.flac", "/lib/a/02.flac"]
    assert seen == [["beet", "ls", "-f", "$path", f"musicos_batch:{BATCH}"]]


def test_batch_items_raises_when_beet_fails() -> None:
    def run(cmd: list[str]) -> Output:
        return Output("", "error: boom\n", 1)

    with pytest.raises(RuntimeError, match="boom"):
        batch_items(run, BATCH)


IMPORT_LOG = """\
import started Sat Oct 24 22:04:41 2026
skip music-test/src/Cake/Comfort Eagle
skip music-test/src/Cake/Fashion Nugget
asis /inbox/Unknown Artist/Demo
duplicate-skip /inbox/Opeth/Heritage
"""


def test_parse_import_log_returns_each_skipped_path_with_its_kind() -> None:
    assert parse_import_log(IMPORT_LOG) == [
        LogEntry("skip", "music-test/src/Cake/Comfort Eagle"),
        LogEntry("skip", "music-test/src/Cake/Fashion Nugget"),
        LogEntry("asis", "/inbox/Unknown Artist/Demo"),
        LogEntry("duplicate-skip", "/inbox/Opeth/Heritage"),
    ]


def test_parse_import_log_ignores_the_header_and_blank_lines() -> None:
    assert parse_import_log("import started Sat Oct 24 22:04:41 2026\n\n") == []


def test_batch_id_of_a_folder_named_in_another_script_has_a_slug() -> None:
    assert make_batch_id(WHEN, Path("/inbox/日本語")) == "20261024-2140-import"


def test_has_audio_ignores_macos_shadow_files(tmp_path: Path) -> None:
    (tmp_path / "._01.flac").write_bytes(b"\x00\x05\x16\x07")

    assert not has_audio(tmp_path)
