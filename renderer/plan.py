"""The backend-neutral page plan of `renderer.output`.

A plan is what a document paints, expressed once so that the PDF and the
PostScript writers cannot disagree: `Fill` and `Stroke` operations carry Section
8.2 geometry in the object's own millimetres plus the matrix that places it on
the page, `Text` carries one single-line run, `Image` carries a raster picture's
compressed stream plus the box it fills, and a `Body` ties a label's operations
to the region they may ink (`RT-104`). All lengths are page millimetres with Y
increasing downwards (RenderSpec Section 3); a writer converts them to its own
units and rounds them at emission.

Nothing here is derived from the clock, the environment or a random source, which
is what lets two renders of one document be byte-identical (`RS-119`, `DT-101`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from renderer.assets import Picture
from renderer.coordinates import Affine
from renderer.geometry import Point, Subpath
from renderer.layout import Box


@dataclass(frozen=True)
class Face:
    """One typeface a run is set in: a base-14 name or a registered program.

    A registered face carries both the whole program (PostScript embeds it as a
    Type 42 font) and the deterministic subset of the glyphs the document uses
    (PDF embeds that subset). `cids` maps each character to its subset CID for
    PDF's `Identity-H` encoding, and `glyphs` maps each WinAnsi byte to its
    glyph id in the whole program for the PostScript `CharStrings` dictionary.
    Dimensions are in PDF's 1000-unit glyph space.
    """

    name: str
    tag: str = ""
    program: bytes | None = None
    subset: bytes | None = None
    cids: Mapping[str, int] = field(default_factory=dict)
    widths: Mapping[int, int] = field(default_factory=dict)
    glyphs: Mapping[int, int] = field(default_factory=dict)
    units_per_em: int = 1000
    bbox: tuple[int, int, int, int] = (0, 0, 1000, 1000)
    ascent: int = 800
    descent: int = -200
    cap_height: int = 700
    italic_angle: float = 0.0
    flags: int = 32
    stem_v: int = 80

    @property
    def embedded(self) -> bool:
        """Whether this face carries a font program to embed."""

        return self.subset is not None

    @property
    def pdf_name(self) -> str:
        """The `/BaseFont` name, with the subset tag when the face is embedded."""

        return f"{self.tag}+{self.name}" if self.tag else self.name


@dataclass(frozen=True)
class Colour:
    """One paint colour in the declared output colour space, with its alpha."""

    space: str
    values: tuple[float, ...]
    alpha: float = 1.0


@dataclass(frozen=True)
class Fill:
    """Fill `subpaths`, given in the object's local millimetres, through `matrix`.

    `evenodd` selects the even-odd rule for an SVG asset whose `fill-rule` asks
    for it. `clip` is a page-millimetre polygon the fill is clipped to before
    `matrix` places it: SVG artwork is clipped to its viewport, and a polygon
    (rather than an axis-aligned box) keeps that clip correct when the object
    is rotated.
    """

    matrix: Affine
    subpaths: tuple[Subpath, ...]
    colour: Colour
    alpha: float = 1.0
    evenodd: bool = False
    clip: tuple[Point, ...] | None = None


@dataclass(frozen=True)
class Stroke:
    """Stroke `subpaths` with a width and dash pattern in the matrix's units."""

    matrix: Affine
    subpaths: tuple[Subpath, ...]
    colour: Colour
    width: float
    dash: tuple[float, ...] = ()
    alpha: float = 1.0
    clip: tuple[Point, ...] | None = None


@dataclass(frozen=True)
class Text:
    """One single-line run, with `baseline` millimetres below the em-box top."""

    matrix: Affine
    content: str
    font: str
    size: float
    baseline: float
    colour: Colour
    alpha: float = 1.0


@dataclass(frozen=True)
class Image:
    """Place `picture` in a `width` x `height` mm box at the object's origin.

    `picture.data` is the source's own compressed stream, carried unchanged; the
    writers wrap it in their image operator without re-encoding or resampling it.
    PostScript unfilters a PNG's scanlines first, because a Level 2 image
    dictionary has no deflate filter (`renderer.assets.samples`).
    """

    matrix: Affine
    picture: Picture
    width: float
    height: float
    alpha: float = 1.0


Op = Fill | Stroke | Text | Image


@dataclass(frozen=True)
class Body:
    """One label body: the region it may ink and the operations inside it."""

    clip: Box
    ops: tuple[Op, ...]


@dataclass(frozen=True)
class Page:
    """One output page: the sheet and the bodies placed on it."""

    box: Box
    bodies: tuple[Body, ...]
