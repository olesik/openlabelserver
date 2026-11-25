"""PDF 1.4 output for a page plan (`RO-102`, `RO-106`, `RO-109`, `RO-110`, `RO-104`).

The writer emits one page object and one content stream per plan page, a
`MediaBox` carrying the Section 5.1 page size in points (`RO-109`), vector
operators for the Section 8.2 shapes and `BT`/`Tf`/`Tj` text runs, and for a
Section 8.2.9 `image` the source's own compressed stream as an image XObject —
a PNG with the PNG predictor, a JPEG with `DCTDecode` — drawn by `/Do`, so
nothing is decoded, re-encoded or rasterized (`RO-102`).

A base-14 run names its standard face directly (`RO-102`). A run set in a face
registered through Section 7.1 is emitted as `Identity-H` text over the
deterministic glyph subset `renderer.fonts` built for the characters the document
uses: a Type0 font, a CIDFontType2 descendant whose `/W` widths come from the
program's `hmtx`, a descriptor, the `/FontFile2` program itself and a
`/ToUnicode` CMap so the text stays searchable. Nothing is emitted unembedded
(`RO-104`).

Determinism is structural, not a promise: object numbers follow a fixed order,
the only resource names are derived from the sorted fonts and alpha values, the
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
from collections.abc import Mapping, Sequence

from renderer import geometry
from renderer.assets import Picture
from renderer.coordinates import Affine
from renderer.geometry import Subpath
from renderer.plan import Colour, Face, Fill, Image, Op, Page, Stroke, Text

# 1 in = 25.4 mm and 1 pt = 1/72 in, so PDF user space is 72/25.4 units per mm.
SCALE = 72.0 / 25.4

HEADER = b"%PDF-"
BINARY = b"%\xe2\xe3\xcf\xd3\n"

# Objects each embedded face contributes, in the order they are written.
OBJECTS_PER_FACE = 5

# Mappings one `beginbfchar`/`endbfchar` section of a CMap may carry.
CMAP_SECTION_ENTRIES = 100


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


def _hex(codes: bytes) -> str:
    """A hex string of the two-byte CIDs one embedded-face run selects."""

    return "<" + codes.hex().upper() + ">"


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


def _clip(points: Sequence[tuple[float, float]]) -> list[str]:
    """A clip path in page millimetres, emitted before the operation's `cm`."""

    parts = [f"{number(points[0][0])} {number(points[0][1])} m"]
    parts += [f"{number(x)} {number(y)} l" for x, y in points[1:]]
    parts.append("h")
    parts.append("W n")
    return parts


def _text_codes(content: str, face: Face) -> bytes:
    """The `Identity-H` CIDs one run selects, two bytes each."""

    codes = bytearray()
    for character in content:
        cid = face.cids.get(character, 0)
        codes += cid.to_bytes(2, "big")
    return bytes(codes)


def _image_space(picture: Picture) -> str:
    """The colour space of one image XObject."""

    if picture.palette is not None:
        entries = len(picture.palette) // 3 - 1
        return f"[/Indexed /DeviceRGB {entries} <{picture.palette.hex().upper()}>]"
    return {1: "/DeviceGray", 3: "/DeviceRGB", 4: "/DeviceCMYK"}[picture.colours]


def _image_stream(picture: Picture) -> bytes:
    """The image XObject: the source's own compressed stream, wrapped unchanged.

    A PNG keeps its zlib stream and declares the PNG predictor, which is exactly
    how PDF stores such scanlines; a JPEG keeps its entropy-coded stream and
    declares `DCTDecode`. Neither is decoded, re-encoded or rasterized, and the
    writer never re-deflates them, since that would change the document's bytes.
    """

    header = (
        f"<< /Type /XObject /Subtype /Image /Width {picture.width} "
        f"/Height {picture.height} /ColorSpace {_image_space(picture)} "
        f"/BitsPerComponent {picture.bits} /Length {len(picture.data)} "
    )
    if picture.kind == "jpeg":
        header += "/Filter /DCTDecode"
    else:
        header += (
            "/Filter /FlateDecode "
            f"/DecodeParms << /Predictor 15 /Colors {picture.colours} "
            f"/BitsPerComponent {picture.bits} /Columns {picture.width} >>"
        )
    return header.encode("ascii") + b" >>\nstream\n" + picture.data + b"\nendstream"


