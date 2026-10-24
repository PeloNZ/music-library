"""Find and remove the `._*` shadow files macOS writes next to files on an SMB share.

A shadow file holds a file's extended attributes in the AppleDouble format.
A file whose name starts with `._` is only treated as one when its first
bytes are the AppleDouble header, so a real file with such a name is safe.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

APPLEDOUBLE_MAGIC = bytes([0x00, 0x05, 0x16, 0x07])


def _is_shadow(path: Path) -> bool:
    if not stat.S_ISREG(path.lstat().st_mode):  # a FIFO would block on open
        return False
    with path.open("rb") as f:
        return f.read(len(APPLEDOUBLE_MAGIC)) == APPLEDOUBLE_MAGIC


def find_appledouble(root: Path) -> list[Path]:
    """Every AppleDouble shadow file under root, in path order. Symlinked
    folders are not followed. A shadow whose data file is gone is included."""
    found = []
    for folder, _, names in os.walk(root, followlinks=False):
        for name in names:
            path = Path(folder) / name
            if not name.startswith("._"):
                continue
            try:
                shadow = _is_shadow(path)
            except OSError:
                continue  # a file that cannot be read is not deleted either
            if shadow:
                found.append(path)
    return sorted(found)


@dataclass(frozen=True)
class DeleteResult:
    deleted: list[Path] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)
    bytes: int = 0


def delete_appledouble(paths: list[Path]) -> DeleteResult:
    """Delete shadow files. Each is checked again just before it goes. A file
    that cannot be deleted is reported and the rest carry on."""
    deleted: list[Path] = []
    failed: list[tuple[Path, str]] = []
    freed = 0
    for path in paths:
        try:
            if not _is_shadow(path):
                continue
            size = path.stat().st_size
            path.unlink()
        except OSError as exc:
            failed.append((path, exc.strerror or str(exc)))
            continue
        deleted.append(path)
        freed += size
    return DeleteResult(deleted, failed, freed)
