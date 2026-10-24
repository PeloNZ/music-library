"""Find the same album more than once, before anything is imported.

This only reads. It describes each folder of audio files, groups folders that
look like the same album, and shows them side by side. The user chooses which
to keep: it never picks one and never deletes.
"""

from __future__ import annotations

import os
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import mutagen

from musicos.ingest import AUDIO_SUFFIXES
from musicos.split import cue_track_count, read_cue


@dataclass(frozen=True)
class Tags:
    album: str
    artist: str
    year: str
    disc: str
    length: float
    fmt: str


TagReader = Callable[[Path], Tags | None]


@dataclass(frozen=True)
class Release:
    folder: Path
    artist: str
    album: str
    year: str
    disc: str
    tracks: int
    seconds: float
    fmt: str
    size: int
    cue: bool
    unreadable: int


def _audio_files(folder: Path) -> list[Path]:
    return sorted(
        p
        for p in folder.iterdir()
        if p.is_file()
        and not p.name.startswith("._")
        and p.suffix.lower() in AUDIO_SUFFIXES
    )


def audio_folders(root: Path) -> list[Path]:
    """Every folder with audio files directly inside, in path order."""
    return sorted(
        Path(folder)
        for folder, _, _ in os.walk(root, followlinks=False)
        if _audio_files(Path(folder))
    )


def _most_common(values: list[str], default: str = "") -> str:
    counted = Counter(v for v in values if v)
    return counted.most_common(1)[0][0] if counted else default


def cue_header(text: str) -> dict[str, str]:
    """Artist, album and year from the lines before the first TRACK."""
    header: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if re.match(r"TRACK\s+\d+", line, re.IGNORECASE):
            break
        if match := re.match(r'PERFORMER\s+"(.*)"', line, re.IGNORECASE):
            header.setdefault("artist", match[1])
        elif match := re.match(r'TITLE\s+"(.*)"', line, re.IGNORECASE):
            header.setdefault("album", match[1])
        elif match := re.match(r"REM\s+DATE\s+(\S+)", line, re.IGNORECASE):
            header.setdefault("year", match[1])
    return header


def describe(folder: Path, read_tags: TagReader) -> Release:
    """One folder as a release. A single audio file with a cue sheet is an
    image rip: its track count and, where the tags are empty, its names come
    from the cue sheet."""
    files = _audio_files(folder)
    tags = [t for t in (read_tags(p) for p in files) if t]
    artist = _most_common([t.artist for t in tags])
    album = _most_common([t.album for t in tags])
    year = _most_common([t.year for t in tags])
    tracks = len(files)
    cues = sorted(p for p in folder.iterdir() if p.suffix.lower() == ".cue")
    is_rip = len(files) == 1 and bool(cues)
    if is_rip:
        text = read_cue(cues[0])
        header = cue_header(text)
        artist = artist or header.get("artist", "")
        album = album or header.get("album", "")
        year = year or header.get("year", "")
        tracks = cue_track_count(text)
    return Release(
        folder=folder,
        artist=artist,
        album=album,
        year=year,
        disc=_most_common([t.disc for t in tags], "1"),
        tracks=tracks,
        seconds=sum(t.length for t in tags),
        fmt=_most_common([t.fmt for t in tags]),
        size=sum(p.stat().st_size for p in files),
        cue=is_rip,
        unreadable=len(files) - len(tags),
    )


def normalize(name: str) -> str:
    """A name for comparing: no case, accents, punctuation or bracketed notes
    such as `(Reissue 2016)`, and no leading `The`. A name made only of a
    bracket keeps its words."""
    ascii_name = (
        unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    )
    stripped = re.sub(r"\([^)]*\)|\[[^\]]*\]|\{[^}]*\}", " ", ascii_name)
    text = stripped if re.search(r"[a-z0-9]", stripped) else ascii_name
    words = re.sub(r"[^a-z0-9]+", " ", text).split()
    if len(words) > 1 and words[0] == "the":
        words = words[1:]
    return " ".join(words)


