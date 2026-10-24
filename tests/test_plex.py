import pytest

from musicos.plex import (
    PlexError,
    Section,
    choose_section,
    music_sections,
    parse_sections,
)

SECTIONS_JSON = """{"MediaContainer": {"size": 3, "allowSync": false, "Directory": [
 {"key": "1", "type": "movie", "title": "Movies", "agent": "tv.plex.agents.movie",
  "Location": [{"id": 1, "path": "/data/movies"}]},
 {"key": "3", "type": "artist", "title": "Music", "agent": "tv.plex.agents.music",
  "Location": [{"id": 3, "path": "/data/music"}, {"id": 4, "path": "/data/more-music"}]},
 {"key": "5", "type": "artist", "title": "Live", "agent": "tv.plex.agents.music",
  "Location": [{"id": 6, "path": "/data/live"}]}
]}}"""

MOVIES = Section("1", "movie", "Movies", ["/data/movies"])
MUSIC = Section("3", "artist", "Music", ["/data/music", "/data/more-music"])
LIVE = Section("5", "artist", "Live", ["/data/live"])


def test_parse_sections_reads_id_type_title_and_every_location() -> None:
    assert parse_sections(SECTIONS_JSON) == [MOVIES, MUSIC, LIVE]


def test_parse_sections_of_an_empty_server_is_empty() -> None:
    assert parse_sections('{"MediaContainer": {"size": 0}}') == []


def test_music_sections_keeps_only_artist_libraries() -> None:
    assert music_sections([MOVIES, MUSIC, LIVE]) == [MUSIC, LIVE]


def test_choose_section_takes_the_only_music_library() -> None:
    assert choose_section([MOVIES, MUSIC], None) == MUSIC


def test_choose_section_by_id_or_by_title_in_any_case() -> None:
    sections = [MUSIC, LIVE]

    assert choose_section(sections, "5") == LIVE
    assert choose_section(sections, "live") == LIVE


def test_choose_section_with_several_music_libraries_lists_them() -> None:
    with pytest.raises(PlexError, match=r"Music \(3\).*Live \(5\)"):
        choose_section([MUSIC, LIVE], None)


def test_choose_section_with_no_music_library_says_so() -> None:
    with pytest.raises(PlexError, match="no music library"):
        choose_section([MOVIES], None)


def test_choose_section_with_an_unknown_name_lists_the_choices() -> None:
    with pytest.raises(PlexError, match=r"no library 'Jazz'.*Music \(3\)"):
        choose_section([MUSIC, LIVE], "Jazz")
