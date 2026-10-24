"""Talk to Plex Media Server: list libraries and start a rescan.

The token goes in the `X-Plex-Token` header and is never printed or logged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass


class PlexError(Exception):
    pass


@dataclass(frozen=True)
class Section:
    id: str
    type: str
    title: str
    locations: list[str]


def parse_sections(body: str) -> list[Section]:
    """The libraries in a `/library/sections` JSON response, with every folder.

    JSON is requested on purpose: it needs no XML parser, which could be fed a
    hostile document over plain HTTP.
    """
    container = json.loads(body)["MediaContainer"]
    return [
        Section(
            id=str(d["key"]),
            type=d["type"],
            title=d["title"],
            locations=[loc["path"] for loc in d.get("Location", [])],
        )
        for d in container.get("Directory", [])
    ]


def music_sections(sections: list[Section]) -> list[Section]:
    return [s for s in sections if s.type == "artist"]


def _names(sections: list[Section]) -> str:
    return ", ".join(f"{s.title} ({s.id})" for s in sections)


def choose_section(sections: list[Section], wanted: str | None) -> Section:
    """The music library to rescan: the one named by id or title, or the only one."""
    music = music_sections(sections)
    if not music:
        raise PlexError("no music library on this server")
    if wanted is None:
        if len(music) > 1:
            raise PlexError(
                f"several music libraries: {_names(music)}. Choose one with --section"
            )
        return music[0]
    for section in music:
        if wanted == section.id or wanted.casefold() == section.title.casefold():
            return section
    raise PlexError(f"no library {wanted!r}. Choices: {_names(music)}")
