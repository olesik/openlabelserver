"""Vector geometry for the RenderSpec Section 8.2 primitives.

A `rect`, `circle`, `ellipse`, `line`, `polyline`, `polygon` and `path` all
become the same value here: one or more `Subpath`s of line and cubic segments in
the object's local millimetres, with Y increasing downwards (RenderSpec
Section 3). Converting once means the PDF and the PostScript backends paint
identical geometry, and the quarter-circle approximation constant lives in
exactly one place.

Section 3.2 asks vector renderers to keep coordinate resolution, so nothing here
rounds: rounding to output units happens when a backend emits a number.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

Point = tuple[float, float]

# The cubic control-point distance that approximates a quarter circle:
# 4/3 * tan(pi/8) = 0.5522847498307936 of the radius.
KAPPA = 0.5522847498307936


class GeometryError(ValueError):
    """A primitive whose geometry cannot be expressed as subpaths."""


@dataclass(frozen=True)
class Line:
    """A straight segment to `end`."""

    end: Point


@dataclass(frozen=True)
class Curve:
    """A cubic Bézier segment from the current point to `end`."""

    control1: Point
    control2: Point
    end: Point


Segment = Line | Curve


@dataclass(frozen=True)
class Subpath:
    """A start point, its segments in order, and whether it closes back."""

    start: Point
    segments: tuple[Segment, ...] = ()
    closed: bool = False

    @property
    def end(self) -> Point:
        """The point the last segment reaches, or the start point when empty."""

        return self.segments[-1].end if self.segments else self.start


def rectangle(width: float, height: float, rx: float = 0.0, ry: float = 0.0) -> tuple[Subpath, ...]:
    """Section 8.2.2: a rectangle from the origin, with optional corner radii."""

    width, height = float(width), float(height)
    # A radius wider than half the side has no corner left to describe, so the
    # renderer bounds it there rather than emitting a self-intersecting path.
    rx, ry = min(float(rx), width / 2.0), min(float(ry), height / 2.0)
    if rx <= 0.0 or ry <= 0.0:
        return (
            Subpath(
                start=(0.0, 0.0),
                segments=(Line((width, 0.0)), Line((width, height)), Line((0.0, height))),
                closed=True,
            ),
        )

    kx, ky = rx * KAPPA, ry * KAPPA
    return (
        Subpath(
            start=(0.0, 0.0),
            segments=(
                Line((width - rx, 0.0)),
                Curve((width - rx + kx, 0.0), (width, ry - ky), (width, ry)),
                Line((width, height - ry)),
                Curve((width, height - ry + ky), (width - rx + kx, height), (width - rx, height)),
                Line((rx, height)),
                Curve((rx - kx, height), (0.0, height - ry + ky), (0.0, height - ry)),
                Line((0.0, ry)),
                Curve((0.0, ry - ky), (rx - kx, 0.0), (rx, 0.0)),
            ),
            closed=True,
        ),
    )


def ellipse(rx: float, ry: float) -> tuple[Subpath, ...]:
    """Section 8.2.4: an ellipse about the anchor, as four cubic quarters.

    Y increases downwards (Section 3), so the path runs east, south, west,
    north — clockwise on the page.
    """

    rx, ry = float(rx), float(ry)
    kx, ky = rx * KAPPA, ry * KAPPA
    return (
        Subpath(
            start=(rx, 0.0),
            segments=(
                Curve((rx, ky), (kx, ry), (0.0, ry)),
                Curve((-kx, ry), (-rx, ky), (-rx, 0.0)),
                Curve((-rx, -ky), (-kx, -ry), (0.0, -ry)),
                Curve((kx, -ry), (rx, -ky), (rx, 0.0)),
            ),
            closed=True,
        ),
    )


def circle(r: float) -> tuple[Subpath, ...]:
    """Section 8.2.3: a circle of radius `r` about the anchor."""

    return ellipse(r, r)


def polyline(points: Iterable[Sequence[float]], *, closed: bool = False) -> tuple[Subpath, ...]:
    """Sections 8.2.5-8.2.7: a line, polyline or polygon through `points`."""

    vertices = [(float(point[0]), float(point[1])) for point in points]
    if len(vertices) < 2:
        return ()
    return (
        Subpath(
            start=vertices[0],
            segments=tuple(Line(end) for end in vertices[1:]),
            closed=closed,
        ),
    )


# Section 8.2.8 interprets `d` as standard SVG path data in millimetres. The
# arc commands are the one family a backend cannot emit without converting
# them, so `svg_path` reports them instead of approximating them silently.
COMMANDS = frozenset("MmLlHhVvCcSsQqTtAaZz")
ARITY = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7}
TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _point(origin: Point, x: float, y: float, relative: bool) -> Point:
    return (origin[0] + x, origin[1] + y) if relative else (x, y)


def _reflect(control: Point | None, current: Point) -> Point:
    """The control point a smooth continuation mirrors, or `current` when none."""

    if control is None:
        return current
    return (2.0 * current[0] - control[0], 2.0 * current[1] - control[1])


def _quadratic(start: Point, control: Point, end: Point) -> Curve:
    """The cubic that is exactly the quadratic Bézier `start`-`control`-`end`."""

    def toward(origin: Point, target: Point) -> Point:
        return (
            origin[0] + 2.0 / 3.0 * (target[0] - origin[0]),
            origin[1] + 2.0 / 3.0 * (target[1] - origin[1]),
        )

    return Curve(toward(start, control), toward(end, control), end)


def svg_path(data: str) -> tuple[Subpath, ...]:
    """Parse Section 8.2.8 SVG path data into subpaths of line and cubic segments.

    Both absolute and relative commands are supported, as are the smooth
    continuations `S` and `T` and the implicit repetition of a command's
    coordinate set. `A`/`a` raise `GeometryError`: converting an elliptical arc
    to cubics is a geometry decision this backend does not make on its own.
    """

    tokens = TOKEN.findall(data or "")
    subpaths: list[Subpath] = []
    segments: list[Segment] = []
    start: Point = (0.0, 0.0)
    current: Point = (0.0, 0.0)
    closed = False
    command: str | None = None
    applied: str | None = None
    cubic: Point | None = None
    quadratic: Point | None = None

    def flush() -> None:
        nonlocal segments, closed
        if segments:
            subpaths.append(Subpath(start=start, segments=tuple(segments), closed=closed))
        segments = []
        closed = False

    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in COMMANDS:
            command = token
            index += 1
            if command in "Zz":
                closed = True
                flush()
                current = start
                applied = "Z"
                continue
        if command is None:
            raise GeometryError(f"path data starts with {token!r} instead of a command")

        upper = command.upper()
        if upper == "A":
            raise GeometryError("elliptical arc commands (`A` and `a`) are not supported")
        arity = ARITY[upper]
        arguments = tokens[index : index + arity]
        if len(arguments) < arity or any(argument in COMMANDS for argument in arguments):
            raise GeometryError(f"`{command}` needs {arity} number(s), found {len(arguments)}")
        index += arity
        numbers = [float(argument) for argument in arguments]
        relative = command.islower()

        if upper == "M":
            flush()
            current = _point(current, numbers[0], numbers[1], relative)
            start = current
            command = "l" if relative else "L"
        elif upper in ("L", "H", "V"):
            if upper == "H":
                x = current[0] + numbers[0] if relative else numbers[0]
                current = (x, current[1])
            elif upper == "V":
                y = current[1] + numbers[0] if relative else numbers[0]
                current = (current[0], y)
            else:
                current = _point(current, numbers[0], numbers[1], relative)
            segments.append(Line(current))
            cubic, quadratic = None, None
        elif upper == "C":
            control1 = _point(current, numbers[0], numbers[1], relative)
            control2 = _point(current, numbers[2], numbers[3], relative)
            end = _point(current, numbers[4], numbers[5], relative)
            segments.append(Curve(control1, control2, end))
            cubic, quadratic, current = control2, None, end
        elif upper == "S":
            control1 = _reflect(cubic, current) if applied in ("C", "S") else current
            control2 = _point(current, numbers[0], numbers[1], relative)
            end = _point(current, numbers[2], numbers[3], relative)
            segments.append(Curve(control1, control2, end))
            cubic, quadratic, current = control2, None, end
        elif upper == "Q":
            control = _point(current, numbers[0], numbers[1], relative)
            end = _point(current, numbers[2], numbers[3], relative)
            segments.append(_quadratic(current, control, end))
            quadratic, cubic, current = control, None, end
        elif upper == "T":
            control = _reflect(quadratic, current) if applied in ("Q", "T") else current
            end = _point(current, numbers[0], numbers[1], relative)
            segments.append(_quadratic(current, control, end))
            quadratic, cubic, current = control, None, end
        applied = upper

    flush()
    return tuple(subpaths)
