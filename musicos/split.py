"""Split a FLAC image plus cue sheet into one FLAC per track."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

AUDIO_TRACK = re.compile(r"^\s*TRACK\s+\d+\s+AUDIO\b", re.IGNORECASE | re.MULTILINE)


def read_cue(path: Path) -> str:
    """UTF-8 (with or without a byte order mark), else Windows-1252."""
    data = path.read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252")


def cue_track_count(text: str) -> int:
    return len(AUDIO_TRACK.findall(text))


@dataclass(frozen=True)
class Rip:
    folder: Path
    flac: Path
    cue: Path


@dataclass(frozen=True)
class Scan:
    rips: list[Rip] = field(default_factory=list)
    ambiguous: list[Path] = field(default_factory=list)


def _files(folder: Path, suffix: str) -> list[Path]:
    return sorted(
        p
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() == suffix and not p.name.startswith("._")
    )


def scan(root: Path) -> Scan:
    """Folders under root that hold one FLAC image and a cue sheet.

    One FLAC with two or more cue sheets is ambiguous: the user picks one.
    """
    rips: list[Rip] = []
    ambiguous: list[Path] = []
    for folder in sorted({p.parent for p in root.rglob("*") if p.is_file()}):
        flacs, cues = _files(folder, ".flac"), _files(folder, ".cue")
        if len(flacs) != 1 or not cues:
            continue
        if len(cues) == 1:
            rips.append(Rip(folder, flacs[0], cues[0]))
        else:
            ambiguous.append(folder)
    return Scan(rips, ambiguous)
