"""Conformance checks that drive the calibration engine (`CP-CE`).

The suite's own formula lives in `rules.apply_calibration`; these checks exercise
`printing/calibration.py`, the reference implementation, against ConformanceSpec
`CS-113` to `CS-119` and the selection clauses of `CS-115`, `CS-116` and `CS-122`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import rules  # noqa: E402

from printing import calibration  # noqa: E402

PRINTER = "printer-a"

# ConformanceSpec Section 9.3 normative worked example.
WORKED_TRANSFORM: dict[str, Any] = {
    "offset": {"x": 2.0, "y": -1.0},
    "scale": {"x": 1.02, "y": 0.98},
    "rotation": {"angle": 1.5, "origin": {"x": 100.0, "y": 50.0}},
}


def _profile(identifier: str, **overrides: Any) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "calibrationspec": "1.0",
        "metadata": {"id": identifier, "name": identifier},
        "printer": {"identifier": PRINTER},
        "transform": {},
    }
    profile.update(overrides)
    return profile


def post_layout_application() -> tuple[bool, str]:
    """CS-113: the transform applies to post-layout coordinates, not before."""

    profile = _profile("order", transform=WORKED_TRANSFORM)
    frame_origin = (4.65 + 66.675, 21.5)  # SS-104 / RT-103 origin of frame (1, 0)
    calibrated = calibration.calibrate(profile, [frame_origin])[0]
    reference = rules.apply_calibration(frame_origin, WORKED_TRANSFORM)
    if abs(calibrated[0] - reference[0]) > 1e-9 or abs(calibrated[1] - reference[1]) > 1e-9:
        return False, f"engine gave {calibrated}, the Section 7 formula {reference}"

    pre_layout = calibration.calibrate(profile, [(0.0, 0.0)])[0]
    translated_after = (pre_layout[0] + frame_origin[0], pre_layout[1] + frame_origin[1])
    same = (
        abs(calibrated[0] - translated_after[0]) <= 1e-9
        and abs(calibrated[1] - translated_after[1]) <= 1e-9
    )
    if same:
        return False, "calibrating before placement gives the same result; order is unobservable"
    return True, (
        f"frame origin {frame_origin} calibrates to "
        f"({calibrated[0]:.6f}, {calibrated[1]:.6f}), unlike the pre-layout composition"
    )


def selection_precedence() -> tuple[bool, str]:
    """CS-114: stock, then page format, then printer-only, then identity."""

    stock = _profile("stock", target={"stock_id": "S1"})
    page = _profile("page", target={"page_format": "a4"})
    bare = _profile("bare")
    disabled = _profile("disabled", enabled=False, target={"stock_id": "S1"})
    profiles = [stock, page, bare, disabled]

    cases = [
        (dict(stock_id="S1", page_format="a4"), "stock"),
        (dict(stock_id="S2", page_format="a4"), "page"),
        (dict(stock_id="S2", page_format="letter"), "bare"),
    ]
    observed = []
    for job, expected in cases:
        chosen = calibration.select_profile(profiles, PRINTER, **job)
        got = chosen["metadata"]["id"] if chosen else None
        observed.append(f"{job['stock_id']}/{job['page_format']}={got}")
        if got != expected:
            return False, f"{job} selected {got!r}, expected {expected!r}"

    other = calibration.select_profile(profiles, "printer-b", stock_id="S1")
    if other is not None:
        return False, f"a printer with no profile selected {other['metadata']['id']!r}"
    return True, "resolved " + ", ".join(observed) + ", and identity for another printer"


def informational_target_fallback() -> tuple[bool, str]:
    """CS-114/CS-122: a target with only informational fields matches at level 3."""

    informational = _profile("informational", target={"media_type": "laser-sheet"})
    page = _profile("page", target={"page_format": "a4"})

    chosen = calibration.select_profile([informational], PRINTER, stock_id="S9", page_format="a4")
    got = chosen["metadata"]["id"] if chosen else None
    if got != "informational":
        return False, f"an informational-only target hid the profile (selected {got!r})"

    ranked = calibration.select_profile(
        [informational, page], PRINTER, stock_id="S9", page_format="a4"
    )
    got = ranked["metadata"]["id"] if ranked else None
    if got != "page":
        return False, f"the page-format profile should outrank the printer-only one, got {got!r}"

    bare_job = calibration.select_profile([informational], PRINTER, stock_id="S9")
    got = bare_job["metadata"]["id"] if bare_job else None
    if got != "informational":
        return False, f"without a page format the informational profile was skipped ({got!r})"
    return True, "informational-only target matches at the printer-only level, below page-format"


def ambiguous_selection() -> tuple[bool, str]:
    """CS-115: equal-level matches reject with AJ-108 unless timestamps order them."""

    first = _profile("first", target={"stock_id": "S1"})
    second = _profile("second", target={"stock_id": "S1"})
    try:
        calibration.select_profile([first, second], PRINTER, stock_id="S1")
    except calibration.AmbiguousProfileError as exc:
        if exc.code != "AJ-108":
            return False, f"error code {exc.code!r}, expected 'AJ-108'"
    else:
        return False, "two equally ranked profiles were resolved without an error"

    first["metadata"]["updated_at"] = "2026-01-01T00:00:00Z"
    second["metadata"]["updated_at"] = "2026-02-01T00:00:00Z"
    chosen = calibration.select_profile([first, second], PRINTER, stock_id="S1")
    got = chosen["metadata"]["id"] if chosen else None
    if got != "second":
        return False, f"the newest profile should win, selected {got!r}"

    # A bare profile and one carrying only informational fields tie at level 3
    # (RFC-0002), so the same rule applies instead of the bare profile winning.
    bare = _profile("bare")
    informational = _profile("informational", target={"media_type": "laser-sheet"})
    try:
        calibration.select_profile([bare, informational], PRINTER, stock_id="S1")
    except calibration.AmbiguousProfileError as exc:
        if exc.code != "AJ-108":
            return False, f"level-3 tie error code {exc.code!r}, expected 'AJ-108'"
    else:
        return False, "a bare profile and an informational-only one resolved silently"

    return True, (
        "equal matches reject with AJ-108 at stock and printer-only levels; "
        "distinct updated_at selects the newest"
    )


def stock_scoped_selection() -> tuple[bool, str]:
    """CS-116: a profile targeting one stock never matches another that shares a format."""

    profile = _profile("stock-a", target={"stock_id": "A", "page_format": "a4"})
    chosen = calibration.select_profile([profile], PRINTER, stock_id="B", page_format="a4")
    if chosen is not None:
        return False, f"stock B matched the profile for stock A as {chosen['metadata']['id']!r}"

    same = calibration.select_profile([profile], PRINTER, stock_id="A", page_format="a4")
    got = same["metadata"]["id"] if same else None
    if got != "stock-a":
        return False, f"stock A did not match its own profile (selected {got!r})"
    return True, "stock B with page_format a4 does not match the stock-A profile"


def disabled_profile_is_identity() -> tuple[bool, str]:
    """CS-109: `enabled: false` leaves coordinates unchanged (Section 9.8)."""

    points = [(0.0, 0.0), (10.0, 20.0), (71.325, 21.5)]
    disabled = _profile("disabled", enabled=False, transform=WORKED_TRANSFORM)
    calibrated = calibration.calibrate(disabled, points)
    expected = [(float(x), float(y)) for x, y in points]
    if calibrated != expected:
        return False, f"a disabled profile moved {points} to {calibrated}"

    moved = calibration.calibrate(_profile("enabled", transform=WORKED_TRANSFORM), points)
    if moved == calibrated:
        return False, "the transform changed nothing; the check cannot distinguish disabled"

    chosen = calibration.select_profile([disabled], PRINTER, stock_id="S1")
    if chosen is not None:
        return False, "a disabled profile was selected for a job"
    return True, (
        f"{len(points)} points unchanged and the profile stays unselectable, while the "
        "same transform enabled moves them"
    )


def recommended_range_warnings() -> tuple[bool, str]:
    """CS-117: out-of-range parameters warn without failing; in-range values stay quiet."""

    wide = _profile(
        "wide",
        transform={"offset": {"x": 60.0, "y": 0.0}, "rotation": {"angle": 8.0}},
    )
    warnings = calibration.range_warnings(wide)
    missing = [
        name
        for name in ("offset.x", "rotation.angle")
        if not any(name in warning for warning in warnings)
    ]
    if missing:
        return False, "no warning for " + ", ".join(missing) + f": {warnings}"

    in_range = _profile(
        "in-range",
        transform={
            "offset": {"x": -2.0, "y": 1.0},
            "scale": {"uniform": 1.02},
            "rotation": {"angle": 3.0},
        },
    )
    quiet = calibration.range_warnings(in_range)
    if quiet:
        return False, f"an in-range profile warned: {quiet}"

    calibrated = calibration.calibrate(wide, [(10.0, 10.0)])
    if not all(abs(value) < 1e6 for point in calibrated for value in point):
        return False, f"an out-of-range profile produced unusable coordinates: {calibrated}"
    return True, f"warning-only for {len(warnings)} values, coordinates still produced"


def independent_engine_agreement() -> tuple[bool, str]:
    """CS-119: identical input gives identical coordinates, matching the formula."""

    point = (30.0, 40.0)
    profile = _profile("worked", transform=WORKED_TRANSFORM)
    first = calibration.calibrate(profile, [point])[0]
    second = calibration.calibrate(profile, [point])[0]
    if first != second:
        return False, f"the same input produced {first} and {second}"

    expected = (30.881001, 37.334324)
    if abs(first[0] - expected[0]) > 1e-6 or abs(first[1] - expected[1]) > 1e-6:
        return False, f"engine gave {first}, the documented result is {expected}"

    reference = rules.apply_calibration(point, WORKED_TRANSFORM)
    if abs(first[0] - reference[0]) > 1e-9 or abs(first[1] - reference[1]) > 1e-9:
        return False, f"engine {first} disagrees with the independent formula {reference}"
    return (
        True,
        f"({point[0]}, {point[1]}) -> ({first[0]:.6f}, {first[1]:.6f}) twice, matching the formula",
    )


def media_type_is_ignored() -> tuple[bool, str]:
    """CS-122: profiles differing only in target.media_type resolve identically."""

    labels = _profile("labels", target={"stock_id": "S1", "media_type": "labels"})
    sheets = _profile("sheets", target={"stock_id": "S1", "media_type": "sheets"})
    labels["metadata"]["updated_at"] = "2026-01-01T00:00:00Z"
    sheets["metadata"]["updated_at"] = "2026-03-01T00:00:00Z"

    first = calibration.select_profile([labels, sheets], PRINTER, stock_id="S1")
    second = calibration.select_profile([sheets, labels], PRINTER, stock_id="S1")
    ids = {first["metadata"]["id"], second["metadata"]["id"]} if first and second else set()
    if ids != {"sheets"}:
        return False, f"media_type changed the outcome: {ids}"

    chosen = calibration.select_profile(
        [labels, sheets], PRINTER, stock_id="S1", page_format="labels"
    )
    got = chosen["metadata"]["id"] if chosen else None
    if got != "sheets":
        return False, f"page_format equal to a media_type value changed the selection: {got!r}"
    return True, "selection ignores target.media_type in both direction and order"


CHECKS = {
    "calibration_post_layout_application": post_layout_application,
    "calibration_selection_precedence": selection_precedence,
    "calibration_informational_target_fallback": informational_target_fallback,
    "calibration_ambiguous_selection": ambiguous_selection,
    "calibration_disabled_profile_is_identity": disabled_profile_is_identity,
    "calibration_stock_scoped_selection": stock_scoped_selection,
    "calibration_recommended_range_warnings": recommended_range_warnings,
    "calibration_independent_engine_agreement": independent_engine_agreement,
    "calibration_media_type_is_ignored": media_type_is_ignored,
}
