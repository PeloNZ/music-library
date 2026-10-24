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

from musicos.appledouble import delete_appledouble, find_appledouble
from musicos.candidates import list_candidates, record_candidates
from musicos.changelog import filter_entries, format_entry, read_entries, record
from musicos.dupereport import activity_line as dupes_activity_line
from musicos.dupereport import render_report as render_dupes_report
from musicos.dupes import (
    TagReader,
    audio_folders,
    describe,
    find_duplicates,
    read_tags,
)
from musicos.envfile import merged_env
from musicos.folders import (
    FolderError,
    check_outside_plex,
    create_plex_free_folder,
    parse_path_map,
    to_server_path,
)
from musicos.gaps import activity_line as gaps_activity_line
from musicos.gaps import export_albums, find_gaps
from musicos.gaps import render_report as render_gaps_report
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
from musicos.plex import (
    Get,
    PlexError,
    choose_section,
    http_get,
    plex_from_env,
    section_for_path,
)
from musicos.preflight import (
    Result,
    check_beetsdir,
    check_mount,
    check_plugins,
    check_tools,
    configured_plugins,
)
from musicos.rules import decide
from musicos.runner import Run, run_command
from musicos.split import (
    SplitError,
    check_one_share,
    cue_track_count,
    read_cue,
    scan,
    split_rip,
)

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
    http: Get = http_get,
    refresh_plex: bool = True,
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
    if refresh_plex and not already:
        rescan_plex(env, http, when, batch)
    return 0


def rescan_plex(env: Mapping[str, str], http: Get, when: datetime, batch: str) -> None:
    """After an import, rescan the Plex music library that holds beets' directory.

    A rescan that cannot run never undoes the import. It prints why and moves on.
    """
    try:
        plex = plex_from_env(env, http)
    except PlexError as exc:
        print(f"plex: not refreshed ({exc})")
        return
    try:
        maps = parse_path_map([m for m in env.get("PLEX_PATH_MAP", "").split(",") if m])
        library = Path(load_config(env)["directory"])
        server = to_server_path(library, maps)
        if server is None:
            print(f"plex: not refreshed (no PLEX_PATH_MAP entry covers {library})")
            return
        section = section_for_path(server, plex.sections())
        if section is None:
            print(f"plex: not refreshed ({server} is not in a Plex music library)")
            return
        plex.refresh(section.id)
    except (PlexError, FolderError) as exc:
        print(f"WARN plex: not refreshed: {exc}")
        return
    record(
        Path(env["BEETSDIR"]) / "logs" / "changes.jsonl",
        "plex-refresh",
        when,
        batch=batch,
        section=section.id,
        title=section.title,
        locations=section.locations,
    )
    print(f"ok   plex rescan started: {section.title} ({section.id})")


def ingest(
    env: Mapping[str, str],
    run: Run,
    when: datetime,
    source: Path,
    unattended: bool,
    http: Get = http_get,
    refresh_plex: bool = True,
) -> int:
    source = source.resolve()
    if not source.is_dir() or not has_audio(source):
        print(f"FAIL source: no audio files under {source}")
        return 1
    batch = make_batch_id(when, source)
    logs = Path(env["BEETSDIR"]) / "logs"
    logs.mkdir(exist_ok=True)
    dry_run = run(dry_run_command(source))
    if dry_run.code != 0:
        message = dry_run.stderr.strip().splitlines()[:1] or [
            f"exit code {dry_run.code}"
        ]
        print(f"FAIL dry run: {message[0]}")
        return 1
    # beets prints the --pretend file list to stderr
    print(dry_run.stderr or dry_run.stdout, end="")
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
    return report_batch(env, run, batch, when, source, http, refresh_plex)


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
    try:
        check_one_share(root, inbox, holding)
    except SplitError as exc:
        print(f"FAIL shares: {exc}")
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


def gaps(env: Mapping[str, str], run: Run, when: datetime) -> int:
    try:
        albums = export_albums(run)
    except RuntimeError as exc:
        print(f"FAIL gaps: {exc}")
        return 1
    results = find_gaps(albums)
    logs = Path(env["BEETSDIR"]) / "logs"
    logs.mkdir(exist_ok=True)
    report = logs / "last-gaps-report.md"
    report.write_text(render_gaps_report(results, len(albums), when))
    log_activity(env, gaps_activity_line(results, len(albums), when))
    for r in results:
        print(f"{r.name}: {len(r.albums)}")
    print(f"report: {report}")
    return 0


def clean_appledouble(
    env: Mapping[str, str], args: argparse.Namespace, when: datetime
) -> int:
    root: Path = args.root.resolve()
    if root in (Path("/"), Path("/Volumes")):
        print(f"FAIL root: refusing to scan {root}; name a folder inside a share")
        return 1
    if not root.is_dir():
        print(f"FAIL root: {root} is not a folder")
        return 1
    if args.apply and not print_results_if_failed([check_beetsdir(env)]):
        return 1  # deleting is a change, so it must be logged
    found = find_appledouble(root)
    if not found:
        print(f"no AppleDouble files found under {root}")
        return 0
    size = sum(p.stat().st_size for p in found)
    print(f"found {len(found)} AppleDouble files ({size} bytes) under {root}")
    for path in found[:10]:
        print(f"  {path}")
    if len(found) > 10:
        print(f"  ... {len(found) - 10} more")
    if not args.apply:
        print("dry run: nothing deleted. Add --apply to delete them.")
        return 0
    result = delete_appledouble(found)
    print(f"deleted {len(result.deleted)} AppleDouble files ({result.bytes} bytes)")
    for path, reason in result.failed[:10]:
        print(f"FAIL {path.name}: {reason}")
    if result.deleted:
        record(
            Path(env["BEETSDIR"]) / "logs" / "changes.jsonl",
            "clean-appledouble",
            when,
            root=str(root),
            deleted=len(result.deleted),
            failed=len(result.failed),
            bytes=result.bytes,
            examples=[str(p) for p in result.deleted[:20]],
        )
    return 1 if result.failed else 0


