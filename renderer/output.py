"""Deterministic PDF and PostScript output (RenderSpec Section 4.2, `RS-119`).

`artifact` is the renderer's output step. It validates the document, expands it
into pages — page-absolute documents render once, stock-grid documents render
one page per grid of `data` records — and for each label body walks
`renderer.composition.draw_list`, resolves every drawn object through
`renderer.objects.primitive`, and hands a backend-neutral page plan to
`renderer.pdf` or `renderer.postscript`.

The plan is a list of `Fill`, `Stroke` and `Text` operations in page space, so
the two writers only differ in syntax, never in what they paint. Every value is
derived from the document: no timestamp, clock, random number or environment
value reaches the output, so the same document always produces the same bytes
(`RS-119`, `DT-101`, `DT-105`) and no artifact carries a `/CreationDate` or a
`%%CreationDate` (IN-3, `RO-110`).

A family declared in the Section 7.1 `fonts` registry is embedded, never drawn
through a substitute face (`RO-104`): `_Fonts` resolves the variant a run asks
for, `renderer.fonts` subsets the glyphs the document actually uses, and the
writers embed that subset (PDF) or the whole program (PostScript). A document
that registers a face but sets `output.embed_fonts` to false is rejected rather
than emitted with an unembedded font. A character the face does not cover is
reported, as is a program the loader cannot embed.

A Section 8.2.9 `image` is carried as the source supplied it: `renderer.assets`
reads the picture's header and the plan keeps the source's compressed data, so
the PDF carries a PNG's zlib stream as a predictor image and a JPEG's
entropy-coded stream as a DCT image. PostScript carries the JPEG the same way and
a PNG as its unfiltered samples, because a Level 2 image dictionary has no
deflate filter. Nothing is re-encoded or rasterized. A Section 8.2.10 `barcode` is drawn from `renderer.barcode`: the
encoded modules become as few bar rectangles as the runs allow, scaled to the
declared `width` and `height`, over the declared background, for every linear symbology,
followed by the Section 8.2.10 human-readable caption when `draw_text` is true: one
centred line of the normalized payload in the caption band below the bars, measured
with the base-14 or registered face's own advances. `pdf417` is drawn the same way
from `renderer.pdf417`, one row of module runs at a time, and its caption stays
reported because Section 8.2.10 leaves it undefined. A Section
8.2.11 `qrcode` is drawn from `renderer.qrcode` the same way: every horizontal run
of dark modules in one row becomes one rectangle, and the whole grid spans the
declared `size` in both directions. Section 8.2 properties an output backend needs
geometry or glyph metrics for are reported rather than approximated: `align` other
than `left` and `wrap` need glyph measurement. Text is placed with the em box
convention below until those arrive.

Section 4.2 `color_space` conversions, one documented algorithm each (`RO-105`):

* `rgb` — the sRGB channels of Section 7.3, unchanged.
* `grayscale` — the luma `Y = 0.299 R + 0.587 G + 0.114 B` (ITU-R BT.601).
* `cmyk` — `K = 1 - max(R, G, B)` and `C = (1 - R - K) / (1 - K)` with the same
  formula for M and Y; a pure black input stays `(0, 0, 0, 1)`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from renderer import (
    assets,
    barcode,
    binding,
    composition,
    fonts,
    geometry,
    layout,
    objects,
    pdf,
    pdf417,
    postscript,
    qrcode,
    renderspec,
)
from renderer.coordinates import IDENTITY, Affine
from renderer.geometry import Subpath
from renderer.layout import Box
from renderer.plan import Body, Colour, Face, Fill, Image, Op, Page, Stroke, Text

FORMATS = ("pdf", "postscript")
COLOUR_SPACES = ("rgb", "cmyk", "grayscale")

# RenderSpec fixes the em size but not the baseline of a run, and no font
# metrics are available before the R2 text plugin, so the em box a run occupies
# is split 80/20 above and below the baseline. `valign` positions that box.
ASCENT = 0.8
DESCENT = 0.2

_HEX = re.compile(r"^#(?P<digits>[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_FUNCTION = re.compile(r"^rgba?\((?P<channels>[^)]*)\)$")
_VERSION = re.compile(r"^\d+\.\d+$")

_TIMES = {
    (False, False): "Times-Roman",
    (True, False): "Times-Bold",
    (False, True): "Times-Italic",
    (True, True): "Times-BoldItalic",
}

# Advance widths of the printable ASCII range (codes 32-126) per 1000 em for the
# base-14 regular faces, from the standard's AFM metrics (PDF 32000-1 Annex D).
# A caption is always set normal/normal, so only these three faces are needed.
# The table is WinAnsi's: code 39 is `quotesingle`, which Times sets at 180, not
# the `quoteright` StandardEncoding maps to that code. Courier is monospaced.
_HELVETICA = (
    278, 278, 355, 556, 556, 889, 667, 222, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
    1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
    222, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
    556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584,
)
_TIMES_ROMAN = (
    250, 333, 408, 500, 500, 833, 778, 180, 333, 333, 500, 564, 250, 333, 250, 278,
    500, 500, 500, 500, 500, 500, 500, 500, 500, 500, 278, 278, 564, 564, 564, 444,
    921, 722, 667, 667, 722, 611, 556, 722, 722, 333, 389, 722, 611, 889, 722, 722,
    556, 722, 667, 556, 611, 722, 722, 944, 722, 722, 611, 333, 278, 333, 469, 500,
    333, 444, 500, 444, 500, 444, 333, 500, 500, 278, 278, 500, 278, 778, 500, 500,
    500, 500, 333, 389, 278, 500, 500, 722, 500, 500, 444, 480, 200, 480, 541,
)
_STANDARD_ADVANCES = {"Helvetica": _HELVETICA, "Times-Roman": _TIMES_ROMAN}
_COURIER_ADVANCE = 600


class OutputError(ValueError):
    """A document the output backend cannot express, with the reason named."""


def _channels(value: str) -> tuple[float, float, float, float]:
    """Section 7.3 colour string as red, green, blue and alpha in 0..1."""

    text = value.strip()
    hex_match = _HEX.match(text)
    if hex_match:
        digits = hex_match.group("digits")
        if len(digits) == 3:
            digits = "".join(digit * 2 for digit in digits)
        alpha = int(digits[6:8], 16) / 255.0 if len(digits) == 8 else 1.0
        return (
            int(digits[0:2], 16) / 255.0,
            int(digits[2:4], 16) / 255.0,
            int(digits[4:6], 16) / 255.0,
            alpha,
        )

    function = _FUNCTION.match(text)
    if function:
        fields = [field.strip() for field in function.group("channels").split(",")]
        if len(fields) not in (3, 4):
            raise OutputError(f"colour {value!r} needs three channels and at most one alpha")
        try:
            numbers = [float(field) for field in fields]
        except ValueError:
            raise OutputError(f"colour {value!r} has a non-numeric channel") from None
        channels = numbers[:3]
        alpha = numbers[3] if len(numbers) == 4 else 1.0
        if any(not 0.0 <= channel <= 255.0 for channel in channels):
            raise OutputError(f"colour {value!r} has a channel outside 0-255")
        if not 0.0 <= alpha <= 1.0:
            raise OutputError(f"colour {value!r} has an alpha outside 0.0-1.0")
        return (channels[0] / 255.0, channels[1] / 255.0, channels[2] / 255.0, alpha)

    raise OutputError(f"colour {value!r} is not one of the Section 7.3 formats")


def colour(value: str, space: str = "rgb") -> Colour:
    """Resolve one Section 7.3 colour into `space`, per the module algorithms."""

    if space not in COLOUR_SPACES:
        raise OutputError(f"colour space {space!r} is not one of {COLOUR_SPACES}")
    red, green, blue, alpha = _channels(value)
    if space == "rgb":
        return Colour("rgb", (red, green, blue), alpha)
    if space == "grayscale":
        return Colour("grayscale", (0.299 * red + 0.587 * green + 0.114 * blue,), alpha)

    black = 1.0 - max(red, green, blue)
    if black >= 1.0:
        return Colour("cmyk", (0.0, 0.0, 0.0, 1.0), alpha)
    scale = 1.0 - black
    return Colour(
        "cmyk",
        (
            max(0.0, (scale - red) / scale),
            max(0.0, (scale - green) / scale),
            max(0.0, (scale - blue) / scale),
            black,
        ),
        alpha,
    )


def _weight_value(weight: str) -> int:
    """One Section 8.2.1 weight as the number variant selection compares."""

    if weight == "bold":
        return 700
    if weight.isdigit():
        return int(weight)
    return 400


class _Fonts:
    """The registered typefaces one document may draw with (`RO-104`)."""

    def __init__(self, document: Mapping[str, Any]) -> None:
        constraints = document.get("output") or {}
        registered = document.get("fonts") or ()
        if registered and constraints.get("embed_fonts", True) is False:
            raise OutputError(
                "output.embed_fonts is false, but the document registers custom fonts; "
                "a registered face is embedded, never emitted unembedded (RO-104)"
            )
        self._variants: dict[str, list[tuple[str, str, str]]] = {}
        for entry in registered:
            family = str(entry["family"])
            variants = self._variants.setdefault(family, [])
            variants.extend(
                (str(variant["style"]), str(variant["weight"]), str(variant.get("source", "")))
                for variant in entry["variants"]
            )
        self._programs: dict[str, fonts.Sfnt] = {}
        self._used: dict[str, fonts.Sfnt] = {}
        self._characters: dict[str, set[str]] = {}

    def select(self, family: str | None, weight: str, style: str, path: str) -> str | None:
        """The plan key of the variant a run resolves to, or `None` for base-14."""

        if family is None:
            return None
        variants = self._variants.get(str(family))
        if not variants:
            return None
        wanted = _weight_value(weight)
        # Style first, then the closest weight; the remaining fields break ties
        # the same way on every run so the choice cannot depend on registry order.
        chosen = min(
            variants,
            key=lambda variant: (
                0 if variant[0] == style else (1 if variant[0] == "normal" else 2),
                abs(_weight_value(variant[1]) - wanted),
                variant[1],
                variant[2],
            ),
        )
        key = f"{family} {chosen[0]} {chosen[1]}"
        if key not in self._used:
            self._used[key] = self._program(chosen[2], path)
            self._characters[key] = set()
        return key

    def _program(self, source: str, path: str) -> fonts.Sfnt:
        if source not in self._programs:
            try:
                self._programs[source] = fonts.Sfnt(fonts.load(source))
            except fonts.FontError as exc:
                raise OutputError(f"{path}: {exc}") from None
        return self._programs[source]

    def advance(self, key: str, content: str) -> float:
        """`content`'s advance in `key`'s ems, after `note` accepted its characters."""

        program = self._used[key]
        width = 0
        for character in content:
            glyph = program.glyph_id(character)
            width += program.advance(0 if glyph is None else glyph)
        return width / program.units_per_em

    def note(self, key: str, content: str, path: str) -> None:
        """Record the characters a run needs, reporting any the face lacks."""

        program = self._used[key]
        for character in content:
            if program.glyph_id(character) is None:
                raise OutputError(f"{path}: font {key!r} has no glyph for {character!r}")
            self._characters[key].add(character)

    def faces(self) -> dict[str, Face]:
        """The plan faces for every registered variant the document used."""

        faces: dict[str, Face] = {}
        for key in sorted(self._used):
            program = self._used[key]
            subset = program.subset(self._characters[key])
            metrics = program.metrics
            faces[key] = Face(
                name=metrics.postscript_name,
                tag=subset.tag,
                program=program.data,
                subset=subset.program,
                cids=subset.cids,
                widths=subset.widths,
                glyphs={
                    character.encode("cp1252")[0]: program.glyph_id(character)
                    for character in self._characters[key]
                },
                units_per_em=metrics.units_per_em,
                bbox=tuple(metrics.scaled(value) for value in metrics.bbox),
                ascent=metrics.scaled(metrics.ascent),
                descent=metrics.scaled(metrics.descent),
                cap_height=metrics.scaled(metrics.cap_height),
                italic_angle=metrics.italic_angle,
                flags=program.flags,
                stem_v=120 if metrics.weight >= 600 else 80,
            )
        return faces


def font_name(family: str | None, weight: str = "normal", style: str = "normal") -> str:
    """The base-14 face for one Section 8.2.1 run, with the Section 7.1 fallback."""

    base = (family or "Helvetica").strip().lower()
    if base not in ("helvetica", "times", "courier"):
        base = "helvetica"
    bold = weight == "bold" or (weight.isdigit() and int(weight) >= 600)
    italic = style in ("italic", "oblique")
    if base == "times":
        return _TIMES[(bold, italic)]
    if bold:
        return base.capitalize() + ("-BoldOblique" if italic else "-Bold")
    return base.capitalize() + ("-Oblique" if italic else "")


def _baseline(text: objects.Text) -> float:
    """Where the baseline sits below the em-box top, honouring Section 8.2.1 `valign`."""

    if text.height is None or text.valign == "top":
        return ASCENT * text.size
    if text.valign == "middle":
        return (text.height - text.size) / 2.0 + ASCENT * text.size
    return text.height - DESCENT * text.size


def _subpaths(drawn: composition.Drawn, primitive: objects.Primitive) -> tuple[Subpath, ...]:
    """The geometry one Section 8.2 shape paints, in its own millimetres."""

    try:
        if isinstance(primitive, objects.Rect):
            return geometry.rectangle(primitive.width, primitive.height, primitive.rx, primitive.ry)
        if isinstance(primitive, objects.Circle):
            return geometry.circle(primitive.r)
        if isinstance(primitive, objects.Ellipse):
            return geometry.ellipse(primitive.rx, primitive.ry)
        if isinstance(primitive, objects.Segment):
            return geometry.polyline(primitive.points, closed=primitive.closed)
        if isinstance(primitive, objects.Path):
            return geometry.svg_path(primitive.d)
    except geometry.GeometryError as exc:
        raise OutputError(f"{drawn.path}: {exc}") from None
    raise OutputError(f"{drawn.path}: no geometry for {type(primitive).__name__}")


def _dark_runs(modules: tuple[bool, ...]) -> tuple[tuple[int, int], ...]:
    """The half-open index ranges of each run of dark modules in one row."""

    runs: list[tuple[int, int]] = []
    index = 0
    while index < len(modules):
        if not modules[index]:
            index += 1
            continue
        end = index
        while end < len(modules) and modules[end]:
            end += 1
        runs.append((index, end))
        index = end
    return tuple(runs)


def _pdf417_caption_refused(drawn: composition.Drawn) -> OutputError:
    """The error a pdf417 `draw_text` object gets while its caption is undefined."""

    return OutputError(
        f"{drawn.path}: draw_text is true, and RenderSpec leaves the pdf417 caption "
        "undefined; set draw_text to false"
    )


def _standard_advance(font: str, content: str, path: str) -> float:
    """`content`'s advance in `font`'s ems, from the base-14 width table."""

    if font == "Courier":
        return _COURIER_ADVANCE * len(content) / 1000.0
    widths = _STANDARD_ADVANCES.get(font)
    if widths is None:
        raise OutputError(f"{path}: base-14 caption face {font!r} has no advance widths")
    total = 0
    for character in content:
        index = ord(character) - 0x20
        if not 0 <= index < len(widths):
            raise OutputError(
                f"{path}: base-14 caption face {font!r} has no advance for {character!r}; "
                "set caption_font_family to a registered face"
            )
        total += widths[index]
    return total / 1000.0


def _caption_string(encoded: barcode.Symbol) -> str:
    """Section 8.2.10's caption table: the payload without symbol structure."""

    # Every encoder already reports check digits, the UPC-E number system and
    # uppercase guards in `content`; only Codabar still carries its A-D guards.
    if encoded.symbology == "codabar":
        return encoded.content[1:-1]
    return encoded.content


