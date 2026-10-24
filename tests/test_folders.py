from pathlib import Path, PurePosixPath

import pytest

from musicos.folders import (
    FolderError,
    check_outside_plex,
    parse_path_map,
    to_server_path,
)

MAPS = parse_path_map(
    ["/Volumes/media=/data", "/Volumes/music=/data/jbod2/media/music"]
)
LIBRARIES = [
    PurePosixPath("/data/jbod2/media/music"),
    PurePosixPath("/data/jbod2/media/Movies"),
]


def test_a_path_is_mapped_to_the_server_by_its_share_prefix() -> None:
    assert to_server_path(Path("/Volumes/media/jbod2/media/music-inbox"), MAPS) == (
        PurePosixPath("/data/jbod2/media/music-inbox")
    )


def test_the_longest_matching_prefix_wins() -> None:
    assert to_server_path(Path("/Volumes/music/Cake"), MAPS) == PurePosixPath(
        "/data/jbod2/media/music/Cake"
    )


def test_the_share_root_itself_maps() -> None:
    assert to_server_path(Path("/Volumes/media"), MAPS) == PurePosixPath("/data")


def test_a_path_on_no_mapped_share_has_no_server_path() -> None:
    assert to_server_path(Path("/Users/me/music-test"), MAPS) is None


def test_a_prefix_must_match_whole_folder_names() -> None:
    assert to_server_path(Path("/Volumes/media-old/x"), MAPS) is None


def test_a_malformed_path_map_is_rejected() -> None:
    with pytest.raises(FolderError, match="MAC=SERVER"):
        parse_path_map(["/Volumes/media"])


def test_a_sibling_of_a_library_is_outside_plex() -> None:
    server = PurePosixPath("/data/jbod2/media/music-inbox")

    check_outside_plex(server, LIBRARIES)  # does not raise


def test_a_library_folder_is_not_outside_plex() -> None:
    with pytest.raises(FolderError, match="is a Plex library folder"):
        check_outside_plex(PurePosixPath("/data/jbod2/media/music"), LIBRARIES)


def test_a_folder_inside_a_library_is_not_outside_plex() -> None:
    with pytest.raises(
        FolderError, match=r"inside the Plex library folder /data/jbod2/media/music"
    ):
        check_outside_plex(PurePosixPath("/data/jbod2/media/music/_inbox"), LIBRARIES)


def test_a_name_that_only_starts_like_a_library_is_outside_plex() -> None:
    check_outside_plex(PurePosixPath("/data/jbod2/media/music2"), LIBRARIES)
