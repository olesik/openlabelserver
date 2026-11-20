"""PostScript Level 2 output for a page plan (`RO-102`, `RO-106`, `RO-110`).

One DSC-conformant document carries a page for every plan page, a
`/PageSize` of the Section 5.1 page dimensions and the same vector operators the
PDF writer uses: `moveto`/`lineto`/`curveto` for shapes and `show` for text in a
base-14 face, so nothing is rasterized (`RO-102`).

The header names no creation date (IN-3, `RO-110`), nothing is random or
time-derived (`DT-105`), and the operator sequence follows the page plan, so the
same document always produces the same bytes (`DT-101`).

Coordinates: the program opens with the millimetre-to-point CTM and its Y flip,
so every number the writer emits is a page millimetre from the plan; rounding to
output units happens here only (ConformanceSpec 5.1). PostScript Level 2 has no
transparency, so the builder refuses a plan that needs it — `renderer.output`
reports that rather than flattening a document silently.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from renderer import geometry
from renderer.geometry import Subpath
from renderer.plan import Colour, Fill, Op, Page, Stroke, Text

SCALE = 72.0 / 25.4


def number(value: float) -> str:
    """One output number: four decimals, no trailing zeros and no ``-0``."""

    rounded = round(float(value), 4)
    if rounded == 0.0:
        rounded = 0.0
    text = f"{rounded:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _matrix(values: Sequence[float]) -> str:
    return "[" + " ".join(number(value) for value in values) + "]"


def _literal(text: str) -> str:
    """A PostScript string with the delimiters and line breaks escaped."""

    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    escaped = escaped.replace("\r", "\\r").replace("\n", "\\n")
    return f"({escaped})"


def _paint(ink: Colour) -> str:
    values = " ".join(number(value) for value in ink.values)
    if ink.space == "rgb":
        return f"{values} setrgbcolor"
    if ink.space == "grayscale":
        return f"{values} setgray"
    return f"{values} setcmykcolor"


def _path(subpaths: Sequence[Subpath]) -> list[str]:
    """Path construction operators for one shape."""

    parts = ["newpath"]
    for subpath in subpaths:
        parts.append(f"{number(subpath.start[0])} {number(subpath.start[1])} moveto")
        for segment in subpath.segments:
            if isinstance(segment, geometry.Line):
                parts.append(f"{number(segment.end[0])} {number(segment.end[1])} lineto")
                continue
            points = (segment.control1, segment.control2, segment.end)
            parts.append(
                " ".join(number(value) for point in points for value in point) + " curveto"
            )
        if subpath.closed:
            parts.append("closepath")
    return parts


def _op(op: Op) -> list[str]:
    """Painting operators for one plan operation, in its own graphics state."""

    matrix = op.matrix
    lines = [
        "gsave",
        f"{_matrix((matrix.a, matrix.b, matrix.c, matrix.d, matrix.e, matrix.f))} concat",
    ]

    if isinstance(op, Text):
        lines += [
            _paint(op.colour),
            f"{_matrix((1.0, 0.0, 0.0, -1.0, 0.0, op.baseline))} concat",
            f"/{op.font} findfont {number(op.size)} scalefont setfont",
            f"0 0 moveto {_literal(op.content)} show",
        ]
    else:
        lines.append(_paint(op.colour))
        if isinstance(op, Stroke):
            lines.append(f"{number(op.width)} setlinewidth")
            if op.dash:
                pattern = " ".join(number(step) for step in op.dash)
                lines.append(f"[{pattern}] 0 setdash")
        lines += _path(op.subpaths)
        lines.append("fill" if isinstance(op, Fill) else "stroke")

    lines.append("grestore")
    return lines


def write(pages: Sequence[Page]) -> bytes:
    """Serialise a page plan as one DSC-conformant PostScript program."""

    box = pages[0].box
    lines = [
        "%!PS-Adobe-3.0",
        "%%Creator: OpenLabelServer",
        "%%LanguageLevel: 2",
        f"%%Pages: {len(pages)}",
        f"%%BoundingBox: 0 0 {math.ceil(box.width * SCALE)} {math.ceil(box.height * SCALE)}",
        "%%EndComments",
        f"<< /PageSize [{number(box.width * SCALE)} {number(box.height * SCALE)}] >> setpagedevice",
        f"{_matrix((SCALE, 0.0, 0.0, -SCALE, 0.0, box.height * SCALE))} concat",
    ]

    for index, page in enumerate(pages, start=1):
        lines.append(f"%%Page: {index} {index}")
        for body in page.bodies:
            lines.append("gsave")
            clip = body.clip
            lines.append(
                f"{number(clip.x)} {number(clip.y)} "
                f"{number(clip.width)} {number(clip.height)} rectclip"
            )
            for op in body.ops:
                lines += _op(op)
            lines.append("grestore")
        lines.append("showpage")

    lines.append("%%EOF")
    return ("\n".join(lines) + "\n").encode("cp1252")