def _caption_op(
    drawn: composition.Drawn,
    primitive: objects.Barcode,
    encoded: barcode.Symbol,
    matrix: Affine,
    space: str,
    typefaces: _Fonts,
) -> Text:
    """The one centred caption line of a Section 8.2.10 object (`RT-118`)."""

    content = _caption_string(encoded)
    face = typefaces.select(primitive.caption_font_family, "normal", "normal", drawn.path)
    if face is None:
        face = font_name(primitive.caption_font_family)
        advance = _standard_advance(face, content, drawn.path)
    else:
        typefaces.note(face, content, drawn.path)
        advance = typefaces.advance(face, content)
    ink = colour(primitive.color, space)
    return Text(
        matrix=matrix @ Affine.translation(
            (primitive.width - advance * primitive.caption_size) / 2.0,
            primitive.height + primitive.caption_gap,
        ),
        content=content,
        font=face,
        size=primitive.caption_size,
        baseline=ASCENT * primitive.caption_size,
        colour=ink,
        alpha=drawn.alpha * ink.alpha,
    )


def _barcode_ops(
    drawn: composition.Drawn,
    primitive: objects.Barcode,
    matrix: Affine,
    space: str,
    typefaces: _Fonts,
) -> tuple[Op, ...]:
    """The background, bars and caption of one Section 8.2.10 symbol (`RT-116`, `RT-118`)."""

    try:
        encoded = barcode.symbol(primitive.symbology, primitive.content)
    except barcode.BarcodeError as exc:
        raise OutputError(f"{drawn.path}: {exc}") from None

    ops: list[Op] = []
    if primitive.background != "none":
        backdrop = colour(primitive.background, space)
        ops.append(
            Fill(
                matrix=matrix,
                subpaths=geometry.rectangle(primitive.width, primitive.height),
                colour=backdrop,
                alpha=drawn.alpha * backdrop.alpha,
            )
        )

    # One rectangle per run of modules: consecutive bars merge, so the pattern is
    # drawn with as few operations as the symbol allows and no module is skipped.
    module = primitive.width / encoded.module_count
    ink = colour(primitive.color, space)
    for start, end in _dark_runs(encoded.modules):
        left = start * module
        right = primitive.width if end == encoded.module_count else end * module
        ops.append(
            Fill(
                matrix=matrix @ Affine.translation(left, 0.0),
                subpaths=geometry.rectangle(right - left, primitive.height),
                colour=ink,
                alpha=drawn.alpha * ink.alpha,
            )
        )
    if primitive.draw_text:
        ops.append(_caption_op(drawn, primitive, encoded, matrix, space, typefaces))
    return tuple(ops)