def dupes(
    env: Mapping[str, str], args: argparse.Namespace, when: datetime, read: TagReader
) -> int:
    root: Path = args.root.resolve()
    if not root.is_dir():
        print(f"FAIL root: {root} is not a folder")
        return 1
    if not print_results_if_failed([check_beetsdir(env)]):
        return 1  # the report is written under BEETSDIR
    releases = [describe(folder, read) for folder in audio_folders(root)]
    groups = [decide(g) for g in find_duplicates(releases)]
    report = render_dupes_report(groups, len(releases), root, when)
    logs = Path(env["BEETSDIR"]) / "logs"
    logs.mkdir(exist_ok=True)
    (logs / "last-duplicates-report.md").write_text(report)
    log_activity(env, dupes_activity_line(groups, len(releases), when))
    candidates_log = logs / "deletion-candidates.jsonl"
    added = record_candidates(
        candidates_log, [d for group in groups for d in group], root, when
    )
    print(report, end="")
    noun = "candidate" if added == 1 else "candidates"
    print(f"{added} new deletion {noun} added to {candidates_log}")
    return 0


def candidates_command(env: Mapping[str, str], args: argparse.Namespace) -> int:
    if not print_results_if_failed([check_beetsdir(env)]):
        return 1
    log = Path(env["BEETSDIR"]) / "logs" / "deletion-candidates.jsonl"
    if not read_entries(log):
        print("no deletion candidates recorded")
        return 0
    listed = list_candidates(log, include_done=args.all)
    if not listed:
        print("no open deletion candidates")
        return 0
    counts = {"open": 0, "stale": 0, "done": 0}
    open_bytes = 0
    for entry, status in listed:
        counts[status] += 1
        if status == "open":
            open_bytes += entry["size"]
        print(
            f"{status:5}  {entry['size'] / 1048576:5.0f} MiB  {entry['album']}  {entry['folder']}"
        )
        print(f"       why: {entry['rule']}")
        print(f"       kept: {'; '.join(entry['kept_by'])}")
        if status == "stale":
            print("       do not delete: a copy that outranked it is missing")
    summary = f"{counts['open']} open ({open_bytes / 1048576:.0f} MiB), {counts['stale']} stale"
    if args.all:
        summary += f", {counts['done']} done"
    print(summary)
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
    tag_reader: TagReader = read_tags,
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
    commands.add_parser("gaps", help="report albums with no artist, year, genre or art")
    ingest_parser = commands.add_parser("ingest", help="import a folder of new music")
    ingest_parser.add_argument("source", type=Path)
    ingest_parser.add_argument(
        "--unattended",
        action="store_true",
        help="run the import now; skip albums that need a decision",
    )
    ingest_parser.add_argument(
        "--no-plex-refresh", action="store_true", help="do not rescan Plex afterwards"
    )
    summary_parser = commands.add_parser("summary", help="report on an import batch")
    summary_parser.add_argument("batch")
    summary_parser.add_argument(
        "--no-plex-refresh", action="store_true", help="do not rescan Plex afterwards"
    )
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
    clean_parser = commands.add_parser(
        "clean-appledouble", help="remove macOS ._ shadow files under a folder"
    )
    clean_parser.add_argument(
        "root", type=Path, help="folder to scan, not a whole share"
    )
    clean_parser.add_argument(
        "--apply", action="store_true", help="delete them (default is a dry run)"
    )
    dupes_parser = commands.add_parser(
        "dupes", help="report the same album in more than one folder (read-only)"
    )
    dupes_parser.add_argument(
        "root", type=Path, help="folder to scan, such as an artist"
    )
    candidates_parser = commands.add_parser(
        "candidates", help="list the deletion candidates still waiting for you"
    )
    candidates_parser.add_argument(
        "--all", action="store_true", help="include candidates that are already gone"
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
    if args.command == "clean-appledouble":
        return clean_appledouble(env, args, now())
    if args.command == "dupes":
        return dupes(env, args, now(), tag_reader)
    if args.command == "candidates":
        return candidates_command(env, args)
    if not print_results(preflight(env, run)):
        return 1
    if args.command == "lint":
        return lint(env, run, now())
    if args.command == "gaps":
        return gaps(env, run, now())
    if args.command == "ingest":
        return ingest(
            env,
            run,
            now(),
            args.source,
            args.unattended,
            http,
            not args.no_plex_refresh,
        )
    if args.command == "split":
        return split(env, run, now(), args, which)
    if args.command == "summary":
        return report_batch(
            env, run, args.batch, now(), None, http, not args.no_plex_refresh
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
