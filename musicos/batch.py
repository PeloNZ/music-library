"""Which folders of one artist go into an import batch.

This only decides. It reads the deletion candidates log, never writes it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from musicos.dupes import Release


@dataclass
class BatchPlan:
    kept: list[Release] = field(default_factory=list)  # to import
    candidates: list[Release] = field(default_factory=list)  # open: left out
    undecided: list[list[Release]] = field(default_factory=list)  # user picks one
    to_split: list[Release] = field(default_factory=list)  # a cue rip: split first
    review: list[Release] = field(default_factory=list)  # needs a look

    @property
    def size(self) -> int:
        return sum(r.size for r in self.kept)


def plan_batch(
    releases: list[Release], groups: list[list[Release]], status: dict[str, str]
) -> BatchPlan:
    """`status` maps a folder to its deletion candidate status: open or stale."""
    plan = BatchPlan()
    in_group = {r.folder for g in groups for r in g}
    pending = [[r] for r in releases if r.folder not in in_group] + groups
    for group in pending:
        left = []
        for release in group:
            state = status.get(str(release.folder))
            if state == "open":
                plan.candidates.append(release)
            elif state == "stale" or release.ambiguous:
                plan.review.append(release)
            else:
                left.append(release)
        if len(left) > 1:
            plan.undecided.append(left)
        elif left and left[0].cue:
            plan.to_split.append(left[0])
        else:
            plan.kept += left
    plan.kept.sort(key=lambda r: r.folder)
    return plan