def _pdf417_ops(
    drawn: composition.Drawn,
    primitive: objects.Barcode,
    matrix: Affine,
    space: str,
) -> tuple[Op, ...]:
    """The background and bar rectangles of one Section 8.2.10 PDF417 symbol (`RT-116`)."""

    if primitive.draw_text:
        raise _pdf417_caption_refused(drawn)
    try:
        encoded = pdf417.encode(primitive.content, primitive.width, primitive.height)
    except pdf417.Pdf417Error as exc:
        raise OutputError(f"{drawn.path}: {exc}") from None

    ops: list[Op] = []
    if primitive.background != "none":
        backdrop = colour(primitive.background, space)
        ops.append(
            Fill(
                matrix=matrix,
                subpaths=geometry.rectangle(primitive.width, primitive.height),
                colour=backdrop,
                alpha=drawn.alpha * backdrop.alpha,
            )
        )

    # One rectangle per run of dark modules, row by row. The last column and the
    # last row are pinned to the declared edges, so the symbol spans exactly
    # `width` and `height` however the divisions round.
    module = primitive.width / encoded.module_count
    row_height = primitive.height / encoded.row_count
    ink = colour(primitive.color, space)
    for row, modules in enumerate(encoded.modules):
        top = row * row_height
        bottom = primitive.height if row == encoded.row_count - 1 else (row + 1) * row_height
        for start, end in _dark_runs(modules):
            left = start * module
            right = primitive.width if end == encoded.module_count else end * module
            ops.append(
                Fill(
                    matrix=matrix @ Affine.translation(left, top),
                    subpaths=geometry.rectangle(right - left, bottom - top),
                    colour=ink,
                    alpha=drawn.alpha * ink.alpha,
                )
            )
    return tuple(ops)


