"""RenderSpec Section 7.2.1 SVG artwork profile (`RO-103`, `RO-113`).

An asset of Section 7.2 `type: "svg"` is drawn as vector operations: this module
reads the profile's elements and presentation properties, maps its user space
into the Section 8.2.9 `image` box through the root `viewBox` and
`preserveAspectRatio`, and yields `Shape` values whose geometry is the same
`Subpath` vocabulary the Section 8.2 shapes use — so the two backends paint SVG
artwork through the operators they already emit, and nothing is rasterized.

The profile is closed and deterministic. The elements it draws are `svg`, `g`,
`rect`, `circle`, `ellipse`, `line`, `polyline`, `polygon` and `path`;
`title`, `desc`, `metadata` and the contents of `defs` are ignored because they
paint nothing on their own; every other element is reported by name rather than
dropped, approximated or rasterized (`RO-113`), and a property that references a
definition (`fill="url(#...)"`) is reported when that element is read. Paint is read from the presentation attributes and from
a `style` attribute naming the same properties, with SVG's own inheritance and
its fill/stroke defaults (black fill, no stroke, one-unit stroke). Lengths are
user units; a percentage or a physical unit is reported because the profile
scales user space itself. `path` data is parsed exactly as Section 8.2.8 parses
it, so an elliptical arc is reported here for the same reason it is reported
there.

`opacity` multiplies down the tree, as Section 6 layer opacity and Section 8.1
object opacity do, so the artwork's alpha reaches the plan as one product and
`renderer.output` reports it for PostScript, which has no transparency.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass

from renderer import geometry
from renderer.coordinates import Affine
from renderer.geometry import Subpath

# The elements the profile draws, and the ones it reads but never paints.
_RENDERED = frozenset({"g", "rect", "circle", "ellipse", "line", "polyline", "polygon", "path"})
# Definitions paint nothing until a property references them, and that reference
# is reported when the element carrying it is read.
_IGNORED = frozenset({"title", "desc", "metadata", "defs"})

# The sixteen CSS basic colour keywords, as CSS Color 3 defines them.
_KEYWORDS = {
    "aqua": "#00FFFF",
    "black": "#000000",
    "blue": "#0000FF",
    "fuchsia": "#FF00FF",
    "gray": "#808080",
    "green": "#008000",
    "lime": "#00FF00",
    "maroon": "#800000",
    "navy": "#000080",
    "olive": "#808000",
    "purple": "#800080",
    "red": "#FF0000",
    "silver": "#C0C0C0",
    "teal": "#008080",
    "white": "#FFFFFF",
    "yellow": "#FFFF00",
}

_ALIGNMENTS = frozenset(
    f"{x}{y}" for x in ("xMin", "xMid", "xMax") for y in ("YMin", "YMid", "YMax")
)

_NUMBER = re.compile(r"^[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$")
_TRANSFORM = re.compile(r"([A-Za-z]+)\s*\(([^)]*)\)")
_SEPARATOR = re.compile(r"[,\s]+")


class SvgError(ValueError):
    """An SVG asset outside the Section 7.2.1 profile, with the reason named."""


@dataclass(frozen=True)
class Shape:
    """One painted element, in user units, and the matrix that places it.

    `matrix` maps user space to the object's own millimetres, so the plan's
    `Fill`/`Stroke` carries the composition of the page, object and artwork
    transforms. `width` and `dash` are user units too: a backend sets them in
    the transformed space, which is how SVG scales a stroke with its geometry.
    """

    matrix: Affine
    subpaths: tuple[Subpath, ...]
    fill: str | None = None
    stroke: str | None = None
    width: float = 1.0
    dash: tuple[float, ...] = ()
    evenodd: bool = False
    opacity: float = 1.0
    fill_opacity: float = 1.0
    stroke_opacity: float = 1.0


@dataclass(frozen=True)
class Artwork:
    """The vector operations one SVG asset paints, in document order."""

    shapes: tuple[Shape, ...]


@dataclass(frozen=True)
class _Paint:
    """The inherited presentation state one element draws with."""

    fill: str | None = "#000000"
    stroke: str | None = None
    width: float = 1.0
    dash: tuple[float, ...] = ()
    fill_rule: str = "nonzero"
    fill_opacity: float = 1.0
    stroke_opacity: float = 1.0


def _local(tag: str) -> str:
    """An element's name without the namespace ElementTree carries in the tag."""

    return tag.rsplit("}", 1)[-1]


