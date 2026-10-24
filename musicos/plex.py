"""Talk to Plex Media Server: list libraries and start a rescan.

The token goes in the `X-Plex-Token` header and is never printed or logged.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
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


@dataclass(frozen=True)
class Response:
    status: int
    body: str


Get = Callable[[str, Mapping[str, str]], Response]


def http_get(url: str, headers: Mapping[str, str]) -> Response:
    """The one real network call. An HTTP error status is returned, not raised."""
    request = urllib.request.Request(url, headers=dict(headers))
    try:
        with urllib.request.urlopen(request, timeout=10) as reply:
            return Response(reply.status, reply.read().decode())
    except urllib.error.HTTPError as exc:
        return Response(exc.code, "")


class Plex:
    def __init__(self, url: str, token: str, get: Get = http_get) -> None:
        self.url = url.rstrip("/")
        self._token = token
        self._get = get

    def _request(self, path: str) -> Response:
        headers = {"X-Plex-Token": self._token, "Accept": "application/json"}
        try:
            response = self._get(self.url + path, headers)
        except OSError as exc:
            raise PlexError(f"cannot reach {self.url}: {exc}") from exc
        if response.status == 401:
            raise PlexError("Plex rejected the token (401)")
        if not 200 <= response.status < 300:
            raise PlexError(f"Plex answered {response.status} for {path}")
        return response

    def sections(self) -> list[Section]:
        return parse_sections(self._request("/library/sections").body)

    def refresh(self, section_id: str) -> None:
        """Start a rescan of one library. Plex scans in the background."""
        self._request(f"/library/sections/{section_id}/refresh")
