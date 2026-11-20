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

Section 8.2 properties an output backend needs geometry or glyph metrics for are
reported rather than approximated: images, barcodes and QR codes belong to the
object plugins of `MILESTONES.md` R2/R3, `align` other than `left` and `wrap`
need glyph measurement, and a family declared in `fonts` needs font embedding
(`RO-104`). Text is placed with the em box convention below until those arrive.

Section 4.2 `color_space` conversions, one documented algorithm each (`RO-105`):

* `rgb` — the sRGB channels of Section 7.3, unchanged.
* `grayscale` — the luma `Y = 0.299 R + 0.587 G + 0.114 B` (ITU-R BT.601).
* `cmyk` — `K = 1 - max(R, G, B)` and `C = (1 - R - K) / (1 - K)` with the same
  formula for M and Y; a pure black input stays `(0, 0, 0, 1)`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from renderer import binding, composition, geometry, layout, objects, pdf, postscript, renderspec
from renderer.coordinates import IDENTITY, Affine
from renderer.geometry import Subpath
from renderer.layout import Box
from renderer.plan import Body, Colour, Fill, Op, Page, Stroke, Text

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


def _drawn_ops(
    drawn: composition.Drawn, origin: Affine, space: str, registered: Iterable[str]
) -> tuple[Op, ...]:
    """The operations one drawn object contributes, placed in page space."""

    matrix = origin @ drawn.matrix
    try:
        primitive = objects.primitive(drawn.object)
    except ValueError as exc:
        raise OutputError(f"{drawn.path}: {exc}") from None

    if isinstance(primitive, objects.Text):
        if primitive.font_family is not None and primitive.font_family in registered:
            raise OutputError(
                f"{drawn.path}: font {primitive.font_family!r} is declared in `fonts`; "
                "embedding a custom face is not implemented (RO-104)"
            )
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
        ink = colour(primitive.color, space)
        return (
            Text(
                matrix=matrix,
                content=primitive.content,
                font=font_name(primitive.font_family, primitive.font_weight, primitive.font_style),
                size=primitive.size,
                baseline=_baseline(primitive),
                colour=ink,
                alpha=drawn.alpha * ink.alpha,
            ),
        )

    if isinstance(primitive, objects.Image | objects.Barcode | objects.Qrcode):
        raise OutputError(
            f"{drawn.path}: {drawn.object.get('type')!r} objects need the R2/R3 object "
            "plugins; this backend paints Section 8.2 text and vector shapes"
        )

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
    registered: Iterable[str],
) -> tuple[Op, ...]:
    """Every operation one label body paints, with its record bound."""

    ops: list[Op] = []
    for drawn in composition.draw_list(binding.bind(document, record)):
        ops.extend(_drawn_ops(drawn, origin, space, registered))
    return tuple(ops)


def display_pages(document: Mapping[str, Any]) -> tuple[Page, ...]:
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
    registered = {font.get("family") for font in document.get("fonts") or ()}
    page = layout.page_box(document)

    if document.get("stock") is None:
        body = Body(clip=page, ops=_ops(document, {}, IDENTITY, space, registered))
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
            bodies.append(Body(clip=clip, ops=_ops(document, record, origin, space, registered)))
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

    pages = display_pages(accepted)
    if requested == "pdf":
        version = str(constraints.get("pdf_version", "1.4"))
        if not _VERSION.match(version):
            raise OutputError(f"pdf_version {version!r} is not a version number")
        return pdf.write(pages, version=version, compress=bool(constraints.get("compress", True)))

    if any(op.alpha != 1.0 for page in pages for body in page.bodies for op in body.ops):
        raise OutputError(
            "PostScript has no transparency; use PDF for a document with an opacity "
            "below 1.0 or a translucent colour"
        )
    return postscript.write(pages)