def _numbers(value: str, what: str) -> tuple[float, ...]:
    """One comma- or space-separated number list, as SVG spells it."""

    tokens = [token for token in _SEPARATOR.split(value.strip()) if token]
    numbers: list[float] = []
    for token in tokens:
        if not _NUMBER.match(token):
            raise SvgError(f"{what} {value!r} carries {token!r}, which is not a number")
        numbers.append(float(token))
    return tuple(numbers)


def _length(value: str | None, what: str, default: float | None = None) -> float:
    """One attribute length in user units; only unitless and `px` are accepted."""

    if value is None:
        if default is None:
            raise SvgError(f"{what} is required")
        return default
    token = value.strip()
    if token.endswith("px"):
        token = token[:-2].strip()
    if not _NUMBER.match(token):
        raise SvgError(
            f"{what} {value!r} is not a user-unit length; the Section 7.2.1 profile "
            "accepts unitless numbers and px, and scales user space through the viewBox"
        )
    return float(token)


def _alpha(value: str | None, what: str, default: float = 1.0) -> float:
    """One opacity in 0..1; a percentage or an out-of-range value is reported."""

    if value is None:
        return default
    number = _length(value, what)
    if not 0.0 <= number <= 1.0:
        raise SvgError(f"{what} {value!r} is outside 0.0-1.0")
    return number


def _declarations(element: ElementTree.Element) -> dict[str, str]:
    """The `style` attribute's declarations, later ones winning."""

    style = element.get("style")
    declarations: dict[str, str] = {}
    for declaration in (style or "").split(";"):
        name, separator, value = declaration.partition(":")
        if separator and name.strip():
            declarations[name.strip().lower()] = value.strip()
    return declarations


def _property(element: ElementTree.Element, style: dict[str, str], name: str) -> str | None:
    """One presentation property: the `style` declaration wins over the attribute."""

    if name in style:
        return style[name]
    return element.get(name)


def _paint_value(value: str, what: str) -> str | None:
    """A `fill` or `stroke` value: `none`, a keyword, or a Section 7.3 string."""

    token = value.strip()
    lowered = token.lower()
    if lowered == "none":
        return None
    if lowered in _KEYWORDS:
        return _KEYWORDS[lowered]
    if lowered in ("inherit", "currentcolor") or lowered.startswith("url("):
        raise SvgError(
            f"{what} {value!r} is outside the Section 7.2.1 paint model; paint "
            "servers, inherit and currentColor are not part of the profile"
        )
    return token


def _dash(value: str | None, what: str) -> tuple[float, ...]:
    """A `stroke-dasharray`, with SVG's odd-length repetition."""

    if value is None or value.strip().lower() == "none":
        return ()
    pattern = _numbers(value, what)
    if any(step < 0.0 for step in pattern):
        raise SvgError(f"{what} {value!r} carries a negative dash length")
    if not pattern:
        return ()
    return pattern * 2 if len(pattern) % 2 else pattern


