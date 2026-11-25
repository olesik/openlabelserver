"""Tests for `tests/conformance/mutations.py`, the conformance-case integrity harness."""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "conformance"))

import mutations  # noqa: E402


def test_every_named_breakage_is_caught_by_its_case() -> None:
    outcomes = mutations.run()

    assert [outcome.mutation.name for outcome in outcomes] == [
        mutation.name for mutation in mutations.MUTATIONS
    ]
    uncaught = [f"{outcome.mutation.name}: {outcome.detail}" for outcome in outcomes if not outcome.caught]
    assert not uncaught, uncaught


def test_a_breakage_that_changes_nothing_is_uncaught() -> None:
    noop = mutations.Mutation(
        name="noop",
        requirement="DT-101",
        check="renderspec_output_is_repeatable",
        expect="",
        breakage=contextlib.nullcontext,
    )

    (outcome,) = mutations.run((noop,))

    assert not outcome.caught
    assert "still passes" in outcome.detail


def test_a_failure_that_does_not_name_the_breakage_is_uncaught() -> None:
    mislabelled = mutations.Mutation(
        name="mislabelled",
        requirement="RT-108",
        check="renderspec_effective_alpha",
        expect="this text appears in no case report",
        breakage=mutations._dropped_alpha,
    )

    (outcome,) = mutations.run((mislabelled,))

    assert not outcome.caught
    assert "without naming it" in outcome.detail
