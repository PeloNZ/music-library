"""Split a FLAC image plus cue sheet into one FLAC per track."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from musicos.runner import Output, Run

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


class SplitError(Exception):
    pass


def device_of(path: Path) -> int:
    """The device id of a path, or of its nearest existing parent. Each mounted
    share has its own, so two paths on one share have the same id."""
    for candidate in (path, *path.parents):
        if candidate.exists():
            return os.stat(candidate).st_dev
    raise SplitError(f"{path} has no parent folder that exists")


def check_one_share(*paths: Path) -> None:
    """Moves must be renames on one share. Nothing is copied between shares."""
    if len({device_of(p) for p in paths}) > 1:
        raise SplitError(
            "the source, the inbox and the holding folder must be on one share: "
            + ", ".join(str(p) for p in paths)
        )


@dataclass(frozen=True)
class SplitResult:
    tracks: list[Path]
    track_count: int
    holding: Path


def _check(out: Output, tool: str) -> Output:
    if out.code != 0:
        message = out.stderr.strip().splitlines()[:1] or [f"{tool} failed"]
        raise SplitError(message[0])
    return out


def split_rip(rip: Rip, inbox: Path, holding: Path, run: Run) -> SplitResult:
    """Split one rip into the inbox and move the source folder to holding.

    The tracks are made in a staging folder first. Any failure, or a track
    count that differs from the cue sheet, removes the staging folder and
    leaves the source as it was. Nothing in the source is deleted, and an
    existing album is never overwritten.
    """
    check_one_share(rip.folder, inbox, holding)
    count = cue_track_count(read_cue(rip.cue))
    if count == 0:
        raise SplitError(f"{rip.cue.name} lists no audio tracks")
    album = inbox / rip.folder.name
    held = holding / rip.folder.name
    staging = inbox / f".split-{rip.folder.name}"
    for path in (album, held, staging):
        if path.exists():
            raise SplitError(f"{path} already exists")

    staging.mkdir(parents=True)
    try:
        points = _check(run(["cuebreakpoints", str(rip.cue)]), "cuebreakpoints")
        with tempfile.TemporaryDirectory() as tmp:
            points_file = Path(tmp) / "points.txt"
            points_file.write_text(points.stdout)
            _check(
                run(
                    ["shnsplit", "-f", str(points_file), "-q", "-o", "flac"]
                    + ["-d", str(staging), str(rip.flac)]
                ),
                "shnsplit",
            )
        made = sorted(staging.glob("split-track*.flac"))
        if len(made) != count:
            raise SplitError(f"cue lists {count} tracks, split made {len(made)}")
        _check(run(["cuetag.sh", str(rip.cue), *map(str, made)]), "cuetag.sh")
    except BaseException:
        shutil.rmtree(staging)  # made above in this call, holds only split output
        raise

    staging.rename(album)
    holding.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(rip.folder, held)
    except OSError as exc:
        raise SplitError(
            f"the tracks are in {album} but the source was not moved: {exc}"
        ) from exc
    return SplitResult(sorted(album.glob("*.flac")), count, held)
