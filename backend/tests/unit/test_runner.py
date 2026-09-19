"""FakeRunner itself (system/runner.py): exact `.expect()` matches, the
`.respond()` prefix fallback for argv that can't be predicted exactly
ahead of time, and the strict/non-strict fallback behavior.
"""

from __future__ import annotations

import pytest

from nasos.system.runner import CommandResult, FakeRunner


async def test_expect_matches_exact_argv() -> None:
    runner = FakeRunner()
    runner.expect(["echo", "hi"], stdout="hi\n")

    result = await runner.run(["echo", "hi"])

    assert result.stdout == "hi\n"
    assert runner.calls == [["echo", "hi"]]


async def test_strict_raises_on_unstubbed_command() -> None:
    runner = FakeRunner()

    with pytest.raises(AssertionError, match="no expectation set"):
        await runner.run(["nope"])


async def test_non_strict_returns_canned_success_for_unstubbed_command() -> None:
    runner = FakeRunner(strict=False)

    result = await runner.run(["whatever"])

    assert result.ok
    assert result.stdout == ""


async def test_respond_computes_a_result_from_the_actual_argv() -> None:
    runner = FakeRunner()

    def echo_last(argv: list[str]) -> CommandResult:
        return CommandResult(argv=argv, returncode=0, stdout=f"{argv[-1]}!\n", stderr="")

    runner.respond(["greet"], echo_last)

    result = await runner.run(["greet", "world"])

    assert result.stdout == "world!\n"


async def test_exact_expect_takes_priority_over_respond() -> None:
    runner = FakeRunner()
    runner.expect(["greet", "world"], stdout="exact match\n")
    runner.respond(
        ["greet"],
        lambda argv: CommandResult(argv=argv, returncode=0, stdout="fallback\n", stderr=""),
    )

    result = await runner.run(["greet", "world"])

    assert result.stdout == "exact match\n"


async def test_respond_falls_back_to_strict_error_when_prefix_does_not_match() -> None:
    runner = FakeRunner()
    runner.respond(
        ["greet"], lambda argv: CommandResult(argv=argv, returncode=0, stdout="", stderr="")
    )

    with pytest.raises(AssertionError):
        await runner.run(["farewell", "world"])
