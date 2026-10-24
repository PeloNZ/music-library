from musicos.lint import CHECKS, CheckResult, run_lint
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
