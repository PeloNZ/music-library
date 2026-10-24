"""Command line entry point: `uv run musicos <command>`."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from musicos.changelog import filter_entries, format_entry, read_entries, record
from musicos.ingest import (
    batch_items,
    dry_run_command,
    has_audio,
    import_command,
    make_batch_id,
    parse_import_log,
    summarize_batch,
)
from musicos.lint import activity_line, render_report, run_lint
from musicos.preflight import (
    Result,
    check_beetsdir,
    check_mount,
    check_plugins,
    configured_plugins,
)
from musicos.runner import Run, run_command


def load_config(env: Mapping[str, str]) -> dict[str, Any]:
    config: dict[str, Any] = yaml.safe_load(
        (Path(env["BEETSDIR"]) / "config.yaml").read_text()
    )
    return config


def preflight(env: Mapping[str, str], run: Run) -> list[Result]:
    results = [check_beetsdir(env)]
    if not results[0].ok:
        return results
    config = load_config(env)
    results.append(check_mount(config["directory"], run(["mount"]).stdout))
    wanted = configured_plugins(config)
    version = run(["beet", "version"])
    if version.code != 0:
        message = version.stderr.strip().splitlines()[:1] or ["beet version failed"]
        results.append(Result("beet", False, message[0]))
        return results
    results.append(check_plugins(version.stdout, wanted))
    return results


def print_results(results: list[Result]) -> bool:
    for r in results:
        print(f"{'ok  ' if r.ok else 'FAIL'} {r.name}: {r.detail}")
    return all(r.ok for r in results)


def lint(env: Mapping[str, str], run: Run, when: datetime) -> int:
    checks = run_lint(run)
    logs = Path(env["BEETSDIR"]) / "logs"
    logs.mkdir(exist_ok=True)
    report = logs / "last-health-report.md"
    report.write_text(render_report(checks, when))
    log_activity(env, activity_line(checks, when))
    for c in checks:
        print(f"{c.name}: {'could not run (' + c.error + ')' if c.error else c.count}")
    print(f"report: {report}")
    return 1 if any(c.error for c in checks) else 0


def log_activity(env: Mapping[str, str], line: str) -> None:
    logs = Path(env["BEETSDIR"]) / "logs"
    logs.mkdir(exist_ok=True)
    with (logs / "musicos-activity.log").open("a") as log:
        log.write(line + "\n")


def report_batch(
    env: Mapping[str, str],
    run: Run,
    batch: str,
    when: datetime,
    source: Path | None = None,
) -> int:
    try:
        summary = summarize_batch(run, batch)
        items = batch_items(run, batch)
    except RuntimeError as exc:
        print(f"FAIL summary: {exc}")
        return 1
    flagged = len(summary.flagged)
    print(f"{batch}: {summary.albums} albums, {flagged} without a MusicBrainz match")
    for a in summary.flagged:
        print(f"  - {a.get('albumartist', '?')} - {a.get('album', '?')}")
    import_log = Path(env["BEETSDIR"]) / "logs" / f"import-{batch}.log"
    logged = parse_import_log(import_log.read_text()) if import_log.exists() else []
    if logged:
        print(f"{len(logged)} logged by the importer (not imported as matched):")
        for entry in logged:
            print(f"  {entry.kind}: {entry.path}")
    fields: dict[str, Any] = {"batch": batch}
    if source is not None:
        fields["source"] = str(source)
    changes = Path(env["BEETSDIR"]) / "logs" / "changes.jsonl"
    already = any(
        e["action"] == "import" and e.get("batch") == batch
        for e in read_entries(changes)
    )
    if already:
        print("import already in the change log; not recorded again")
    else:
        record(
            changes,
            "import",
            when,
            **fields,
            albums=summary.albums,
            flagged=flagged,
            skipped=[{"kind": e.kind, "path": e.path} for e in logged],
            items=items,
        )
    log_activity(
        env,
        f"{when:%Y-%m-%d %H:%M:%S} ingest {batch} {summary.albums} albums, {flagged} flagged",
    )
    return 0


def ingest(
    env: Mapping[str, str], run: Run, when: datetime, source: Path, unattended: bool
) -> int:
    source = source.resolve()
    if not source.is_dir() or not has_audio(source):
        print(f"FAIL source: no audio files under {source}")
        return 1
    batch = make_batch_id(when, source)
    logs = Path(env["BEETSDIR"]) / "logs"
    logs.mkdir(exist_ok=True)
    print(run(dry_run_command(source)).stdout, end="")
    cmd = import_command(source, batch, logs, unattended)
    if not unattended:
        print("Run this in your own terminal. The match prompts need one:")
        print(f"  uv run {shlex.join(cmd)}")
        print(f"Then: uv run musicos summary {batch}")
        return 0
    out = run(cmd)
    if out.code != 0:
        message = out.stderr.strip().splitlines()[:1] or [f"exit code {out.code}"]
        print(f"FAIL import: {message[0]}")
        return 1
    return report_batch(env, run, batch, when, source)


def show_log(env: Mapping[str, str], args: argparse.Namespace) -> int:
    beetsdir = check_beetsdir(env)
    if not beetsdir.ok:
        print_results([beetsdir])
        return 1
    try:
        entries = read_entries(Path(env["BEETSDIR"]) / "logs" / "changes.jsonl")
    except ValueError as exc:
        print(f"FAIL log: {exc}")
        return 1
    shown = filter_entries(entries, args.batch, args.action, args.since, args.last)
    if not shown:
        print("no changes recorded")
    for entry in shown:
        print(
            json.dumps(entry, ensure_ascii=False) if args.json else format_entry(entry)
        )
    return 0


def main(
    argv: Sequence[str] | None = None,
    env: Mapping[str, str] = os.environ,
    run: Run = run_command,
    now: Callable[[], datetime] = datetime.now,
) -> int:
    parser = argparse.ArgumentParser(prog="musicos")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "preflight", help="check BEETSDIR, the share mount and the plugins"
    )
    commands.add_parser("lint", help="run the read-only health checks")
    ingest_parser = commands.add_parser("ingest", help="import a folder of new music")
    ingest_parser.add_argument("source", type=Path)
    ingest_parser.add_argument(
        "--unattended",
        action="store_true",
        help="run the import now; skip albums that need a decision",
    )
    summary_parser = commands.add_parser("summary", help="report on an import batch")
    summary_parser.add_argument("batch")
    log_parser = commands.add_parser("log", help="show the change log")
    log_parser.add_argument("--batch")
    log_parser.add_argument("--action")
    log_parser.add_argument("--since", type=datetime.fromisoformat, help="YYYY-MM-DD")
    log_parser.add_argument("--last", type=int, help="only the newest N entries")
    log_parser.add_argument("--json", action="store_true", help="print raw entries")
    args = parser.parse_args(argv)

    if args.command == "log":
        return show_log(env, args)
    if not print_results(preflight(env, run)):
        return 1
    if args.command == "lint":
        return lint(env, run, now())
    if args.command == "ingest":
        return ingest(env, run, now(), args.source, args.unattended)
    if args.command == "summary":
        return report_batch(env, run, args.batch, now())
    return 0


if __name__ == "__main__":
    sys.exit(main())
