"""What to do with the copies in a group of duplicate albums.

The ruleset, highest priority first:

1. FLAC tracks already split.
2. A single FLAC with a cue file.
3. Lossy tracks.

A copy is a deletion candidate only when a strictly higher priority copy
exists. This only decides and records: it never deletes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from musicos.dupes import Release

PRIORITY = {
    1: "FLAC tracks already split",
    2: "FLAC + cue file",
    3: "lossy tracks",
}


def rank(release: Release) -> int | None:
    """1 split FLAC, 2 FLAC with a cue file, 3 lossy. None when the format is
    not in the ranking, such as WAV or ALAC."""
    if release.kind == "flac":
        return 2 if release.cue else 1
    if release.kind == "lossy":
        return 3
    return None


@dataclass(frozen=True)
class Decision:
    release: Release
    action: str  # keep, tie, candidate or review
    reason: str
    kept_by: tuple[Path, ...] = ()  # the copies that outrank a candidate


def decide(group: list[Release]) -> list[Decision]:
    """One decision per copy, in the order of the group.

    - keep: the single highest priority copy.
    - tie: several copies share the top priority, so the user chooses.
    - candidate: a strictly lower priority than a copy that has at least as
      many tracks. Marked for the user to delete by hand.
    - review: a lower priority copy with more tracks than the best copy, or any
      group that holds a format that is not in the ranking. Nothing is marked.
    """
    ranks = [rank(r) for r in group]
    if None in ranks:
        return [
            Decision(
                r,
                "review",
                f"{r.fmt} is not in the ranking"
                if rank(r) is None
                else "the group holds a format that is not in the ranking",
            )
            for r in group
        ]
    ranked = [k for k in ranks if k is not None]  # every rank is known here
    best = min(ranked)
    keepers = [r for r, k in zip(group, ranked, strict=True) if k == best]
    kept_by = tuple(r.folder for r in keepers)
    best_tracks = max(r.tracks for r in keepers)
    decisions = []
    for release, release_rank in zip(group, ranked, strict=True):
        if release_rank == best:
            if len(keepers) == 1:
                decisions.append(Decision(release, "keep", PRIORITY[best]))
            else:
                decisions.append(
                    Decision(
                        release,
                        "tie",
                        f"{len(keepers)} copies share the top priority ({PRIORITY[best]})",
                    )
                )
        elif release.tracks > best_tracks:
            decisions.append(
                Decision(
                    release,
                    "review",
                    f"{release.tracks} tracks here, only {best_tracks} in the "
                    f"{PRIORITY[best]} copy",
                )
            )
        else:
            decisions.append(
                Decision(
                    release,
                    "candidate",
                    f"{PRIORITY[release_rank]} is lower priority than {PRIORITY[best]}",
                    kept_by,
                )
            )
    return decisions