def _qrcode_ops(
    drawn: composition.Drawn,
    primitive: objects.Qrcode,
    matrix: Affine,
    space: str,
) -> tuple[Op, ...]:
    """The background and dark-module rectangles of one `qrcode` (`RT-116`)."""

    try:
        encoded = qrcode.encode(primitive.content, primitive.error_correction)
    except qrcode.QrcodeError as exc:
        raise OutputError(f"{drawn.path}: {exc}") from None

    ops: list[Op] = []
    if primitive.background != "none":
        backdrop = colour(primitive.background, space)
        ops.append(
            Fill(
                matrix=matrix,
                subpaths=geometry.rectangle(primitive.size, primitive.size),
                colour=backdrop,
                alpha=drawn.alpha * backdrop.alpha,
            )
        )

    # One rectangle per horizontal run of dark modules, row by row. The last
    # column and the last row are pinned to the declared edge, so the grid spans
    # exactly `size` mm however the division rounds.
    module = primitive.size / encoded.module_count
    ink = colour(primitive.color, space)
    for row, modules in enumerate(encoded.modules):
        top = row * module
        bottom = primitive.size if row == encoded.module_count - 1 else (row + 1) * module
        for start, end in _dark_runs(modules):
            left = start * module
            right = primitive.size if end == encoded.module_count else end * module
            ops.append(
                Fill(
                    matrix=matrix @ Affine.translation(left, top),
                    subpaths=geometry.rectangle(right - left, bottom - top),
                    colour=ink,
                    alpha=drawn.alpha * ink.alpha,
                )
            )
    return tuple(ops)


