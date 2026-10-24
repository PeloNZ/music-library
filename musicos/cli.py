"""Command line entry point: `uv run musicos <command>`."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from musicos.changelog import filter_entries, format_entry, read_entries, record
from musicos.envfile import merged_env
from musicos.folders import (
    FolderError,
    check_outside_plex,
    create_plex_free_folder,
    parse_path_map,
    to_server_path,
)
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
from musicos.plex import Get, PlexError, choose_section, http_get, plex_from_env
from musicos.preflight import (
    Result,
    check_beetsdir,
    check_mount,
    check_plugins,
    check_tools,
    configured_plugins,
)
from musicos.runner import Run, run_command
from musicos.split import SplitError, cue_track_count, read_cue, scan, split_rip

# Settings kept out of the repo and out of shell history, such as PLEX_TOKEN.
# Variables already set in the shell take priority.
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


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


def split(
    env: Mapping[str, str],
    run: Run,
    when: datetime,
    args: argparse.Namespace,
    which: Callable[[str], str | None],
) -> int:
    tools = check_tools(["cuebreakpoints", "shnsplit", "cuetag.sh"], which)
    if not tools.ok:
        print_results([tools])
        return 1
    root, inbox, holding = (p.resolve() for p in (args.root, args.inbox, args.holding))
    for name, folder in (("inbox", inbox), ("holding", holding)):
        if folder == root or root in folder.parents:
            print(f"FAIL {name}: {folder} is inside {root}; a later scan would find it")
            return 1
    found = scan(root)
    for rip in found.rips:
        count = cue_track_count(read_cue(rip.cue))
        print(f"  {rip.folder.relative_to(root)} ({count} tracks)")
    if found.ambiguous:
        names = ", ".join(str(p.relative_to(root)) for p in found.ambiguous)
        print(f"ambiguous (one FLAC, several cue sheets): {names}")
    if not args.apply:
        print("dry run: nothing changed. Add --apply to split.")
        return 0
    failed = False
    for rip in found.rips:
        label = rip.folder.relative_to(root)
        try:
            result = split_rip(rip, inbox, holding, run)
        except SplitError as exc:
            print(f"FAIL {label}: {exc}")
            failed = True
            continue
        record(
            Path(env["BEETSDIR"]) / "logs" / "changes.jsonl",
            "split",
            when,
            source=str(rip.folder),
            flac=rip.flac.name,
            cue=rip.cue.name,
            track_count=result.track_count,
            tracks=[str(t) for t in result.tracks],
            holding=str(result.holding),
        )
        print(f"ok   {label}: {result.track_count} tracks in {inbox / rip.folder.name}")
    return 1 if failed else 0


def plex_command(
    env: Mapping[str, str], args: argparse.Namespace, when: datetime, http: Get
) -> int:
    refreshing = args.plex_command == "refresh"
    if refreshing and not print_results_if_failed([check_beetsdir(env)]):
        return 1  # a rescan is a change, so it must be logged
    try:
        plex = plex_from_env(env, http)
        sections = plex.sections()
        if not refreshing:
            for section in sections:
                print(f"{section.id}  {section.type}  {section.title}")
                for path in section.locations:
                    print(f"     {path}")
            return 0
        section = choose_section(sections, args.section or env.get("PLEX_SECTION"))
        plex.refresh(section.id)
    except PlexError as exc:
        print(f"FAIL plex: {exc}")
        return 1
    record(
        Path(env["BEETSDIR"]) / "logs" / "changes.jsonl",
        "plex-refresh",
        when,
        section=section.id,
        title=section.title,
        locations=section.locations,
    )
    print(f"ok   rescan started: {section.title} ({section.id})")
    return 0


def folders_command(
    env: Mapping[str, str], args: argparse.Namespace, when: datetime, http: Get
) -> int:
    if args.apply and not print_results_if_failed([check_beetsdir(env)]):
        return 1  # making the folders is a change, so it must be logged
    plan: list[tuple[Path, PurePosixPath]] = []
    try:
        sections = plex_from_env(env, http).sections()
    except PlexError as exc:
        print(f"FAIL plex: {exc}")
        return 1
    libraries = [PurePosixPath(p) for section in sections for p in section.locations]
    from_env = [m for m in env.get("PLEX_PATH_MAP", "").split(",") if m]
    try:
        maps = parse_path_map(args.path_map or from_env)
        for folder in (args.inbox.resolve(), args.holding.resolve()):
            server = to_server_path(folder, maps)
            if server is None:
                raise FolderError(f"no --path-map covers {folder}")
            check_outside_plex(server, libraries)
            if not folder.parent.is_dir():
                raise FolderError(
                    f"{folder.parent} does not exist; is the share mounted?"
                )
            plan.append((folder, server))
    except FolderError as exc:
        print(f"FAIL folders: {exc}")
        return 1
    if not args.apply:
        for folder, server in plan:
            verb = "exists" if folder.exists() else "would create"
            print(f"{verb} {folder.name} ({server})")
        print("dry run: nothing changed. Add --apply to create them.")
        return 0
    results = [create_plex_free_folder(folder) for folder, _ in plan]
    created = [str(r.path) for r in results if r.made]
    ignores = [str(r.path / ".plexignore") for r in results if r.plexignore_written]
    if not created and not ignores:
        print("already in place")
        return 0
    record(
        Path(env["BEETSDIR"]) / "logs" / "changes.jsonl",
        "folders",
        when,
        created=created,
        plexignore=ignores,
    )
    for folder, server in plan:
        print(f"ok   {folder} ({server})")
    return 0


def print_results_if_failed(results: list[Result]) -> bool:
    """Print only failures. True when every result passed."""
    failed = [r for r in results if not r.ok]
    if failed:
        print_results(failed)
    return not failed


def main(
    argv: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
    run: Run = run_command,
    now: Callable[[], datetime] = datetime.now,
    which: Callable[[str], str | None] = shutil.which,
    env_file: Path = ENV_FILE,
    http: Get = http_get,
) -> int:
    if env is None:
        try:
            env = merged_env(env_file, os.environ)
        except ValueError as exc:
            print(f"FAIL env: {exc}")
            return 1
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
    split_parser = commands.add_parser("split", help="split FLAC + cue rips")
    split_parser.add_argument("root", type=Path, help="folder to scan")
    split_parser.add_argument("--inbox", type=Path, required=True)
    split_parser.add_argument("--holding", type=Path, required=True)
    split_parser.add_argument(
        "--apply", action="store_true", help="split (default is a dry run)"
    )
    plex_parser = commands.add_parser("plex", help="list or rescan Plex libraries")
    plex_commands = plex_parser.add_subparsers(dest="plex_command", required=True)
    plex_commands.add_parser("sections", help="list libraries and their folders")
    refresh_parser = plex_commands.add_parser("refresh", help="rescan a music library")
    refresh_parser.add_argument(
        "--section", help="library id or title (or set PLEX_SECTION)"
    )
    folders_parser = commands.add_parser(
        "folders", help="make inbox and holding folders that Plex ignores"
    )
    folders_parser.add_argument("--inbox", type=Path, required=True)
    folders_parser.add_argument("--holding", type=Path, required=True)
    folders_parser.add_argument(
        "--path-map",
        action="append",
        help="MAC=SERVER, for example /Volumes/media=/data (or set PLEX_PATH_MAP)",
    )
    folders_parser.add_argument(
        "--apply", action="store_true", help="create the folders (default is a dry run)"
    )
    log_parser = commands.add_parser("log", help="show the change log")
    log_parser.add_argument("--batch")
    log_parser.add_argument("--action")
    log_parser.add_argument("--since", type=datetime.fromisoformat, help="YYYY-MM-DD")
    log_parser.add_argument("--last", type=int, help="only the newest N entries")
    log_parser.add_argument("--json", action="store_true", help="print raw entries")
    args = parser.parse_args(argv)

    if args.command == "log":
        return show_log(env, args)
    if args.command == "plex":
        return plex_command(env, args, now(), http)
    if args.command == "folders":
        return folders_command(env, args, now(), http)
    if not print_results(preflight(env, run)):
        return 1
    if args.command == "lint":
        return lint(env, run, now())
    if args.command == "ingest":
        return ingest(env, run, now(), args.source, args.unattended)
    if args.command == "split":
        return split(env, run, now(), args, which)
    if args.command == "summary":
        return report_batch(env, run, args.batch, now())
    return 0


if __name__ == "__main__":
    sys.exit(main())
