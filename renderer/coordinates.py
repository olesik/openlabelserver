"""Coordinate engine for RenderSpec Sections 3 and 9.

Section 3 fixes the coordinate system every renderer shares: millimetres,
origin at the top-left of the active canvas, X increasing rightwards and Y
increasing downwards, with typography sizes in points. Section 9 fixes how an
object's transform is composed:

    M = M_parent x T(x, y) x R(rotation) x S(scale_x, scale_y) x M_custom

This module provides the affine algebra and the composition; it does not place
labels on a sheet or compute bounds, which belong to the layout engine. A
positive rotation moves the positive X-axis toward positive Y, so with Y
increasing downwards it is clockwise on the page, matching CalibrationSpec
Section 7 (`CN-102`).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

Point = tuple[float, float]

# 1 pt = 1/72 in and 1 in = 25.4 mm (RenderSpec Section 3.1, ConformanceSpec 5.1).
MM_PER_POINT = 25.4 / 72.0


def points_to_mm(points: float) -> float:
    """Convert a typography size in points to millimetres."""

    return float(points) * MM_PER_POINT


@dataclass(frozen=True)
class Affine:
    """A 2D affine transform with the 3x3 matrix rows ``[a c e]`` and ``[b d f]``.

    ``(x, y)`` maps to ``(a*x + c*y + e, b*x + d*y + f)``.
    """

    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    e: float = 0.0
    f: float = 0.0

    @classmethod
    def translation(cls, x: float, y: float) -> Affine:
        return cls(e=float(x), f=float(y))

    @classmethod
    def scaling(cls, sx: float, sy: float) -> Affine:
        return cls(a=float(sx), d=float(sy))

    @classmethod
    def rotation(cls, degrees: float) -> Affine:
        """Rotate clockwise on a Y-down page by `degrees` around the origin."""

        angle = math.radians(float(degrees))
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        return cls(a=cos_a, b=sin_a, c=-sin_a, d=cos_a)

    @classmethod
    def from_matrix(cls, values: Iterable[float]) -> Affine:
        """Build an affine transform from `[a, b, c, d, e, f]`."""

        a, b, c, d, e, f = (float(value) for value in values)
        return cls(a, b, c, d, e, f)

    def apply(self, point: Point) -> Point:
        """Map one point through this transform."""

        x, y = float(point[0]), float(point[1])
        return (self.a * x + self.c * y + self.e, self.b * x + self.d * y + self.f)

    def __matmul__(self, other: Affine) -> Affine:
        """Compose transforms so that ``(self @ other).apply(p) == self.apply(other.apply(p))``."""

        return Affine(
            a=self.a * other.a + self.c * other.b,
            b=self.b * other.a + self.d * other.b,
            c=self.a * other.c + self.c * other.d,
            d=self.b * other.c + self.d * other.d,
            e=self.a * other.e + self.c * other.f + self.e,
            f=self.b * other.e + self.d * other.f + self.f,
        )


IDENTITY = Affine()


def operation_matrix(operation: Mapping[str, Any]) -> Affine:
    """Return the transform one Section 9.1 `transforms` entry contributes."""

    kind = operation.get("type")
    if kind == "translate":
        return Affine.translation(operation["x"], operation["y"])
    if kind == "scale":
        return Affine.scaling(operation["sx"], operation["sy"])
    if kind == "rotate":
        rotation = Affine.rotation(operation["angle"])
        if "cx" in operation or "cy" in operation:
            cx, cy = float(operation.get("cx", 0.0)), float(operation.get("cy", 0.0))
            return Affine.translation(cx, cy) @ rotation @ Affine.translation(-cx, -cy)
        return rotation
    if kind == "matrix":
        return Affine.from_matrix(operation["matrix"])
    raise ValueError(f"unknown transform operation {kind!r}")


def custom_matrix(transforms: Iterable[Mapping[str, Any]]) -> Affine:
    """Compose the `transforms` array in the order Section 9 defines it."""

    matrix = IDENTITY
    for operation in transforms:
        matrix = matrix @ operation_matrix(operation)
    return matrix


def object_matrix(obj: Mapping[str, Any], parent: Affine = IDENTITY) -> Affine:
    """Return the matrix Section 9 assigns to one object, in its parent's space."""

    local = (
        Affine.translation(float(obj.get("x", 0.0)), float(obj.get("y", 0.0)))
        @ Affine.rotation(float(obj.get("rotation", 0.0)))
        @ Affine.scaling(float(obj.get("scale_x", 1.0)), float(obj.get("scale_y", 1.0)))
        @ custom_matrix(obj.get("transforms") or ())
    )
    return parent @ local


def transform_point(obj: Mapping[str, Any], point: Point, parent: Affine = IDENTITY) -> Point:
    """Map a point given in the object's local coordinates into the parent space."""

    return object_matrix(obj, parent).apply(point)
