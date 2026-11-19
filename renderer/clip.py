"""Label-shape clipping: the region ink may occupy inside one label.

StockSpec Section 5.3 fixes the clip for every declared `label.shape`:

    rectangle          the bounding box
    rounded-rectangle  radius `corner_radius` at each corner
    round              a circle of diameter `width` centred in the box
    oval               the ellipse inscribed in the box

and RenderSpec Section 5.2 gives the stock-grid clip `(X, Y, width, height)`
for the inline `stock` object, which has no shape of its own: every label is
the plain rectangle of ConformanceSpec `RT-104`. Section 6.6 of StockSpec keeps
the shapes well defined (a `round` label is square and a corner radius never
exceeds half the smaller side), so the region is computed directly from the
declared numbers.

`Clip.contains` answers whether a point may be drawn. It is the predicate a
rasterizer or content-stream writer applies per pixel or per path point, which
is how the two requirements are verified while no output backend exists.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from renderer.layout import EDGE_TOLERANCE, Box, stock_frames

Point = tuple[float, float]

SHAPES = ("rectangle", "rounded-rectangle", "round", "oval")


@dataclass(frozen=True)
class Clip:
    """The region one label may be drawn in, positioned at its top-left corner."""

    boundary: Box
    shape: str = "rectangle"
    corner_radius: float = 0.0

    def __post_init__(self) -> None:
        if self.shape not in SHAPES:
            raise ValueError(f"unknown label shape {self.shape!r}")

    def contains(self, point: Point) -> bool:
        """True when `point` falls inside the declared shape."""

        x, y = float(point[0]), float(point[1])
        box = self.boundary
        if not (
            box.x - EDGE_TOLERANCE <= x <= box.right + EDGE_TOLERANCE
            and box.y - EDGE_TOLERANCE <= y <= box.bottom + EDGE_TOLERANCE
        ):
            return False
        if self.shape == "rounded-rectangle":
            return self._in_rounded_rectangle(x, y)
        if self.shape == "round":
            radius = box.width / 2.0
            return (
                math.hypot(x - (box.x + radius), y - (box.y + box.height / 2.0))
                <= radius + EDGE_TOLERANCE
            )
        if self.shape == "oval":
            rx = box.width / 2.0
            ry = box.height / 2.0
            dx = (x - (box.x + rx)) / rx
            dy = (y - (box.y + ry)) / ry
            return dx * dx + dy * dy <= 1.0 + EDGE_TOLERANCE
        return True

    def _in_rounded_rectangle(self, x: float, y: float) -> bool:
        radius = self.corner_radius
        if radius <= 0.0:
            return True
        box = self.boundary
        centre_x = box.x + radius if x < box.x + radius else None
        if centre_x is None and x > box.right - radius:
            centre_x = box.right - radius
        centre_y = box.y + radius if y < box.y + radius else None
        if centre_y is None and y > box.bottom - radius:
            centre_y = box.bottom - radius
        if centre_x is None or centre_y is None:
            return True
        return math.hypot(x - centre_x, y - centre_y) <= radius + EDGE_TOLERANCE


def label_clip(box: Box, *, shape: str = "rectangle", corner_radius: float = 0.0) -> Clip:
    """The clip for one label of `box` with the given declared shape."""

    return Clip(boundary=box, shape=shape, corner_radius=float(corner_radius))


def stock_clips(stock: Mapping[str, Any]) -> tuple[Clip, ...]:
    """One clip per frame of a StockSpec document, in row-major order.

    Reads `label.shape` (Section 5.3, default `rectangle`) and
    `label.corner_radius`, and places each clip on the frame
    `stock_frames` computed.
    """

    label = stock["label"]
    shape = label.get("shape", "rectangle")
    radius = float(label.get("corner_radius", 0.0))
    return tuple(
        label_clip(
            Box(frame.x, frame.y, frame.width, frame.height),
            shape=shape,
            corner_radius=radius,
        )
        for frame in stock_frames(stock)
    )
