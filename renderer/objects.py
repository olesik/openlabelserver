"""Per-object renderers for RenderSpec Section 8.2 (RT-113, RT-116).

`renderer.composition` decides what is drawn, in which order, with which matrix
and which alpha. This module answers the next question a backend asks: for one
drawn object, what does it actually paint? Each Section 8.2 primitive becomes
one dataclass holding the object's geometry in millimetres, in the object's own
local space, with every Section 8.2 default applied:

* `text` resolves `font_size` from points to its nominal em size in millimetres
  (`RT-113`: 10 pt is 3.5277 mm), and carries the alignment, wrapping and
  spacing properties a backend needs.
* `rect`, `circle`, `ellipse`, `line`, `polyline`, `polygon` and `path` resolve
  into `Paint` plus their shape parameters, where the Section 8.2 `"none"`
  colour becomes `None` so a backend can skip that paint entirely, and `line`
  alone carries the Section 8.2.5 `stroke_dasharray`.
* `image`, `barcode` and `qrcode` keep the declared extents a backend draws to;
  `barcode.width` / `barcode.height` and `qrcode.size` are the drawn pattern
  size, and `barcode.draw_text` defaults to `true` (`RT-116`).
* `group` has no primitive: `renderer.composition` replaces a group with its
  children, which are the objects a backend paints.

Only properties Section 8.2 documents are interpreted here. A `circle` and an
`ellipse` define a radius with no other origin than the object's own anchor, so
their local origin is that anchor; `renderer.barcode` and `renderer.qrcode` turn
the declared extents into modules, and rasterizing an image and interpreting SVG
path commands are renderer concerns that consume these primitives rather than
re-read the document.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from renderer.coordinates import points_to_mm

Point = tuple[float, float]


@dataclass(frozen=True)
class Paint:
    """A shape's fill and stroke, with the Section 8.2 defaults applied.

    `None` is the Section 8.2 `"none"` value: that paint is absent.
    """

    fill: str | None = None
    stroke: str | None = None
    width: float = 1.0
    dash: tuple[float, ...] = ()


@dataclass(frozen=True)
class Rect:
    """Section 8.2.2: a rectangle at the object's anchor."""

    width: float
    height: float
    rx: float = 0.0
    ry: float = 0.0
    paint: Paint = Paint()


@dataclass(frozen=True)
class Circle:
    """Section 8.2.3: a circle of radius `r` about the object's anchor."""

    r: float
    paint: Paint = Paint()


@dataclass(frozen=True)
class Ellipse:
    """Section 8.2.4: an ellipse about the object's anchor."""

    rx: float
    ry: float
    paint: Paint = Paint()


@dataclass(frozen=True)
class Segment:
    """Sections 8.2.5-8.2.7: a line, polyline or polygon through `points`."""

    points: tuple[Point, ...]
    closed: bool = False
    paint: Paint = Paint()


@dataclass(frozen=True)
class Path:
    """Section 8.2.8: SVG path data, in millimetres, from the object's anchor."""

    d: str
    paint: Paint = Paint()


@dataclass(frozen=True)
class Text:
    """Section 8.2.1: one typography run with its resolved defaults.

    `size` is the nominal em size in millimetres, already converted from the
    document's points (`RT-113`). `width` and `height` are the bounding box the
    document declared, or `None` when it declared none.
    """

    content: str
    size: float
    font_family: str | None = None
    font_weight: str = "normal"
    font_style: str = "normal"
    color: str = "#000000"
    align: str = "left"
    valign: str = "top"
    line_spacing: float = 1.0
    wrap: bool = False
    width: float | None = None
    height: float | None = None


@dataclass(frozen=True)
class Image:
    """Section 8.2.9: an asset drawn into a `width` x `height` mm box."""

    asset_id: str
    width: float
    height: float
    preserve_aspect_ratio: bool = True


@dataclass(frozen=True)
class Barcode:
    """Section 8.2.10: a linear barcode whose pattern spans `width` x `height` mm."""

    content: str
    symbology: str
    width: float
    height: float
    draw_text: bool = True
    color: str = "#000000"
    background: str = "#ffffff"


@dataclass(frozen=True)
class Qrcode:
    """Section 8.2.11: a QR code whose grid spans `size` x `size` mm."""

    content: str
    size: float
    error_correction: str = "M"
    color: str = "#000000"
    background: str = "#ffffff"


