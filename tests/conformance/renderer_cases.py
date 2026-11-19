"""Conformance checks that drive the parser, coordinate engine and layout engine.

`CP-RS` and `CP-ST` requirements that needed a parser implementation (`CN-102`),
a configured parser mode (`CN-105`), a layout (`SS-104`, `SS-113`, `SS-115`,
`SS-118`), a label clip (`SS-112`, `RT-104`) or computed object geometry
(`RS-118`) were deferred until `renderer/` existed. These checks exercise that
reference implementation, the way `engine_cases.py` exercises the calibration
engine, instead of the suite's own formula.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from renderer import clip, coordinates, layout, renderspec  # noqa: E402

EXAMPLES = ROOT / "specs" / "renderspec" / "examples"
FIXTURES = ROOT / "tests" / "conformance" / "fixtures" / "renderspec"
STOCK_EXAMPLES = ROOT / "specs" / "stockspec" / "examples"
STOCK_FIXTURES = ROOT / "tests" / "conformance" / "fixtures" / "stockspec"
TOLERANCE = 1e-9


def _close(observed: tuple[float, float], expected: tuple[float, float]) -> bool:
    return (
        abs(observed[0] - expected[0]) <= TOLERANCE and abs(observed[1] - expected[1]) <= TOLERANCE
    )


def coordinate_convention() -> tuple[bool, str]:
    """CN-102: origin top-left, X right, Y down, millimetres, clockwise rotation."""

    document = renderspec.load(EXAMPLES / "simple_label.json")
    obj = document["layers"][0]["objects"][0]
    origin = coordinates.transform_point(obj, (0.0, 0.0))
    right = coordinates.transform_point(obj, (10.0, 0.0))
    down = coordinates.transform_point(obj, (0.0, 10.0))

    observed = {
        "origin": origin,
        "x-right": right,
        "y-down": down,
    }
    expected = {
        # The example's first object sits at (1, 1) mm, the page's top-left corner.
        "origin": (1.0, 1.0),
        "x-right": (11.0, 1.0),
        "y-down": (1.0, 11.0),
    }
    wrong = [name for name in expected if not _close(observed[name], expected[name])]
    if wrong:
        return False, ", ".join(f"{name} gave {observed[name]}" for name in wrong)

    rotated = coordinates.object_matrix({"rotation": 90.0}).apply((10.0, 0.0))
    if not _close(rotated, (0.0, 10.0)):
        return (
            False,
            f"90 degrees maps (10, 0) to {rotated}, expected (0, 10) clockwise",
        )

    millimetres = coordinates.transform_point({"x": 10.0, "y": 20.0}, (0.0, 0.0))
    if not _close(millimetres, (10.0, 20.0)):
        return False, f"a 10 x 20 mm offset became {millimetres}"
    if abs(coordinates.points_to_mm(72.0) - 25.4) > TOLERANCE:
        return False, f"72 pt is {coordinates.points_to_mm(72.0)} mm, expected 25.4"

    return True, (
        f"origin {origin}, +X {right}, +Y {down}, 90 degrees clockwise to {rotated}, "
        "and 72 pt = 25.4 mm"
    )


def _strict_rejection(path: Path) -> renderspec.RenderSpecError | None:
    try:
        renderspec.load(path)
    except renderspec.RenderSpecError as exc:
        return exc
    return None


def forward_compatibility_mode() -> tuple[bool, str]:
    """CN-105: strict is the default; forward mode drops unknown properties only."""

    unknown = FIXTURES / "invalid" / "unknown_property.json"
    strict = _strict_rejection(unknown)
    if strict is None:
        return False, "strict mode accepted a page property the schema does not define"
    paths = [diagnostic.path for diagnostic in strict.diagnostics]
    if "page" not in paths:
        return False, f"the strict rejection named {paths}, expected the page location"

    accepted = renderspec.load(unknown, strict=False)
    if "bleed" in accepted["page"]:
        return False, "forward mode kept the unknown property"
    if accepted["page"]["width"] != 50.0 or accepted["layers"][0]["id"] != "base":
        return False, "forward mode changed a recognized property"

    opacity = FIXTURES / "invalid" / "layer_opacity_out_of_range.json"
    try:
        renderspec.load(opacity, strict=False)
    except renderspec.RenderSpecError as exc:
        failed_paths = [diagnostic.path for diagnostic in exc.diagnostics]
        if "layers.0.opacity" not in failed_paths:
            return False, f"forward mode rejected the opacity at {failed_paths}"
    else:
        return False, "forward mode accepted an opacity of 1.5"

    return True, (
        "strict rejects page.bleed by default, forward mode drops it while keeping "
        "recognized properties, and forward mode still rejects opacity 1.5"
    )


def _stock(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def stockspec_frame_origins() -> tuple[bool, str]:
    """SS-104: every frame origin follows margins + index x pitch."""

    stock = _stock(STOCK_EXAMPLES / "avery_5160.yaml")
    frames = layout.stock_frames(stock)
    if len(frames) != 30:
        return False, f"laid out {len(frames)} frames, expected 30"

    # The published example pins these numbers; asserting against them keeps the
    # check independent of the document's own arithmetic.
    left, top, pitch_x, pitch_y = 4.76, 12.7, 69.85, 25.4
    wrong = [
        f"({frame.column}, {frame.row}) at ({frame.x:.6f}, {frame.y:.6f})"
        for frame in frames
        if abs(frame.x - (left + frame.column * pitch_x)) > 1e-6
        or abs(frame.y - (top + frame.row * pitch_y)) > 1e-6
    ]
    if wrong:
        return False, f"{len(wrong)} frame(s) off the formula, e.g. {wrong[0]}"

    last = frames[-1]
    expected = (left + 2 * pitch_x + 66.675, top + 9 * pitch_y + 25.4)
    if abs(last.right - expected[0]) > 1e-6 or abs(last.bottom - expected[1]) > 1e-6:
        return (
            False,
            f"the last frame ends at ({last.right}, {last.bottom}), expected {expected}",
        )

    return True, (
        f"30 frames follow X = {left} + c x {pitch_x}, Y = {top} + r x {pitch_y} "
        f"within 1e-6 mm; the last ends at ({last.right}, {last.bottom})"
    )


def stockspec_row_major_fill() -> tuple[bool, str]:
    """SS-113: labels fill row-major, column index increasing first."""

    frames = layout.stock_frames(_stock(STOCK_FIXTURES / "valid" / "grid_2x2.yaml"))
    if len(frames) != 4:
        return False, f"laid out {len(frames)} frames, expected 4"

    origins = [(5.0, 10.0), (55.0, 10.0), (5.0, 50.0), (55.0, 50.0)]
    observed = [(frame.x, frame.y) for frame in frames]
    off = [index for index, pair in enumerate(observed) if not _close(pair, origins[index])]
    if off:
        return False, f"slot {off[0]} at {observed[off[0]]}, expected {origins[off[0]]}"

    # Four records over the 2 x 2 grid: record i lands at (i mod columns, i // columns).
    slots = [(frame.index, frame.column, frame.row) for frame in frames]
    expected_slots = [(0, 0, 0), (1, 1, 0), (2, 0, 1), (3, 1, 1)]
    if slots != expected_slots:
        return False, f"slot order is {slots}, expected {expected_slots}"

    return True, (
        "4 records fill the 2 x 2 grid as (0, 0), (1, 0), (0, 1), (1, 1): column increases first"
    )


def stockspec_declared_dimensions() -> tuple[bool, str]:
    """SS-115: page.format is informational; width and height drive geometry."""

    stock = _stock(STOCK_FIXTURES / "valid" / "format_a4_letter_dims.yaml")
    page = layout.page_box(stock)
    if not _close((page.width, page.height), (215.9, 279.4)):
        return False, (
            f"the sheet measured {page.width} x {page.height} mm; a4 (210 x 297) "
            "must not override the declared dimensions"
        )

    frames = layout.stock_frames(stock)
    last = frames[-1]
    if not _close((last.right, last.bottom), (211.135, 266.7)):
        return (
            False,
            f"the last frame ends at ({last.right}, {last.bottom}), expected (211.135, 266.7)",
        )
    outside = [
        frame
        for frame in frames
        if frame.right > page.width + TOLERANCE or frame.bottom > page.height + TOLERANCE
    ]
    if outside:
        return False, f"{len(outside)} frame(s) fall outside the declared page"

    return True, (
        "a stock declaring format a4 with 215.9 x 279.4 mm lays out on those numbers; "
        f"all 30 frames fit and the last ends at ({last.right}, {last.bottom})"
    )


def stockspec_layout_ignores_timestamps() -> tuple[bool, str]:
    """SS-118: metadata timestamps must not affect layout."""

    stock = _stock(STOCK_EXAMPLES / "avery_5160.yaml")
    baseline = [
        (frame.x, frame.y, frame.width, frame.height) for frame in layout.stock_frames(stock)
    ]

    changed = copy.deepcopy(stock)
    changed["metadata"]["created_at"] = "1999-01-01T00:00:00Z"
    changed["metadata"]["updated_at"] = "2031-12-31T23:59:59Z"
    without = copy.deepcopy(stock)
    without["metadata"].pop("created_at", None)
    without["metadata"].pop("updated_at", None)

    for document, label in (
        (changed, "different timestamps"),
        (without, "no timestamps"),
    ):
        observed = [
            (frame.x, frame.y, frame.width, frame.height) for frame in layout.stock_frames(document)
        ]
        if observed != baseline:
            return False, f"layout changed with {label}"

    return (
        True,
        "all 30 frame origins and sizes are identical with different or missing timestamps",
    )


def renderspec_boundary_overflow() -> tuple[bool, str]:
    """RS-118: overflow warns, but never invalidates the document."""

    document = {
        "renderspec": "1.0",
        "id": "overflow_probe",
        "name": "Overflow Probe",
        "page": {"width": 100.0, "height": 100.0},
        "stock": {
            "width": 50.0,
            "height": 30.0,
            "rows": 1,
            "columns": 1,
            "margin_left": 10.0,
            "margin_top": 10.0,
            "horizontal_pitch": 50.0,
            "vertical_pitch": 30.0,
        },
        "layers": [
            {
                "id": "base",
                "name": "Base",
                "objects": [
                    {
                        "id": "inside",
                        "type": "rect",
                        "x": 5.0,
                        "y": 5.0,
                        "width": 10.0,
                        "height": 10.0,
                    },
                    {
                        "id": "outside",
                        "type": "rect",
                        "x": 45.0,
                        "y": 25.0,
                        "width": 20.0,
                        "height": 20.0,
                    },
                ],
            }
        ],
    }

    accepted = renderspec.parse(document)
    if accepted != document:
        return False, "parsing changed the document"

    warnings = layout.overflow_warnings(accepted)
    if len(warnings) != 1:
        return False, f"{len(warnings)} overflow warning(s) for one out-of-bounds rect"
    warning = warnings[0]
    if warning.path != "layers.0.objects.1" or warning.object_id != "outside":
        return False, f"the warning names {warning.path} ({warning.object_id!r})"
    if warning.edges != ("right", "bottom"):
        return (
            False,
            f"the warning reports edges {warning.edges}, expected right and bottom",
        )
    if not _close((warning.boundary.width, warning.boundary.height), (50.0, 30.0)):
        return False, (
            "the boundary measured "
            f"{warning.boundary.width} x {warning.boundary.height} mm, expected the 50 x 30 label"
        )

    return True, (
        "a rect past a 50 x 30 mm label is accepted and still processed, and one warning "
        f"names {warning.path} on the {', '.join(warning.edges)} edge(s)"
    )


SHAPE_FIXTURES = (
    "label_shape_rectangle.yaml",
    "label_shape_rounded_rectangle.yaml",
    "label_shape_round.yaml",
    "label_shape_oval.yaml",
)


def _corner_probes(box: layout.Box, inset: float) -> tuple[tuple[float, float], ...]:
    """The four corner probes, `inset` mm inside `box`."""

    return (
        (box.x + inset, box.y + inset),
        (box.right - inset, box.y + inset),
        (box.right - inset, box.bottom - inset),
        (box.x + inset, box.bottom - inset),
    )


def _edge_probes(box: layout.Box, inset: float) -> tuple[tuple[float, float], ...]:
    """The four edge midpoints, `inset` mm inside `box`."""

    return (
        (box.x + box.width / 2.0, box.y + inset),
        (box.right - inset, box.y + box.height / 2.0),
        (box.x + box.width / 2.0, box.bottom - inset),
        (box.x + inset, box.y + box.height / 2.0),
    )


def renderspec_page_absolute_once() -> tuple[bool, str]:
    """RT-101: without `stock` the page is rendered once, at its origin."""

    document = renderspec.load(EXAMPLES / "simple_label.json")
    frames = layout.document_frames(document)
    if len(frames) != 1:
        return False, f"page-absolute document produced {len(frames)} bodies, expected 1"
    frame = frames[0]
    page = document["page"]
    if not _close((frame.x, frame.y), (0.0, 0.0)):
        return False, f"the body starts at ({frame.x}, {frame.y}), expected the page origin"
    if not _close((frame.width, frame.height), (page["width"], page["height"])):
        return False, (
            f"the body measures {frame.width} x {frame.height} mm, "
            f"expected the {page['width']} x {page['height']} mm page"
        )

    obj = document["layers"][0]["objects"][0]
    expected = (obj["x"], obj["y"])
    observed = coordinates.transform_point(obj, (0.0, 0.0))
    if not _close(observed, expected):
        return (
            False,
            f"an object at {expected} maps to {observed}, so content was offset or repeated",
        )

    return True, (
        "the page-absolute page renders as one "
        f"{frame.width} x {frame.height} mm body at (0, 0), and its first object "
        f"stays at {expected} instead of being offset like a stock label"
    )


def renderspec_stock_grid_replication() -> tuple[bool, str]:
    """RT-102: with `stock` the layers repeat identically in every frame."""

    document = {
        "renderspec": "1.0",
        "id": "replication_probe",
        "name": "Replication Probe",
        "page": {"width": 100.0, "height": 40.0},
        "stock": {
            "width": 40.0,
            "height": 30.0,
            "rows": 1,
            "columns": 2,
            "margin_left": 10.0,
            "margin_top": 5.0,
            "horizontal_pitch": 45.0,
            "vertical_pitch": 30.0,
        },
        "layers": [
            {
                "id": "base",
                "name": "Base",
                "objects": [
                    {
                        "id": "probe",
                        "type": "rect",
                        "x": 5.0,
                        "y": 6.0,
                        "width": 10.0,
                        "height": 4.0,
                    }
                ],
            }
        ],
    }
    accepted = renderspec.parse(document)
    frames = layout.document_frames(accepted)
    if len(frames) != 2:
        return False, f"a 1 x 2 stock produced {len(frames)} bodies, expected 2"

    expected_origins = [(10.0, 5.0), (55.0, 5.0)]
    origins = [(frame.x, frame.y) for frame in frames]
    if origins != expected_origins:
        return False, f"the bodies start at {origins}, expected {expected_origins}"
    if {(frame.width, frame.height) for frame in frames} != {(40.0, 30.0)}:
        return False, "the two bodies are not the same 40 x 30 mm label"

    bounds = layout.object_bounds(accepted["layers"][0]["objects"][0])
    bodies = [
        (bounds.x + frame.x, bounds.y + frame.y, bounds.width, bounds.height) for frame in frames
    ]
    expected_bodies = [(15.0, 11.0, 10.0, 4.0), (60.0, 11.0, 10.0, 4.0)]
    if bodies != expected_bodies:
        return False, f"the object landed at {bodies}, expected {expected_bodies}"

    return True, (
        "a 1 x 2 stock renders two identical 40 x 30 mm bodies at (10, 5) and (55, 5); "
        "the object at (5, 6) in label space lands at (15, 11) and (60, 11) on the page"
    )


def stockspec_shape_clipping() -> tuple[bool, str]:
    """SS-112: a full-bleed object is clipped to the declared label shape."""

    # Each fixture is a full-bleed rect: at 0.5 mm inside the bounding box the
    # four corner probes stand in for the corner pixels the requirement names.
    observed: list[str] = []
    for name in SHAPE_FIXTURES:
        stock = _stock(STOCK_FIXTURES / "valid" / name)
        shape = stock["label"]["shape"]
        regions = clip.stock_clips(stock)
        if len(regions) != 1:
            return False, f"{name} produced {len(regions)} clips, expected 1"
        region = regions[0]
        corners = _corner_probes(region.boundary, 0.5)
        blank_edges = [
            point for point in _edge_probes(region.boundary, 0.5) if not region.contains(point)
        ]
        if blank_edges:
            return False, f"{shape}: edge midpoint {blank_edges[0]} was clipped away"
        centre = (
            region.boundary.x + region.boundary.width / 2.0,
            region.boundary.y + region.boundary.height / 2.0,
        )
        if not region.contains(centre):
            return False, f"{shape}: the label centre was clipped away"
        if shape == "rectangle":
            blank = [point for point in corners if not region.contains(point)]
            if blank:
                return False, f"rectangle: corner {blank[0]} was clipped away"
            observed.append("rectangle keeps its full box")
            continue
        inked = [point for point in corners if region.contains(point)]
        if inked:
            return False, f"{shape}: corner probe {inked[0]} still receives ink"
        observed.append(f"{shape} blanks all four corner probes")

    return True, (
        "four full-bleed fixtures: " + ", ".join(observed) + "; every edge midpoint and centre "
        "still receives ink"
    )


def renderspec_frame_clipping() -> tuple[bool, str]:
    """RT-104: each stock-grid label clips to its frame and cannot bleed."""

    frames = layout.grid_frames(
        rows=2,
        columns=2,
        margin_left=5.0,
        margin_top=10.0,
        horizontal_pitch=60.0,
        vertical_pitch=50.0,
        width=50.0,
        height=40.0,
    )
    regions = tuple(
        clip.label_clip(layout.Box(frame.x, frame.y, frame.width, frame.height)) for frame in frames
    )
    if len(regions) != 4:
        return False, f"built {len(regions)} label clips, expected 4"

    for index, region in enumerate(regions):
        box = region.boundary
        for corner in box.corners():
            if not region.contains(corner):
                return False, f"frame {index} clips its own corner {corner}"
        outside = (
            (box.x - 5.0, box.y + box.height / 2.0),
            (box.right + 5.0, box.y + box.height / 2.0),
            (box.x + box.width / 2.0, box.y - 5.0),
            (box.x + box.width / 2.0, box.bottom + 5.0),
        )
        for probe in outside:
            receivers = [other for other, r in enumerate(regions) if r.contains(probe)]
            if receivers:
                return (
                    False,
                    f"a probe 5 mm outside frame {index} still lands in clip {receivers[0]}",
                )

    return True, (
        "four labels clip to their (X, Y, 50 x 40 mm) frames and probes 5 mm outside "
        "every edge land in no label, so no content bleeds into a neighbour"
    )


CHECKS: dict[str, Any] = {
    "renderspec_coordinate_convention": coordinate_convention,
    "renderspec_forward_compatibility": forward_compatibility_mode,
    "renderspec_boundary_overflow": renderspec_boundary_overflow,
    "stockspec_frame_origins": stockspec_frame_origins,
    "stockspec_row_major_fill": stockspec_row_major_fill,
    "stockspec_declared_dimensions": stockspec_declared_dimensions,
    "stockspec_layout_ignores_timestamps": stockspec_layout_ignores_timestamps,
    "stockspec_shape_clipping": stockspec_shape_clipping,
    "renderspec_frame_clipping": renderspec_frame_clipping,
    "renderspec_page_absolute_once": renderspec_page_absolute_once,
    "renderspec_stock_grid_replication": renderspec_stock_grid_replication,
}
