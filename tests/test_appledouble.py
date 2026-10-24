import os
from pathlib import Path

from musicos.appledouble import APPLEDOUBLE_MAGIC, find_appledouble

HEADER = APPLEDOUBLE_MAGIC + b"\x00\x02\x00\x00" + b"\x00" * 4088  # a 4096-byte shadow


def shadow(path: Path, content: bytes = HEADER) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_the_magic_number_is_the_appledouble_header() -> None:
    assert APPLEDOUBLE_MAGIC == bytes([0x00, 0x05, 0x16, 0x07])


def test_finds_shadow_files_in_any_subfolder(tmp_path: Path) -> None:
    a = shadow(tmp_path / "Cake" / "Fashion Nugget" / "._01 Song.flac")
    b = shadow(tmp_path / "._cover.jpg")

    assert find_appledouble(tmp_path) == sorted([a, b])


def test_ignores_a_file_that_starts_with_dot_underscore_but_is_not_a_shadow(
    tmp_path: Path,
) -> None:
    real = tmp_path / "._notes.txt"
    real.write_text("my own notes, not a resource fork")

    assert find_appledouble(tmp_path) == []
    assert real.exists()


def test_ignores_other_hidden_files(tmp_path: Path) -> None:
    (tmp_path / ".plexignore").write_text("*\n")
    shadow(tmp_path / ".DS_Store")

    assert find_appledouble(tmp_path) == []


def test_ignores_an_empty_shadow_named_file(tmp_path: Path) -> None:
    (tmp_path / "._empty").write_bytes(b"")

    assert find_appledouble(tmp_path) == []


def test_does_not_follow_a_symlinked_folder(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    shadow(outside / "._x")
    library = tmp_path / "library"
    library.mkdir()
    os.symlink(outside, library / "link")

    assert find_appledouble(library) == []


def test_a_shadow_without_its_data_file_is_still_found(tmp_path: Path) -> None:
    orphan = shadow(tmp_path / "._gone.flac")

    assert find_appledouble(tmp_path) == [orphan]
