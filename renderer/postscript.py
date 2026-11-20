"""PostScript Level 2 output for a page plan (`RO-102`, `RO-106`, `RO-110`).

One DSC-conformant document carries a page for every plan page, a
`/PageSize` of the Section 5.1 page dimensions and the same vector operators the
PDF writer uses: `moveto`/`lineto`/`curveto` for shapes and `show` for text in a
base-14 face, so nothing is rasterized (`RO-102`).

The header names no creation date (IN-3, `RO-110`), nothing is random or
time-derived (`DT-105`), and the operator sequence follows the page plan, so the
same document always produces the same bytes (`DT-101`).

Coordinates: every page opens with the millimetre-to-point CTM and its Y flip,
so every number the writer emits is a page millimetre from the plan; rounding to
output units happens here only (ConformanceSpec 5.1). The transform is emitted
per page because `showpage` performs the equivalent of `initgraphics`, which
would otherwise return page two and later to default points, Y up.

Text runs are written as WinAnsi bytes, the encoding the PDF writer declares.
The base-14 faces carry `StandardEncoding` instead, so the prolog re-encodes one
copy of each face in use and the runs select that copy; accented content would
otherwise paint the wrong glyphs. PostScript Level 2 has no transparency, so the
builder refuses a plan that needs it — `renderer.output` reports that rather
than flattening a document silently.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from renderer import geometry
from renderer.geometry import Subpath
from renderer.plan import Colour, Fill, Op, Page, Stroke, Text

SCALE = 72.0 / 25.4


def _winansi_font(font: str) -> list[str]:
    """The prolog that defines the WinAnsi-encoded copy of one base-14 face.

    The `/FID` entries of the original dictionary must be dropped: a font
    dictionary that reuses them is rejected by `definefont`.
    """

    return [
        f"/{font} findfont dup length dict begin",
        "  {1 index /FID ne {def} {pop pop} ifelse} forall",
        "  /Encoding WinAnsiEncoding def",
        f"currentdict end /{winansi_name(font)} exch definefont pop",
    ]


def winansi_name(font: str) -> str:
    """The WinAnsi-encoded copy of one base-14 face, as the prolog defines it."""

    return f"{font}-WinAnsi"


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
            f"/{winansi_name(op.font)} findfont {number(op.size)} scalefont setfont",
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
    fonts = sorted(
        {
            op.font
            for page in pages
            for body in page.bodies
            for op in body.ops
            if isinstance(op, Text)
        }
    )
    page_transform = _matrix((SCALE, 0.0, 0.0, -SCALE, 0.0, box.height * SCALE))
    lines = [
        "%!PS-Adobe-3.0",
        "%%Creator: OpenLabelServer",
        "%%LanguageLevel: 2",
        f"%%Pages: {len(pages)}",
        f"%%BoundingBox: 0 0 {math.ceil(box.width * SCALE)} {math.ceil(box.height * SCALE)}",
        "%%EndComments",
        "%%BeginProlog",
    ]
    for font in fonts:
        lines += _winansi_font(font)
    lines += [
        "%%EndProlog",
        f"<< /PageSize [{number(box.width * SCALE)} {number(box.height * SCALE)}] >> setpagedevice",
    ]

    for index, page in enumerate(pages, start=1):
        lines.append(f"%%Page: {index} {index}")
        lines.append(f"{page_transform} concat")
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