def _image_op(
    drawn: composition.Drawn,
    primitive: objects.Image,
    matrix: Affine,
    pictures: assets.Registry,
) -> Image:
    """The Section 8.2.9 picture, fitted to its declared box when asked."""

    try:
        picture = pictures.picture(primitive.asset_id, drawn.path)
    except assets.AssetError as exc:
        raise OutputError(str(exc)) from None

    width, height = primitive.width, primitive.height
    offset = IDENTITY
    if primitive.preserve_aspect_ratio:
        scale = min(width / picture.width, height / picture.height)
        width, height = picture.width * scale, picture.height * scale
        offset = Affine.translation((primitive.width - width) / 2.0, (primitive.height - height) / 2.0)
    return Image(matrix=matrix @ offset, picture=picture, width=width, height=height, alpha=drawn.alpha)


def _drawn_ops(
    drawn: composition.Drawn,
    origin: Affine,
    space: str,
    typefaces: _Fonts,
    pictures: assets.Registry,
) -> tuple[Op, ...]:
    """The operations one drawn object contributes, placed in page space."""

    matrix = origin @ drawn.matrix
    try:
        primitive = objects.primitive(drawn.object)
    except ValueError as exc:
        raise OutputError(f"{drawn.path}: {exc}") from None

    if isinstance(primitive, objects.Text):
        if primitive.align != "left":
            raise OutputError(
                f"{drawn.path}: align {primitive.align!r} needs glyph measurement, "
                "which the output backend does not implement"
            )
        if primitive.wrap:
            raise OutputError(
                f"{drawn.path}: wrap needs glyph measurement, "
                "which the output backend does not implement"
            )
        try:
            primitive.content.encode("cp1252")
        except UnicodeEncodeError:
            raise OutputError(
                f"{drawn.path}: content {primitive.content!r} is outside WinAnsiEncoding"
            ) from None
        face = typefaces.select(
            primitive.font_family, primitive.font_weight, primitive.font_style, drawn.path
        )
        if face is None:
            face = font_name(primitive.font_family, primitive.font_weight, primitive.font_style)
        else:
            typefaces.note(face, primitive.content, drawn.path)
        ink = colour(primitive.color, space)
        return (
            Text(
                matrix=matrix,
                content=primitive.content,
                font=face,
                size=primitive.size,
                baseline=_baseline(primitive),
                colour=ink,
                alpha=drawn.alpha * ink.alpha,
            ),
        )

    if isinstance(primitive, objects.Image):
        return (_image_op(drawn, primitive, matrix, pictures),)

    if isinstance(primitive, objects.Barcode):
        if primitive.symbology == "pdf417":
            return _pdf417_ops(drawn, primitive, matrix, space)
        return _barcode_ops(drawn, primitive, matrix, space, typefaces)

    if isinstance(primitive, objects.Qrcode):
        return _qrcode_ops(drawn, primitive, matrix, space)

    subpaths = _subpaths(drawn, primitive)
    paint = primitive.paint
    ops: list[Op] = []
    if paint.fill is not None:
        fill = colour(paint.fill, space)
        ops.append(
            Fill(matrix=matrix, subpaths=subpaths, colour=fill, alpha=drawn.alpha * fill.alpha)
        )
    if paint.stroke is not None:
        stroke = colour(paint.stroke, space)
        ops.append(
            Stroke(
                matrix=matrix,
                subpaths=subpaths,
                colour=stroke,
                width=paint.width,
                dash=paint.dash,
                alpha=drawn.alpha * stroke.alpha,
            )
        )
    return tuple(ops)