def _op(
    op: Op,
    fonts: dict[str, str],
    alphas: dict[float, str],
    faces: Mapping[str, Face],
    images: Mapping[Picture, str],
) -> list[str]:
    """Painting operators for one plan operation, in its own graphics state."""

    lines = ["q"]
    if isinstance(op, (Fill, Stroke)) and op.clip:
        lines += _clip(op.clip)
    lines.append(f"{_matrix(op.matrix)} cm")
    if op.alpha != 1.0:
        lines.append(f"/{alphas[op.alpha]} gs")

    if isinstance(op, Image):
        # The unit square an image paints is flipped so sample row 0 is the top
        # edge of the box the plan declares, matching the Y-down page.
        lines += [
            f"{number(op.width)} 0 0 -{number(op.height)} 0 {number(op.height)} cm",
            f"/{images[op.picture]} Do",
        ]
    elif isinstance(op, Text):
        face = faces.get(op.font)
        content = (
            _hex(_text_codes(op.content, face)) if face and face.embedded else _literal(op.content)
        )
        lines += [
            _paint(op.colour, stroke=False),
            "BT",
            f"/{fonts[op.font]} {number(op.size)} Tf",
            f"1 0 0 -1 0 {number(op.baseline)} Tm",
            f"{content} Tj",
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
        if isinstance(op, Fill):
            lines.append("f*" if op.evenodd else "f")
        else:
            lines.append("S")

    lines.append("Q")
    return lines


def _content(
    page: Page,
    fonts: dict[str, str],
    alphas: dict[float, str],
    faces: Mapping[str, Face],
    images: Mapping[Picture, str],
) -> bytes:
    """The decompressed content stream of one page."""

    parts = [f"{number(SCALE)} 0 0 -{number(SCALE)} 0 {number(page.box.height * SCALE)} cm"]
    for body in page.bodies:
        lines = [
            "q",
            f"{number(body.clip.x)} {number(body.clip.y)} "
            f"{number(body.clip.width)} {number(body.clip.height)} re W n",
        ]
        for op in body.ops:
            lines += _op(op, fonts, alphas, faces, images)
        lines.append("Q")
        parts += lines
    return ("\n".join(parts) + "\n").encode("cp1252")


def _resources(
    fonts: dict[str, str], alphas: dict[str, str], images: dict[str, str]
) -> str:
    font_entries = [f"/{resource} {reference}" for resource, reference in fonts.items()]
    alpha_entries = [f"/{resource} {reference}" for resource, reference in alphas.items()]
    image_entries = [f"/{resource} {reference}" for resource, reference in images.items()]
    parts = ["<<"]
    if font_entries:
        parts.append("/Font << " + " ".join(font_entries) + " >>")
    if alpha_entries:
        parts.append("/ExtGState << " + " ".join(alpha_entries) + " >>")
    if image_entries:
        parts.append("/XObject << " + " ".join(image_entries) + " >>")
    parts.append(">>")
    return " ".join(parts)


def _widths(face: Face) -> str:
    """The `/W` array: one dense run of widths from CID 0 to the last glyph."""

    if not face.widths:
        return "[]"
    last = max(face.widths)
    values = " ".join(number(face.widths.get(cid, 0)) for cid in range(last + 1))
    return f"[0 [{values}]]"


def _to_unicode(face: Face) -> str:
    """A `/ToUnicode` CMap from each subset CID back to its character.

    A CMap section holds at most 100 entries (TN 5411, "Cautionary Notes"), so
    the mappings are emitted in blocks rather than one `101 beginbfchar`.
    """

    reverse = sorted((cid, ord(character)) for character, cid in face.cids.items())
    lines = [
        "/CIDInit /ProcSet findresource begin",
        "12 dict begin",
        "begincmap",
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
        "/CMapName /Adobe-Identity-UCS def",
        "/CMapType 2 def",
        "1 begincodespacerange",
        "<0000> <FFFF>",
        "endcodespacerange",
    ]
    if not reverse:
        lines += ["0 beginbfchar", "endbfchar"]
    for start in range(0, len(reverse), CMAP_SECTION_ENTRIES):
        block = reverse[start : start + CMAP_SECTION_ENTRIES]
        lines.append(f"{len(block)} beginbfchar")
        lines += [f"<{cid:04X}> <{code:04X}>" for cid, code in block]
        lines.append("endbfchar")
    lines += [
        "endcmap",
        "CMapName currentdict /CMap defineresource pop",
        "end",
        "end",
    ]
    return "\n".join(lines) + "\n"


def write(
    pages: Sequence[Page],
    faces: Mapping[str, Face] | None = None,
    *,
    version: str = "1.4",
    compress: bool = True,
) -> bytes:
    """Serialise a page plan as a PDF of `version`, with optional stream compression."""

    faces = faces or {}
    names = sorted(
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
    font_names = {name: f"F{index}" for index, name in enumerate(names, start=1)}
    alpha_names = {value: f"GS{index}" for index, value in enumerate(alphas, start=1)}
    pictures: list[Picture] = []
    for page in pages:
        for body in page.bodies:
            for op in body.ops:
                if isinstance(op, Image) and op.picture not in pictures:
                    pictures.append(op.picture)
    image_names = {picture: f"Im{index}" for index, picture in enumerate(pictures, start=1)}

    embedded = [name for name in names if faces.get(name) and faces[name].embedded]
    standard = [name for name in names if name not in embedded]

    first_page = 3
    content_count = len(pages)
    standard_base = first_page + 2 * content_count
    embedded_base = standard_base + len(standard)
    font_refs = {
        font_names[name]: f"{standard_base + index} 0 R" for index, name in enumerate(standard)
    }
    face_numbers = {
        name: embedded_base + OBJECTS_PER_FACE * index for index, name in enumerate(embedded)
    }
    for name, number_ in face_numbers.items():
        font_refs[font_names[name]] = f"{number_} 0 R"
    alpha_base = embedded_base + OBJECTS_PER_FACE * len(embedded)
    alpha_refs = {
        alpha_names[value]: f"{alpha_base + index} 0 R" for index, value in enumerate(alphas)
    }
    image_base = alpha_base + len(alphas)
    image_refs = {
        image_names[picture]: f"{image_base + index} 0 R"
        for index, picture in enumerate(pictures)
    }
    resources = _resources(font_refs, alpha_refs, image_refs)

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
        stream = _content(page, font_names, alpha_names, faces, image_names)
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

    for name in standard:
        objects.append(
            f"<< /Type /Font /Subtype /Type1 /BaseFont /{name} "
            "/Encoding /WinAnsiEncoding >>".encode("ascii")
        )

    for name in embedded:
        face = faces[name]
        base = face_numbers[name]
        objects += _embedded_font(face, base, compress)

    for value in alphas:
        objects.append(
            f"<< /Type /ExtGState /ca {number(value)} /CA {number(value)} >>".encode("ascii")
        )

    for picture in pictures:
        objects.append(_image_stream(picture))

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


def _embedded_font(face: Face, base: int, compress: bool) -> list[bytes]:
    """The five objects of one embedded face, in `/W`, descriptor, program order."""

    subset = face.subset or b""
    stream = zlib.compress(subset, 9) if compress else subset
    name = face.pdf_name
    type0 = (
        f"<< /Type /Font /Subtype /Type0 /BaseFont /{name} /Encoding /Identity-H "
        f"/DescendantFonts [{base + 1} 0 R] /ToUnicode {base + 4} 0 R >>"
    )
    descendant = (
        f"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /{name} "
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
        f"/FontDescriptor {base + 2} 0 R /W {_widths(face)} /CIDToGIDMap /Identity >>"
    )
    descriptor = (
        f"<< /Type /FontDescriptor /FontName /{name} /Flags {face.flags} "
        f"/FontBBox [{face.bbox[0]} {face.bbox[1]} {face.bbox[2]} {face.bbox[3]}] "
        f"/ItalicAngle {number(face.italic_angle)} /Ascent {face.ascent} "
        f"/Descent {face.descent} /CapHeight {face.cap_height} /StemV {face.stem_v} "
        f"/FontFile2 {base + 3} 0 R >>"
    )
    program_header = f"<< /Length {len(stream)} /Length1 {len(subset)}"
    if compress:
        program_header += " /Filter /FlateDecode"
    program = program_header.encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream"
    unicode = _to_unicode(face)
    unicode_stream = (
        f"<< /Length {len(unicode)}".encode("ascii")
        + b" >>\nstream\n"
        + unicode.encode("cp1252")
        + b"\nendstream"
    )
    return [
        type0.encode("ascii"),
        descendant.encode("ascii"),
        descriptor.encode("ascii"),
        program,
        unicode_stream,
    ]
