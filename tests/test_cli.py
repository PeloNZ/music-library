import errno
import os
from datetime import datetime
from pathlib import Path

import pytest

from musicos.changelog import read_entries, record
from musicos.cli import main
from musicos.dupes import Tags
from musicos.plex import Response
from musicos.runner import Output, Run
from tests.fakes import FakeHttp, Tools
from tests.test_appledouble import shadow
from tests.test_split import CUE

MOUNTS = "//chrisw@192.168.0.63/music on /Volumes/music (smbfs, nodev)\n"
VERSION = "beets version 2.14.1\nplugins: chroma, missing\n"


def make_beetsdir(tmp_path: Path) -> dict[str, str]:
    (tmp_path / "config.yaml").write_text(
        "directory: /Volumes/music\nplugins: chroma missing\n"
    )
    return {"BEETSDIR": str(tmp_path)}


def fake_run(mounts: str = MOUNTS, beet_code: int = 0):  # type: ignore[no-untyped-def]
    def run(cmd: list[str]) -> Output:
        if cmd[0] == "mount":
            return Output(mounts, "", 0)
        return Output(VERSION, "boom: bad config" if beet_code else "", beet_code)

    return run


def test_preflight_passes_when_everything_is_in_place(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["preflight"], env=make_beetsdir(tmp_path), run=fake_run())

    assert code == 0
    assert "FAIL" not in capsys.readouterr().out


def test_preflight_fails_when_share_is_not_mounted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["preflight"], env=make_beetsdir(tmp_path), run=fake_run(mounts=""))

    assert code == 1
    assert "FAIL mount" in capsys.readouterr().out


def test_preflight_fails_when_beetsdir_is_unset(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["preflight"], env={}, run=fake_run())

    assert code == 1
    assert "FAIL beetsdir" in capsys.readouterr().out


def test_preflight_reports_a_failing_beet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["preflight"], env=make_beetsdir(tmp_path), run=fake_run(beet_code=1))

    assert code == 1
    assert "FAIL beet: boom: bad config" in capsys.readouterr().out


def test_preflight_reports_a_failing_beet_with_no_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def run(cmd: list[str]) -> Output:
        return Output(MOUNTS, "", 0) if cmd[0] == "mount" else Output("", "", 1)

    code = main(["preflight"], env=make_beetsdir(tmp_path), run=run)

    assert code == 1
    assert "FAIL beet:" in capsys.readouterr().out


NOW = datetime(2026, 10, 24, 21, 30, 5)


def lint_run(duplicates: str = "") -> Run:
    def run(cmd: list[str]) -> Output:
        if cmd[0] == "mount":
            return Output(MOUNTS, "", 0)
        if cmd == ["beet", "version"]:
            return Output(VERSION, "", 0)
        return Output(duplicates if cmd == ["beet", "duplicates"] else "", "", 0)

    return run


def test_lint_writes_the_report_and_one_log_line(tmp_path: Path) -> None:
    env = make_beetsdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "last-health-report.md").write_text("old report")

    code = main(["lint"], env=env, run=lint_run("Opeth - Heritage\n"), now=lambda: NOW)

    assert code == 0
    report = (tmp_path / "logs" / "last-health-report.md").read_text()
    assert "| duplicates | 1 |" in report
    assert "old report" not in report
    log = (tmp_path / "logs" / "musicos-activity.log").read_text()
    assert log == "2026-10-24 21:30:05 lint 1 issues across 1 categories\n"


def test_lint_appends_to_the_activity_log(tmp_path: Path) -> None:
    env = make_beetsdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "musicos-activity.log").write_text("earlier line\n")

    main(["lint"], env=env, run=lint_run(), now=lambda: NOW)

    log = (tmp_path / "logs" / "musicos-activity.log").read_text()
    assert log.startswith("earlier line\n")
    assert log.endswith("lint 0 issues across 0 categories\n")


def test_lint_does_nothing_when_preflight_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = lambda cmd: Output("", "", 0)

    code = main(["lint"], env=make_beetsdir(tmp_path), run=run, now=lambda: NOW)

    assert code == 1
    assert "FAIL mount" in capsys.readouterr().out
    assert not (tmp_path / "logs").exists()


EXPORT = '[{"id": 1, "album": "Deserted", "mb_albumid": ""}]'


class Recorder:
    """Fake runner that records every command it is given."""

    def __init__(self, import_code: int = 0, dry_run_code: int = 0) -> None:
        self.commands: list[list[str]] = []
        self.import_code = import_code
        self.dry_run_code = dry_run_code

    def __call__(self, cmd: list[str]) -> Output:
        self.commands.append(cmd)
        if cmd[0] == "mount":
            return Output(MOUNTS, "", 0)
        if cmd == ["beet", "version"]:
            return Output(VERSION, "", 0)
        if cmd[:3] == ["beet", "import", "--pretend"]:
            if self.dry_run_code:
                return Output("", "error: no such folder\n", self.dry_run_code)
            # beets prints the --pretend list to stderr, not stdout
            return Output("", "Album: x\n  x/01.flac\n", 0)
        if cmd[:2] == ["beet", "import"]:
            return Output(
                "", "import failed" if self.import_code else "", self.import_code
            )
        if cmd[:2] == ["beet", "export"]:
            return Output(EXPORT, "", 0)
        if cmd[:2] == ["beet", "ls"]:
            return Output("/lib/Gatecreeper/01.flac\n/lib/Gatecreeper/02.flac\n", "", 0)
        return Output("", "", 0)

    def ran_import(self) -> bool:
        return any(
            c[:2] == ["beet", "import"] and "--pretend" not in c for c in self.commands
        )


def make_source(tmp_path: Path) -> Path:
    source = tmp_path / "inbox" / "Deserted"
    source.mkdir(parents=True)
    (source / "01.flac").write_bytes(b"")
    return source


