"""Inbox and holding folders that Plex must not scan.

Plex sees the server's paths, such as /data/jbod2/media/music. This Mac sees
the same files through a mounted share, such as /Volumes/music. A path map
(`MAC=SERVER`) joins the two, so a folder can be checked against Plex's
library folders before it is made.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class FolderError(Exception):
    pass


PathMap = list[tuple[Path, PurePosixPath]]


def parse_path_map(items: list[str]) -> PathMap:
    """`MAC=SERVER` pairs, for example `/Volumes/media=/data`."""
    maps: PathMap = []
    for item in items:
        mac, _, server = item.partition("=")
        if not mac or not server.startswith("/"):
            raise FolderError(f"path map {item!r} must look like MAC=SERVER")
        maps.append((Path(mac), PurePosixPath(server)))
    return maps


def to_server_path(path: Path, maps: PathMap) -> PurePosixPath | None:
    """The server path of a Mac path, by the longest matching share prefix."""
    for mac, server in sorted(maps, key=lambda m: len(m[0].parts), reverse=True):
        if path == mac or mac in path.parents:
            return server / PurePosixPath(*path.relative_to(mac).parts)
    return None


def check_outside_plex(
    server_path: PurePosixPath, libraries: list[PurePosixPath]
) -> None:
    """Raise unless the folder is outside every Plex library folder."""
    for library in libraries:
        if server_path == library:
            raise FolderError(f"{server_path} is a Plex library folder")
        if library in server_path.parents:
            raise FolderError(
                f"{server_path} is inside the Plex library folder {library}"
            )


PLEXIGNORE = "# Plex must not scan this folder.\n*\n"


@dataclass(frozen=True)
class FolderResult:
    path: Path
    made: bool
    plexignore_written: bool


def create_plex_free_folder(path: Path) -> FolderResult:
    """Make the folder, and a .plexignore that ignores everything in it.

    The parent must already exist. A missing parent usually means a share is
    not mounted, and making it would leave a local folder at the share's path.
    An existing folder and an existing .plexignore are left as they are.
    """
    if not path.parent.is_dir():
        raise FolderError(f"{path.parent} does not exist; is the share mounted?")
    made = not path.exists()
    path.mkdir(exist_ok=True)
    ignore = path / ".plexignore"
    written = not ignore.exists()
    if written:
        ignore.write_text(PLEXIGNORE)
    return FolderResult(path, made, written)
