#!/usr/bin/env python3
"""Mutation checks that keep the renderer conformance cases honest.

A conformance case that cannot fail proves nothing: it reports the same `pass`
whether the renderer honours the requirement or ignores it. Each `Mutation`
below applies one named renderer breakage — a group's matrix, its opacity or its
visibility dropped, a creation timestamp written into the artifact, and one font
subset cached across documents — and requires the case that owns that property
to report it.

Every mutation is judged on three things:

* the case passes before the breakage, so a case that was already failing cannot
  be credited with catching it;
* the case fails while the breakage is applied; and
* the reported detail names the breakage (`expect`), so a failure for an
  unrelated reason does not count either.

A mutation names one module attribute and the function that replaces it, and
`_patched` restores the original in a `finally` block, so one breakage cannot
leak into the next case or into the same interpreter afterwards.

Usage:
    python3 tests/conformance/mutations.py            # every mutation
    python3 tests/conformance/mutations.py --filter alpha

The script exits non-zero when a breakage goes uncaught.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

import renderer_cases  # noqa: E402

from renderer import composition, fonts, pdf  # noqa: E402

Result = tuple[bool, str]


@dataclass(frozen=True)
class Mutation:
    """One named renderer breakage, the case that must catch it, and its evidence."""

    name: str
    requirement: str
    check: str
    expect: str
    module: Any
    attribute: str
    breakage: Callable[[Any], Any]


@dataclass(frozen=True)
class Outcome:
    """What one mutation produced: caught or not, with the case's own detail."""

    mutation: Mutation
    caught: bool
    detail: str


@contextmanager
def _patched(module: Any, attribute: str, breakage: Callable[[Any], Any]) -> Iterator[None]:
    """Replace one renderer attribute for the block, then restore it."""

    original = getattr(module, attribute)
    setattr(module, attribute, breakage(original))
    try:
        yield
    finally:
        setattr(module, attribute, original)


def _group_matrix_ignored(real: Callable[..., Any]) -> Callable[..., Any]:
    """A group's children land in the parent's frame, not the group's."""

    def object_matrix(obj: Any, parent: Any) -> Any:
        if obj.get("type") == "group":
            return parent
        return real(obj, parent)

    return object_matrix


def _alpha_dropped(_real: Callable[..., Any]) -> Callable[..., float]:
    """Every layer, group and object paints at full opacity."""

    return lambda value: 1.0


def _visibility_ignored(_real: Callable[..., Any]) -> Callable[..., bool]:
    """A `visible: false` layer, group or object is drawn anyway."""

    return lambda value: False


def _timestamp_injected(real: Callable[..., bytes]) -> Callable[..., bytes]:
    """The PDF writer stamps the creation time the artifact must never carry."""

    def write(*args: Any, **kwargs: Any) -> bytes:
        return real(*args, **kwargs).replace(
            b"%%EOF", b"% /CreationDate (D:20261125000000Z)\n%%EOF"
        )

    return write


def _subset_cache_miskeyed(real: Callable[..., Any]) -> Callable[..., Any]:
    """One subset serves every document, so a smaller glyph set reuses the first."""

    cached: list[Any] = []

    def subset(self: Any, characters: Any) -> Any:
        if not cached:
            cached.append(real(self, characters))
        return cached[0]

    return subset


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        name="group_matrix",
        requirement="RT-117",
        check="renderspec_group_inheritance",
        expect="landed at",
        module=composition,
        attribute="object_matrix",
        breakage=_group_matrix_ignored,
    ),
    Mutation(
        name="dropped_alpha",
        requirement="RT-108",
        check="renderspec_effective_alpha",
        expect="alpha",
        module=composition,
        attribute="_opacity",
        breakage=_alpha_dropped,
    ),
    Mutation(
        name="ignored_visibility",
        requirement="RT-107",
        check="renderspec_hidden_suppresses_drawing",
        expect="draw list carries",
        module=composition,
        attribute="_hidden",
        breakage=_visibility_ignored,
    ),
    Mutation(
        name="injected_timestamp",
        requirement="RO-110",
        check="renderspec_output_has_no_timestamps",
        expect="/CreationDate",
        module=pdf,
        attribute="write",
        breakage=_timestamp_injected,
    ),
    Mutation(
        name="miskeyed_subset_cache",
        requirement="DT-105",
        check="renderspec_identifiers_are_content_derived",
        expect="smaller character set keeps",
        module=fonts.Sfnt,
        attribute="subset",
        breakage=_subset_cache_miskeyed,
    ),
)


def _check(name: str) -> Callable[[], Result]:
    """The conformance case one mutation names."""

    case = getattr(renderer_cases, name, None)
    if case is None:
        raise SystemExit(f"the case {name!r} is not in renderer_cases")
    return case


def run(mutations: Sequence[Mutation] = MUTATIONS) -> list[Outcome]:
    """Run every mutation: the case must pass, then fail and say why."""

    outcomes: list[Outcome] = []
    for mutation in mutations:
        case = _check(mutation.check)
        passed, detail = case()
        if not passed:
            outcomes.append(Outcome(mutation, False, f"the unbroken case already fails: {detail}"))
            continue
        with _patched(mutation.module, mutation.attribute, mutation.breakage):
            passed, detail = case()
        if passed:
            outcomes.append(Outcome(mutation, False, f"the case still passes: {detail}"))
        elif mutation.expect not in detail:
            outcomes.append(
                Outcome(mutation, False, f"the case failed without naming it: {detail}")
            )
        else:
            outcomes.append(Outcome(mutation, True, detail))
    return outcomes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--filter", default="", help="only mutations whose name contains this text")
    args = parser.parse_args(argv)

    chosen = tuple(mutation for mutation in MUTATIONS if args.filter in mutation.name)
    if not chosen:
        print(f"no mutation matches {args.filter!r}", file=sys.stderr)
        return 2

    outcomes = run(chosen)
    for outcome in outcomes:
        mutation = outcome.mutation
        status = "PASS" if outcome.caught else "FAIL"
        print(
            f"{status}  {mutation.name:21} {mutation.requirement:7} "
            f"{mutation.check:38} {outcome.detail}"
        )

    uncaught = [outcome for outcome in outcomes if not outcome.caught]
    caught = len(outcomes) - len(uncaught)
    print(f"\n{caught}/{len(outcomes)} breakages were caught by their cases.")
    return 1 if uncaught else 0


if __name__ == "__main__":
    raise SystemExit(main())
