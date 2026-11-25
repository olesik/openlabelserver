#!/usr/bin/env python3
"""Mutation checks that keep the renderer conformance cases honest.

A conformance case that cannot fail proves nothing: it reports the same `pass`
whether the renderer honours the requirement or ignores it. Each `Mutation`
below applies one named renderer breakage — a group's matrix, its opacity or its
visibility dropped, a cached subset program handed out again after the writer
used it, and a creation timestamp written into the artifact — and requires the
case that owns that property to report it.

Every mutation is judged on three things:

* the case passes before the breakage, so a case that was already failing cannot
  be credited with catching it;
* the case fails while the breakage is applied; and
* the reported detail names the breakage (`expect`), so a failure for an
  unrelated reason does not count either.

The breakages patch the module the case imports, and the patch is removed in a
`finally` block, so one mutation cannot leak into the next case or into the same
interpreter afterwards.

Usage:
    python3 tests/conformance/mutations.py            # every mutation
    python3 tests/conformance/mutations.py --filter alpha

The script exits non-zero when a breakage goes uncaught.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

from renderer import composition, fonts, pdf  # noqa: E402

import renderer_cases  # noqa: E402

Result = tuple[bool, str]


@dataclass(frozen=True)
class Mutation:
    """One named renderer breakage, the case that must catch it, and its evidence."""

    name: str
    requirement: str
    check: str
    expect: str
    breakage: Callable[[], AbstractContextManager[None]]


@dataclass(frozen=True)
class Outcome:
    """What one mutation produced: caught or not, with the case's own detail."""

    mutation: Mutation
    caught: bool
    detail: str


@contextmanager
def _ignored_group_matrix() -> Iterator[None]:
    """A group's children land in the parent's frame, not the group's."""

    real = composition.object_matrix

    def object_matrix(obj, parent):
        if obj.get("type") == "group":
            return parent
        return real(obj, parent)

    composition.object_matrix = object_matrix
    try:
        yield
    finally:
        composition.object_matrix = real


@contextmanager
def _dropped_alpha() -> Iterator[None]:
    """Every layer, group and object paints at full opacity."""

    real = composition._opacity
    composition._opacity = lambda value: 1.0
    try:
        yield
    finally:
        composition._opacity = real


@contextmanager
def _ignored_visibility() -> Iterator[None]:
    """A `visible: false` layer, group or object is drawn anyway."""

    real = composition._hidden
    composition._hidden = lambda value: False
    try:
        yield
    finally:
        composition._hidden = real


@contextmanager
def _poisoned_subset_cache() -> Iterator[None]:
    """A cached subset program is handed out after the writer already used it.

    The cache keeps one program per face and extends it on every hit, which is
    what a cache that hands out its own buffer looks like from outside: the
    second render of the same document embeds a program the first one did not.
    """

    real = fonts.Sfnt.subset
    cache: dict[str, tuple[fonts.Subset, int]] = {}

    def subset(self, characters):
        key = hashlib.sha256(self.data).hexdigest()
        cached = cache.get(key)
        if cached is None:
            cached = (real(self, characters), 0)
        result, hits = cached
        cache[key] = (result, hits + 1)
        return fonts.Subset(
            program=result.program + bytes([hits + 1]),
            tag=result.tag,
            cids=result.cids,
            widths=result.widths,
        )

    fonts.Sfnt.subset = subset
    try:
        yield
    finally:
        fonts.Sfnt.subset = real


@contextmanager
def _injected_timestamp() -> Iterator[None]:
    """The PDF writer stamps the creation time the artifact must never carry."""

    real = pdf.write

    def write(*args, **kwargs):
        stamped = real(*args, **kwargs)
        return stamped.replace(b"%%EOF", b"% /CreationDate (D:20261125000000Z)\n%%EOF")

    pdf.write = write
    try:
        yield
    finally:
        pdf.write = real


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        "group_matrix",
        "RT-117",
        "renderspec_group_inheritance",
        "landed at",
        _ignored_group_matrix,
    ),
    Mutation("dropped_alpha", "RT-108", "renderspec_effective_alpha", "alpha", _dropped_alpha),
    Mutation(
        "ignored_visibility",
        "RT-107",
        "renderspec_hidden_suppresses_drawing",
        "draw list carries",
        _ignored_visibility,
    ),
    Mutation(
        "poisoned_subset_cache",
        "RO-104",
        "renderspec_font_embedding",
        "two renders of the same document differ",
        _poisoned_subset_cache,
    ),
    Mutation(
        "injected_timestamp",
        "RO-110",
        "renderspec_output_has_no_timestamps",
        "/CreationDate",
        _injected_timestamp,
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
            outcomes.append(
                Outcome(mutation, False, f"the unbroken case already fails: {detail}")
            )
            continue
        with mutation.breakage():
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
    print(f"\n{len(outcomes) - len(uncaught)}/{len(outcomes)} breakages were caught by their cases.")
    return 1 if uncaught else 0


if __name__ == "__main__":
    raise SystemExit(main())
