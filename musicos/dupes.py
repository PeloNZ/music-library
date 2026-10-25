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
from pathlib import Path

import mutagen

from musicos.ingest import AUDIO_SUFFIXES
from musicos.split import cue_track_count, files_with_suffix, read_cue
from musicos.text import printable


@dataclass(frozen=True)
class Tags:
    album: str
    artist: str
    disc: str
    length: float
    fmt: str
    kind: str = "flac"  # flac, lossless (any other lossless) or lossy


TagReader = Callable[[Path], Tags | None]


@dataclass(frozen=True)
class Release:
    folder: Path
    artist: str
    album: str
    disc: str
    tracks: int
    seconds: float
    fmt: str
    size: int
    cue: bool
    unreadable: int
    kind: str = "flac"  # flac, lossless, lossy or unknown (no file could be read)
    ambiguous: bool = False  # one audio file with several cue sheets


def _audio_files(folder: Path) -> list[Path]:
    return files_with_suffix(folder, *AUDIO_SUFFIXES)


def _fail(error: OSError) -> None:
    raise error


def audio_folders(root: Path) -> list[Path]:
    """Every folder with audio files directly inside, in path order. A folder
    that cannot be listed, such as one on a share that dropped, raises OSError:
    a partial list would pass for a complete one."""
    return sorted(
        Path(folder)
        for folder, _, _ in os.walk(root, followlinks=False, onerror=_fail)
        if _audio_files(Path(folder))
    )


def most_common(values: list[str], default: str = "") -> str:
    counted = Counter(v for v in values if v)
    return counted.most_common(1)[0][0] if counted else default


def cue_header(text: str) -> dict[str, str]:
    """Artist and album from the lines before the first TRACK."""
    header: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if re.match(r"TRACK\s+\d+", line, re.IGNORECASE):
            break
        if match := re.match(r'PERFORMER\s+"(.*)"', line, re.IGNORECASE):
            header.setdefault("artist", printable(match[1]))
        elif match := re.match(r'TITLE\s+"(.*)"', line, re.IGNORECASE):
            header.setdefault("album", printable(match[1]))
    return header


def describe(folder: Path, read_tags: TagReader) -> Release:
    """One folder as a release. A single audio file with a cue sheet is an
    image rip: its track count and, where the tags are empty, its names come
    from the cue sheet."""
    files = _audio_files(folder)
    tags = [t for t in (read_tags(p) for p in files) if t]
    artist = most_common([t.artist for t in tags])
    album = most_common([t.album for t in tags])
    tracks = len(files)
    cues = files_with_suffix(folder, ".cue") if len(files) == 1 else []
    is_rip = len(cues) == 1
    if is_rip:
        text = read_cue(cues[0])
        header = cue_header(text)
        artist = artist or header.get("artist", "")
        album = album or header.get("album", "")
        tracks = cue_track_count(text)
    return Release(
        folder=folder,
        artist=artist,
        album=album,
        disc=most_common([t.disc for t in tags], "1"),
        tracks=tracks,
        seconds=sum(t.length for t in tags),
        fmt=most_common([t.fmt for t in tags]),
        size=sum(p.stat().st_size for p in files),
        cue=is_rip,
        unreadable=len(files) - len(tags),
        kind=most_common([t.kind for t in tags], "unknown"),
        ambiguous=len(cues) > 1,
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
    matches the artist when only one artist has the album. When several do, it
    groups only with other folders that have no artist. Groups are in artist and
    album order."""
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
                [m for m in members if m.artist and normalize(m.artist) == a]
                for a in artists
            ] + [[m for m in members if not m.artist]]
        groups += [group for group in candidates if len(group) >= 2]

    def order(group: list[Release]) -> tuple[str, str]:
        first = group[0]
        return normalize(first.artist), _album_key(first)[0]

    return sorted(groups, key=order)


LOSSLESS_TYPES = {
    "AIFF",
    "WAVE",
    "MonkeysAudio",
    "WavPack",
    "TrueAudio",
    "EasyTrueAudio",
    "TAK",
    "OggFLAC",
    "OptimFROG",
    "DSF",
    "DSDIFF",
}


def _kind(audio: mutagen.FileType) -> str:
    """flac, lossless for any other lossless format, or lossy. MP4 files are
    lossless only when the codec is ALAC: AAC is lossy but reports bit depth too."""
    name = type(audio).__name__
    if name == "FLAC":
        return "flac"
    if name in LOSSLESS_TYPES:
        return "lossless"
    if name == "EasyMP4":
        return (
            "lossless"
            if str(getattr(audio.info, "codec", "")).startswith("alac")
            else "lossy"
        )
    return "lossy"


def _disc(tag: str) -> str:
    """The disc number from a `1` or `1/2` tag. Missing, unreadable or 0, which
    beets and many taggers use for "not set", all mean disc 1."""
    number = tag.split("/")[0].strip()
    return number.lstrip("0") if number.isdigit() and number.strip("0") else "1"


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
        return printable(str(values[0]).strip())

    info = audio.info
    suffix = path.suffix.lstrip(".").upper()
    kind = _kind(audio)
    if (
        kind != "lossy"
        and hasattr(info, "bits_per_sample")
        and hasattr(info, "sample_rate")
    ):
        fmt = f"{suffix} {info.bits_per_sample}/{info.sample_rate / 1000:g}"
    elif getattr(info, "bitrate", 0):
        fmt = f"{suffix} {round(info.bitrate / 1000)}k"
    else:
        fmt = suffix
    return Tags(
        album=first("album"),
        artist=first("albumartist") or first("artist"),
        disc=_disc(first("discnumber")),
        length=float(info.length),
        fmt=fmt,
        kind=kind,
    )
