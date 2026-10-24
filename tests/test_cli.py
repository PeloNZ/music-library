from datetime import datetime
from pathlib import Path

import pytest

from musicos.changelog import read_entries, record
from musicos.cli import main
from musicos.runner import Output, Run

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

    def __init__(self, import_code: int = 0) -> None:
        self.commands: list[list[str]] = []
        self.import_code = import_code

    def __call__(self, cmd: list[str]) -> Output:
        self.commands.append(cmd)
        if cmd[0] == "mount":
            return Output(MOUNTS, "", 0)
        if cmd == ["beet", "version"]:
            return Output(VERSION, "", 0)
        if cmd[:3] == ["beet", "import", "--pretend"]:
            return Output("Album: x\n  x/01.flac\n", "", 0)
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
