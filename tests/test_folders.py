from pathlib import Path, PurePosixPath

import pytest

from musicos.folders import (
    PLEXIGNORE,
    FolderError,
    check_outside_plex,
    create_plex_free_folder,
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


def test_creating_a_folder_writes_a_plexignore_that_ignores_everything(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "music-inbox"

    result = create_plex_free_folder(folder)

    assert folder.is_dir()
    assert (folder / ".plexignore").read_text() == PLEXIGNORE
    assert "\n*\n" in PLEXIGNORE
    assert result.made and result.plexignore_written


def test_a_missing_parent_is_an_error_and_nothing_is_created(tmp_path: Path) -> None:
    folder = tmp_path / "not-mounted" / "music-inbox"

    with pytest.raises(FolderError, match="is the share mounted"):
        create_plex_free_folder(folder)

    assert not (tmp_path / "not-mounted").exists()


def test_an_existing_folder_is_kept_and_still_gets_its_plexignore(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "music-inbox"
    folder.mkdir()
    (folder / "album").mkdir()

    result = create_plex_free_folder(folder)

    assert (folder / "album").is_dir()
    assert not result.made
    assert result.plexignore_written


def test_an_existing_plexignore_is_never_overwritten(tmp_path: Path) -> None:
    folder = tmp_path / "music-inbox"
    folder.mkdir()
    (folder / ".plexignore").write_text("# mine\nTrash/\n")

    result = create_plex_free_folder(folder)

    assert (folder / ".plexignore").read_text() == "# mine\nTrash/\n"
    assert not result.plexignore_written


def test_running_it_twice_changes_nothing_the_second_time(tmp_path: Path) -> None:
    folder = tmp_path / "music-inbox"
    create_plex_free_folder(folder)

    again = create_plex_free_folder(folder)

    assert not again.made
    assert not again.plexignore_written


def test_a_plexignore_that_is_a_dangling_symlink_is_not_written_through(
    tmp_path: Path,
) -> None:
    victim = tmp_path / "victim.txt"
    folder = tmp_path / "inbox"
    folder.mkdir()
    (folder / ".plexignore").symlink_to(victim)

    result = create_plex_free_folder(folder)

    assert not victim.exists()
    assert result.plexignore_written is False
