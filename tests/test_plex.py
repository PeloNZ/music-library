from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import PurePosixPath
from threading import Thread

import pytest

from musicos.plex import (
    Plex,
    PlexError,
    Response,
    Section,
    choose_section,
    http_get,
    music_sections,
    parse_sections,
    section_for_path,
)
from tests.fakes import FakeHttp

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


URL = "http://192.168.0.63:32400"
TOKEN = "s3cr3t-token"


def test_sections_asks_for_json_and_sends_the_token_in_a_header() -> None:
    http = FakeHttp(Response(200, SECTIONS_JSON))

    sections = Plex(URL, TOKEN, http).sections()

    assert sections == [MOVIES, MUSIC, LIVE]
    ((url, headers),) = http.requests
    assert url == f"{URL}/library/sections"
    assert headers["X-Plex-Token"] == TOKEN
    assert headers["Accept"] == "application/json"
    assert TOKEN not in url


def test_a_trailing_slash_on_the_url_is_ignored() -> None:
    http = FakeHttp(Response(200, SECTIONS_JSON))

    Plex(URL + "/", TOKEN, http).sections()

    assert http.requests[0][0] == f"{URL}/library/sections"


def test_refresh_requests_the_section_refresh_endpoint() -> None:
    http = FakeHttp()

    Plex(URL, TOKEN, http).refresh("5")

    ((url, headers),) = http.requests
    assert url == f"{URL}/library/sections/5/refresh"
    assert headers["X-Plex-Token"] == TOKEN


def test_a_rejected_token_is_reported_without_the_token() -> None:
    with pytest.raises(PlexError, match="rejected the token") as error:
        Plex(URL, TOKEN, FakeHttp(Response(401, ""))).sections()

    assert TOKEN not in str(error.value)


def test_another_error_status_is_reported_with_its_code() -> None:
    with pytest.raises(PlexError, match="500"):
        Plex(URL, TOKEN, FakeHttp(Response(500, ""))).refresh("5")


def test_an_unreachable_server_is_reported_with_its_address() -> None:
    http = FakeHttp(error=OSError("Connection refused"))

    with pytest.raises(
        PlexError, match=r"cannot reach http://192\.168\.0\.63:32400"
    ) as error:
        Plex(URL, TOKEN, http).sections()

    assert TOKEN not in str(error.value)


def test_section_for_path_finds_the_music_library_that_holds_a_folder() -> None:
    sections = [MOVIES, MUSIC, LIVE]

    assert section_for_path(PurePosixPath("/data/music"), sections) == MUSIC
    assert section_for_path(PurePosixPath("/data/more-music/Cake"), sections) == MUSIC
    assert section_for_path(PurePosixPath("/data/live"), sections) == LIVE


def test_section_for_path_ignores_libraries_that_are_not_music() -> None:
    assert section_for_path(PurePosixPath("/data/movies/x"), [MOVIES, MUSIC]) is None


def test_section_for_path_needs_a_whole_folder_name_match() -> None:
    assert section_for_path(PurePosixPath("/data/music2"), [MUSIC]) is None


def test_section_for_path_is_none_when_no_library_holds_the_folder() -> None:
    assert section_for_path(PurePosixPath("/elsewhere"), [MUSIC, LIVE]) is None


def test_a_reply_that_is_not_the_sections_json_is_a_plex_error() -> None:
    with pytest.raises(PlexError):
        parse_sections("<html>Bad gateway</html>")
    with pytest.raises(PlexError):
        parse_sections('{"unexpected": 1}')


def test_http_get_does_not_send_the_token_to_a_redirect_target() -> None:
    seen: list[str | None] = []

    class Target(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            seen.append(self.headers.get("X-Plex-Token"))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args: object) -> None:
            pass

    target = HTTPServer(("127.0.0.1", 0), Target)

    class Redirector(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{target.server_port}/")
            self.end_headers()

        def log_message(self, *args: object) -> None:
            pass

    redirector = HTTPServer(("127.0.0.1", 0), Redirector)
    for server in (target, redirector):
        Thread(target=server.serve_forever, daemon=True).start()
    try:
        response = http_get(
            f"http://127.0.0.1:{redirector.server_port}/", {"X-Plex-Token": "t0k3n"}
        )
    finally:
        for server in (target, redirector):
            server.shutdown()
            server.server_close()

    assert response.status == 302
    assert seen == []
