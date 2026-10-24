import sys
from pathlib import Path

import pytest

from musicos.runner import first_error, stream_command

PY = sys.executable


def test_stream_command_writes_each_line_to_the_log_and_the_terminal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = tmp_path / "import.out"

    out = stream_command([PY, "-c", "print('one'); print('two')"], log)

    assert log.read_text().splitlines()[1:] == ["one", "two"]
    assert capsys.readouterr().out == "one\ntwo\n"
    assert out.stdout == "one\ntwo\n"
    assert out.code == 0


def test_stream_command_starts_the_log_with_the_command_it_ran(tmp_path: Path) -> None:
    log = tmp_path / "import.out"

    stream_command([PY, "-c", "pass"], log)

    assert log.read_text() == f"$ {PY} -c pass\n"


def test_stream_command_merges_stderr_into_the_log_in_order(tmp_path: Path) -> None:
    log = tmp_path / "import.out"
    code = "import sys; print('a'); sys.stdout.flush(); print('b', file=sys.stderr)"

    stream_command([PY, "-c", code], log)

    assert log.read_text().splitlines()[1:] == ["a", "b"]


def test_stream_command_reports_a_failure_with_its_last_line(tmp_path: Path) -> None:
    code = "import sys; print('working'); print('error: no space', file=sys.stderr); sys.exit(3)"

    out = stream_command([PY, "-c", code], tmp_path / "import.out")

    assert out.code == 3
    assert first_error(out) == "error: no space"


def test_stream_command_makes_the_child_write_each_line_at_once(
    tmp_path: Path,
) -> None:
    out = stream_command(
        [PY, "-c", "import os; print(os.environ['PYTHONUNBUFFERED'])"],
        tmp_path / "import.out",
    )

    assert out.stdout == "1\n"


def test_stream_command_appends_to_an_existing_log(tmp_path: Path) -> None:
    log = tmp_path / "import.out"
    log.write_text("earlier\n")

    stream_command([PY, "-c", "print('later')"], log)

    assert log.read_text().startswith("earlier\n")
    assert log.read_text().endswith("later\n")


def test_stream_command_survives_output_that_is_not_utf8(tmp_path: Path) -> None:
    log = tmp_path / "split.out"
    code = "import sys; sys.stdout.buffer.write(b'caf\\xe9\\n'); sys.stdout.flush()"

    out = stream_command([PY, "-c", code], log)

    assert out.code == 0
    assert log.read_text(encoding="utf-8").splitlines()[1] == "caf�"


def test_stream_command_reports_the_last_line_that_is_not_blank(tmp_path: Path) -> None:
    code = "import sys; print('error: no space'); print(); sys.exit(1)"

    out = stream_command([PY, "-c", code], tmp_path / "import.out")

    assert first_error(out) == "error: no space"
