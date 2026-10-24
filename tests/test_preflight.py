from pathlib import Path

from musicos.preflight import check_beetsdir, check_mount, check_plugins

MOUNTS = """\
/dev/disk3s1s1 on / (apfs, sealed, local, read-only, journaled)
//chrisw@192.168.0.63/music on /Volumes/music (smbfs, nodev, nosuid, mounted by chriswharton)
"""


def test_mount_present_passes() -> None:
    assert check_mount("/Volumes/music", MOUNTS).ok


def test_folder_inside_mount_passes() -> None:
    assert check_mount("/Volumes/music/Cake", MOUNTS).ok


def test_share_not_mounted_fails() -> None:
    root_only = MOUNTS.splitlines()[0] + "\n"

    result = check_mount("/Volumes/music", root_only)

    assert not result.ok
    assert "/Volumes/music" in result.detail


def test_beetsdir_unset_fails() -> None:
    result = check_beetsdir({})

    assert not result.ok
    assert "BEETSDIR" in result.detail


def test_beetsdir_without_config_fails(tmp_path: Path) -> None:
    result = check_beetsdir({"BEETSDIR": str(tmp_path)})

    assert not result.ok
    assert "config.yaml" in result.detail


def test_beetsdir_with_config_passes(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text("directory: /x\n")

    result = check_beetsdir({"BEETSDIR": str(tmp_path)})

    assert result.ok


VERSION = (
    "beets version 2.14.1\nPython version 3.14.8\nplugins: chroma, fetchart, missing\n"
)


def test_plugins_all_present_passes() -> None:
    assert check_plugins(VERSION, ["chroma", "missing"]).ok


def test_missing_plugin_is_named() -> None:
    result = check_plugins(VERSION, ["chroma", "lastgenre", "embedart"])

    assert not result.ok
    assert "lastgenre" in result.detail
    assert "embedart" in result.detail
    assert "chroma" not in result.detail
