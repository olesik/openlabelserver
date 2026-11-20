"""Conformance checks that drive the parser, coordinate engine and layout engine.

`CP-RS` and `CP-ST` requirements that needed a parser implementation (`CN-102`),
a configured parser mode (`CN-105`), a layout (`SS-104`, `SS-113`, `SS-115`,
`SS-118`), a label clip (`SS-112`, `RT-104`), computed object geometry
(`RS-118`), data binding (`RB-101`-`RB-104`, `RT-105`, `RT-106`) or composition
(`RT-107`-`RT-112`) were deferred until `renderer/` existed. These checks
exercise that reference implementation, the way `engine_cases.py` exercises
the calibration engine, instead of the suite's own formula.
"""

from __future__ import annotations

import copy
import json
import math
import re
import sys
import zlib
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from renderer import (  # noqa: E402
    binding,
    clip,
    composition,
    coordinates,
    layout,
    objects,
    output,
    renderspec,
)

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
    page = document["page"]
    bodies = [
        (frame.x, frame.y, frame.width, frame.height) for frame in layout.document_frames(document)
    ]
    expected = [(0.0, 0.0, page["width"], page["height"])]
    if bodies != expected:
        return False, f"the page-absolute page rendered {bodies}, expected {expected}"

    first = document["layers"][0]["objects"][0]
    anchor = (first["x"], first["y"])
    placed = coordinates.transform_point(first, (0.0, 0.0))
    if not _close(placed, anchor):
        return False, f"an object at {anchor} maps to {placed}, so content was offset or repeated"

    return True, (
        "the page-absolute document renders as one "
        f"{page['width']} x {page['height']} mm body at (0, 0), and its first object "
        f"stays at {anchor} instead of being offset like a stock label"
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
    bounds = layout.object_bounds(accepted["layers"][0]["objects"][0])
    bodies = [
        (frame.x, frame.y, frame.width, frame.height, bounds.x + frame.x, bounds.y + frame.y)
        for frame in layout.document_frames(accepted)
    ]
    expected = [
        (10.0, 5.0, 40.0, 30.0, 15.0, 11.0),
        (55.0, 5.0, 40.0, 30.0, 60.0, 11.0),
    ]
    if bodies != expected:
        return False, f"a 1 x 2 stock placed {bodies}, expected {expected}"

    return True, (
        "a 1 x 2 stock renders two identical 40 x 30 mm bodies at (10, 5) and (55, 5); "
        "the object at (5, 6) in label space lands at (15, 11) and (60, 11) on the page"
    )


GRID = {
    "width": 40.0,
    "height": 30.0,
    "rows": 2,
    "columns": 3,
    "margin_left": 10.0,
    "margin_top": 10.0,
    "horizontal_pitch": 55.0,
    "vertical_pitch": 40.0,
}


def _data_document(records: list[dict[str, Any]]) -> dict[str, Any]:
    """A 2 x 3 stock whose single text object prints the record's `n`."""

    return {
        "renderspec": "1.0",
        "id": "data_probe",
        "name": "Data Probe",
        "page": {"width": 200.0, "height": 100.0},
        "stock": dict(GRID),
        "layers": [
            {
                "id": "base",
                "name": "Base",
                "objects": [
                    {"id": "probe", "type": "text", "x": 2.0, "y": 2.0, "content": "{{n}}"}
                ],
            }
        ],
        "data": records,
    }


def _contents(document: dict[str, Any]) -> list[str]:
    """Every template-bearing `content`, through groups."""

    found: list[str] = []

    def walk(objects: list[dict[str, Any]]) -> None:
        for obj in objects:
            if obj.get("type") in binding.CONTENT_TYPES:
                found.append(obj["content"])
            walk(obj.get("objects", ()))

    for layer in document["layers"]:
        walk(layer["objects"])
    return found


def renderspec_placeholder_substitution() -> tuple[bool, str]:
    """RB-101: `{{variable}}` resolves in text, barcode and qrcode content."""

    sheet = renderspec.load(EXAMPLES / "sheet_labels.json")
    second = binding.bind(sheet, sheet["data"][1])
    expected_sheet = [
        "Bob Jones",
        "789 Pine Road",
        "Shelbyville, IL 62565",
    ]
    if _contents(second) != expected_sheet:
        return False, f"record 1 of sheet_labels rendered {_contents(second)}"

    codes = renderspec.load(EXAMPLES / "barcode_label.json")
    record = {"product_name": "Widget", "price": 9.5, "sku": "ABC-123"}
    observed = _contents(binding.bind(codes, record))
    expected_codes = [
        "Widget",
        "$ 9.5",
        "SKU: ABC-123",
        "ABC-123",
        "https://openlabelserver.org/products/ABC-123",
        "SCAN TO VERIFY",
    ]
    if observed != expected_codes:
        return False, f"the barcode example rendered {observed}, expected {expected_codes}"

    return True, (
        "text, barcode and qrcode content resolve: record 1 of the sheet renders "
        f"{expected_sheet}, and one sku record renders "
        "https://openlabelserver.org/products/ABC-123"
    )


def renderspec_unresolved_placeholder() -> tuple[bool, str]:
    """RB-102: an unresolved variable resolves to the empty string."""

    document = _data_document([{}])
    document["layers"][0]["objects"][0]["content"] = "{{missing}} tail"
    accepted = renderspec.parse(document)
    bound = binding.bind(accepted, accepted["data"][0])
    if _contents(bound) != [" tail"]:
        return False, f"an unresolved placeholder rendered {_contents(bound)}"
    if renderspec.parse(bound) != bound:
        return False, "the bound document no longer validates"

    return True, "`{{missing}} tail` renders ` tail`, and the document still validates"


def renderspec_value_serialization() -> tuple[bool, str]:
    """RB-103: numeric and boolean values serialise to strings."""

    document = _data_document([{"n": 3}])
    document["layers"][0]["objects"][0]["content"] = "{{n}}|{{flag}}|{{price}}"
    accepted = renderspec.parse(document)
    bound = binding.bind(accepted, {"n": 3, "flag": True, "price": 1.5})
    if _contents(bound) != ["3|true|1.5"]:
        return False, f"numbers and booleans rendered {_contents(bound)}"

    return True, "the integer 3, the boolean true and 1.5 serialise as `3|true|1.5`"


def renderspec_content_fields_only() -> tuple[bool, str]:
    """RB-104: substitution does not touch properties other than content.

    IN-7 resolves the source sentence: only the three `content` fields are
    templates, so `path.d` keeps its `{{x}}` literally.
    """

    document = _data_document([{"n": 7}])
    objects = document["layers"][0]["objects"]
    objects.append(
        {
            "id": "outline",
            "type": "path",
            "x": 0.0,
            "y": 0.0,
            "d": "M 0 0 L {{n}} 10 Z",
        }
    )
    accepted = renderspec.parse(document)
    bound = binding.bind(accepted, accepted["data"][0])
    if _contents(bound) != ["7"]:
        return False, f"the text content rendered {_contents(bound)}"
    if bound["layers"][0]["objects"][1]["d"] != "M 0 0 L {{n}} 10 Z":
        return False, f"path.d became {bound['layers'][0]['objects'][1]['d']!r}"
    if accepted["layers"][0]["objects"][0]["content"] != "{{n}}":
        return False, "binding mutated the source document"

    return True, (
        "text content becomes `7` while `path.d` keeps `{{n}}` literally, "
        "and the source document is unchanged"
    )


def renderspec_row_major_records() -> tuple[bool, str]:
    """RT-105: data records fill frames row-major, column index first."""

    accepted = renderspec.parse(_data_document([{"n": index} for index in range(6)]))
    slots = binding.page_slots(accepted)
    if len(slots) != 1:
        return False, f"6 records over 6 frames produced {len(slots)} page(s)"

    frames = layout.document_frames(accepted)
    observed = [
        (slot["n"], frame.column, frame.row, frame.x, frame.y)
        for slot, frame in zip(slots[0], frames)
    ]
    expected = [
        (0, 0, 0, 10.0, 10.0),
        (1, 1, 0, 65.0, 10.0),
        (2, 2, 0, 120.0, 10.0),
        (3, 0, 1, 10.0, 50.0),
        (4, 1, 1, 65.0, 50.0),
        (5, 2, 1, 120.0, 50.0),
    ]
    if observed != expected:
        return False, f"records landed as {observed}, expected {expected}"

    return True, (
        "6 records fill the 2 x 3 grid row-major: record i lands at "
        "(i mod 3, floor(i / 3)) with the matching frame origin"
    )


def renderspec_record_pagination() -> tuple[bool, str]:
    """RT-106: surplus records add pages, spare frames stay empty."""

    seven = renderspec.parse(_data_document([{"n": index} for index in range(7)]))
    pages = binding.page_slots(seven)
    if [len(page) for page in pages] != [6, 6]:
        return False, f"7 records over 6 frames produced pages of {[len(p) for p in pages]}"
    if [slot["n"] for slot in pages[0]] != [0, 1, 2, 3, 4, 5]:
        return False, f"the first page carries {pages[0]}"
    if pages[1][0]["n"] != 6 or pages[1][1:] != (None,) * 5:
        return False, f"the second page carries {pages[1]}, expected record 6 then five empty"

    two = renderspec.parse(_data_document([{"n": 0}, {"n": 1}]))
    (page,) = binding.page_slots(two)
    if page[2:] != (None,) * 4 or [slot["n"] for slot in page[:2]] != [0, 1]:
        return False, f"2 records over 6 frames produced {page}"

    # `data` is OPTIONAL (Section 4) and Section 10.1 rule 2 resolves a missing
    # record to "", so no records still render the one page, entirely empty.
    without = _data_document([])
    del without["data"]
    for label, sheet in (("omitted", without), ("empty", _data_document([]))):
        slots = binding.page_slots(renderspec.parse(sheet))
        if slots != ((None,) * 6,):
            return False, f"`data` {label} produced {slots}, expected one page of six empty slots"

    return True, (
        "7 records over 6 frames render two pages, the second carrying record 6 and "
        "five empty slots; 2 records leave four empty frames on the single page; "
        "no records still render that page with all six frames empty"
    )


def _composition_document(layers: list[dict[str, Any]]) -> dict[str, Any]:
    """A 100 x 50 mm page-absolute document carrying `layers`."""

    return {
        "renderspec": "1.0",
        "id": "composition_probe",
        "name": "Composition Probe",
        "page": {"width": 100.0, "height": 50.0},
        "layers": layers,
    }


def _layer(layer_id: str, objects: list[dict[str, Any]], **props: Any) -> dict[str, Any]:
    """A named layer carrying `objects` and the Section 6 properties in `props`."""

    return {"id": layer_id, "name": layer_id.title(), "objects": objects, **props}


def _rect(object_id: str, **props: Any) -> dict[str, Any]:
    """A 10 x 10 mm rect unless the case overrides its geometry."""

    return {"id": object_id, "type": "rect", "width": 10.0, "height": 10.0, **props}


def _text(object_id: str, content: str, **props: Any) -> dict[str, Any]:
    return {"id": object_id, "type": "text", "content": content, **props}


def _group(object_id: str, objects: list[dict[str, Any]], **props: Any) -> dict[str, Any]:
    """A group of Section 8.2.12 carrying `objects` and its own transform, visibility and opacity."""

    return {"id": object_id, "type": "group", "objects": objects, **props}


def _probe_document(objects: list[dict[str, Any]], **layer_props: Any) -> dict[str, Any]:
    """A composition document whose single `base` layer carries `objects`."""

    return _composition_document([_layer("base", objects, **layer_props)])


def renderspec_hidden_suppresses_drawing() -> tuple[bool, str]:
    """RT-107: `visible: false` on a layer, group or object suppresses drawing."""

    accepted = renderspec.parse(
        _composition_document(
            [
                _layer("hidden", [_rect("hidden_layer_rect")], visible=False),
                _layer(
                    "base",
                    [
                        _text("shown", "kept"),
                        _rect("hidden_rect", visible=False),
                        _group("hidden_group", [_text("inside", "gone")], visible=False),
                    ],
                ),
            ]
        )
    )
    drawn = composition.draw_list(accepted)
    ids = [entry.object["id"] for entry in drawn]
    if ids != ["shown"]:
        return False, f"the draw list carries {ids}"
    if drawn[0].path != "layers.1.objects.0":
        return False, f"the surviving object sits at {drawn[0].path}"

    return True, (
        "a hidden layer, a hidden object and a hidden group all drop out, leaving "
        "only the visible text object to draw"
    )


def renderspec_effective_alpha() -> tuple[bool, str]:
    """RT-108: layer opacity multiplies objects and ancestor groups recursively."""

    accepted = renderspec.parse(
        _probe_document(
            [
                _rect("direct", opacity=0.5),
                _group("shade", [_rect("nested", opacity=0.5)], opacity=0.5),
            ],
            opacity=0.5,
        )
    )
    alphas = {entry.object["id"]: entry.alpha for entry in composition.draw_list(accepted)}
    if alphas.get("direct") != 0.25:
        return False, f"layer 0.5 with object 0.5 rendered at alpha {alphas.get('direct')}"
    if alphas.get("nested") != 0.125:
        return (
            False,
            f"layer 0.5, group 0.5 and object 0.5 rendered at alpha {alphas.get('nested')}",
        )

    return True, (
        "layer 0.5 with object 0.5 renders at 0.25, and through a 0.5 group at 0.125 "
        "as the product of the chain"
    )


def renderspec_transform_product() -> tuple[bool, str]:
    """RT-109: M = M_parent x T(x, y) x R(t) x S(sx, sy) x M_custom."""

    accepted = renderspec.parse(
        _probe_document(
            [
                _rect(
                    "probe",
                    width=10.0,
                    height=20.0,
                    x=10.0,
                    y=20.0,
                    rotation=90.0,
                    scale_x=2.0,
                    scale_y=3.0,
                    transforms=[{"type": "translate", "x": 5.0, "y": 5.0}],
                )
            ]
        )
    )
    (entry,) = composition.draw_list(accepted)
    # M_custom is the innermost factor, as the product says: (1, 0) moves by the
    # custom (5, 5) to (6, 5), scales to (12, 15), rotates to (-15, 12) and then
    # takes the anchor (10, 20) to (-5, 32). Scaling first would give (18, 35).
    expected = (-5.0, 32.0)
    observed = entry.matrix.apply((1.0, 0.0))
    if not _close(observed, expected):
        return False, f"local (1, 0) mapped to {observed}, expected {expected}"

    return True, (
        "local (1, 0) maps to (-5, 32) through T(10, 20) x R(90) x S(2, 3) x "
        "T(5, 5), where the custom translate acts on the object's own coordinates "
        "first and the anchor last"
    )


def renderspec_rotation_about_anchor() -> tuple[bool, str]:
    """RT-110: rotation is clockwise about (x, y), so X turns toward Y."""

    accepted = renderspec.parse(
        _probe_document([_rect("probe", width=10.0, height=20.0, x=30.0, y=40.0, rotation=90.0)])
    )
    (entry,) = composition.draw_list(accepted)
    if not _close(entry.matrix.apply((0.0, 0.0)), (30.0, 40.0)):
        return False, "the anchor did not stay at its own (30, 40) position"
    corner = entry.matrix.apply((10.0, 0.0))
    if not _close(corner, (30.0, 50.0)):
        return False, f"the anchor-relative corner landed at {corner}, not (30, 50)"

    bounds = layout.object_bounds(entry.object)
    if bounds is None or not _close((bounds.width, bounds.height), (20.0, 10.0)):
        return False, f"the rotated 10 x 20 rect spans {bounds}"

    return True, (
        "a 10 x 20 mm rect at (30, 40) rotated 90 degrees spans 20 x 10 mm, keeps "
        "its anchor at (30, 40) and moves local (10, 0) to (30, 50), toward +Y"
    )


def renderspec_transform_array_order() -> tuple[bool, str]:
    """RT-111: `transforms` entries apply sequentially in array order."""

    translate = {"type": "translate", "x": 5.0, "y": 0.0}
    rotate = {"type": "rotate", "angle": 90.0}

    def probe(transforms: list[dict[str, Any]]) -> tuple[float, float]:
        accepted = renderspec.parse(_probe_document([_rect("probe", transforms=transforms)]))
        (entry,) = composition.draw_list(accepted)
        return entry.matrix.apply((10.0, 0.0))

    # M_custom is the cumulative product in array order, so each entry is
    # expressed in the frame the previous entries establish.
    forward = probe([translate, rotate])
    reversed_order = probe([rotate, translate])
    if not _close(forward, (5.0, 10.0)):
        return False, f"translate then rotate mapped (10, 0) to {forward}, expected (5, 10)"
    if not _close(reversed_order, (0.0, 15.0)):
        return False, f"rotate then translate mapped (10, 0) to {reversed_order}, expected (0, 15)"

    return True, (
        "translate then rotate maps (10, 0) to (5, 10) while the reversed array maps "
        "it to (0, 15), so the array order decides the composition"
    )


def renderspec_parent_offsets() -> tuple[bool, str]:
    """RT-112: `x` and `y` are offsets from the containing group."""

    accepted = renderspec.parse(
        _probe_document([_group("container", [_rect("probe", x=10.0, y=10.0)], x=5.0, y=5.0)])
    )
    (entry,) = composition.draw_list(accepted)
    if entry.path != "layers.0.objects.0.objects.0":
        return False, f"the nested rect sits at {entry.path}"
    origin = entry.matrix.apply((0.0, 0.0))
    if not _close(origin, (15.0, 15.0)):
        return False, f"a rect at (10, 10) in a group at (5, 5) landed at {origin}"

    return True, "a rect at (10, 10) inside a group at (5, 5) lands at (15, 15)"


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


def renderspec_label_frame_origin() -> tuple[bool, str]:
    """RT-103: frame origins are `margin + index x pitch` on both axes."""

    frames = layout.grid_frames(
        rows=2,
        columns=3,
        margin_left=4.5,
        margin_top=12.7,
        horizontal_pitch=66.7,
        vertical_pitch=25.4,
        width=50.0,
        height=40.0,
    )
    for frame in frames:
        expected_x = 4.5 + frame.column * 66.7
        expected_y = 12.7 + frame.row * 25.4
        if abs(frame.x - expected_x) > 1e-6 or abs(frame.y - expected_y) > 1e-6:
            return False, (
                f"frame ({frame.column}, {frame.row}) sits at ({frame.x}, {frame.y}), "
                f"expected ({expected_x}, {expected_y})"
            )

    return True, (
        "all six frames of a 2 x 3 grid follow X = 4.5 + c x 66.7 and "
        "Y = 12.7 + r x 25.4 within 1e-6 mm"
    )


def renderspec_font_size_points() -> tuple[bool, str]:
    """RT-113: `font_size` is in points, at 1 pt = 25.4/72 mm."""

    accepted = renderspec.parse(
        _probe_document(
            [_text("ten_point", "Open Label", font_size=10.0), _text("default", "Open Label")]
        )
    )
    ten_point, default = (
        objects.primitive(entry.object) for entry in composition.draw_list(accepted)
    )
    if not isinstance(ten_point, objects.Text) or not isinstance(default, objects.Text):
        return False, "the two text objects did not resolve to text primitives"
    expected = 10.0 * 25.4 / 72.0
    if abs(ten_point.size - expected) > 1e-9:
        return False, f"a 10 pt run measures {ten_point.size} mm, expected {expected}"
    if abs(default.size - expected) > 1e-9:
        return False, f"an omitted font_size measures {default.size} mm, expected {expected}"

    return True, (
        "a 10 pt run, and a run that omits font_size, both have a nominal em size "
        f"of {expected:.4f} mm on the page"
    )


def renderspec_page_margin_ignored() -> tuple[bool, str]:
    """RT-114: `page.margin` neither translates nor clips content (IN-2)."""

    def placement(margin: float | None) -> tuple[Any, ...]:
        document = _probe_document([_rect("corner", x=0.0, y=0.0)])
        if margin is not None:
            document["page"]["margin"] = {
                "left": margin,
                "top": margin,
                "right": margin,
                "bottom": margin,
            }
        accepted = renderspec.parse(document)
        (frame,) = layout.document_frames(accepted)
        (entry,) = composition.draw_list(accepted)
        return (
            (frame.x, frame.y),
            layout.active_boundary(accepted),
            entry.matrix.apply((0.0, 0.0)),
            tuple(warning.render() for warning in layout.overflow_warnings(accepted)),
        )

    unmargined, margined = placement(None), placement(10.0)
    if margined != unmargined:
        return False, f"a 10 mm margin changed the placement: {margined} against {unmargined}"
    if unmargined[3]:
        return False, f"a 10 x 10 mm rect at (0, 0) already overflows the page: {unmargined[3]}"

    return True, (
        "a rect at (0, 0) keeps its frame origin, active boundary, page point and "
        "empty overflow report when the page declares a 10 mm margin"
    )


def renderspec_text_bounds_validation() -> tuple[bool, str]:
    """RT-115: `align` and `wrap` need `width`, `valign` needs `height` (IN-1)."""

    def rejection(**props: Any) -> str:
        try:
            renderspec.parse(_probe_document([_text("run", "centred", **props)]))
        except renderspec.RenderSpecError as exc:
            return "; ".join(diagnostic.render() for diagnostic in exc.diagnostics)
        return ""

    for props, path in (
        ({"align": "center"}, "layers.0.objects.0.align"),
        ({"wrap": True}, "layers.0.objects.0.wrap"),
        ({"valign": "middle"}, "layers.0.objects.0.valign"),
    ):
        detail = rejection(**props)
        if not detail:
            return False, f"{props} without its bounding box was accepted"
        if path not in detail:
            return False, f"{props} was rejected without naming {path}: {detail}"

    renderspec.parse(
        _probe_document(
            [
                _text(
                    "run",
                    "centred",
                    width=30.0,
                    height=6.0,
                    align="center",
                    valign="middle",
                    wrap=True,
                )
            ]
        )
    )
    return True, (
        "align, wrap and valign are rejected when their width or height is "
        "missing, and accepted once the bounding box is declared"
    )


def renderspec_code_extents() -> tuple[bool, str]:
    """RT-116: barcode and qrcode draw at their declared millimetres."""

    accepted = renderspec.parse(
        _probe_document(
            [
                {
                    "id": "sku_barcode",
                    "type": "barcode",
                    "content": "ABC-123",
                    "symbology": "code128",
                    "width": 42.0,
                    "height": 12.0,
                },
                {
                    "id": "link_qrcode",
                    "type": "qrcode",
                    "content": "https://example.org",
                    "size": 18.0,
                },
            ]
        )
    )
    barcode, qrcode = (objects.primitive(entry.object) for entry in composition.draw_list(accepted))
    if not isinstance(barcode, objects.Barcode):
        return False, "the barcode did not resolve to a barcode primitive"
    if (barcode.width, barcode.height) != (42.0, 12.0):
        return False, f"the barcode draws at {barcode.width} x {barcode.height} mm"
    if barcode.draw_text is not True:
        return False, "draw_text did not default to true"
    if not isinstance(qrcode, objects.Qrcode):
        return False, "the qrcode did not resolve to a qrcode primitive"
    if qrcode.size != 18.0:
        return False, f"the qrcode draws at {qrcode.size} mm"

    return True, (
        "a 42 x 12 mm barcode keeps its pattern extents with draw_text defaulting "
        "to true, and an 18 mm qrcode spans 18 x 18 mm"
    )


def _renderable_example() -> dict[str, Any]:
    """The published page-absolute example: text, a rounded rect, no plugins needed."""

    return renderspec.load(EXAMPLES / "simple_label.json")


def _first_stream(pdf: bytes) -> bytes:
    """The first content stream of a PDF, decompressed."""

    start = pdf.index(b"stream\n") + len(b"stream\n")
    end = pdf.index(b"\nendstream", start)
    return zlib.decompress(pdf[start:end])


def renderspec_output_timestamps_are_inert() -> tuple[bool, str]:
    """RS-119: `created_at` and `updated_at` never reach the artifact."""

    document = _renderable_example()
    stamped = dict(document, created_at="2020-01-01T00:00:00Z", updated_at="2026-11-20T00:00:00Z")
    for target in ("pdf", "postscript"):
        if output.artifact(stamped, format=target) != output.artifact(document, format=target):
            return False, f"the {target} artifact changed with the document timestamps"

    return True, (
        "the PDF and PostScript artifacts are byte-identical with two different "
        "created_at / updated_at pairs"
    )


def renderspec_output_page_size() -> tuple[bool, str]:
    """RO-109: the artifact page size equals the declared page within 0.01 mm."""

    document = _renderable_example()
    page = document["page"]
    media = re.search(rb"/MediaBox \[0 0 ([0-9.]+) ([0-9.]+)\]", output.artifact(document))
    if media is None:
        return False, "the PDF carries no /MediaBox"
    width = float(media.group(1)) * 25.4 / 72.0
    height = float(media.group(2)) * 25.4 / 72.0
    if abs(width - page["width"]) > 0.01 or abs(height - page["height"]) > 0.01:
        return False, (
            f"the MediaBox measures {width:.4f} x {height:.4f} mm, "
            f"expected {page['width']} x {page['height']}"
        )

    program = output.artifact(document, format="postscript")
    bounding = re.search(rb"%%BoundingBox: 0 0 (\d+) (\d+)", program)
    if bounding is None:
        return False, "the PostScript program carries no %%BoundingBox"
    outer = (math.ceil(width * 72.0 / 25.4), math.ceil(height * 72.0 / 25.4))
    if (int(bounding.group(1)), int(bounding.group(2))) != outer:
        return False, (
            f"the PostScript bounding box is {bounding.group(1).decode()} x "
            f"{bounding.group(2).decode()} pt, expected {outer} from the page geometry"
        )

    return True, (
        f"a {page['width']} x {page['height']} mm page is a {width:.4f} x {height:.4f} mm "
        f"MediaBox and a {outer[0]} x {outer[1]} pt bounding box"
    )


def renderspec_output_is_vector() -> tuple[bool, str]:
    """RO-102: text stays text and shapes stay path operators."""

    pdf = output.artifact(_renderable_example())
    content = _first_stream(pdf)
    missing = [
        token for token in (b"BT", b"Tf", b"Tj", b" m", b" l", b" c") if token not in content
    ]
    if missing:
        return False, f"the content stream lacks {missing}"
    if b"/Subtype /Image" in pdf:
        return False, "a shape-only document embedded a raster image"

    return True, (
        "the content stream sets text with BT/Tf/Tj and shapes with m/l/c operators, "
        "and the artifact carries no image XObject"
    )


def renderspec_output_has_no_timestamps() -> tuple[bool, str]:
    """RO-110: no creation or modification timestamp, no time-derived identifier."""

    document = _renderable_example()
    pdf = output.artifact(document)
    program = output.artifact(document, format="postscript")
    present = [
        marker
        for marker in (b"/CreationDate", b"/ModDate", b"%%CreationDate")
        if marker in pdf or marker in program
    ]
    if present:
        return False, f"an artifact carries {present}"
    if b"/ID" in pdf[pdf.rindex(b"endstream") :]:
        return False, "the PDF trailer carries a document identifier"

    return True, (
        "neither artifact carries /CreationDate, /ModDate or %%CreationDate, and the "
        "PDF trailer declares no /ID"
    )


def renderspec_output_defaults() -> tuple[bool, str]:
    """RO-106: an omitted `output` object yields sRGB, PDF 1.4 and compression."""

    document = _renderable_example()
    defaulted = {key: value for key, value in document.items() if key != "output"}
    artifact = output.artifact(defaulted)
    if not artifact.startswith(b"%PDF-1.4"):
        return False, "the default format is not PDF 1.4"
    if b"/Filter /FlateDecode" not in artifact:
        return False, "stream compression is off by default"
    if b" rg" not in _first_stream(artifact):
        return False, "the default colour space is not sRGB"

    return True, (
        "without `output` the artifact is a compressed PDF 1.4 whose content stream "
        "uses sRGB colour operators"
    )


def renderspec_output_is_repeatable() -> tuple[bool, str]:
    """DT-101: two renders of one document are byte-identical."""

    document = _renderable_example()
    for target in ("pdf", "postscript"):
        if output.artifact(document, format=target) != output.artifact(document, format=target):
            return False, f"two {target} renders of one document differ"

    return True, "two PDF renders and two PostScript renders are byte-identical"


def renderspec_output_rejects_invalid_document() -> tuple[bool, str]:
    """RO-101: a document that fails validation produces no artifact."""

    document = json.loads((FIXTURES / "invalid" / "missing_page.json").read_text(encoding="utf-8"))
    try:
        artifact = output.artifact(document)
    except renderspec.RenderSpecError as exc:
        return True, f"the fixture is rejected before rendering: {exc.diagnostics[0].render()}"

    return False, f"the invalid document produced {len(artifact)} bytes"


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
    "renderspec_placeholder_substitution": renderspec_placeholder_substitution,
    "renderspec_unresolved_placeholder": renderspec_unresolved_placeholder,
    "renderspec_value_serialization": renderspec_value_serialization,
    "renderspec_content_fields_only": renderspec_content_fields_only,
    "renderspec_row_major_records": renderspec_row_major_records,
    "renderspec_record_pagination": renderspec_record_pagination,
    "renderspec_hidden_suppresses_drawing": renderspec_hidden_suppresses_drawing,
    "renderspec_effective_alpha": renderspec_effective_alpha,
    "renderspec_transform_product": renderspec_transform_product,
    "renderspec_rotation_about_anchor": renderspec_rotation_about_anchor,
    "renderspec_transform_array_order": renderspec_transform_array_order,
    "renderspec_parent_offsets": renderspec_parent_offsets,
    "renderspec_label_frame_origin": renderspec_label_frame_origin,
    "renderspec_font_size_points": renderspec_font_size_points,
    "renderspec_page_margin_ignored": renderspec_page_margin_ignored,
    "renderspec_text_bounds_validation": renderspec_text_bounds_validation,
    "renderspec_code_extents": renderspec_code_extents,
    "renderspec_output_timestamps_are_inert": renderspec_output_timestamps_are_inert,
    "renderspec_output_page_size": renderspec_output_page_size,
    "renderspec_output_is_vector": renderspec_output_is_vector,
    "renderspec_output_has_no_timestamps": renderspec_output_has_no_timestamps,
    "renderspec_output_defaults": renderspec_output_defaults,
    "renderspec_output_is_repeatable": renderspec_output_is_repeatable,
    "renderspec_output_rejects_invalid_document": renderspec_output_rejects_invalid_document,
}
