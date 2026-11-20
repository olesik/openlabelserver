"""PostScript Level 2 output for a page plan (`RO-102`, `RO-106`, `RO-110`, `RO-104`).

One DSC-conformant document carries a page for every plan page, a
`/PageSize` of the Section 5.1 page dimensions and the same vector operators the
PDF writer uses: `moveto`/`lineto`/`curveto` for shapes and `show` for text, so
nothing is rasterized (`RO-102`).

A base-14 run selects a re-encoded copy of a standard face. A run set in a face
registered through Section 7.1 selects a `Type 42` font the prolog defines: the
whole program in `/sfnts`, a `CharStrings` dictionary naming the glyph each
WinAnsi byte selects, and a 256-entry `/Encoding` that maps those bytes to those
names. The whole program is embedded rather than a subset because PostScript has
no subset mechanism and the spec's subset requirement is stated for PDF; the
glyph coverage is still the document's, and nothing is emitted unembedded
(`RO-104`).

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
otherwise paint the wrong glyphs. PostScript has no `WinAnsiEncoding` resource —
that name belongs to PDF — so the copy's `/Encoding` array names the WinAnsi
glyph for each code the document sets.

The Type 42 dictionary follows TN #5012, because the Type 1 conventions render
nothing: `/FontMatrix` is the identity (the Type 1 scale draws the glyphs a
thousand times too small), the `CharStrings` values are `loca` indices with the
required `/.notdef` entry, and each `/sfnts` string carries the pad byte an
interpreter ignores. PostScript Level 2 has no transparency, so the builder
refuses a plan that needs it — `renderer.output` reports that rather than
flattening a document silently.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from renderer import geometry
from renderer.geometry import Subpath
from renderer.plan import Colour, Face, Fill, Op, Page, Stroke, Text

SCALE = 72.0 / 25.4

# Type 42 `sfnts` strings stay below the PostScript string limit.
SFNTS_CHUNK = 32000


# The WinAnsi glyph names. PostScript defines `StandardEncoding` and
# `ISOLatin1Encoding` but no `WinAnsiEncoding` resource, so the prolog states
# the association the text bytes rely on.
_ASCII_NAMES = (
    "space exclam quotedbl numbersign dollar percent ampersand quotesingle "
    "parenleft parenright asterisk plus comma hyphen period slash "
    "zero one two three four five six seven eight nine "
    "colon semicolon less equal greater question at "
    "A B C D E F G H I J K L M N O P Q R S T U V W X Y Z "
    "bracketleft backslash bracketright asciicircum underscore grave "
    "a b c d e f g h i j k l m n o p q r s t u v w x y z "
    "braceleft bar braceright asciitilde"
).split()

_LATIN1_PUNCTUATION = (
    "space exclamdown cent sterling currency yen brokenbar section "
    "dieresis copyright ordfeminine guillemotleft logicalnot hyphen registered macron "
    "degree plusminus twosuperior threesuperior acute mu paragraph periodcentered "
    "cedilla onesuperior ordmasculine guillemotright onequarter onehalf threequarters "
    "questiondown"
).split()

_LATIN1_LETTERS = (
    "Agrave Aacute Acircumflex Atilde Adieresis Aring AE Ccedilla "
    "Egrave Eacute Ecircumflex Edieresis Igrave Iacute Icircumflex Idieresis "
    "Eth Ntilde Ograve Oacute Ocircumflex Otilde Odieresis multiply "
    "Oslash Ugrave Uacute Ucircumflex Udieresis Yacute Thorn germandbls "
    "agrave aacute acircumflex atilde adieresis aring ae ccedilla "
    "egrave eacute ecircumflex edieresis igrave iacute icircumflex idieresis "
    "eth ntilde ograve oacute ocircumflex otilde odieresis divide "
    "oslash ugrave uacute ucircumflex udieresis yacute thorn ydieresis"
).split()

_WINANSI: dict[int, str] = {0x20 + offset: name for offset, name in enumerate(_ASCII_NAMES)}
_WINANSI.update({0xA0 + offset: name for offset, name in enumerate(_LATIN1_PUNCTUATION)})
_WINANSI.update({0xC0 + offset: name for offset, name in enumerate(_LATIN1_LETTERS)})
# The 0x80-0x9F block is where WinAnsi departs from Latin-1.
_WINANSI.update(
    {
        0x80: "Euro",
        0x82: "quotesinglbase",
        0x83: "florin",
        0x84: "quotedblbase",
        0x85: "ellipsis",
        0x86: "dagger",
        0x87: "daggerdbl",
        0x88: "circumflex",
        0x89: "perthousand",
        0x8A: "Scaron",
        0x8B: "guilsinglleft",
        0x8C: "OE",
        0x8E: "Zcaron",
        0x91: "quoteleft",
        0x92: "quoteright",
        0x93: "quotedblleft",
        0x94: "quotedblright",
        0x95: "bullet",
        0x96: "endash",
        0x97: "emdash",
        0x98: "tilde",
        0x99: "trademark",
        0x9A: "scaron",
        0x9B: "guilsinglright",
        0x9C: "oe",
        0x9E: "zcaron",
        0x9F: "Ydieresis",
    }
)


def _winansi_font(font: str, codes: Sequence[int]) -> list[str]:
    """The prolog that defines the WinAnsi-encoded copy of one base-14 face.

    The `/FID` entries of the original dictionary must be dropped: a font
    dictionary that reuses them is rejected by `definefont`. The encoding array
    names the WinAnsi glyph for every code the document sets, because PostScript
    has no `WinAnsiEncoding` resource to point at.
    """

    lines = [
        f"/{font} findfont dup length dict begin",
        "  {1 index /FID ne {def} {pop pop} ifelse} forall",
        "  /Encoding 256 array",
        "  0 1 255 {1 index exch /.notdef put} for",
    ]
    lines += [f"  dup {code} /{_WINANSI[code]} put" for code in sorted(codes)]
    lines += [
        "  readonly def",
        f"currentdict end /{winansi_name(font)} exch definefont pop",
    ]
    return lines


def winansi_name(font: str) -> str:
    """The WinAnsi-encoded copy of one base-14 face, as the prolog defines it."""

    return f"{font}-WinAnsi"


def _chunks(data: bytes) -> list[bytes]:
    return [data[offset : offset + SFNTS_CHUNK] for offset in range(0, len(data), SFNTS_CHUNK)]


def _sfnts(program: bytes) -> str:
    """The `/sfnts` hex strings, each padded to the odd length TN #5012 requires."""

    strings = []
    for chunk in _chunks(program):
        padded = chunk + b"\0" * (len(chunk) % 2) + b"\0"
        strings.append(f"<{padded.hex().upper()}>")
    return " ".join(strings)


