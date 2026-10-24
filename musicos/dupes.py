"""Find the same album more than once, before anything is imported.

This only reads. It describes each folder of audio files, groups folders that
look like the same album, and shows them side by side. The user chooses which
to keep: it never picks one and never deletes.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

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