def _ops(
    document: Mapping[str, Any],
    record: Mapping[str, Any],
    origin: Affine,
    space: str,
    typefaces: _Fonts,
    pictures: assets.Registry,
) -> tuple[Op, ...]:
    """Every operation one label body paints, with its record bound."""

    ops: list[Op] = []
    for drawn in composition.draw_list(binding.bind(document, record)):
        ops.extend(_drawn_ops(drawn, origin, space, typefaces, pictures))
    return tuple(ops)


def display_pages(
    document: Mapping[str, Any],
    *,
    typefaces: _Fonts | None = None,
    pictures: assets.Registry | None = None,
) -> tuple[Page, ...]:
    """The pages a validated document renders, each with its label bodies.

    Page-absolute mode paints the layers once across the page. Stock-grid mode
    paints one body per frame that carries a record, in row-major order, and one
    page per grid of records: frames without a record stay empty (`RT-105`,
    `RT-106`). Section 10.2 assigns records to grid frames only, so a
    page-absolute body binds an empty record and resolves its placeholders as
    unresolved (`RB-102`).
    """

    space = (document.get("output") or {}).get("color_space", "rgb")
    if space not in COLOUR_SPACES:
        raise OutputError(f"colour space {space!r} is not one of {COLOUR_SPACES}")
    typefaces = typefaces or _Fonts(document)
    pictures = pictures or assets.Registry(document)
    page = layout.page_box(document)

    if document.get("stock") is None:
        body = Body(clip=page, ops=_ops(document, {}, IDENTITY, space, typefaces, pictures))
        return (Page(box=page, bodies=(body,)),)

    frames = layout.document_frames(document)
    pages: list[Page] = []
    for slots in binding.page_slots(document):
        bodies: list[Body] = []
        for frame, record in zip(frames, slots, strict=True):
            if record is None:
                continue
            clip = Box(frame.x, frame.y, frame.width, frame.height)
            origin = Affine.translation(frame.x, frame.y)
            bodies.append(
                Body(
                    clip=clip,
                    ops=_ops(document, record, origin, space, typefaces, pictures),
                )
            )
        pages.append(Page(box=page, bodies=tuple(bodies)))
    return tuple(pages)