def _paint(element: ElementTree.Element, style: dict[str, str], inherited: _Paint) -> _Paint:
    """The presentation state one element draws with, after SVG inheritance."""

    fill = _property(element, style, "fill")
    stroke = _property(element, style, "stroke")
    width = _property(element, style, "stroke-width")
    dash = _property(element, style, "stroke-dasharray")
    rule = _property(element, style, "fill-rule")
    fill_opacity = _property(element, style, "fill-opacity")
    stroke_opacity = _property(element, style, "stroke-opacity")

    resolved_width = inherited.width if width is None else _length(width, "stroke-width")
    if resolved_width < 0.0:
        raise SvgError(f"stroke-width {width!r} is negative")

    resolved_rule = inherited.fill_rule if rule is None else rule.strip().lower()
    if resolved_rule not in ("nonzero", "evenodd"):
        raise SvgError(f"fill-rule {rule!r} is neither nonzero nor evenodd")

    return _Paint(
        fill=inherited.fill if fill is None else _paint_value(fill, "fill"),
        stroke=inherited.stroke if stroke is None else _paint_value(stroke, "stroke"),
        width=resolved_width,
        dash=inherited.dash if dash is None else _dash(dash, "stroke-dasharray"),
        fill_rule=resolved_rule,
        fill_opacity=(
            inherited.fill_opacity
            if fill_opacity is None
            else _alpha(fill_opacity, "fill-opacity")
        ),
        stroke_opacity=(
            inherited.stroke_opacity
            if stroke_opacity is None
            else _alpha(stroke_opacity, "stroke-opacity")
        ),
    )


def _transform(element: ElementTree.Element) -> Affine:
    """The element's `transform` attribute, composed in the order it is written."""

    value = element.get("transform")
    if value is None:
        return Affine()
    matrix = Affine()
    consumed = "".join(match.group(0) for match in _TRANSFORM.finditer(value))
    if _SEPARATOR.sub("", value) != _SEPARATOR.sub("", consumed):
        raise SvgError(f"transform {value!r} is not a list of transform functions")
    for match in _TRANSFORM.finditer(value):
        name, arguments = match.group(1), _numbers(match.group(2), f"transform {match.group(1)}()")
        matrix = matrix @ _operation(name, arguments, value)
    return matrix


def _operation(name: str, arguments: tuple[float, ...], value: str) -> Affine:
    """One transform function of a `transform` attribute."""

    def arity(*allowed: int) -> None:
        if len(arguments) not in allowed:
            raise SvgError(f"transform {value!r} gives {name}() {len(arguments)} argument(s)")

    if name == "matrix":
        arity(6)
        return Affine.from_matrix(arguments)
    if name == "translate":
        arity(1, 2)
        return Affine.translation(arguments[0], arguments[1] if len(arguments) == 2 else 0.0)
    if name == "scale":
        arity(1, 2)
        return Affine.scaling(arguments[0], arguments[1] if len(arguments) == 2 else arguments[0])
    if name == "rotate":
        arity(1, 3)
        rotation = Affine.rotation(arguments[0])
        if len(arguments) == 3:
            cx, cy = arguments[1], arguments[2]
            return Affine.translation(cx, cy) @ rotation @ Affine.translation(-cx, -cy)
        return rotation
    if name == "skewX":
        arity(1)
        return Affine(a=1.0, b=0.0, c=math.tan(math.radians(arguments[0])), d=1.0)
    if name == "skewY":
        arity(1)
        return Affine(a=1.0, b=math.tan(math.radians(arguments[0])), c=0.0, d=1.0)
    raise SvgError(f"transform {value!r} names {name!r}, which the profile does not define")


def _aspect(root: ElementTree.Element, stretch: bool) -> tuple[str, str]:
    """The root's `preserveAspectRatio`, or the stretch the image object asks for."""

    if stretch:
        return ("none", "meet")
    value = root.get("preserveAspectRatio", "xMidYMid meet").strip()
    tokens = value.split()
    if tokens and tokens[0] == "defer":
        tokens = tokens[1:]
    if not 1 <= len(tokens) <= 2:
        raise SvgError(f"preserveAspectRatio {value!r} is not an alignment and a mode")
    alignment = tokens[0]
    mode = tokens[1] if len(tokens) == 2 else "meet"
    if alignment == "none" and mode == "meet":
        return ("none", "meet")
    if alignment not in _ALIGNMENTS or mode not in ("meet", "slice"):
        raise SvgError(
            f"preserveAspectRatio {value!r} is outside the profile's nine alignments "
            "with meet or slice, or none"
        )
    return (alignment, mode)


