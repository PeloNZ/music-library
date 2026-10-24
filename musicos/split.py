"""Split a FLAC image plus cue sheet into one FLAC per track."""

from __future__ import annotations

import re
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