def artifact(document: Mapping[str, Any], *, format: str | None = None) -> bytes:
    """Render one document to PDF or PostScript bytes (`RO-101`-`RO-110`).

    The document is validated first, so an invalid one raises
    `renderer.renderspec.RenderSpecError` and no artifact exists. `format`
    overrides the document's `output.format`, which itself defaults to `pdf`
    (Section 4.2). Nothing is written to disk: the bytes are the artifact.
    """

    accepted = renderspec.parse(document)
    constraints = accepted.get("output") or {}
    requested = format or constraints.get("format") or "pdf"
    if requested not in FORMATS:
        raise OutputError(f"output format {requested!r} is not one of {FORMATS}")

    typefaces = _Fonts(accepted)
    pictures = assets.Registry(accepted)
    pages = display_pages(accepted, typefaces=typefaces, pictures=pictures)
    faces = typefaces.faces()
    if requested == "pdf":
        version = str(constraints.get("pdf_version", "1.4"))
        if not _VERSION.match(version):
            raise OutputError(f"pdf_version {version!r} is not a version number")
        return pdf.write(
            pages,
            faces,
            version=version,
            compress=bool(constraints.get("compress", True)),
        )

    if any(op.alpha != 1.0 for page in pages for body in page.bodies for op in body.ops):
        raise OutputError(
            "PostScript has no transparency; use PDF for a document with an opacity "
            "below 1.0 or a translucent colour"
        )
    if any(
        isinstance(op, Image) and op.picture.kind == "png" and op.picture.bits == 16
        for page in pages
        for body in page.bodies
        for op in body.ops
    ):
        raise OutputError(
            "a Level 2 image dictionary carries at most 12 bits per component, and "
            "this PNG declares 16; render this document to PDF or resample the asset"
        )
    return postscript.write(pages, faces)
