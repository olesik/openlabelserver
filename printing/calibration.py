"""Calibration engine: CalibrationSpec profile selection and transform application.

Implements the normative transform algorithm (CalibrationSpec Section 7), the
profile-selection precedence (Section 8), angle normalization (Section 9.4) and
the RECOMMENDED operating ranges (Section 9.6). ConformanceSpec `CP-CE` covers
this behaviour through `CS-112` to `CS-119`, and ConformanceSpec `CS-122` pins
that `target.media_type` never influences selection.

Coordinates are millimetres in the active space (page or label). Callers pass
**post-layout** points: the transform is applied after RenderSpec layout and
StockSpec grid placement, and before print-ready output is emitted (Section 7,
`CS-113`). The engine is a set of pure functions - no state, no randomness, no
device rounding - so identical input yields identical output (Section 10).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

Point = tuple[float, float]
Profile = Mapping[str, Any]

# REST API error code for an ambiguous profile selection (CalibrationSpec 8, CS-115).
AMBIGUOUS_PROFILE = "AJ-108"

# CalibrationSpec Section 9.6: RECOMMENDED operating ranges.
OFFSET_RANGE = (-50.0, 50.0)
SCALE_RANGE = (0.950, 1.050)
ANGLE_RANGE = (-5.0, 5.0)


class CalibrationError(Exception):
    """A profile cannot be applied or selected."""


class AmbiguousProfileError(CalibrationError):
    """Several profiles match at one precedence level with no tie-break.

    `profiles` holds the tied `metadata.id` values in ascending order and
    `precedence` the Section 8 level they share, so an API layer can serialize
    the `AJ-108` `context` without re-running selection (`RFC-0004`).
    """

    code = AMBIGUOUS_PROFILE

    def __init__(self, message: str, *, profiles: Iterable[str], precedence: int) -> None:
        if precedence not in (1, 2, 3):
            raise ValueError(
                "precedence must be the CalibrationSpec Section 8 level that tied "
                f"(1, 2 or 3), got {precedence!r}"
            )
        super().__init__(message)
        self.profiles = tuple(sorted(profiles))
        self.precedence = precedence


def normalize_angle(angle: float) -> float:
    """Return `angle` in [0, 360) degrees without constraining the input (Section 9.4)."""

    normalized = math.fmod(float(angle), 360.0)
    return normalized + 360.0 if normalized < 0.0 else normalized


def signed_angle(angle: float) -> float:
    """Return `angle` in (-180, 180], for comparing against the recommended range."""

    normalized = normalize_angle(angle)
    return normalized - 360.0 if normalized > 180.0 else normalized


def is_enabled(profile: Profile) -> bool:
    """Return whether the profile participates in selection and application (Section 9.8)."""

    return profile.get("enabled", True) is not False


def scale_factors(transform: Mapping[str, Any]) -> tuple[float, float]:
    """Return the horizontal and vertical scale factors after applying `scale.uniform`."""

    scale = transform.get("scale") or {}
    if "uniform" in scale:
        value = float(scale["uniform"])
        return value, value
    return float(scale.get("x", 1.0)), float(scale.get("y", 1.0))


def apply_transform(point: Point, transform: Mapping[str, Any] | None = None) -> Point:
    """Apply the Section 7 algorithm to one point, in its normative order."""

    transform = transform or {}
    offset = transform.get("offset") or {}
    rotation = transform.get("rotation") or {}
    origin = rotation.get("origin") or {}
    sx, sy = scale_factors(transform)

    ox = float(origin.get("x", 0.0))
    oy = float(origin.get("y", 0.0))
    angle = math.radians(normalize_angle(float(rotation.get("angle", 0.0))))

    # Reposition, scale, rotate clockwise on the page (Y down), restore, translate.
    x = (float(point[0]) - ox) * sx
    y = (float(point[1]) - oy) * sy
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    return (
        x * cos_a - y * sin_a + ox + float(offset.get("x", 0.0)),
        x * sin_a + y * cos_a + oy + float(offset.get("y", 0.0)),
    )


def calibrate(profile: Profile, points: Iterable[Point]) -> list[Point]:
    """Calibrate post-layout points; a disabled profile returns them unchanged."""

    materialized = [(float(point[0]), float(point[1])) for point in points]
    if not is_enabled(profile):
        return materialized
    transform = profile.get("transform") or {}
    return [apply_transform(point, transform) for point in materialized]


def _matches(
    profile: Profile, printer_id: str, stock_id: str | None, page_format: str | None
) -> int | None:
    """Return the Section 8 precedence level this profile matches, or None."""

    if not is_enabled(profile):
        return None
    if (profile.get("printer") or {}).get("identifier") != printer_id:
        return None
    target = profile.get("target") or {}
    if "stock_id" in target:
        return 1 if target["stock_id"] == stock_id else None
    if "page_format" in target:
        return 2 if page_format is not None and target["page_format"] == page_format else None
    # Level 3: no selection-bearing target. A target that carries only
    # informational fields (CalibrationSpec 6.3, `media_type`) imposes no
    # condition and must not hide the profile from the printer-only level.
    return 3


def _updated_at(profile: Profile) -> datetime | None:
    raw = (profile.get("metadata") or {}).get("updated_at")
    if not isinstance(raw, str):
        return None
    text = f"{raw[:-1]}+00:00" if raw.endswith("Z") else raw
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def select_profile(
    profiles: Iterable[Profile],
    printer_id: str,
    *,
    stock_id: str | None = None,
    page_format: str | None = None,
) -> Profile | None:
    """Pick the profile for a job by Section 8 precedence; None means identity.

    `target.media_type` is never consulted (Section 6.3, `CS-122`): a profile
    whose target carries only informational fields still matches at the
    printer-only level. Several profiles matching at the winning level are
    ordered by `metadata.updated_at`;
    when that cannot order them the selection raises `AmbiguousProfileError`
    carrying the `AJ-108` error code rather than choosing arbitrarily.
    """

    ranked = [
        (level, profile)
        for profile in profiles
        if (level := _matches(profile, printer_id, stock_id, page_format)) is not None
    ]
    if not ranked:
        return None

    best = min(level for level, _ in ranked)
    candidates = [profile for level, profile in ranked if level == best]
    if len(candidates) == 1:
        return candidates[0]

    stamps = [_updated_at(profile) for profile in candidates]
    if all(stamp is not None for stamp in stamps) and len(set(stamps)) == len(stamps):
        return max(zip(stamps, candidates, strict=True))[1]
    raise AmbiguousProfileError(
        f"{len(candidates)} profiles match at precedence {best} and cannot be "
        "ordered by metadata.updated_at",
        profiles=[str((profile.get("metadata") or {}).get("id", "")) for profile in candidates],
        precedence=best,
    )


def _outside(value: float, bounds: tuple[float, float]) -> bool:
    return not bounds[0] <= value <= bounds[1]


def range_warnings(profile: Profile) -> list[str]:
    """Return warnings for values outside the Section 9.6 recommended ranges (CS-117)."""

    transform = profile.get("transform") or {}
    warnings: list[str] = []

    offset = transform.get("offset") or {}
    for axis in ("x", "y"):
        if axis in offset and _outside(float(offset[axis]), OFFSET_RANGE):
            warnings.append(f"offset.{axis} {offset[axis]} is outside [-50.0, 50.0] mm")

    scale = transform.get("scale") or {}
    if "uniform" in scale:
        factors: dict[str, Any] = {"uniform": scale["uniform"]}
    else:
        factors = {axis: scale[axis] for axis in ("x", "y") if axis in scale}
    for key, value in factors.items():
        if _outside(float(value), SCALE_RANGE):
            warnings.append(f"scale.{key} {value} is outside [0.950, 1.050]")

    rotation = transform.get("rotation") or {}
    if "angle" in rotation and _outside(signed_angle(float(rotation["angle"])), ANGLE_RANGE):
        warnings.append(f"rotation.angle {rotation['angle']} is outside [-5.0, 5.0] degrees")

    return warnings
