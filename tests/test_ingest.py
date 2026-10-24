import json
from datetime import datetime
from pathlib import Path

from musicos.ingest import (
    dry_run_command,
    has_audio,
    import_command,
    make_batch_id,
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
    assert dry_run_command(SOURCE) == ["beet", "import", "--pretend", str(SOURCE)]


def test_assisted_import_logs_and_tags_the_batch() -> None:
    assert import_command(SOURCE, BATCH, LOGS, unattended=False) == [
        "beet",
        "import",
        "-l",
        f"/repo/beetsdir/logs/import-{BATCH}.log",
        "--set",
        f"musicos_batch={BATCH}",
        str(SOURCE),
    ]


def test_unattended_import_skips_what_it_cannot_match() -> None:
    cmd = import_command(SOURCE, BATCH, LOGS, unattended=True)

    assert cmd[-4:-1] == ["-q", "--quiet-fallback", "skip"]
    assert cmd[-1] == str(SOURCE)
    assert "-l" in cmd
    assert f"musicos_batch={BATCH}" in cmd


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
