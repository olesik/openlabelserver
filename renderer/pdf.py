"""PDF 1.4 output for a page plan (`RO-102`, `RO-106`, `RO-109`, `RO-110`).

The writer emits one page object and one content stream per plan page, a
`MediaBox` carrying the Section 5.1 page size in points (`RO-109`), and vector
operators only: paths for the Section 8.2 shapes and `BT`/`Tf`/`Tj` text runs in
a base-14 face, so nothing is rasterized (`RO-102`) and no font program has to
be embedded yet.

Determinism is structural, not a promise: object numbers follow a fixed order,
the only resource names are derived from the sorted font and alpha values, the
document has no `/ID`, and no `/CreationDate`, `/ModDate` or random value is
ever written (`IN-3`, `RO-110`, `DT-105`). The same page plan therefore always
produces the same bytes (`DT-101`). Stream compression uses zlib at a fixed
level, which is deterministic for identical input (`DT-104`).

Coordinates: the content stream opens with the millimetre-to-point CTM and its
Y flip, so every number the writer emits is a page millimetre from the plan.
Rounding to output units happens here and nowhere else (ConformanceSpec 5.1).
"""

from __future__ import annotations

import zlib
from collections.abc import Sequence

from renderer import geometry
from renderer.coordinates import Affine
from renderer.geometry import Subpath
from renderer.plan import Colour, Fill, Op, Page, Text

# 1 in = 25.4 mm and 1 pt = 1/72 in, so PDF user space is 72/25.4 units per mm.
SCALE = 72.0 / 25.4

HEADER = b"%PDF-"
BINARY = b"%\xe2\xe3\xcf\xd3\n"


def number(value: float) -> str:
    """One output number: four decimals, no trailing zeros and no ``-0``."""

    rounded = round(float(value), 4)
    if rounded == 0.0:
        rounded = 0.0
    text = f"{rounded:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _matrix(matrix: Affine) -> str:
    return " ".join(
        number(value) for value in (matrix.a, matrix.b, matrix.c, matrix.d, matrix.e, matrix.f)
    )


def _literal(text: str) -> str:
    """A PDF string with the delimiters and line breaks escaped."""

    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    escaped = escaped.replace("\r", "\\r").replace("\n", "\\n")
    return f"({escaped})"


def _paint(ink: Colour, *, stroke: bool) -> str:
    values = " ".join(number(value) for value in ink.values)
    if ink.space == "rgb":
        return f"{values} {'RG' if stroke else 'rg'}"
    if ink.space == "grayscale":
        return f"{values} {'G' if stroke else 'g'}"
    return f"{values} {'K' if stroke else 'k'}"


def _path(subpaths: Sequence[Subpath]) -> list[str]:
    """Path construction operators for one shape."""

    parts: list[str] = []
    for subpath in subpaths:
        parts.append(f"{number(subpath.start[0])} {number(subpath.start[1])} m")
        for segment in subpath.segments:
            if isinstance(segment, geometry.Line):
                parts.append(f"{number(segment.end[0])} {number(segment.end[1])} l")
                continue
            points = (segment.control1, segment.control2, segment.end)
            parts.append(" ".join(number(value) for point in points for value in point) + " c")
        if subpath.closed:
            parts.append("h")
    return parts


def _op(op: Op, fonts: dict[str, str], alphas: dict[float, str]) -> list[str]:
    """Painting operators for one plan operation, in its own graphics state."""

    lines = ["q", _matrix(op.matrix)]
    if op.alpha != 1.0:
        lines.append(f"/{alphas[op.alpha]} gs")

    if isinstance(op, Text):
        lines += [
            _paint(op.colour, stroke=False),
            "BT",
            f"/{fonts[op.font]} {number(op.size)} Tf",
            f"1 0 0 -1 0 {number(op.baseline)} Tm",
            f"{_literal(op.content)} Tj",
            "ET",
        ]
    else:
        if isinstance(op, Fill):
            lines.append(_paint(op.colour, stroke=False))
        else:
            lines.append(_paint(op.colour, stroke=True))
            lines.append(f"{number(op.width)} w")
            if op.dash:
                pattern = " ".join(number(step) for step in op.dash)
                lines.append(f"[{pattern}] 0 d")
        lines += _path(op.subpaths)
        lines.append("f" if isinstance(op, Fill) else "S")

    lines.append("Q")
    return lines


