from pathlib import Path

import pytest

from musicos.cli import main
from musicos.runner import Output

MOUNTS = "//chrisw@192.168.0.63/music on /Volumes/music (smbfs, nodev)\n"
VERSION = "beets version 2.14.1\nplugins: chroma, missing\n"


def make_beetsdir(tmp_path: Path) -> dict[str, str]:
    (tmp_path / "config.yaml").write_text(
        "directory: /Volumes/music\nplugins: chroma missing\n"
    )
    return {"BEETSDIR": str(tmp_path)}


def fake_run(mounts: str = MOUNTS, beet_code: int = 0):  # type: ignore[no-untyped-def]
    def run(cmd: list[str]) -> Output:
        if cmd[0] == "mount":
            return Output(mounts, "", 0)
        return Output(VERSION, "boom: bad config" if beet_code else "", beet_code)

    return run


def test_preflight_passes_when_everything_is_in_place(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["preflight"], env=make_beetsdir(tmp_path), run=fake_run())

    assert code == 0
    assert "FAIL" not in capsys.readouterr().out


def test_preflight_fails_when_share_is_not_mounted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["preflight"], env=make_beetsdir(tmp_path), run=fake_run(mounts=""))

    assert code == 1
    assert "FAIL mount" in capsys.readouterr().out


def test_preflight_fails_when_beetsdir_is_unset(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["preflight"], env={}, run=fake_run())

    assert code == 1
    assert "FAIL beetsdir" in capsys.readouterr().out


def test_preflight_reports_a_failing_beet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["preflight"], env=make_beetsdir(tmp_path), run=fake_run(beet_code=1))

    assert code == 1
    assert "FAIL beet: boom: bad config" in capsys.readouterr().out


def test_preflight_reports_a_failing_beet_with_no_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def run(cmd: list[str]) -> Output:
        return Output(MOUNTS, "", 0) if cmd[0] == "mount" else Output("", "", 1)

    code = main(["preflight"], env=make_beetsdir(tmp_path), run=run)

    assert code == 1
    assert "FAIL beet:" in capsys.readouterr().out