def _viewbox(root: ElementTree.Element) -> tuple[float, float, float, float] | None:
    """The root's `viewBox`, with the positive extents the mapping needs."""

    value = root.get("viewBox")
    if value is None:
        return None
    numbers = _numbers(value, "viewBox")
    if len(numbers) != 4:
        raise SvgError(f"viewBox {value!r} does not carry four numbers")
    if numbers[2] <= 0.0 or numbers[3] <= 0.0:
        raise SvgError(f"viewBox {value!r} declares a non-positive width or height")
    return (numbers[0], numbers[1], numbers[2], numbers[3])


def _viewport(
    viewbox: tuple[float, float, float, float] | None,
    width: float,
    height: float,
    aspect: tuple[str, str],
) -> Affine:
    """Map user space into the `image` object's box, honouring the alignment."""

    if viewbox is None:
        # No viewBox: one user unit is one millimetre, so the box is the only scale.
        return Affine()
    vx, vy, vw, vh = viewbox
    alignment, mode = aspect
    if alignment == "none":
        return (
            Affine.scaling(width / vw, height / vh) @ Affine.translation(-vx, -vy)
        )
    scale = (
        max(width / vw, height / vh)
        if mode == "slice"
        else min(width / vw, height / vh)
    )
    span_x, span_y = vw * scale, vh * scale
    offset_x = {"xMin": 0.0, "xMid": (width - span_x) / 2.0, "xMax": width - span_x}[
        alignment[:4]
    ]
    offset_y = {"YMin": 0.0, "YMid": (height - span_y) / 2.0, "YMax": height - span_y}[
        alignment[4:]
    ]
    return (
        Affine.translation(offset_x, offset_y)
        @ Affine.scaling(scale, scale)
        @ Affine.translation(-vx, -vy)
    )


def _points(element: ElementTree.Element, name: str) -> tuple[tuple[float, float], ...]:
    """A `points` attribute as vertices."""

    value = element.get("points")
    if value is None:
        raise SvgError(f"<{name}> has no points attribute")
    numbers = _numbers(value, f"<{name}> points")
    if len(numbers) % 2:
        raise SvgError(f"<{name}> points {value!r} carry an odd number of coordinates")
    return tuple((numbers[index], numbers[index + 1]) for index in range(0, len(numbers), 2))


def _shape(
    element: ElementTree.Element, name: str, matrix: Affine, paint: _Paint, alpha: float
) -> Shape | None:
    """One painted element, or `None` when its geometry paints nothing."""

    origin = Affine()
    if name == "rect":
        width = _length(element.get("width"), "<rect> width")
        height = _length(element.get("height"), "<rect> height")
        if width <= 0.0 or height <= 0.0:
            return None
        rx = element.get("rx")
        ry = element.get("ry")
        if rx is None and ry is None:
            resolved_x = resolved_y = 0.0
        elif rx is None:
            resolved_x = resolved_y = _length(ry, "<rect> ry")
        elif ry is None:
            resolved_x = resolved_y = _length(rx, "<rect> rx")
        else:
            resolved_x, resolved_y = _length(rx, "<rect> rx"), _length(ry, "<rect> ry")
        subpaths = geometry.rectangle(width, height, resolved_x, resolved_y)
        origin = Affine.translation(
            _length(element.get("x"), "<rect> x", 0.0),
            _length(element.get("y"), "<rect> y", 0.0),
        )
    elif name == "circle":
        radius = _length(element.get("r"), "<circle> r")
        if radius <= 0.0:
            return None
        subpaths = geometry.circle(radius)
        origin = Affine.translation(
            _length(element.get("cx"), "<circle> cx", 0.0),
            _length(element.get("cy"), "<circle> cy", 0.0),
        )
    elif name == "ellipse":
        rx = _length(element.get("rx"), "<ellipse> rx")
        ry = _length(element.get("ry"), "<ellipse> ry")
        if rx <= 0.0 or ry <= 0.0:
            return None
        subpaths = geometry.ellipse(rx, ry)
        origin = Affine.translation(
            _length(element.get("cx"), "<ellipse> cx", 0.0),
            _length(element.get("cy"), "<ellipse> cy", 0.0),
        )
    elif name == "line":
        vertices = (
            (
                _length(element.get("x1"), "<line> x1", 0.0),
                _length(element.get("y1"), "<line> y1", 0.0),
            ),
            (
                _length(element.get("x2"), "<line> x2", 0.0),
                _length(element.get("y2"), "<line> y2", 0.0),
            ),
        )
        subpaths = geometry.polyline(vertices)
    elif name == "polyline":
        subpaths = geometry.polyline(_points(element, name))
    elif name == "polygon":
        subpaths = geometry.polyline(_points(element, name), closed=True)
    else:
        try:
            subpaths = geometry.svg_path(element.get("d", ""))
        except geometry.GeometryError as exc:
            raise SvgError(str(exc)) from None

    if not subpaths:
        return None
    stroke = paint.stroke if paint.width > 0.0 else None
    if paint.fill is None and stroke is None:
        return None
    return Shape(
        matrix=matrix @ origin,
        subpaths=subpaths,
        fill=paint.fill,
        stroke=stroke,
        width=paint.width,
        dash=paint.dash,
        evenodd=paint.fill_rule == "evenodd",
        opacity=alpha,
        fill_opacity=paint.fill_opacity,
        stroke_opacity=paint.stroke_opacity,
    )


