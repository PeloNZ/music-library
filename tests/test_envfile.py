from pathlib import Path

import pytest

from musicos.envfile import merged_env, parse_env_file


def test_parses_plain_assignments(tmp_path: Path) -> None:
    file = tmp_path / "vars"
    file.write_text("PLEX_URL=http://192.168.0.63:32400\nPLEX_TOKEN=abc123\n")

    assert parse_env_file(file) == {
        "PLEX_URL": "http://192.168.0.63:32400",
        "PLEX_TOKEN": "abc123",
    }


def test_ignores_comments_and_blank_lines(tmp_path: Path) -> None:
    file = tmp_path / "vars"
    file.write_text("# Plex\n\nPLEX_TOKEN=abc\n   # indented comment\n")

    assert parse_env_file(file) == {"PLEX_TOKEN": "abc"}


def test_accepts_export_prefix_and_spaces_around_the_equals_sign(
    tmp_path: Path,
) -> None:
    file = tmp_path / "vars"
    file.write_text("export PLEX_URL = http://x:32400\n")

    assert parse_env_file(file) == {"PLEX_URL": "http://x:32400"}


def test_strips_matching_quotes(tmp_path: Path) -> None:
    file = tmp_path / "vars"
    file.write_text('A="one two"\nB=\'three\'\nC="unbalanced\n')

    assert parse_env_file(file) == {"A": "one two", "B": "three", "C": '"unbalanced'}


def test_keeps_equals_signs_inside_a_value(tmp_path: Path) -> None:
    file = tmp_path / "vars"
    file.write_text("URL=http://x/?a=1&b=2\n")

    assert parse_env_file(file) == {"URL": "http://x/?a=1&b=2"}


def test_does_not_expand_dollar_signs(tmp_path: Path) -> None:
    file = tmp_path / "vars"
    file.write_text("TOKEN=ab$HOME$cd\n")

    assert parse_env_file(file) == {"TOKEN": "ab$HOME$cd"}


def test_a_missing_file_gives_no_variables(tmp_path: Path) -> None:
    assert parse_env_file(tmp_path / "nothing") == {}


def test_a_bad_line_is_named_by_number_and_not_by_content(tmp_path: Path) -> None:
    file = tmp_path / "vars"
    file.write_text("A=1\nsecret-without-equals-sign\n")

    with pytest.raises(ValueError, match="line 2") as error:
        parse_env_file(file)

    assert "secret" not in str(error.value)


def test_variables_already_in_the_environment_win(tmp_path: Path) -> None:
    file = tmp_path / "vars"
    file.write_text("A=from-file\nB=from-file\n")

    assert merged_env(file, {"A": "from-shell", "C": "x"}) == {
        "A": "from-shell",
        "B": "from-file",
        "C": "x",
    }