def _font_box(face: Face) -> str:
    """The `/FontBBox` in the font's own units, the Type 42 glyph space."""

    return " ".join(str(round(value * face.units_per_em / 1000)) for value in face.bbox)


def _type42(face: Face) -> list[str]:
    """The prolog that defines one registered face as a Type 42 font.

    TN #5012 fixes the shape of the dictionary: `FontMatrix` is the identity,
    the `CharStrings` values are `loca` indices with the required `/.notdef`
    entry, and each `sfnts` string ends with the pad byte an interpreter skips.
    """

    name = face.pdf_name
    codes = sorted(face.glyphs)
    lines = [
        f"/{name} 12 dict begin",
        "/FontType 42 def",
        f"/FontName /{name} def",
        "/FontMatrix [1 0 0 1 0 0] def",
        f"/FontBBox [{_font_box(face)}] def",
        "/PaintType 0 def",
        "/Encoding 256 array",
        "0 1 255 {1 index exch /.notdef put} for",
    ]
    lines += [f"dup {code} /c{code} put" for code in codes]
    lines += [
        "readonly def",
        "/FontInfo 2 dict dup begin",
        f"/FullName ({face.name}) readonly def",
        f"/FamilyName ({face.name}) readonly def",
        "end readonly def",
        f"/sfnts [{_sfnts(face.program or b'')}] def",
        f"/CharStrings {len(codes) + 1} dict dup begin",
        "/.notdef 0 def",
    ]
    lines += [f"/c{code} {face.glyphs[code]} def" for code in codes]
    lines += [
        "end readonly def",
        "currentdict end",
        f"/{name} exch definefont pop",
    ]
    return lines


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


def _face_name(op: Text, faces: Mapping[str, Face]) -> str:
    """The font a run selects: an embedded Type 42 name or a re-encoded base-14."""

    face = faces.get(op.font)
    if face is not None and face.embedded:
        return face.pdf_name
    return winansi_name(op.font)


def _op(op: Op, faces: Mapping[str, Face]) -> list[str]:
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
            f"/{_face_name(op, faces)} findfont {number(op.size)} scalefont setfont",
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


def write(pages: Sequence[Page], faces: Mapping[str, Face] | None = None) -> bytes:
    """Serialise a page plan as one DSC-conformant PostScript program."""

    faces = faces or {}
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
    codes: dict[str, set[int]] = {}
    for page in pages:
        for body in page.bodies:
            for op in body.ops:
                if isinstance(op, Text):
                    codes.setdefault(op.font, set()).update(op.content.encode("cp1252"))
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
    defined: set[str] = set()
    for font in fonts:
        face = faces.get(font)
        if face is not None and face.embedded:
            # Two runs can resolve to different variants of one program; the
            # same face name is defined once, since `definefont` would replace it.
            if face.pdf_name in defined:
                continue
            defined.add(face.pdf_name)
            lines += _type42(face)
        else:
            lines += _winansi_font(font, codes.get(font, ()))
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
                lines += _op(op, faces)
            lines.append("grestore")
        lines.append("showpage")

    lines.append("%%EOF")
    return ("\n".join(lines) + "\n").encode("cp1252")
