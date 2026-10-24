"""The paths: layout in beetsdir/config.example.yaml, run through beets itself."""

from collections.abc import Iterator
from pathlib import Path

import beets.library
import beets.plugins
import pytest
from beets import config

EXAMPLE = Path(__file__).parent.parent / "beetsdir" / "config.example.yaml"


@pytest.fixture
def library(tmp_path: Path) -> Iterator[beets.library.Library]:
    config.clear()
    config.read(user=False, defaults=True)
    config.set_file(str(EXAMPLE))
    config["plugins"] = ["inline"]  # the only plugin the layout needs
    beets.plugins.load_plugins()
    yield beets.library.Library(str(tmp_path / "library.db"), "/lib")
    beets.plugins._instances.clear()
    config.clear()


def album_track(
    lib: beets.library.Library, comp: bool = False, **fields: object
) -> str:
    item = beets.library.Item(
        albumartist="Opeth",
        artist="Opeth",
        album="Blackwater Park",
        year=2001,
        track=3,
        disc=1,
        disctotal=1,
        title="The Drapery Falls",
        format="FLAC",
        comp=comp,
        path=b"/x/a.flac",
    )
    for key, value in fields.items():
        item[key] = value
    lib.add(item)
    lib.add_album([item])
    return item.destination(relative_to_libdir=True).decode()


def test_single_disc_album(library: beets.library.Library) -> None:
    assert (
        album_track(library) == "Opeth/2001 - Blackwater Park/03 The Drapery Falls.flac"
    )


def test_multi_disc_album_prefixes_the_disc(
    library: beets.library.Library,
) -> None:
    assert (
        album_track(library, disc=2, disctotal=2)
        == "Opeth/2001 - Blackwater Park/02-03 The Drapery Falls.flac"
    )


def test_compilation_goes_under_various_artists(
    library: beets.library.Library,
) -> None:
    assert (
        album_track(library, comp=True, albumartist="Various Artists")
        == "Various Artists/Blackwater Park/03 The Drapery Falls.flac"
    )


def test_singleton_goes_under_non_album(library: beets.library.Library) -> None:
    item = beets.library.Item(
        artist="Opeth", title="Windowpane", format="FLAC", path=b"/x/b.flac"
    )
    library.add(item)

    assert (
        item.destination(relative_to_libdir=True).decode()
        == "Opeth/Non-Album/Windowpane.flac"
    )