def test_ingest_prints_the_command_and_does_not_import(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    beets = tmp_path / "beets"
    beets.mkdir()
    run = Recorder()

    code = main(
        ["ingest", str(make_source(tmp_path))],
        env=make_beetsdir(beets),
        run=run,
        now=lambda: NOW,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "Album: x" in out
    assert "uv run beet import -l " in out
    assert "musicos_batch=20261024-2130-deserted" in out
    assert "-q" not in out
    assert not run.ran_import()


def test_ingest_stops_when_the_source_has_no_audio(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    beets = tmp_path / "beets"
    beets.mkdir()
    empty = tmp_path / "empty"
    empty.mkdir()

    code = main(
        ["ingest", str(empty)],
        env=make_beetsdir(beets),
        run=Recorder(),
        now=lambda: NOW,
    )

    assert code == 1
    assert "FAIL source" in capsys.readouterr().out


def test_unattended_ingest_imports_summarises_and_logs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    beets = tmp_path / "beets"
    beets.mkdir()
    run = Recorder()

    code = main(
        ["ingest", str(make_source(tmp_path)), "--unattended"],
        env=make_beetsdir(beets),
        run=run,
        now=lambda: NOW,
    )

    assert code == 0
    assert run.ran_import()
    assert "1 albums, 1 without a MusicBrainz match" in capsys.readouterr().out
    log = (beets / "logs" / "musicos-activity.log").read_text()
    assert (
        log == "2026-10-24 21:30:05 ingest 20261024-2130-deserted 1 albums, 1 flagged\n"
    )


def test_unattended_ingest_reports_a_failed_import(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    beets = tmp_path / "beets"
    beets.mkdir()

    code = main(
        ["ingest", str(make_source(tmp_path)), "--unattended"],
        env=make_beetsdir(beets),
        run=Recorder(import_code=1),
        now=lambda: NOW,
    )

    assert code == 1
    assert "FAIL import: import failed" in capsys.readouterr().out
    assert not (beets / "logs" / "musicos-activity.log").exists()


def test_summary_reads_a_finished_batch_and_logs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    beets = tmp_path / "beets"
    beets.mkdir()

    code = main(
        ["summary", "20261024-2130-deserted"],
        env=make_beetsdir(beets),
        run=Recorder(),
        now=lambda: NOW,
    )

    assert code == 0
    assert "Deserted" in capsys.readouterr().out
    log = (beets / "logs" / "musicos-activity.log").read_text()
    assert log.endswith("ingest 20261024-2130-deserted 1 albums, 1 flagged\n")


def fill_log(beets: Path) -> None:
    log = beets / "logs" / "changes.jsonl"
    record(
        log,
        "import",
        datetime(2026, 10, 23, 9, 0, 0),
        batch="b1",
        albums=2,
        items=["/lib/a.flac", "/lib/b.flac", "/lib/c.flac"],
        source="/inbox/x",
    )
    record(
        log, "move", datetime(2026, 10, 24, 9, 0, 0), batch="b2", moved=[["/a", "/b"]]
    )


def test_log_prints_one_line_per_entry_with_lists_as_counts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fill_log(tmp_path)

    code = main(["log"], env=make_beetsdir(tmp_path), run=fake_run())

    assert code == 0
    assert capsys.readouterr().out.splitlines() == [
        "2026-10-23T09:00:00 import batch=b1 albums=2 items=3 source=/inbox/x",
        "2026-10-24T09:00:00 move batch=b2 moved=1",
    ]


def test_log_filters_by_batch_and_action(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fill_log(tmp_path)

    main(["log", "--batch", "b2"], env=make_beetsdir(tmp_path), run=fake_run())
    by_batch = capsys.readouterr().out
    main(["log", "--action", "import"], env=make_beetsdir(tmp_path), run=fake_run())
    by_action = capsys.readouterr().out

    assert by_batch.count("\n") == 1 and "move" in by_batch
    assert by_action.count("\n") == 1 and "import" in by_action


def test_log_filters_by_start_date_and_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fill_log(tmp_path)

    main(["log", "--since", "2026-10-24"], env=make_beetsdir(tmp_path), run=fake_run())
    since = capsys.readouterr().out
    main(["log", "--last", "1"], env=make_beetsdir(tmp_path), run=fake_run())
    last = capsys.readouterr().out

    assert since == last
    assert "move" in since


def test_log_json_prints_the_raw_entries(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fill_log(tmp_path)

    main(["log", "--json", "--last", "1"], env=make_beetsdir(tmp_path), run=fake_run())

    raw = (tmp_path / "logs" / "changes.jsonl").read_text().splitlines()[-1]
    assert capsys.readouterr().out == raw + "\n"


def test_log_says_when_nothing_was_recorded(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["log"], env=make_beetsdir(tmp_path), run=fake_run())

    assert code == 0
    assert "no changes recorded" in capsys.readouterr().out


def test_log_needs_no_mounted_share(tmp_path: Path) -> None:
    fill_log(tmp_path)

    code = main(["log"], env=make_beetsdir(tmp_path), run=fake_run(mounts=""))

    assert code == 0


def test_log_reports_a_corrupt_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fill_log(tmp_path)
    with (tmp_path / "logs" / "changes.jsonl").open("a") as f:
        f.write("{oops\n")

    code = main(["log"], env=make_beetsdir(tmp_path), run=fake_run())

    assert code == 1
    assert "line 3" in capsys.readouterr().out


def test_log_fails_when_beetsdir_is_unset(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["log"], env={}, run=fake_run())

    assert code == 1
    assert "FAIL beetsdir" in capsys.readouterr().out


def test_summary_reports_a_failing_export_and_logs_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    class BrokenExport(Recorder):
        def __call__(self, cmd: list[str]) -> Output:
            if cmd[:2] == ["beet", "export"]:
                return Output("", "error: no such field\n", 1)
            return super().__call__(cmd)

    beets = tmp_path / "beets"
    beets.mkdir()

    code = main(
        ["summary", "b1"], env=make_beetsdir(beets), run=BrokenExport(), now=lambda: NOW
    )

    assert code == 1
    assert "FAIL summary: error: no such field" in capsys.readouterr().out
    assert not (beets / "logs").exists()


def test_unattended_ingest_records_the_import_in_the_change_log(
    tmp_path: Path,
) -> None:
    beets = tmp_path / "beets"
    beets.mkdir()
    source = make_source(tmp_path)

    main(
        ["ingest", str(source), "--unattended"],
        env=make_beetsdir(beets),
        run=Recorder(),
        now=lambda: NOW,
    )

    entries = read_entries(beets / "logs" / "changes.jsonl")
    assert entries == [
        {
            "time": "2026-10-24T21:30:05",
            "action": "import",
            "batch": "20261024-2130-deserted",
            "source": str(source.resolve()),
            "albums": 1,
            "flagged": 1,
            "skipped": [],
            "items": ["/lib/Gatecreeper/01.flac", "/lib/Gatecreeper/02.flac"],
        }
    ]


def test_summary_records_the_import_without_a_source(tmp_path: Path) -> None:
    beets = tmp_path / "beets"
    beets.mkdir()

    main(["summary", "b1"], env=make_beetsdir(beets), run=Recorder(), now=lambda: NOW)

    (entry,) = read_entries(beets / "logs" / "changes.jsonl")
    assert entry["batch"] == "b1"
    assert "source" not in entry
    assert len(entry["items"]) == 2


def write_import_log(beets: Path, batch: str, text: str) -> None:
    (beets / "logs").mkdir(exist_ok=True)
    (beets / "logs" / f"import-{batch}.log").write_text(text)


def test_summary_lists_the_albums_the_importer_skipped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    beets = tmp_path / "beets"
    beets.mkdir()
    write_import_log(
        beets,
        "b1",
        "import started Sat Oct 24 22:04:41 2026\n"
        "skip /inbox/Cake/Fashion Nugget\n"
        "asis /inbox/Demo\n",
    )

    main(["summary", "b1"], env=make_beetsdir(beets), run=Recorder(), now=lambda: NOW)

    out = capsys.readouterr().out
    assert "2 logged by the importer" in out
    assert "  skip: /inbox/Cake/Fashion Nugget" in out
    assert "  asis: /inbox/Demo" in out
    (entry,) = read_entries(beets / "logs" / "changes.jsonl")
    assert entry["skipped"] == [
        {"kind": "skip", "path": "/inbox/Cake/Fashion Nugget"},
        {"kind": "asis", "path": "/inbox/Demo"},
    ]


def test_summary_without_an_import_log_lists_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    beets = tmp_path / "beets"
    beets.mkdir()

    main(["summary", "b1"], env=make_beetsdir(beets), run=Recorder(), now=lambda: NOW)

    assert "logged by the importer" not in capsys.readouterr().out
    (entry,) = read_entries(beets / "logs" / "changes.jsonl")
    assert entry["skipped"] == []


def test_ingest_records_the_source_as_an_absolute_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    beets = tmp_path / "beets"
    beets.mkdir()
    source = make_source(tmp_path)
    monkeypatch.chdir(tmp_path)

    main(
        ["ingest", "inbox/Deserted", "--unattended"],
        env=make_beetsdir(beets),
        run=Recorder(),
        now=lambda: NOW,
    )

    (entry,) = read_entries(beets / "logs" / "changes.jsonl")
    assert entry["source"] == str(source.resolve())


def test_rerunning_summary_does_not_record_the_import_twice(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    beets = tmp_path / "beets"
    beets.mkdir()
    env = make_beetsdir(beets)

    main(["summary", "b1"], env=env, run=Recorder(), now=lambda: NOW)
    code = main(["summary", "b1"], env=env, run=Recorder(), now=lambda: NOW)

    assert code == 0
    assert len(read_entries(beets / "logs" / "changes.jsonl")) == 1
    assert "already in the change log" in capsys.readouterr().out


class SplitTools(Tools):
    """Tools fake that also answers the preflight commands."""

    def __call__(self, cmd: list[str]) -> Output:
        if cmd[0] == "mount":
            return Output(MOUNTS, "", 0)
        if cmd == ["beet", "version"]:
            return Output(VERSION, "", 0)
        return super().__call__(cmd)


def make_rips(root: Path, *names: str) -> None:
    for name in names:
        folder = root / name
        folder.mkdir(parents=True)
        (folder / "a.flac").write_bytes(b"big")
        (folder / "a.cue").write_text(CUE)


def have_tools(name: str) -> str | None:
    return f"/usr/bin/{name}"


def split_args(root: Path, *extra: str) -> list[str]:
    return [
        "split",
        str(root / "src"),
        "--inbox",
        str(root / "inbox"),
        "--holding",
        str(root / "holding"),
        *extra,
    ]


def test_split_without_apply_lists_rips_and_changes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    beets = tmp_path / "beets"
    beets.mkdir()
    make_rips(tmp_path / "src", "Deserted", "Sonoran")
    tools = SplitTools()

    code = main(
        split_args(tmp_path),
        env=make_beetsdir(beets),
        run=tools,
        now=lambda: NOW,
        which=have_tools,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "Deserted (3 tracks)" in out and "Sonoran (3 tracks)" in out
    assert "dry run: nothing changed. Add --apply to split." in out
    assert [c[0] for c in tools.commands if c[0] == "shnsplit"] == []
    assert (tmp_path / "src" / "Deserted" / "a.flac").exists()
    assert not (beets / "logs" / "changes.jsonl").exists()


def test_split_apply_splits_and_records_each_rip(tmp_path: Path) -> None:
    beets = tmp_path / "beets"
    beets.mkdir()
    make_rips(tmp_path / "src", "Deserted")

    code = main(
        split_args(tmp_path, "--apply"),
        env=make_beetsdir(beets),
        run=SplitTools(),
        now=lambda: NOW,
        which=have_tools,
    )

    assert code == 0
    album = tmp_path / "inbox" / "Deserted"
    held = tmp_path / "holding" / "Deserted"
    assert not (tmp_path / "src" / "Deserted").exists()
    (entry,) = read_entries(beets / "logs" / "changes.jsonl")
    assert entry == {
        "time": "2026-10-24T21:30:05",
        "action": "split",
        "source": str(tmp_path / "src" / "Deserted"),
        "flac": "a.flac",
        "cue": "a.cue",
        "track_count": 3,
        "tracks": [str(album / f"split-track0{n}.flac") for n in (1, 2, 3)],
        "holding": str(held),
    }


def test_split_apply_reports_a_failed_rip_and_carries_on(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    beets = tmp_path / "beets"
    beets.mkdir()
    make_rips(tmp_path / "src", "Bad", "Good")
    (tmp_path / "src" / "Bad" / "a.cue").write_text('PERFORMER "x"\n')

    code = main(
        split_args(tmp_path, "--apply"),
        env=make_beetsdir(beets),
        run=SplitTools(),
        now=lambda: NOW,
        which=have_tools,
    )

    assert code == 1
    assert "FAIL Bad: a.cue lists no audio tracks" in capsys.readouterr().out
    assert (tmp_path / "holding" / "Good").exists()
    assert (tmp_path / "src" / "Bad" / "a.flac").exists()
    assert len(read_entries(beets / "logs" / "changes.jsonl")) == 1


def test_split_lists_ambiguous_folders_and_does_not_split_them(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    beets = tmp_path / "beets"
    beets.mkdir()
    make_rips(tmp_path / "src", "Heritage")
    (tmp_path / "src" / "Heritage" / "b.cue").write_text(CUE)

    code = main(
        split_args(tmp_path, "--apply"),
        env=make_beetsdir(beets),
        run=SplitTools(),
        now=lambda: NOW,
        which=have_tools,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "ambiguous (one FLAC, several cue sheets): Heritage" in out
    assert (tmp_path / "src" / "Heritage" / "a.flac").exists()


def test_split_refuses_a_holding_folder_inside_the_scanned_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    beets = tmp_path / "beets"
    beets.mkdir()
    make_rips(tmp_path / "src", "Deserted")

    code = main(
        [
            "split",
            str(tmp_path / "src"),
            "--inbox",
            str(tmp_path / "inbox"),
            "--holding",
            str(tmp_path / "src" / "_holding"),
            "--apply",
        ],
        env=make_beetsdir(beets),
        run=SplitTools(),
        now=lambda: NOW,
        which=have_tools,
    )

    assert code == 1
    assert "FAIL holding" in capsys.readouterr().out
    assert (tmp_path / "src" / "Deserted" / "a.flac").exists()


def test_split_stops_when_a_tool_is_not_installed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    beets = tmp_path / "beets"
    beets.mkdir()
    make_rips(tmp_path / "src", "Deserted")

    code = main(
        split_args(tmp_path, "--apply"),
        env=make_beetsdir(beets),
        run=SplitTools(),
        now=lambda: NOW,
        which=lambda name: None if name == "shnsplit" else f"/usr/bin/{name}",
    )

    assert code == 1
    assert "FAIL tools: shnsplit not found" in capsys.readouterr().out
    assert (tmp_path / "src" / "Deserted" / "a.flac").exists()


def test_main_reads_variables_from_the_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    beets = tmp_path / "beets"
    (beets / "logs").mkdir(parents=True)
    record(beets / "logs" / "changes.jsonl", "import", NOW, batch="b1")
    (beets / "config.yaml").write_text("directory: /x\n")
    env_file = tmp_path / "vars"
    env_file.write_text(f"BEETSDIR={beets}\n")
    monkeypatch.delenv("BEETSDIR", raising=False)

    code = main(["log"], env_file=env_file)

    assert code == 0


def test_main_prefers_the_shell_over_the_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    real = tmp_path / "real"
    (real / "logs").mkdir(parents=True)
    record(real / "logs" / "changes.jsonl", "import", NOW, batch="from-shell")
    (real / "config.yaml").write_text("directory: /x\n")
    env_file = tmp_path / "vars"
    env_file.write_text(f"BEETSDIR={tmp_path / 'other'}\n")
    monkeypatch.setenv("BEETSDIR", str(real))

    main(["log"], env_file=env_file)

    assert "from-shell" in capsys.readouterr().out


def test_main_reports_a_bad_env_file_without_echoing_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env_file = tmp_path / "vars"
    env_file.write_text("my-secret-token\n")

    code = main(["log"], env_file=env_file)

    out = capsys.readouterr().out
    assert code == 1
    assert "FAIL env: " in out and "line 1" in out
    assert "my-secret-token" not in out


TOKEN = "s3cr3t-token"
PLEX_ENV = {"PLEX_URL": "http://192.168.0.63:32400", "PLEX_TOKEN": TOKEN}
TWO_MUSIC = (
    '{"MediaContainer": {"Directory": ['
    '{"key": "6", "type": "artist", "title": "Audiobook", '
    '"Location": [{"id": 9, "path": "/data/audiobooks"}]},'
    '{"key": "5", "type": "artist", "title": "Music", '
    '"Location": [{"id": 5, "path": "/data/music"}]},'
    '{"key": "1", "type": "movie", "title": "Movies", '
    '"Location": [{"id": 7, "path": "/data/movies"}, {"id": 1, "path": "/data/movies2"}]}'
    "]}}"
)


def plex_http() -> FakeHttp:
    return FakeHttp(routes={"/library/sections": Response(200, TWO_MUSIC)})


def test_plex_sections_lists_each_library_with_its_folders(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["plex", "sections"], env=PLEX_ENV, http=plex_http())

    assert code == 0
    assert capsys.readouterr().out.splitlines() == [
        "6  artist  Audiobook",
        "     /data/audiobooks",
        "5  artist  Music",
        "     /data/music",
        "1  movie  Movies",
        "     /data/movies",
        "     /data/movies2",
    ]


def test_plex_sections_never_prints_the_token(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["plex", "sections"], env=PLEX_ENV, http=plex_http())

    assert TOKEN not in capsys.readouterr().out


@pytest.mark.parametrize("missing", ["PLEX_URL", "PLEX_TOKEN"])
def test_plex_stops_when_a_setting_is_missing(
    missing: str, capsys: pytest.CaptureFixture[str]
) -> None:
    env = {k: v for k, v in PLEX_ENV.items() if k != missing}
    http = plex_http()

    code = main(["plex", "sections"], env=env, http=http)

    assert code == 1
    assert f"FAIL plex: {missing} is not set" in capsys.readouterr().out
    assert http.requests == []


def test_plex_refresh_starts_the_scan_and_records_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = {**make_beetsdir(tmp_path), **PLEX_ENV}
    http = plex_http()

    code = main(
        ["plex", "refresh", "--section", "Music"], env=env, http=http, now=lambda: NOW
    )

    assert code == 0
    assert http.paths() == ["/library/sections", "/library/sections/5/refresh"]
    assert "ok   rescan started: Music (5)" in capsys.readouterr().out
    (entry,) = read_entries(tmp_path / "logs" / "changes.jsonl")
    assert entry == {
        "time": "2026-10-24T21:30:05",
        "action": "plex-refresh",
        "section": "5",
        "title": "Music",
        "locations": ["/data/music"],
    }


def test_plex_refresh_takes_the_library_from_plex_section(tmp_path: Path) -> None:
    env = {**make_beetsdir(tmp_path), **PLEX_ENV, "PLEX_SECTION": "Audiobook"}
    http = plex_http()

    main(["plex", "refresh"], env=env, http=http, now=lambda: NOW)

    assert http.paths()[-1] == "/library/sections/6/refresh"


def test_plex_refresh_will_not_guess_between_two_music_libraries(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = {**make_beetsdir(tmp_path), **PLEX_ENV}
    http = plex_http()

    code = main(["plex", "refresh"], env=env, http=http, now=lambda: NOW)

    assert code == 1
    assert (
        "several music libraries: Audiobook (6), Music (5)" in capsys.readouterr().out
    )
    assert http.paths() == ["/library/sections"]


def test_plex_refresh_needs_beetsdir_so_it_can_log(
    capsys: pytest.CaptureFixture[str],
) -> None:
    http = plex_http()

    code = main(["plex", "refresh", "--section", "Music"], env=PLEX_ENV, http=http)

    assert code == 1
    assert "FAIL beetsdir" in capsys.readouterr().out
    assert http.requests == []


def test_plex_refresh_logs_nothing_when_the_token_is_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = {**make_beetsdir(tmp_path), **PLEX_ENV}
    http = FakeHttp(Response(401, ""))

    code = main(
        ["plex", "refresh", "--section", "Music"], env=env, http=http, now=lambda: NOW
    )

    out = capsys.readouterr().out
    assert code == 1
    assert "FAIL plex: Plex rejected the token (401)" in out
    assert TOKEN not in out
    assert not (tmp_path / "logs").exists()


LIBRARY_JSON = (
    '{"MediaContainer": {"Directory": ['
    '{"key": "5", "type": "artist", "title": "Music", '
    '"Location": [{"id": 5, "path": "/data/jbod2/media/music"}]},'
    '{"key": "1", "type": "movie", "title": "Movies", '
    '"Location": [{"id": 1, "path": "/data/jbod2/media/Movies"}]}'
    "]}}"
)


def media_share(tmp_path: Path) -> Path:
    """A fake mounted `media` share, with the Plex folders in place."""
    media = tmp_path / "media" / "jbod2" / "media"
    (media / "music").mkdir(parents=True)
    return media


def folders_args(tmp_path: Path, media: Path, *extra: str) -> list[str]:
    return [
        "folders",
        "--inbox",
        str(media / "music-inbox"),
        "--holding",
        str(media / "music-holding"),
        "--path-map",
        f"{tmp_path / 'media'}=/data",
        *extra,
    ]


def folders_http() -> FakeHttp:
    return FakeHttp(routes={"/library/sections": Response(200, LIBRARY_JSON)})


def test_folders_without_apply_shows_the_plan_and_creates_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    media = media_share(tmp_path)

    code = main(
        folders_args(tmp_path, media),
        env=PLEX_ENV,
        http=folders_http(),
        now=lambda: NOW,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "would create music-inbox (/data/jbod2/media/music-inbox)" in out
    assert "dry run: nothing changed. Add --apply to create them." in out
    assert not (media / "music-inbox").exists()


def test_folders_apply_creates_both_with_a_plexignore_and_logs_it(
    tmp_path: Path,
) -> None:
    media = media_share(tmp_path)
    beets = tmp_path / "beets"
    beets.mkdir()
    env = {**make_beetsdir(beets), **PLEX_ENV}

    code = main(
        folders_args(tmp_path, media, "--apply"),
        env=env,
        http=folders_http(),
        now=lambda: NOW,
    )

    assert code == 0
    for name in ("music-inbox", "music-holding"):
        assert (media / name / ".plexignore").read_text().endswith("*\n")
    (entry,) = read_entries(beets / "logs" / "changes.jsonl")
    assert entry == {
        "time": "2026-10-24T21:30:05",
        "action": "folders",
        "created": [str(media / "music-inbox"), str(media / "music-holding")],
        "plexignore": [
            str(media / "music-inbox" / ".plexignore"),
            str(media / "music-holding" / ".plexignore"),
        ],
    }


def test_folders_apply_twice_logs_nothing_the_second_time(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    media = media_share(tmp_path)
    beets = tmp_path / "beets"
    beets.mkdir()
    env = {**make_beetsdir(beets), **PLEX_ENV}
    args = folders_args(tmp_path, media, "--apply")
    main(args, env=env, http=folders_http(), now=lambda: NOW)
    capsys.readouterr()

    code = main(args, env=env, http=folders_http(), now=lambda: NOW)

    assert code == 0
    assert "already in place" in capsys.readouterr().out
    assert len(read_entries(beets / "logs" / "changes.jsonl")) == 1


def test_folders_refuses_a_folder_inside_a_plex_library(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    media = media_share(tmp_path)
    args = [
        "folders",
        "--inbox",
        str(media / "music" / "_inbox"),
        "--holding",
        str(media / "music-holding"),
        "--path-map",
        f"{tmp_path / 'media'}=/data",
        "--apply",
    ]
    beets = tmp_path / "beets"
    beets.mkdir()

    code = main(
        args,
        env={**make_beetsdir(beets), **PLEX_ENV},
        http=folders_http(),
        now=lambda: NOW,
    )

    assert code == 1
    assert "FAIL folders: " in capsys.readouterr().out
    assert not (media / "music" / "_inbox").exists()
    assert not (media / "music-holding").exists()


def test_folders_stops_when_no_path_map_covers_a_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    media = media_share(tmp_path)
    args = folders_args(tmp_path, media)
    args[args.index("--path-map") + 1] = "/Volumes/elsewhere=/data"

    code = main(args, env=PLEX_ENV, http=folders_http(), now=lambda: NOW)

    assert code == 1
    assert "no --path-map covers" in capsys.readouterr().out


def test_folders_takes_the_path_map_from_the_environment(tmp_path: Path) -> None:
    media = media_share(tmp_path)
    args = folders_args(tmp_path, media)
    del args[args.index("--path-map") : args.index("--path-map") + 2]
    env = {**PLEX_ENV, "PLEX_PATH_MAP": f"{tmp_path / 'media'}=/data"}

    code = main(args, env=env, http=folders_http(), now=lambda: NOW)

    assert code == 0


def test_folders_apply_with_a_missing_mount_creates_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    media = tmp_path / "media" / "jbod2" / "media"  # share not mounted: no folders
    beets = tmp_path / "beets"
    beets.mkdir()

    code = main(
        folders_args(tmp_path, media, "--apply"),
        env={**make_beetsdir(beets), **PLEX_ENV},
        http=folders_http(),
        now=lambda: NOW,
    )

    assert code == 1
    assert "is the share mounted" in capsys.readouterr().out
    assert not (tmp_path / "media").exists()


def test_folders_apply_needs_beetsdir_so_it_can_log(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    media = media_share(tmp_path)

    code = main(
        folders_args(tmp_path, media, "--apply"), env=PLEX_ENV, http=folders_http()
    )

    assert code == 1
    assert "FAIL beetsdir" in capsys.readouterr().out
    assert not (media / "music-inbox").exists()


GAP_EXPORT = (
    '[{"id": "1", "albumartist": "Cake", "album": "Comfort Eagle", "year": "2001", '
    '"genres": "Alternative", "artpath": "", "path": "/lib/Cake/2001"},'
    '{"id": "2", "albumartist": "Gatecreeper", "album": "Deserted", "year": "2019", '
    '"genres": "Death Metal", "artpath": "/lib/g/cover.jpg", "path": "/lib/g"}]'
)


def gaps_run(export_code: int = 0, mounts: str = MOUNTS) -> Run:
    def run(cmd: list[str]) -> Output:
        if cmd[0] == "mount":
            return Output(mounts, "", 0)
        if cmd == ["beet", "version"]:
            return Output(VERSION, "", 0)
        if cmd[:2] == ["beet", "export"]:
            if export_code:
                return Output("", "error: no such field\n", export_code)
            return Output(GAP_EXPORT, "", 0)
        return Output("", "", 0)

    return run


def test_gaps_writes_the_report_and_one_log_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "last-gaps-report.md").write_text("old report")

    code = main(["gaps"], env=make_beetsdir(tmp_path), run=gaps_run(), now=lambda: NOW)

    out = capsys.readouterr().out
    assert code == 0
    assert "no art: 1" in out and "no year: 0" in out
    report = (tmp_path / "logs" / "last-gaps-report.md").read_text()
    assert "- Cake - Comfort Eagle | /lib/Cake/2001" in report
    assert "old report" not in report
    log = (tmp_path / "logs" / "musicos-activity.log").read_text()
    assert log == "2026-10-24 21:30:05 gaps 2 albums checked, 1 with gaps, 1 gaps\n"


def test_gaps_changes_nothing_in_the_library_log(tmp_path: Path) -> None:
    main(["gaps"], env=make_beetsdir(tmp_path), run=gaps_run(), now=lambda: NOW)

    assert not (tmp_path / "logs" / "changes.jsonl").exists()


def test_gaps_stops_when_preflight_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        ["gaps"], env=make_beetsdir(tmp_path), run=gaps_run(mounts=""), now=lambda: NOW
    )

    assert code == 1
    assert "FAIL mount" in capsys.readouterr().out
    assert not (tmp_path / "logs").exists()


def test_gaps_reports_a_failing_export_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        ["gaps"],
        env=make_beetsdir(tmp_path),
        run=gaps_run(export_code=1),
        now=lambda: NOW,
    )

    assert code == 1
    assert "FAIL gaps: error: no such field" in capsys.readouterr().out
    assert not (tmp_path / "logs").exists()


LIBRARY_MAP = "/Volumes/music=/data/jbod2/media/music"


def ingest_env(beets: Path, **extra: str) -> dict[str, str]:
    return {**make_beetsdir(beets), **PLEX_ENV, "PLEX_PATH_MAP": LIBRARY_MAP, **extra}


def run_unattended(
    tmp_path: Path, beets: Path, env: dict[str, str], http: FakeHttp, *flags: str
) -> int:
    return main(
        ["ingest", str(make_source(tmp_path)), "--unattended", *flags],
        env=env,
        run=Recorder(),
        now=lambda: NOW,
        http=http,
    )


def test_ingest_rescans_the_plex_library_that_holds_the_library_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    beets = tmp_path / "beets"
    beets.mkdir()
    http = folders_http()

    code = run_unattended(tmp_path, beets, ingest_env(beets), http)

    assert code == 0
    assert http.paths() == ["/library/sections", "/library/sections/5/refresh"]
    assert "ok   plex rescan started: Music (5)" in capsys.readouterr().out
    actions = [e["action"] for e in read_entries(beets / "logs" / "changes.jsonl")]
    assert actions == ["import", "plex-refresh"]
    refresh = read_entries(beets / "logs" / "changes.jsonl")[1]
    assert refresh["batch"] == "20261024-2130-deserted"
    assert refresh["title"] == "Music"


def test_ingest_says_why_it_did_not_rescan_when_plex_is_not_set_up(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    beets = tmp_path / "beets"
    beets.mkdir()
    http = folders_http()
    env = make_beetsdir(beets)  # no Plex settings

    code = run_unattended(tmp_path, beets, env, http)

    assert code == 0
    assert "plex: not refreshed (PLEX_URL is not set)" in capsys.readouterr().out
    assert http.requests == []


def test_ingest_skips_the_rescan_when_the_library_is_not_in_plex(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    beets = tmp_path / "beets"
    beets.mkdir()
    env = ingest_env(beets)
    (beets / "config.yaml").write_text(
        "directory: /Users/me/music-test/library\nplugins: chroma\n"
    )
    http = folders_http()

    code = run_unattended(tmp_path, beets, env, http)

    assert code == 0
    assert (
        "plex: not refreshed (no PLEX_PATH_MAP entry covers" in capsys.readouterr().out
    )
    assert http.paths() == []


def test_ingest_with_no_plex_refresh_never_calls_plex(tmp_path: Path) -> None:
    beets = tmp_path / "beets"
    beets.mkdir()
    http = folders_http()

    run_unattended(tmp_path, beets, ingest_env(beets), http, "--no-plex-refresh")

    assert http.requests == []


def test_a_plex_failure_does_not_undo_the_import(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    beets = tmp_path / "beets"
    beets.mkdir()
    http = FakeHttp(Response(401, ""))

    code = run_unattended(tmp_path, beets, ingest_env(beets), http)

    out = capsys.readouterr().out
    assert code == 0
    assert "WARN plex: not refreshed: Plex rejected the token (401)" in out
    assert TOKEN not in out
    actions = [e["action"] for e in read_entries(beets / "logs" / "changes.jsonl")]
    assert actions == ["import"]


def test_summary_rescans_once_per_batch(tmp_path: Path) -> None:
    beets = tmp_path / "beets"
    beets.mkdir()
    env = ingest_env(beets)
    http = folders_http()

    for _ in range(2):
        main(["summary", "b1"], env=env, run=Recorder(), now=lambda: NOW, http=http)

    assert http.paths().count("/library/sections/5/refresh") == 1


def test_split_reports_a_file_system_error_as_a_failure_and_carries_on(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    beets = tmp_path / "beets"
    beets.mkdir()
    make_rips(tmp_path / "src", "Bad", "Good")
    bad = (tmp_path / "src" / "Bad").resolve()
    real_rename = os.rename

    def rename(src: object, dst: object) -> None:
        if Path(str(src)) == bad:
            raise OSError(errno.EIO, "Input/output error")
        real_rename(src, dst)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "rename", rename)

    code = main(
        split_args(tmp_path, "--apply"),
        env=make_beetsdir(beets),
        run=SplitTools(),
        now=lambda: NOW,
        which=have_tools,
    )

    out = capsys.readouterr().out
    assert code == 1
    assert "FAIL Bad: " in out and "Input/output error" in out
    assert (tmp_path / "holding" / "Good").exists()


def test_ingest_stops_when_the_dry_run_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    beets = tmp_path / "beets"
    beets.mkdir()
    run = Recorder(dry_run_code=1)

    code = main(
        ["ingest", str(make_source(tmp_path))],
        env=make_beetsdir(beets),
        run=run,
        now=lambda: NOW,
    )

    out = capsys.readouterr().out
    assert code == 1
    assert "FAIL dry run: error: no such folder" in out
    assert "uv run beet import" not in out
    assert not run.ran_import()


def dirty_share(root: Path) -> Path:
    """An album folder with data files, two shadows and one real ._ file."""
    album = root / "Cake" / "Fashion Nugget"
    album.mkdir(parents=True)
    (album / "01 Song.flac").write_bytes(b"audio")
    shadow(album / "._01 Song.flac")
    shadow(album / "._cover.jpg")
    (album / "._notes.txt").write_text("my own notes")
    return root


def test_clean_appledouble_without_apply_lists_and_deletes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = dirty_share(tmp_path / "share")

    code = main(["clean-appledouble", str(root)], env={})

    out = capsys.readouterr().out
    assert code == 0
    assert "found 2 AppleDouble files (8192 bytes)" in out
    assert "._01 Song.flac" in out
    assert "dry run: nothing deleted. Add --apply to delete them." in out
    assert len(list(root.rglob("._*"))) == 3


def test_clean_appledouble_apply_deletes_only_real_shadows_and_logs_it(
    tmp_path: Path,
) -> None:
    root = dirty_share(tmp_path / "share")
    beets = tmp_path / "beets"
    beets.mkdir()

    code = main(
        ["clean-appledouble", str(root), "--apply"],
        env=make_beetsdir(beets),
        now=lambda: NOW,
    )

    assert code == 0
    left = sorted(p.name for p in root.rglob("._*"))
    assert left == ["._notes.txt"]
    assert (root / "Cake" / "Fashion Nugget" / "01 Song.flac").read_bytes() == b"audio"
    (entry,) = read_entries(beets / "logs" / "changes.jsonl")
    assert entry["action"] == "clean-appledouble"
    assert entry["root"] == str(root)
    assert entry["deleted"] == 2
    assert entry["bytes"] == 8192
    assert len(entry["examples"]) == 2


def test_clean_appledouble_apply_needs_beetsdir_so_it_can_log(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = dirty_share(tmp_path / "share")

    code = main(["clean-appledouble", str(root), "--apply"], env={})

    assert code == 1
    assert "FAIL beetsdir" in capsys.readouterr().out
    assert len(list(root.rglob("._*"))) == 3


def test_clean_appledouble_reports_a_file_it_cannot_delete_and_carries_on(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = dirty_share(tmp_path / "share")
    beets = tmp_path / "beets"
    beets.mkdir()
    real_unlink = Path.unlink

    def unlink(self: Path, missing_ok: bool = False) -> None:
        if self.name == "._cover.jpg":
            raise PermissionError(errno.EACCES, "Permission denied")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink)

    code = main(
        ["clean-appledouble", str(root), "--apply"],
        env=make_beetsdir(beets),
        now=lambda: NOW,
    )

    out = capsys.readouterr().out
    assert code == 1
    assert "FAIL ._cover.jpg: Permission denied" in out
    (entry,) = read_entries(beets / "logs" / "changes.jsonl")
    assert entry["deleted"] == 1 and entry["failed"] == 1


def test_clean_appledouble_with_nothing_to_delete_logs_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "share"
    (root / "A").mkdir(parents=True)
    beets = tmp_path / "beets"
    beets.mkdir()

    code = main(
        ["clean-appledouble", str(root), "--apply"],
        env=make_beetsdir(beets),
        now=lambda: NOW,
    )

    assert code == 0
    assert "no AppleDouble files found" in capsys.readouterr().out
    assert not (beets / "logs").exists()


@pytest.mark.parametrize("bad", ["/", "/Volumes"])
def test_clean_appledouble_refuses_a_root_that_is_too_broad(
    bad: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["clean-appledouble", bad], env={})

    assert code == 1
    assert "FAIL root: refusing to scan" in capsys.readouterr().out


def test_clean_appledouble_stops_when_the_root_is_not_a_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["clean-appledouble", str(tmp_path / "missing")], env={})

    assert code == 1
    assert "FAIL root: " in capsys.readouterr().out


def test_split_dry_run_already_refuses_folders_on_different_shares(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    beets = tmp_path / "beets"
    beets.mkdir()
    make_rips(tmp_path / "src", "Deserted")
    holding = (tmp_path / "holding").resolve()
    monkeypatch.setattr("musicos.split.device_of", lambda p: 2 if p == holding else 1)

    code = main(
        split_args(tmp_path),
        env=make_beetsdir(beets),
        run=SplitTools(),
        now=lambda: NOW,
        which=have_tools,
    )

    out = capsys.readouterr().out
    assert code == 1
    assert "FAIL shares: " in out and "one share" in out
    assert "Deserted (3 tracks)" not in out


def isis_library(root: Path) -> Path:
    """Celestial twice (a cue rip and a track-by-track copy) and Oceanic once."""
    rip = root / "Isis - Celestial (2000) [EAC-FLAC]"
    rip.mkdir(parents=True)
    (rip / "rip.flac").write_bytes(b"x" * 10)
    (rip / "rip.cue").write_text(
        'PERFORMER "Isis"\nTITLE "Celestial"\n  TRACK 01 AUDIO\n  TRACK 02 AUDIO\n'
    )
    copy = root / "Discography" / "(2000) Celestial"
    copy.mkdir(parents=True)
    for n in (1, 2):
        (copy / f"0{n}.flac").write_bytes(b"x" * 5)
    oceanic = root / "Oceanic"
    oceanic.mkdir()
    (oceanic / "01.flac").write_bytes(b"x")
    return root


def isis_tags(path: Path) -> Tags | None:
    album = "Oceanic" if path.parent.name == "Oceanic" else "Celestial"
    return Tags(album, "Isis", "2000", "1", 600.0, "FLAC 16/44.1")


def test_dupes_prints_the_report_and_writes_the_file_and_one_log_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = isis_library(tmp_path / "Isis")
    beets = tmp_path / "beets"
    beets.mkdir()

    code = main(
        ["dupes", str(root)],
        env=make_beetsdir(beets),
        now=lambda: NOW,
        tag_reader=isis_tags,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "## Isis - Celestial (disc 1)" in out
    assert (
        "| Isis - Celestial (2000) [EAC-FLAC] | 2 | 10.0 | FLAC 16/44.1 | 0 MiB "
        "| cue rip | deletion candidate |"
    ) in out
    assert "Oceanic" not in out.split("## ", 1)[1]  # Oceanic is not in a group
    report = (beets / "logs" / "last-duplicates-report.md").read_text()
    assert out.startswith(report)
    log = (beets / "logs" / "musicos-activity.log").read_text()
    assert log == (
        "2026-10-24 21:30:05 dupes 3 folders checked, 1 groups, 2 folders in groups, "
        "1 deletion candidate\n"
    )
    assert not (beets / "logs" / "changes.jsonl").exists()


def test_dupes_adds_each_deletion_candidate_to_the_log_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = isis_library(tmp_path / "Isis")
    beets = tmp_path / "beets"
    beets.mkdir()
    args = ["dupes", str(root)]
    env = make_beetsdir(beets)

    main(args, env=env, now=lambda: NOW, tag_reader=isis_tags)
    first = capsys.readouterr().out
    main(args, env=env, now=lambda: NOW, tag_reader=isis_tags)
    second = capsys.readouterr().out

    entries = read_entries(beets / "logs" / "deletion-candidates.jsonl")
    assert [e["folder"] for e in entries] == [
        str((root / "Isis - Celestial (2000) [EAC-FLAC]").resolve())
    ]
    assert entries[0]["kept_by"] == [
        str((root / "Discography" / "(2000) Celestial").resolve())
    ]
    assert "1 new deletion candidate added to " in first
    assert "0 new deletion candidates added to " in second


def test_dupes_deletes_nothing_even_when_it_marks_candidates(tmp_path: Path) -> None:
    root = isis_library(tmp_path / "Isis")
    beets = tmp_path / "beets"
    beets.mkdir()

    main(
        ["dupes", str(root)],
        env=make_beetsdir(beets),
        now=lambda: NOW,
        tag_reader=isis_tags,
    )

    assert (root / "Isis - Celestial (2000) [EAC-FLAC]" / "rip.flac").exists()


def test_dupes_changes_nothing_in_the_folder(tmp_path: Path) -> None:
    root = isis_library(tmp_path / "Isis")
    beets = tmp_path / "beets"
    beets.mkdir()
    before = sorted(p.name for p in root.rglob("*"))

    main(
        ["dupes", str(root)],
        env=make_beetsdir(beets),
        now=lambda: NOW,
        tag_reader=isis_tags,
    )

    assert sorted(p.name for p in root.rglob("*")) == before


def test_dupes_says_when_there_are_none(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Isis"
    (root / "Oceanic").mkdir(parents=True)
    (root / "Oceanic" / "01.flac").write_bytes(b"x")
    beets = tmp_path / "beets"
    beets.mkdir()

    code = main(
        ["dupes", str(root)],
        env=make_beetsdir(beets),
        now=lambda: NOW,
        tag_reader=isis_tags,
    )

    assert code == 0
    assert "No duplicate albums found." in capsys.readouterr().out


def test_dupes_stops_when_the_root_is_not_a_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["dupes", str(tmp_path / "missing")], env={}, tag_reader=isis_tags)

    assert code == 1
    assert "FAIL root: " in capsys.readouterr().out


def test_dupes_needs_beetsdir_for_its_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = isis_library(tmp_path / "Isis")

    code = main(["dupes", str(root)], env={}, tag_reader=isis_tags)

    assert code == 1
    assert "FAIL beetsdir" in capsys.readouterr().out


def candidate_log(beets: Path, root: Path) -> Path:
    main(
        ["dupes", str(root)],
        env=make_beetsdir(beets),
        now=lambda: NOW,
        tag_reader=isis_tags,
    )
    return beets / "logs" / "deletion-candidates.jsonl"


def test_candidates_lists_what_is_still_open_with_why_and_what_was_kept(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = isis_library(tmp_path / "Isis")
    beets = tmp_path / "beets"
    beets.mkdir()
    candidate_log(beets, root)
    capsys.readouterr()

    code = main(["candidates"], env=make_beetsdir(beets))

    out = capsys.readouterr().out
    assert code == 0
    assert "open" in out and "Isis - Celestial (2000) [EAC-FLAC]" in out
    assert "FLAC + cue file is lower priority than FLAC tracks already split" in out
    assert "kept: " in out and "(2000) Celestial" in out
    assert "1 open" in out and "0 stale" in out


def test_candidates_flags_one_whose_kept_copy_has_gone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = isis_library(tmp_path / "Isis")
    beets = tmp_path / "beets"
    beets.mkdir()
    candidate_log(beets, root)
    for f in (root / "Discography" / "(2000) Celestial").iterdir():
        f.unlink()
    (root / "Discography" / "(2000) Celestial").rmdir()
    capsys.readouterr()

    main(["candidates"], env=make_beetsdir(beets))

    out = capsys.readouterr().out
    assert "stale" in out and "do not delete" in out
    assert "0 open" in out and "1 stale" in out


def test_candidates_hides_done_ones_unless_all_is_given(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = isis_library(tmp_path / "Isis")
    beets = tmp_path / "beets"
    beets.mkdir()
    candidate_log(beets, root)
    rip = root / "Isis - Celestial (2000) [EAC-FLAC]"
    for f in rip.iterdir():
        f.unlink()
    rip.rmdir()
    capsys.readouterr()

    main(["candidates"], env=make_beetsdir(beets))
    hidden = capsys.readouterr().out
    main(["candidates", "--all"], env=make_beetsdir(beets))
    shown = capsys.readouterr().out

    assert "Isis - Celestial (2000) [EAC-FLAC]" not in hidden
    assert "no open deletion candidates" in hidden
    assert "done" in shown and "Isis - Celestial (2000) [EAC-FLAC]" in shown


def test_candidates_with_no_log_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["candidates"], env=make_beetsdir(tmp_path))

    assert code == 0
    assert "no deletion candidates recorded" in capsys.readouterr().out


def test_candidates_needs_beetsdir(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["candidates"], env={})

    assert code == 1
    assert "FAIL beetsdir" in capsys.readouterr().out
