from datetime import datetime

import pytest

from musicos.gaps import (
    GAP_FIELDS,
    activity_line,
    export_albums,
    find_gaps,
    render_report,
)
from musicos.runner import Output

WHEN = datetime(2026, 10, 24, 22, 40, 0)


def album(**fields: str | None) -> dict[str, str | None]:
    complete = {
        "id": "1",
        "albumartist": "Gatecreeper",
        "album": "Deserted",
        "year": "2019",
        "genres": "Death Metal",
        "artpath": "/lib/Gatecreeper/2019 - Deserted/cover.jpg",
        "path": "/lib/Gatecreeper/2019 - Deserted",
    }
    return {**complete, **fields}


def names(results, category: str) -> list[str | None]:  # type: ignore[no-untyped-def]
    return [a["album"] for r in results if r.name == category for a in r.albums]


def test_a_complete_album_has_no_gaps() -> None:
    results = find_gaps([album()])

    assert [len(r.albums) for r in results] == [0, 0, 0, 0]


def test_each_empty_field_is_its_own_gap() -> None:
    albums = [
        album(album="A", albumartist=""),
        album(album="B", year="0"),
        album(album="C", genres=""),
        album(album="D", artpath=""),
    ]

    results = find_gaps(albums)

    assert names(results, "no album artist") == ["A"]
    assert names(results, "no year") == ["B"]
    assert names(results, "no genre") == ["C"]
    assert names(results, "no art") == ["D"]


def test_a_missing_value_may_come_as_null_or_spaces() -> None:
    results = find_gaps([album(album="A", artpath=None, genres="  ")])

    assert names(results, "no art") == ["A"]
    assert names(results, "no genre") == ["A"]


def test_an_album_with_several_gaps_is_listed_under_each() -> None:
    results = find_gaps([album(album="A", year="0", artpath="")])

    assert names(results, "no year") == ["A"]
    assert names(results, "no art") == ["A"]
    assert names(results, "no genre") == []


def test_gap_fields_cover_the_four_gaps_the_plan_names() -> None:
    assert [name for name, _ in GAP_FIELDS] == [
        "no album artist",
        "no year",
        "no genre",
        "no art",
    ]


def test_export_albums_asks_beets_for_the_gap_fields_of_every_album() -> None:
    seen: list[list[str]] = []

    def run(cmd: list[str]) -> Output:
        seen.append(cmd)
        return Output('[{"id": "1", "album": "x"}]', "", 0)

    assert export_albums(run) == [{"id": "1", "album": "x"}]
    assert seen[0][:5] == ["beet", "export", "-a", "-f", "json"]
    fields = seen[0][seen[0].index("-i") + 1].split(",")
    assert {"albumartist", "album", "year", "genres", "artpath", "path"} <= set(fields)
    assert len(seen[0]) == seen[0].index("-i") + 2  # no query: every album


def test_export_of_an_empty_library_is_empty() -> None:
    assert export_albums(lambda cmd: Output("", "", 0)) == []


def test_export_failure_raises_with_the_message() -> None:
    with pytest.raises(RuntimeError, match="no such field"):
        export_albums(lambda cmd: Output("", "error: no such field\n", 1))


def test_report_shows_counts_and_each_album_with_its_path() -> None:
    results = find_gaps(
        [
            album(
                album="Comfort Eagle",
                albumartist="Cake",
                artpath="",
                path="/lib/Cake/2001",
            ),
            album(album="Deserted"),
        ]
    )

    report = render_report(results, 2, WHEN)

    assert report.startswith("# Metadata gaps\n")
    assert "2026-10-24 22:40:00" in report
    assert "2 albums checked" in report
    assert "| no art | 1 |" in report
    assert "| no year | 0 |" in report
    assert "- Cake - Comfort Eagle | /lib/Cake/2001" in report


def test_report_names_an_album_with_no_title_by_its_path() -> None:
    results = find_gaps([album(album="", year="0", path="/lib/x")])

    assert "- Gatecreeper - ? | /lib/x" in render_report(results, 1, WHEN)


def test_activity_line_counts_albums_with_gaps_and_gaps() -> None:
    results = find_gaps(
        [album(year="0", artpath=""), album(album="Fine"), album(genres="")]
    )

    assert (
        activity_line(results, 3, WHEN)
        == "2026-10-24 22:40:00 gaps 3 albums checked, 2 with gaps, 3 gaps"
    )
