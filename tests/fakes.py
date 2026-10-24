"""Fake external tools shared by tests."""

from pathlib import Path

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
