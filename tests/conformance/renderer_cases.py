"""Conformance checks that drive the RenderSpec parser and coordinate engine.

`CP-RS` requirements that needed a parser implementation (`CN-102`) or a
configured parser mode (`CN-105`) were deferred until `renderer/` existed. These
checks exercise that reference implementation, the way `engine_cases.py`
exercises the calibration engine, instead of the suite's own formula.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from renderer import coordinates, renderspec  # noqa: E402

EXAMPLES = ROOT / "specs" / "renderspec" / "examples"
FIXTURES = ROOT / "tests" / "conformance" / "fixtures" / "renderspec"
TOLERANCE = 1e-9


def _close(observed: tuple[float, float], expected: tuple[float, float]) -> bool:
    return (
        abs(observed[0] - expected[0]) <= TOLERANCE and abs(observed[1] - expected[1]) <= TOLERANCE
    )


def coordinate_convention() -> tuple[bool, str]:
    """CN-102: origin top-left, X right, Y down, millimetres, clockwise rotation."""

    document = renderspec.load(EXAMPLES / "simple_label.json")
    obj = document["layers"][0]["objects"][0]
    origin = coordinates.transform_point(obj, (0.0, 0.0))
    right = coordinates.transform_point(obj, (10.0, 0.0))
    down = coordinates.transform_point(obj, (0.0, 10.0))

    observed = {
        "origin": origin,
        "x-right": right,
        "y-down": down,
    }
    expected = {
        # The example's first object sits at (1, 1) mm, the page's top-left corner.
        "origin": (1.0, 1.0),
        "x-right": (11.0, 1.0),
        "y-down": (1.0, 11.0),
    }
    wrong = [name for name in expected if not _close(observed[name], expected[name])]
    if wrong:
        return False, ", ".join(f"{name} gave {observed[name]}" for name in wrong)

    rotated = coordinates.object_matrix({"rotation": 90.0}).apply((10.0, 0.0))
    if not _close(rotated, (0.0, 10.0)):
        return False, f"90 degrees maps (10, 0) to {rotated}, expected (0, 10) clockwise"

    millimetres = coordinates.transform_point({"x": 10.0, "y": 20.0}, (0.0, 0.0))
    if not _close(millimetres, (10.0, 20.0)):
        return False, f"a 10 x 20 mm offset became {millimetres}"
    if abs(coordinates.points_to_mm(72.0) - 25.4) > TOLERANCE:
        return False, f"72 pt is {coordinates.points_to_mm(72.0)} mm, expected 25.4"

    return True, (
        f"origin {origin}, +X {right}, +Y {down}, 90 degrees clockwise to {rotated}, "
        "and 72 pt = 25.4 mm"
    )


def _strict_rejection(path: Path) -> renderspec.RenderSpecError | None:
    try:
        renderspec.load(path)
    except renderspec.RenderSpecError as exc:
        return exc
    return None


def forward_compatibility_mode() -> tuple[bool, str]:
    """CN-105: strict is the default; forward mode drops unknown properties only."""

    unknown = FIXTURES / "invalid" / "unknown_property.json"
    strict = _strict_rejection(unknown)
    if strict is None:
        return False, "strict mode accepted a page property the schema does not define"
    paths = [diagnostic.path for diagnostic in strict.diagnostics]
    if "page" not in paths:
        return False, f"the strict rejection named {paths}, expected the page location"

    accepted = renderspec.load(unknown, strict=False)
    if "bleed" in accepted["page"]:
        return False, "forward mode kept the unknown property"
    if accepted["page"]["width"] != 50.0 or accepted["layers"][0]["id"] != "base":
        return False, "forward mode changed a recognized property"

    opacity = FIXTURES / "invalid" / "layer_opacity_out_of_range.json"
    try:
        renderspec.load(opacity, strict=False)
    except renderspec.RenderSpecError as exc:
        failed_paths = [diagnostic.path for diagnostic in exc.diagnostics]
        if "layers.0.opacity" not in failed_paths:
            return False, f"forward mode rejected the opacity at {failed_paths}"
    else:
        return False, "forward mode accepted an opacity of 1.5"

    return True, (
        "strict rejects page.bleed by default, forward mode drops it while keeping "
        "recognized properties, and forward mode still rejects opacity 1.5"
    )


CHECKS: dict[str, Any] = {
    "renderspec_coordinate_convention": coordinate_convention,
    "renderspec_forward_compatibility": forward_compatibility_mode,
}