Primitive = Rect | Circle | Ellipse | Segment | Path | Text | Image | Barcode | Qrcode


def _colour(value: Any, default: str | None) -> str | None:
    """Resolve one Section 8.2 colour, where `"none"` means no paint."""

    colour = default if value is None else value
    return None if colour in (None, "none") else str(colour)


def _paint(obj: Mapping[str, Any], *, stroke_default: str | None) -> Paint:
    """Section 8.2 fill/stroke with the per-primitive stroke default.

    The dash pattern stays out of here: Section 8.2.5 documents
    `stroke_dasharray` for `line` alone, so only that primitive sets `dash`.
    """

    return Paint(
        fill=_colour(obj.get("fill_color"), "none"),
        stroke=_colour(obj.get("stroke_color"), stroke_default),
        width=float(obj.get("stroke_width", 1.0)),
    )


def _points(points: Sequence[Sequence[float]]) -> tuple[Point, ...]:
    return tuple((float(point[0]), float(point[1])) for point in points)


def _text(obj: Mapping[str, Any]) -> Text:
    width = obj.get("width")
    height = obj.get("height")
    return Text(
        content=str(obj["content"]),
        size=points_to_mm(obj.get("font_size", 10.0)),
        font_family=obj.get("font_family"),
        font_weight=str(obj.get("font_weight", "normal")),
        font_style=str(obj.get("font_style", "normal")),
        color=str(obj.get("color", "#000000")),
        align=str(obj.get("align", "left")),
        valign=str(obj.get("valign", "top")),
        line_spacing=float(obj.get("line_spacing", 1.0)),
        wrap=bool(obj.get("wrap", False)),
        width=None if width is None else float(width),
        height=None if height is None else float(height),
    )


def primitive(obj: Mapping[str, Any]) -> Primitive:
    """Return the primitive one Section 8.2 object paints, defaults applied.

    `obj` is a drawn object as `renderer.composition.draw_list` yields it, so a
    `group` cannot reach here: composition replaces it with its children.
    """

    kind = obj.get("type")
    if kind == "text":
        return _text(obj)
    if kind == "rect":
        return Rect(
            width=float(obj["width"]),
            height=float(obj["height"]),
            rx=float(obj.get("rx", 0.0)),
            ry=float(obj.get("ry", 0.0)),
            paint=_paint(obj, stroke_default=None),
        )
    if kind == "circle":
        return Circle(r=float(obj["r"]), paint=_paint(obj, stroke_default=None))
    if kind == "ellipse":
        return Ellipse(
            rx=float(obj["rx"]),
            ry=float(obj["ry"]),
            paint=_paint(obj, stroke_default=None),
        )
    if kind == "line":
        dash = tuple(float(step) for step in obj.get("stroke_dasharray") or ())
        return Segment(
            points=((0.0, 0.0), (float(obj["x2"]), float(obj["y2"]))),
            paint=replace(_paint(obj, stroke_default="#000000"), dash=dash),
        )
    if kind == "polyline":
        return Segment(points=_points(obj["points"]), paint=_paint(obj, stroke_default="#000000"))
    if kind == "polygon":
        return Segment(
            points=_points(obj["points"]),
            closed=True,
            paint=_paint(obj, stroke_default=None),
        )
    if kind == "path":
        return Path(d=str(obj["d"]), paint=_paint(obj, stroke_default=None))
    if kind == "image":
        return Image(
            asset_id=str(obj["asset_id"]),
            width=float(obj["width"]),
            height=float(obj["height"]),
            preserve_aspect_ratio=bool(obj.get("preserve_aspect_ratio", True)),
        )
    if kind == "barcode":
        return Barcode(
            content=str(obj["content"]),
            symbology=str(obj["symbology"]),
            width=float(obj["width"]),
            height=float(obj["height"]),
            draw_text=bool(obj.get("draw_text", True)),
            color=str(obj.get("color", "#000000")),
            background=str(obj.get("background_color", "#ffffff")),
        )
    if kind == "qrcode":
        return Qrcode(
            content=str(obj["content"]),
            size=float(obj["size"]),
            error_correction=str(obj.get("error_correction", "M")),
            color=str(obj.get("color", "#000000")),
            background=str(obj.get("background_color", "#ffffff")),
        )
    raise ValueError(f"{kind!r} has no Section 8.2 primitive")
