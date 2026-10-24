"""Fake external tools shared by tests."""

import os
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from musicos.plex import Response
from musicos.runner import Output


class Tools:
    """Fake cuebreakpoints, shnsplit and cuetag.sh. shnsplit writes track files."""

    def __init__(self, tracks_made: int = 3, fail: str | None = None) -> None:
        self.tracks_made = tracks_made
        self.fail = fail
        self.commands: list[list[str]] = []

    def __call__(self, cmd: list[str]) -> Output:
        self.commands.append(cmd)
        if cmd[0] == self.fail:
            return Output("", f"{cmd[0]}: boom\n", 1)
        if cmd[0] == "cuebreakpoints":
            return Output("5:20.56\n8:08.32\n", "", 0)
        if cmd[0] == "shnsplit":
            out_dir = Path(cmd[cmd.index("-d") + 1])
            for n in range(1, self.tracks_made + 1):
                (out_dir / f"split-track{n:02d}.flac").write_bytes(b"x")
        return Output("", "", 0)


class FakeHttp:
    """Fake HTTP GET. Records each request. `routes` maps the end of a URL to a
    response; anything else gets `response`."""

    def __init__(
        self,
        response: Response | None = None,
        error: OSError | None = None,
        routes: dict[str, Response] | None = None,
    ) -> None:
        self.response = response or Response(200, "")
        self.error = error
        self.routes = routes or {}
        self.requests: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: Mapping[str, str]) -> Response:
        self.requests.append((url, dict(headers)))
        if self.error:
            raise self.error
        for end, response in self.routes.items():
            if url.endswith(end):
                return response
        return self.response

    def paths(self) -> list[str]:
        return [url.split(":32400", 1)[-1] for url, _ in self.requests]


def on_another_device(monkeypatch: pytest.MonkeyPatch, folder: Path) -> None:
    """Make `os.stat` report a different device id for one existing folder."""
    folder.mkdir(parents=True, exist_ok=True)
    real_stat = os.stat
    target = str(folder)

    def fake_stat(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
        st = real_stat(path, *args, **kwargs)
        if str(path) != target:
            return st
        fields = list(st)
        fields[2] = st.st_dev + 1
        return os.stat_result(fields)

    monkeypatch.setattr(os, "stat", fake_stat)


def clock(*times: datetime) -> Callable[[], datetime]:
    """A clock that returns each given time once, in order."""
    ticks = iter(times)
    return lambda: next(ticks)