def _content(page: Page, fonts: dict[str, str], alphas: dict[float, str]) -> bytes:
    """The decompressed content stream of one page."""

    parts = [f"{number(SCALE)} 0 0 -{number(SCALE)} 0 {number(page.box.height * SCALE)} cm"]
    for body in page.bodies:
        lines = [
            "q",
            f"{number(body.clip.x)} {number(body.clip.y)} "
            f"{number(body.clip.width)} {number(body.clip.height)} re W n",
        ]
        for op in body.ops:
            lines += _op(op, fonts, alphas)
        lines.append("Q")
        parts += lines
    return ("\n".join(parts) + "\n").encode("cp1252")


def _resources(fonts: dict[str, str], alphas: dict[float, str]) -> str:
    font_entries = [f"/{resource} {reference}" for resource, reference in fonts.items()]
    alpha_entries = [f"/{resource} {reference}" for resource, reference in alphas.items()]
    parts = ["<<"]
    if font_entries:
        parts.append("/Font << " + " ".join(font_entries) + " >>")
    if alpha_entries:
        parts.append("/ExtGState << " + " ".join(alpha_entries) + " >>")
    parts.append(">>")
    return " ".join(parts)


def write(pages: Sequence[Page], *, version: str = "1.4", compress: bool = True) -> bytes:
    """Serialise a page plan as a PDF of `version`, with optional stream compression."""

    fonts = sorted(
        {
            op.font
            for page in pages
            for body in page.bodies
            for op in body.ops
            if isinstance(op, Text)
        }
    )
    alphas = sorted(
        {op.alpha for page in pages for body in page.bodies for op in body.ops if op.alpha != 1.0}
    )
    font_names = {name: f"F{index}" for index, name in enumerate(fonts, start=1)}
    alpha_names = {value: f"GS{index}" for index, value in enumerate(alphas, start=1)}

    first_page = 3
    content_count = len(pages)
    font_base = first_page + 2 * content_count
    alpha_base = font_base + len(fonts)
    font_refs = {name: f"{font_base + index} 0 R" for index, name in enumerate(fonts)}
    alpha_refs = {value: f"{alpha_base + index} 0 R" for index, value in enumerate(alphas)}
    resources = _resources(font_refs, alpha_refs)

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids ["
        + b" ".join(
            f"{first_page + 2 * index} 0 R".encode("ascii") for index in range(content_count)
        )
        + b"] /Count "
        + str(content_count).encode("ascii")
        + b" >>",
    ]

    for index, page in enumerate(pages):
        stream = _content(page, font_names, alpha_names)
        body = zlib.compress(stream, 9) if compress else stream
        media = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 "
            f"{number(page.box.width * SCALE)} {number(page.box.height * SCALE)}] "
            f"/Resources {resources} /Contents {first_page + 2 * index + 1} 0 R >>"
        )
        objects.append(media.encode("ascii"))
        header = f"<< /Length {len(body)}"
        if compress:
            header += " /Filter /FlateDecode"
        objects.append(header.encode("ascii") + b" >>\nstream\n" + body + b"\nendstream")

    for name in fonts:
        objects.append(
            f"<< /Type /Font /Subtype /Type1 /BaseFont /{name} "
            "/Encoding /WinAnsiEncoding >>".encode("ascii")
        )
    for value in alphas:
        objects.append(
            f"<< /Type /ExtGState /ca {number(value)} /CA {number(value)} >>".encode("ascii")
        )

    out = bytearray(HEADER + version.encode("ascii") + b"\n" + BINARY)
    offsets: list[int] = []
    for ordinal, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{ordinal} 0 obj\n".encode("ascii") + body + b"\nendobj\n"

    start = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n"
    ).encode("ascii")
    return bytes(out)