def _album_key(release: Release) -> tuple[str, str]:
    """The album name, from the tags or else from the folder name, and the disc."""
    name = release.album or re.sub(r"^\d{4}\s*-\s*", "", release.folder.name)
    return normalize(name), release.disc


def find_duplicates(releases: list[Release]) -> list[list[Release]]:
    """Groups of two or more folders that look like the same album: the same
    album name and disc, and the same artist. A folder with no artist tag
    matches any artist. Groups are in artist and album order."""
    by_album: dict[tuple[str, str], list[Release]] = defaultdict(list)
    for release in releases:
        by_album[_album_key(release)].append(release)
    groups: list[list[Release]] = []
    for members in by_album.values():
        artists = sorted({normalize(m.artist) for m in members if m.artist})
        if len(artists) <= 1:
            candidates = [members]
        else:
            candidates = [
                [m for m in members if not m.artist or normalize(m.artist) == a]
                for a in artists
            ]
        groups += [group for group in candidates if len(group) >= 2]

    def order(group: list[Release]) -> tuple[str, str]:
        first = group[0]
        return normalize(first.artist), _album_key(first)[0]

    return sorted(groups, key=order)


def _title(group: list[Release]) -> str:
    artist = _most_common([r.artist for r in group], "?")
    album = _most_common([r.album for r in group]) or group[0].folder.name
    return f"{artist} - {album} (disc {group[0].disc})"


def _row(release: Release, root: Path) -> str:
    try:
        folder = release.folder.relative_to(root)
    except ValueError:
        folder = release.folder
    notes = ", ".join(
        ["cue rip"] * release.cue
        + ([f"{release.unreadable} unreadable"] if release.unreadable else [])
    )
    return (
        f"| {folder} | {release.tracks} | {release.seconds / 60:.1f} "
        f"| {release.fmt} | {release.size / 1048576:.0f} MiB | {notes} |"
    )


def _when(when: datetime) -> str:
    return when.strftime("%Y-%m-%d %H:%M:%S")


def render_report(
    groups: list[list[Release]], checked: int, root: Path, when: datetime
) -> str:
    plural = "group" if len(groups) == 1 else "groups"
    summary = (
        f"Run at {_when(when)}. {checked} folders checked under {root}. "
        f"{len(groups)} {plural} found."
    )
    lines = ["# Duplicate albums", "", summary]
    if not groups:
        lines += ["", "No duplicate albums found."]
    for group in groups:
        lines += [
            "",
            f"## {_title(group)}",
            "",
            "| Folder | Tracks | Minutes | Format | Size | Notes |",
            "|---|---|---|---|---|---|",
        ]
        lines += [_row(r, root) for r in group]
    return "\n".join(lines) + "\n"


def activity_line(groups: list[list[Release]], checked: int, when: datetime) -> str:
    members = sum(len(g) for g in groups)
    return (
        f"{_when(when)} dupes {checked} folders checked, "
        f"{len(groups)} groups, {members} folders in groups"
    )


def read_tags(path: Path) -> Tags | None:
    """Tags and stream details of one audio file, or None if it cannot be read."""
    try:
        audio = mutagen.File(path, easy=True)
    except (mutagen.MutagenError, OSError):
        return None
    if audio is None or audio.info is None:
        return None

    def first(key: str) -> str:
        values = audio.get(key) or [""]
        return str(values[0]).strip()

    info = audio.info
    suffix = path.suffix.lstrip(".").upper()
    if hasattr(info, "bits_per_sample") and hasattr(info, "sample_rate"):
        fmt = f"{suffix} {info.bits_per_sample}/{info.sample_rate / 1000:g}"
    elif getattr(info, "bitrate", 0):
        fmt = f"{suffix} {round(info.bitrate / 1000)}k"
    else:
        fmt = suffix
    return Tags(
        album=first("album"),
        artist=first("albumartist") or first("artist"),
        year=first("date")[:4],
        disc=first("discnumber").split("/")[0] or "1",
        length=float(info.length),
        fmt=fmt,
    )
