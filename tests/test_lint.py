from datetime import datetime

from musicos.lint import CHECKS, CheckResult, activity_line, render_report, run_lint
from musicos.runner import Output, Run

ESC = "\x1b"
MOVE_STDOUT = (
    "/lib/Band/Record/01 Song 1.flac \n"
    f"  -> /lib/{ESC}[1;32mX/{ESC}[39;49;00mBand/Record/01 Song 1.flac\n"
    "/lib/Band/Record/02 Song 2.flac \n"
    f"  -> /lib/{ESC}[1;32mX/{ESC}[39;49;00mBand/Record/02 Song 2.flac\n"
)
MOVE = ("beet", "move", "--pretend")


def runner(**outputs: Output) -> Run:
    """Fake runner: every command is clean unless a check name has an output."""
    by_command = {tuple(cmd): name for name, cmd in CHECKS}

    def run(cmd: list[str]) -> Output:
        return outputs.get(by_command[tuple(cmd)], Output("", "", 0))

    return run


def result(results: list[CheckResult], name: str) -> CheckResult:
    return next(r for r in results if r.name == name)


def test_clean_library_has_no_findings() -> None:
    results = run_lint(runner())

    assert [r.count for r in results] == [0] * len(CHECKS)
    assert all(r.error is None for r in results)


def test_placement_drift_counts_items_from_the_header() -> None:
    results = run_lint(
        runner(**{"placement drift": Output(MOVE_STDOUT, "Moving 2 items.\n", 0)})
    )

    drift = result(results, "placement drift")
    assert drift.count == 2
    assert drift.examples == [
        "/lib/Band/Record/01 Song 1.flac -> /lib/X/Band/Record/01 Song 1.flac",
        "/lib/Band/Record/02 Song 2.flac -> /lib/X/Band/Record/02 Song 2.flac",
    ]


def test_items_already_in_place_are_not_drift() -> None:
    stderr = "Moving 0 items (2 already in place).\n"

    results = run_lint(runner(**{"placement drift": Output("", stderr, 0)}))

    assert result(results, "placement drift").count == 0


def test_empty_library_is_not_a_failure() -> None:
    stderr = "error: No matching items found.\n"

    results = run_lint(runner(**{"placement drift": Output("", stderr, 1)}))

    drift = result(results, "placement drift")
    assert drift.count == 0
    assert drift.error is None


def test_each_output_line_is_a_finding() -> None:
    stdout = "Opeth - Heritage\nOpeth - Orchid\n"

    results = run_lint(runner(duplicates=Output(stdout, "", 0)))

    dupes = result(results, "duplicates")
    assert dupes.count == 2
    assert dupes.examples == ["Opeth - Heritage", "Opeth - Orchid"]


def test_examples_are_capped_but_the_count_is_not() -> None:
    stdout = "".join(f"track {n}\n" for n in range(25))

    results = run_lint(runner(**{"unimported files": Output(stdout, "", 0)}))

    unimported = result(results, "unimported files")
    assert unimported.count == 25
    assert len(unimported.examples) == 10


def test_a_failing_command_is_reported_with_its_message() -> None:
    results = run_lint(runner(duplicates=Output("", "error: plugin not found\n", 1)))

    dupes = result(results, "duplicates")
    assert dupes.error == "error: plugin not found"
    assert dupes.count == 0


WHEN = datetime(2026, 10, 24, 21, 30, 5)
FINDINGS = [
    CheckResult("duplicates", 2, ["Opeth - Heritage", "Opeth - Orchid"]),
    CheckResult("incomplete albums", 0),
    CheckResult("unimported files", 0, error="exit code 2"),
]


def test_report_lists_every_check_with_its_count() -> None:
    report = render_report(FINDINGS, WHEN)

    assert report.startswith("# Library health report\n")
    assert "2026-10-24 21:30:05" in report
    assert "| duplicates | 2 |" in report
    assert "| incomplete albums | 0 |" in report


def test_report_shows_examples_and_errors() -> None:
    report = render_report(FINDINGS, WHEN)

    assert "- Opeth - Heritage\n- Opeth - Orchid" in report
    assert "unimported files: could not run (exit code 2)" in report


def test_report_says_how_many_examples_are_hidden() -> None:
    capped = [CheckResult("singletons", 25, [f"t{n}" for n in range(10)])]

    assert "15 more not shown" in render_report(capped, WHEN)


def test_activity_line_counts_issues_and_categories() -> None:
    assert (
        activity_line(FINDINGS, WHEN)
        == "2026-10-24 21:30:05 lint 2 issues across 1 categories"
    )
