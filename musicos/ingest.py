"""Bring new music into the library with beet import."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from musicos.runner import Output, Run, first_error

SLUG_LIMIT = 40


def make_batch_id(when: datetime, source: Path) -> str:
    """`<YYYYMMDD-HHMM>-<slug of the source folder name>`."""
    ascii_name = (
        unicodedata.normalize("NFKD", source.name)
        .encode("ascii", "ignore")
        .decode()
        .lower()
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")[:SLUG_LIMIT].strip("-")
    return f"{when:%Y%m%d-%H%M}-{slug or 'import'}"


def dry_run_command(sources: list[Path], incremental: bool = False) -> list[str]:
    """Lists the files beets would import. It does not show matches. With
    `incremental`, folders beets imported before are left out."""
    return [
        "beet",
        "import",
        "--pretend",
        *(["-i"] if incremental else []),
        *map(str, sources),
    ]


def log_path(logs: Path, batch: str, suffix: str = "") -> Path:
    return logs / f"import-{batch}{suffix}.log"


def import_command(
    sources: list[Path],
    batch: str,
    logs: Path,
    unattended: bool,
    log_suffix: str = "",
    incremental: bool = False,
) -> list[str]:
    """The real import. `-q` is only ever paired with `--quiet-fallback skip`,
    so a weak match is never applied as-is. With `incremental`, `-i -R` makes
    beets skip a folder it already imported and retry one it skipped."""
    cmd = ["beet", "import", *(["-i", "-R"] if incremental else [])]
    cmd += ["-l", str(log_path(logs, batch, log_suffix))]
    cmd += ["--set", f"musicos_batch={batch}"]
    if unattended:
        cmd += ["-q", "--quiet-fallback", "skip"]
    return cmd + [str(s) for s in sources]


RETRY_SUFFIX = "-retry"


def retry_command(skipped: list[Path], batch: str, logs: Path) -> list[str]:
    """Import the folders an unattended run skipped, with prompts."""
    return import_command(
        skipped,
        batch,
        logs,
        unattended=False,
        log_suffix=RETRY_SUFFIX,
        incremental=True,
    )


def _raise_on_failure(out: Output) -> None:
    if out.code != 0:
        raise RuntimeError(first_error(out))


EXPORT_FIELDS = "id,album,albumartist,year,mb_albumid,albumtypes"


@dataclass(frozen=True)
class BatchSummary:
    albums: int
    flagged: list[dict[str, object]]


def summarize_batch(run: Run, batch: str) -> BatchSummary:
    """Read an import batch back from beets. An album with no MusicBrainz id
    was imported as-is or never matched, so it needs a closer look."""
    out = run(
        [
            "beet",
            "export",
            "-a",
            "-f",
            "json",
            "-i",
            EXPORT_FIELDS,
            f"musicos_batch:{batch}",
        ]
    )
    _raise_on_failure(out)
    albums = json.loads(out.stdout) if out.stdout.strip() else []
    return BatchSummary(len(albums), [a for a in albums if not a.get("mb_albumid")])


AUDIO_SUFFIXES = {
    ".flac", ".mp3", ".m4a", ".ogg", ".opus", ".wav", ".aac", ".wma", ".ape", ".wv",
}  # fmt: skip


def has_audio(source: Path) -> bool:
    return any(
        p.suffix.lower() in AUDIO_SUFFIXES and not p.name.startswith("._")
        for p in source.rglob("*")
    )


def batch_items(run: Run, batch: str) -> list[str]:
    """The path of every item beets holds for an import batch."""
    out = run(["beet", "ls", "-f", "$path", f"musicos_batch:{batch}"])
    _raise_on_failure(out)
    return [line for line in out.stdout.splitlines() if line.strip()]


def held_folders(run: Run) -> set[str]:
    """The album folders beets holds. In copy mode these are library folders, never import sources."""
    out = run(["beet", "ls", "-a", "-f", "$path"])
    _raise_on_failure(out)
    return {line for line in out.stdout.splitlines() if line.strip()}


LOG_KINDS = (
    "skip",
    "asis",
    "duplicate-skip",
    "duplicate-keep",
    "duplicate-replace",
)  # the statuses beets writes: importer/session.py, tag_log


@dataclass(frozen=True)
class LogEntry:
    kind: str
    path: str


def parse_import_log(text: str) -> list[LogEntry]:
    """Albums the importer logged: skipped, imported as-is, or duplicates."""
    entries = []
    for line in text.splitlines():
        kind, _, path = line.partition(" ")
        if kind in LOG_KINDS and path:
            entries.append(LogEntry(kind, path))
    return entries


def read_import_logs(logs: Path, batch: str) -> list[LogEntry]:
    """What the importer logged for a batch. A retry log replaces the first run's skips."""
    first, retry = log_path(logs, batch), log_path(logs, batch, RETRY_SUFFIX)
    entries = parse_import_log(first.read_text()) if first.exists() else []
    if retry.exists():
        entries = [e for e in entries if e.kind != "skip"]
        entries += parse_import_log(retry.read_text())
    return entries


def entry_folders(entry: LogEntry) -> list[Path]:
    """The folders of a log entry. beets joins the folders of one album with
    "; ", so a path that exists as written is one folder."""
    if Path(entry.path).is_dir():
        return [Path(entry.path)]
    return [Path(p) for p in re.split(r"; (?=/)", entry.path)]