def _walk(
    element: ElementTree.Element,
    matrix: Affine,
    paint: _Paint,
    alpha: float,
    shapes: list[Shape],
) -> None:
    """Draw `element`'s children, carrying the inherited state down the tree."""

    for child in element:
        name = _local(child.tag)
        if name in _IGNORED:
            continue
        if name not in _RENDERED:
            raise SvgError(f"<{name}> is outside the Section 7.2.1 SVG profile")
        style = _declarations(child)
        placed = matrix @ _transform(child)
        child_alpha = alpha * _alpha(
            _property(child, style, "opacity"), f"<{name}> opacity"
        )
        inherited = _paint(child, style, paint)
        if name == "g":
            _walk(child, placed, inherited, child_alpha, shapes)
            continue
        shape = _shape(child, name, placed, inherited, child_alpha)
        if shape is not None:
            shapes.append(shape)


def parse(
    data: bytes, *, width: float, height: float, stretch: bool = False
) -> Artwork:
    """Read one Section 7.2.1 SVG asset into the vector operations it paints.

    `width` and `height` are the Section 8.2.9 `image` box in millimetres, which
    is the viewport the artwork is mapped into and clipped by. `stretch` is the
    `image` object's `preserve_aspect_ratio: false`: it overrides the root's
    `preserveAspectRatio` and scales each axis to the box, as it does for a
    raster picture.
    """

    if width <= 0.0 or height <= 0.0:
        raise SvgError(f"the image box is {width} x {height} mm, which has no area")
    if b"<!doctype" in data.lower():
        raise SvgError(
            "the asset carries a document type declaration, which the Section 7.2.1 "
            "profile rejects: no entity expansion or external reference is allowed"
        )
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise SvgError(f"the asset is not well-formed XML: {exc}") from None

    name = _local(root.tag)
    if name != "svg":
        raise SvgError(f"the root element is <{name}>, and the profile requires <svg>")
    if root.get("transform") is not None:
        raise SvgError("<svg> carries a transform, which the Section 7.2.1 profile does not define")

    viewbox = _viewbox(root)
    matrix = _viewport(viewbox, width, height, _aspect(root, stretch))
    style = _declarations(root)
    paint = _paint(root, style, _Paint())
    alpha = _alpha(_property(root, style, "opacity"), "<svg> opacity")

    shapes: list[Shape] = []
    _walk(root, matrix, paint, alpha, shapes)
    return Artwork(tuple(shapes))
