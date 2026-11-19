"""Layout engine: stock-grid frame placement and active-boundary diagnostics.

Two published rules meet here.

StockSpec Section 6.2 fixes the label frame origins on the sheet:

    X_col(c) = margins.left + c * pitch.horizontal
    Y_row(r) = margins.top + r * pitch.vertical

and Section 5.4 fixes the fill order: row-major, column index increasing first.
RenderSpec Section 5.2 states the same formula for inline `stock`, with the
canvas origin at the top-left of the individual label in stock-grid mode and at
the page top-left in page-absolute mode (RenderSpec Section 3). Every physical
value is millimetres, so placement stays in millimetres and is only converted
by the object transforms in `renderer.coordinates`.

RenderSpec Section 11 rule 4 and ConformanceSpec `RS-118` make boundary overflow
a RECOMMENDED diagnostic: an object whose computed bounding box extends past the
active boundary is reported, but the document stays valid. `overflow_warnings`
returns those findings and never raises, so a caller can report them and keep
processing (clipping is `RT-104`, outside this module).

Only geometry the specification fixes is measured. A `circle` or `ellipse` has
no documented anchor convention, and `path` data and `text` without `width` and
`height` have no documented extent, so those objects produce no measurement
rather than a guess.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from renderer.coordinates import IDENTITY, Affine, object_matrix

Point = tuple[float, float]

# A box edge exactly on the boundary is not an overflow; the tolerance only
# absorbs floating-point representation of an edge computed by two routes.
EDGE_TOLERANCE = 1e-9

# Object types whose local geometry the specification defines, mapped to the
# properties that give it. `text` also needs both, and is handled separately.
_SIZED_TYPES = ("rect", "image", "barcode")


@dataclass(frozen=True)
class Box:
    """An axis-aligned box in millimetres, positioned by its top-left corner."""

    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    def corners(self) -> tuple[Point, Point, Point, Point]:
        """The four corners, clockwise from the top-left."""

        return (
            (self.x, self.y),
            (self.right, self.y),
            (self.right, self.bottom),
            (self.x, self.bottom),
        )


@dataclass(frozen=True)
class Frame:
    """One label frame on the sheet, positioned by its top-left corner."""

    column: int
    row: int
    columns: int
    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def index(self) -> int:
        """Row-major slot index: column increases first (StockSpec Section 5.4)."""

        return self.row * self.columns + self.column


@dataclass(frozen=True)
class Overflow:
    """An object whose bounding box exceeds the active boundary (`RS-118`)."""

    path: str
    object_id: str | None
    bounds: Box
    edges: tuple[str, ...]
    boundary: Box

    def render(self) -> str:
        name = f"object {self.object_id!r}" if self.object_id else "object"
        edges = ", ".join(self.edges)
        return (
            f"{self.path}: {name} extends past the active boundary "
            f"({self.boundary.width} x {self.boundary.height} mm) "
            f"on the {edges} edge(s)"
        )


def grid_frames(
    *,
    rows: int,
    columns: int,
    margin_left: float,
    margin_top: float,
    horizontal_pitch: float,
    vertical_pitch: float,
    width: float,
    height: float,
) -> tuple[Frame, ...]:
    """Return every frame origin in row-major order (StockSpec Section 6.2).

    `width` and `height` are the label dimensions each frame spans.
    """

    frames: list[Frame] = []
    for row in range(int(rows)):
        for column in range(int(columns)):
            frames.append(
                Frame(
                    column=column,
                    row=row,
                    columns=int(columns),
                    x=float(margin_left) + column * float(horizontal_pitch),
                    y=float(margin_top) + row * float(vertical_pitch),
                    width=float(width),
                    height=float(height),
                )
            )
    return tuple(frames)


def stock_frames(stock: Mapping[str, Any]) -> tuple[Frame, ...]:
    """Place the frames of a StockSpec document on its sheet.

    Reads the fields Section 6.2 names: `grid`, `margins`, `pitch` and `label`.
    The document is expected to be structurally valid, so the members are
    present; mathematical validity is the parser's concern, not the layout's.
    """

    grid = stock["grid"]
    margins = stock["margins"]
    pitch = stock["pitch"]
    label = stock["label"]
    return grid_frames(
        rows=grid["rows"],
        columns=grid["columns"],
        margin_left=margins["left"],
        margin_top=margins["top"],
        horizontal_pitch=pitch["horizontal"],
        vertical_pitch=pitch["vertical"],
        width=label["width"],
        height=label["height"],
    )


def page_box(document: Mapping[str, Any]) -> Box:
    """The page as a box, always anchored at the page top-left (Section 3)."""

    page = document["page"]
    return Box(0.0, 0.0, float(page["width"]), float(page["height"]))


def active_boundary(document: Mapping[str, Any]) -> Box:
    """The boundary layout coordinates are valid in.

    RenderSpec Section 3: the active boundary is the page in page-absolute mode
    and an individual label when `stock` is present. Section 5.2 puts the label
    origin at `(0, 0)` in stock-grid mode, so the boundary starts there too.
    """

    stock = document.get("stock")
    if stock is None:
        return page_box(document)
    return Box(0.0, 0.0, float(stock["width"]), float(stock["height"]))


def _points_box(points: Sequence[Sequence[float]]) -> Box:
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return Box(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def local_box(obj: Mapping[str, Any]) -> Box | None:
    """The object's own geometry before its transform, or `None` if undefined.

    Only the primitives whose extent the specification fixes are measured:
    sized rectangles (rect, image, barcode), the square `qrcode`, a `text` box
    with both `width` and `height`, `line` end points, and the vertices of
    `polyline` and `polygon`. `circle`, `ellipse` and `path` leave the anchor or
    the extent undefined, so they are not guessed.
    """

    kind = obj.get("type")
    if kind in _SIZED_TYPES:
        return Box(0.0, 0.0, float(obj["width"]), float(obj["height"]))
    if kind == "qrcode":
        size = float(obj["size"])
        return Box(0.0, 0.0, size, size)
    if kind == "text":
        if "width" in obj and "height" in obj:
            return Box(0.0, 0.0, float(obj["width"]), float(obj["height"]))
        return None
    if kind == "line":
        return _points_box([(0.0, 0.0), (obj["x2"], obj["y2"])])
    if kind in ("polyline", "polygon"):
        points = [(0.0, 0.0), *((float(p[0]), float(p[1])) for p in obj["points"])]
        return _points_box(points)
    return None


def _transform_box(box: Box, matrix: Affine) -> Box:
    """Map a box through a transform and return its axis-aligned envelope."""

    return _points_box([matrix.apply(corner) for corner in box.corners()])


def _union(boxes: Sequence[Box]) -> Box | None:
    if not boxes:
        return None
    return Box(
        min(box.x for box in boxes),
        min(box.y for box in boxes),
        max(box.right for box in boxes) - min(box.x for box in boxes),
        max(box.bottom for box in boxes) - min(box.y for box in boxes),
    )


def object_bounds(obj: Mapping[str, Any], parent: Affine = IDENTITY) -> Box | None:
    """Return an object's bounding box in its parent space, or `None`.

    The object's Section 9 transform is applied, and a rotated object yields the
    axis-aligned envelope of its transformed corners. A `group` returns the
    union of its visible children, each measured through the group's transform
    (RenderSpec Section 8.2.12).
    """

    raw = obj.get("type")
    matrix = object_matrix(obj, parent)

    if raw == "group":
        boxes = [
            bounds
            for child in obj.get("objects") or ()
            if child.get("visible", True) is not False
            for bounds in (object_bounds(child, matrix),)
            if bounds is not None
        ]
        return _union(boxes)

    if obj.get("visible", True) is False:
        return None
    measured = local_box(obj)
    if measured is None:
        return None
    return _transform_box(measured, matrix)


def _edges_outside(bounds: Box, boundary: Box) -> tuple[str, ...]:
    edges: list[str] = []
    if bounds.x < -EDGE_TOLERANCE:
        edges.append("left")
    if bounds.y < -EDGE_TOLERANCE:
        edges.append("top")
    if bounds.right > boundary.width + EDGE_TOLERANCE:
        edges.append("right")
    if bounds.bottom > boundary.height + EDGE_TOLERANCE:
        edges.append("bottom")
    return tuple(edges)


def _walk(
    objects: Sequence[Mapping[str, Any]], path: str, parent: Affine
) -> Iterator[tuple[str, Mapping[str, Any], Affine]]:
    """Yield every drawn object with the matrix of the groups containing it.

    A group is not drawn, so only its children are yielded; each one carries the
    group's transform so a nested object is measured where it actually lands
    (RenderSpec Section 8.2.12, `RT-117`).
    """

    for index, obj in enumerate(objects):
        if obj.get("visible", True) is False:
            continue
        child_path = f"{path}.{index}"
        if obj.get("type") == "group":
            yield from _walk(
                obj.get("objects") or (),
                f"{child_path}.objects",
                object_matrix(obj, parent),
            )
            continue
        yield child_path, obj, parent


def overflow_warnings(document: Mapping[str, Any]) -> tuple[Overflow, ...]:
    """Report every object that extends past the active boundary (`RS-118`).

    RECOMMENDED, not an error: the findings are returned and the document stays
    valid (RenderSpec Section 11 rule 4). Hidden layers and hidden objects are
    skipped, because Section 6 and Section 8.1 require them not to be drawn, so
    they cannot overflow an active boundary.
    """

    boundary = active_boundary(document)
    findings: list[Overflow] = []
    for layer_index, layer in enumerate(document.get("layers") or ()):
        if layer.get("visible", True) is False:
            continue
        root = f"layers.{layer_index}.objects"
        for path, obj, parent in _walk(layer.get("objects") or (), root, IDENTITY):
            bounds = object_bounds(obj, parent)
            if bounds is None:
                continue
            edges = _edges_outside(bounds, boundary)
            if edges:
                findings.append(
                    Overflow(
                        path=path,
                        object_id=obj.get("id"),
                        bounds=bounds,
                        edges=edges,
                        boundary=boundary,
                    )
                )
    return tuple(findings)
