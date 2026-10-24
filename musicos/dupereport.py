"""The duplicate albums report: each group as a table, with what the ruleset
decided for every copy."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from musicos.changelog import stamp
from musicos.dupes import most_common
from musicos.rules import Decision

ACTIONS = {
    "keep": "keep",
    "tie": "tie: choose one",
    "candidate": "deletion candidate",
    "review": "review",
}


def _title(group: list[Decision]) -> str:
    releases = [d.release for d in group]
    artist = most_common([r.artist for r in releases], "?")
    album = most_common([r.album for r in releases]) or releases[0].folder.name
    return f"{artist} - {album} (disc {releases[0].disc})"


def _row(decision: Decision, root: Path) -> str:
    release = decision.release
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
        f"| {release.fmt} | {release.size / 1048576:.0f} MiB | {notes} "
        f"| {ACTIONS[decision.action]} |"
    )


def _candidates(groups: list[list[Decision]]) -> list[Decision]:
    return [d for group in groups for d in group if d.action == "candidate"]


def render_report(
    groups: list[list[Decision]], checked: int, root: Path, when: datetime
) -> str:
    plural = "group" if len(groups) == 1 else "groups"
    summary = (
        f"Run at {stamp(when)}. {checked} folders checked under {root}. "
        f"{len(groups)} {plural} found."
    )
    lines = ["# Duplicate albums", "", summary]
    if not groups:
        lines += ["", "No duplicate albums found."]
    candidates = _candidates(groups)
    if candidates:
        size = sum(d.release.size for d in candidates) / 1048576
        noun = "candidate" if len(candidates) == 1 else "candidates"
        lines += [
            "",
            f"{len(candidates)} deletion {noun} ({size:.0f} MiB). Nothing was deleted.",
        ]
    for group in groups:
        lines += [
            "",
            f"## {_title(group)}",
            "",
            "| Folder | Tracks | Minutes | Format | Size | Notes | Action |",
            "|---|---|---|---|---|---|---|",
        ]
        lines += [_row(d, root) for d in group]
        reasons = [d for d in group if d.action != "keep"]
        if reasons:
            lines.append("")
            lines += [f"- {d.release.folder.name}: {d.reason}" for d in reasons]
    return "\n".join(lines) + "\n"


def activity_line(groups: list[list[Decision]], checked: int, when: datetime) -> str:
    members = sum(len(g) for g in groups)
    candidates = len(_candidates(groups))
    noun = "candidate" if candidates == 1 else "candidates"
    return (
        f"{stamp(when)} dupes {checked} folders checked, {len(groups)} groups, "
        f"{members} folders in groups, {candidates} deletion {noun}"
    )
