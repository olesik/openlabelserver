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

import base64
import copy
import hashlib
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zlib
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from renderer import (  # noqa: E402
    assets,
    barcode,
    binding,
    clip,
    composition,
    coordinates,
    layout,
    objects,
    output,
    pdf417,
    qrcode,
    renderspec,
)
from renderer.plan import Fill, Image, Stroke, Text  # noqa: E402

import barcode_reader  # noqa: E402
import qr_reader  # noqa: E402

EXAMPLES = ROOT / "specs" / "renderspec" / "examples"
GOLDEN = ROOT / "tests" / "regression"
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


def renderspec_group_inheritance() -> tuple[bool, str]:
    """RT-117: group children inherit the group's transform, visibility and opacity."""

    accepted = renderspec.parse(
        _probe_document(
            [
                _group(
                    "outer",
                    [
                        _rect("direct", x=10.0, y=10.0),
                        _group(
                            "inner",
                            [
                                _rect("deep"),
                                _group("hidden", [_text("dropped", "gone")], visible=False),
                            ],
                            x=10.0,
                            rotation=90.0,
                            opacity=0.5,
                        ),
                    ],
                    x=5.0,
                    y=5.0,
                    rotation=90.0,
                    opacity=0.5,
                )
            ]
        )
    )
    drawn = composition.draw_list(accepted)
    paths = [entry.path for entry in drawn]
    expected_paths = [
        "layers.0.objects.0.objects.0",
        "layers.0.objects.0.objects.1.objects.0",
    ]
    if paths != expected_paths:
        return False, f"the draw list carries {paths}"

    alphas = {entry.object["id"]: entry.alpha for entry in drawn}
    if alphas.get("direct") != 0.5:
        return False, f"the 0.5 group rendered its child at alpha {alphas.get('direct')}"
    if alphas.get("deep") != 0.25:
        return (
            False,
            f"the two nested 0.5 groups rendered their child at alpha {alphas.get('deep')}",
        )

    direct, deep = drawn
    # The outer group turns its own coordinates 90 degrees clockwise: the child
    # at (10, 10) lands at (-5, 15) and its local (10, 0) corner at (-5, 25).
    if not _close(direct.matrix.apply((0.0, 0.0)), (-5.0, 15.0)):
        return False, f"the child at (10, 10) landed at {direct.matrix.apply((0.0, 0.0))}"
    if not _close(direct.matrix.apply((10.0, 0.0)), (-5.0, 25.0)):
        corner = direct.matrix.apply((10.0, 0.0))
        return False, f"the child's local (10, 0) corner landed at {corner}, not (-5, 25)"
    # The inner group adds its own translate and rotation inside the outer one.
    if not _close(deep.matrix.apply((0.0, 0.0)), (5.0, 15.0)):
        return False, f"the grandchild landed at {deep.matrix.apply((0.0, 0.0))}, not (5, 15)"

    return True, (
        "a group at (5, 5) rotated 90 degrees and set to 0.5 opacity carries its child "
        "to (-5, 15) at alpha 0.5, a group nested inside it carries its grandchild to "
        "(5, 15) at alpha 0.25, and a hidden inner group draws nothing"
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


def _flate_streams(pdf: bytes) -> list[tuple[bytes, bytes]]:
    """Every `/Filter /FlateDecode` stream in a PDF, as compressed and inflated bytes."""

    streams: list[tuple[bytes, bytes]] = []
    start = 0
    while True:
        marker = pdf.find(b"/Filter /FlateDecode", start)
        if marker < 0:
            return streams
        body = pdf.index(b"stream\n", marker) + len(b"stream\n")
        end = pdf.index(b"\nendstream", body)
        raw = pdf[body:end]
        streams.append((raw, zlib.decompress(raw)))
        start = end


def renderspec_compression_is_deterministic() -> tuple[bool, str]:
    """DT-104: compressed streams repeat exactly and carry no time or environment."""

    document = _renderable_example()
    pinned = dict(document, output={**(document.get("output") or {}), "compress": True})

    first = output.artifact(pinned)
    second = output.artifact(pinned)
    if first != second:
        return False, "two renders of one compressed document differ"

    streams = _flate_streams(first)
    if not streams:
        return False, "the artifact carries no deflate stream"
    if _flate_streams(second) != streams:
        return False, "two renders of one compressed document carry different streams"

    content = b"".join(inflated for _raw, inflated in streams)
    metadata = [
        marker
        for marker in (b"/CreationDate", b"/ModDate", b"%%CreationDate")
        if marker in first or marker in content
    ]
    if metadata:
        return False, f"the artifact or its operators carry {metadata}"

    stamps = [
        value
        for value in (document.get("created_at"), document.get("updated_at"))
        if value and value.encode("ascii") in content
    ]
    if stamps:
        return False, f"a decompressed stream carries the document timestamp(s) {stamps}"

    paths = [
        value.decode()
        for value in {str(ROOT).encode(), os.getcwd().encode()}
        if value and value in content
    ]
    if paths:
        return False, f"a decompressed stream names the environment path(s) {paths}"

    headers = {raw[:2] for raw, _inflated in streams}
    if any(header[1] & 0x20 for header in headers):
        return False, f"a deflate stream declares a preset dictionary: {sorted(headers)}"

    return True, (
        f"two renders of one compressed document are byte-identical, and its "
        f"{len(streams)} deflate stream(s), {len(content)} bytes of operators in all, "
        "carry no creation or modification stamp, neither of the document's own "
        "timestamps, no repository or working-directory path, and no preset dictionary"
    )


@contextmanager
def _frozen_sources(stamp: float, fill: int) -> Iterator[None]:
    """Pin the clock and the random source a writer could take an identifier from."""

    real_time, real_ns, real_urandom = time.time, time.time_ns, os.urandom
    time.time = lambda: stamp
    time.time_ns = lambda: int(stamp * 1_000_000_000)
    os.urandom = lambda size: bytes([fill]) * size
    try:
        yield
    finally:
        time.time, time.time_ns, os.urandom = real_time, real_ns, real_urandom


def renderspec_identifiers_are_content_derived() -> tuple[bool, str]:
    """DT-105: no identifier is random or time-derived; identifiers follow content."""

    program = (FIXTURES / "fonts" / "probe.ttf").read_bytes()
    source = "data:font/ttf;base64," + base64.b64encode(program).decode("ascii")

    def document(content: str) -> dict[str, Any]:
        listed = _probe_document(
            [_text("run", content, x=4.0, y=8.0, font_family="Probe Sans", font_size=10.0)]
        )
        listed["fonts"] = [
            {
                "family": "Probe Sans",
                "variants": [{"style": "normal", "weight": "normal", "source": source}],
            }
        ]
        return listed

    def rendered(content: str, stamp: float, fill: int) -> tuple[bytes, str | None]:
        with _frozen_sources(stamp, fill):
            artifact = output.artifact(renderspec.parse(document(content)))
        tagged = re.search(rb"/BaseFont /([A-Z]{6})\+ProbeSans-Regular", artifact)
        return artifact, tagged.group(1).decode() if tagged else None

    # The same glyphs at a 2023 clock with zero-filled randomness and at a 2039
    # clock with 0xFF-filled randomness: an identifier taken from either source
    # moves the bytes.
    first, first_tag = rendered("AB", 1_700_000_000.0, 0x00)
    second, second_tag = rendered("AB", 2_200_000_000.0, 0xFF)
    if first_tag is None or second_tag is None:
        return False, "the artifact carries no subset-tagged base font"
    if first != second:
        return False, (
            "the artifact changed with the clock and the random source: "
            f"{hashlib.sha256(first).hexdigest()[:16]} against "
            f"{hashlib.sha256(second).hexdigest()[:16]}"
        )
    if first_tag != second_tag:
        return False, f"the same content is tagged {first_tag} once and {second_tag} once"

    other, other_tag = rendered("A", 1_700_000_000.0, 0x00)
    if other_tag is None or other_tag == first_tag:
        return False, (
            f"a smaller character set keeps the tag {first_tag}, so the tag does not "
            "derive from the content"
        )

    return True, (
        f"the same glyphs are tagged {first_tag} at a 2023 clock with zero-filled "
        f"randomness and at a 2039 clock with 0xFF-filled randomness, and a smaller "
        f"character set is tagged {other_tag}"
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


# How far a PDF and its PostScript rendering may disagree on an edge: hinting
# and rounding move each one by a fraction of a point, a layout error does not.
RENDER_TOLERANCE = 1.0

# The palette check renders at 288 dpi, where each quadrant of the 8 mm picture
# spans dozens of device pixels: a sample reads one colour rather than a blend.
PIXEL_DPI = 288
PIXEL_MM = 25.4 / PIXEL_DPI
PIXEL_TOLERANCE = 2


def _ghostscript() -> str | None:
    """The Ghostscript executable that renders the published artifacts."""

    for candidate in (os.environ.get("OPENLABEL_GS"), "gs", "gswin64c", "gswin32c"):
        if candidate and shutil.which(candidate):
            return candidate
    return None


def _rendered_box(executable: str, artifact: Path) -> tuple[float, ...] | None:
    """The extent Ghostscript paints for one artifact, or None when it rejects it."""

    result = subprocess.run(
        [executable, "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER", "-sDEVICE=bbox", str(artifact)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    match = re.search(r"%%HiResBoundingBox: (\S+) (\S+) (\S+) (\S+)", result.stderr)
    if result.returncode != 0 or match is None:
        return None
    return tuple(float(value) for value in match.groups())


def renderspec_golden_artifacts() -> tuple[bool, str]:
    """RO-111: published PDF and PostScript artifacts match their digests.

    The artifacts live under `tests/regression/` (ConformanceSpec Section 4.2)
    with the exact byte count and SHA-256 digest of each: a base-14 stock label
    whose bytes pin placement and resource order, and a registered-face document
    whose bytes pin the embedded subset, the `/W` widths, the `/ToUnicode` CMap
    and the Type 42 prolog. The check reads the committed bytes, verifies them
    against the manifest, re-renders each document and requires the result to be
    byte-identical, so a change names the artifact that moved. Each artifact
    is then rendered with Ghostscript: byte-identical output can still be a
    page no interpreter draws, so the PostScript artifact has to paint where
    the PDF of the same document paints.
    """

    manifest = json.loads((GOLDEN / "artifacts.json").read_text(encoding="utf-8"))
    if manifest.get("requirement") != "RO-111":
        return False, "artifacts.json does not publish RO-111"
    entries = manifest.get("artifacts") or ()
    if not entries:
        return False, "the manifest publishes no artifacts"
    by_document: dict[str, set[str]] = {}
    for entry in entries:
        by_document.setdefault(entry["document"], set()).add(entry["format"])
    for document_path, formats in by_document.items():
        if formats != {"pdf", "postscript"}:
            return False, (
                f"{document_path} publishes {sorted(formats)}, "
                "expected a pdf and a postscript"
            )

    summary: list[str] = []
    for entry in entries:
        published = (ROOT / entry["path"]).read_bytes()
        digest = hashlib.sha256(published).hexdigest()
        if len(published) != entry["bytes"] or digest != entry["sha256"]:
            return False, (
                f"{entry['path']} is {len(published)} bytes / {digest}, the manifest "
                f"publishes {entry['bytes']} bytes / {entry['sha256']}"
            )

        document = renderspec.load(ROOT / entry["document"])
        rendered = output.artifact(document, format=entry["format"])
        if rendered != published:
            return False, (
                f"the {entry['format']} render is {len(rendered)} bytes / "
                f"{hashlib.sha256(rendered).hexdigest()}, {entry['path']} is "
                f"{len(published)} bytes / {digest}"
            )
        summary.append(
            f"{Path(entry['path']).stem} {entry['format']} {len(published)} bytes / "
            f"{digest[:16]}..."
        )

    executable = _ghostscript()
    if executable is None:
        return False, (
            "Ghostscript renders the published artifacts and was not found; install it "
            "or point OPENLABEL_GS at the executable"
        )
    boxes: dict[str, dict[str, tuple[float, ...]]] = {}
    for entry in entries:
        box = _rendered_box(executable, ROOT / entry["path"])
        if box is None:
            return False, f"{entry['path']} does not render under {executable}"
        boxes.setdefault(entry["document"], {})[entry["format"]] = box
    for document_path, formats in boxes.items():
        painted = formats["postscript"]
        plain = formats["pdf"]
        if painted[2] - painted[0] < 1.0 or painted[3] - painted[1] < 1.0:
            return False, f"{document_path}: the PostScript artifact paints nothing"
        if any(abs(left - right) > RENDER_TOLERANCE for left, right in zip(painted, plain)):
            return False, (
                f"{document_path}: the PostScript artifact paints {painted}, "
                f"the PDF paints {plain}"
            )

    return True, (
        "re-rendered artifacts are byte-identical to the published digests and "
        f"{Path(executable).name} paints each PostScript artifact where its PDF paints: "
        + ", ".join(summary)
    )


def renderspec_palette_pixels() -> tuple[bool, str]:
    """RO-111: the raster golden paints its paletted picture's table entries.

    A paletted picture's samples are indices, so its Decode has to span the
    depth's range; either value the writer used before painted every index as
    entry 0 while still producing stable bytes. The golden pins those bytes, and
    this check reads the colour Ghostscript paints in each quadrant of the
    picture's 2 x 2 grid, so the regression cannot return as a republished
    golden either.
    """

    executable = _ghostscript()
    if executable is None:
        return False, (
            "Ghostscript paints the raster golden and was not found; install it "
            "or point OPENLABEL_GS at the executable"
        )
    document = renderspec.load(FIXTURES / "valid" / "golden_image.json")
    (page,) = output.display_pages(document)
    (op,) = [
        op
        for body in page.bodies
        for op in body.ops
        if isinstance(op, Image) and op.picture.palette is not None
    ]
    table = [
        tuple(op.picture.palette[index : index + 3])
        for index in range(0, len(op.picture.palette), 3)
    ]
    # The picture's 2 x 2 samples list their four entries in reading order, so a
    # sample in each quadrant proves every entry is reachable from its own sample.
    quadrants = ((0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75))

    painted = []
    with tempfile.TemporaryDirectory() as directory:
        for target, extension in (("pdf", "pdf"), ("postscript", "ps")):
            artifact = GOLDEN / target / f"golden_image.{extension}"
            if not artifact.is_file():
                return False, f"{artifact.relative_to(ROOT)} is not published"
            raster = Path(directory) / f"{target}.png"
            result = subprocess.run(
                [
                    executable,
                    "-q",
                    "-dNOPAUSE",
                    "-dBATCH",
                    "-dSAFER",
                    "-sDEVICE=png16m",
                    f"-r{PIXEL_DPI}",
                    f"-sOutputFile={raster}",
                    str(artifact),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                return False, f"the {target} golden does not render: {result.stderr.strip()}"
            try:
                drawn = assets.picture(str(raster))
            except assets.AssetError as exc:
                return False, f"the {target} rendering is not readable: {exc}"
            rows = assets.samples(drawn)
            stride = drawn.width * 3
            for index, (fx, fy) in enumerate(quadrants):
                x, y = op.matrix.apply((op.width * fx, op.height * fy))
                start = int(y / PIXEL_MM) * stride + int(x / PIXEL_MM) * 3
                seen = tuple(rows[start : start + 3])
                wanted = table[index]
                if len(seen) != 3 or any(
                    abs(left - right) > PIXEL_TOLERANCE
                    for left, right in zip(seen, wanted, strict=True)
                ):
                    return False, (
                        f"the {target} golden paints {seen} in quadrant {index}, "
                        f"where the source sample declares {wanted}"
                    )
            painted.append(target)

    return True, "each of the four table entries paints in its own quadrant: " + ", ".join(painted)


def renderspec_font_embedding() -> tuple[bool, str]:
    """RO-104: a registered family is embedded, never emitted unembedded."""

    program = (FIXTURES / "fonts" / "probe.ttf").read_bytes()
    source = "data:font/ttf;base64," + base64.b64encode(program).decode("ascii")
    document = _probe_document([_text("run", "AB", font_family="Probe Sans")])
    document["fonts"] = [
        {
            "family": "Probe Sans",
            "variants": [{"style": "normal", "weight": "normal", "source": source}],
        }
    ]
    accepted = renderspec.parse(document)

    pdf = output.artifact(accepted)
    if pdf.count(b"/FontFile2") != 1:
        return False, f"the PDF embeds {pdf.count(b'/FontFile2')} font programs, expected one"
    tagged = re.search(rb"/BaseFont /([A-Z]{6})\+ProbeSans-Regular", pdf)
    if tagged is None:
        return False, "the PDF has no subset-tagged base font for the registered family"

    marker = pdf.index(b"/Length1")
    start = pdf.index(b"stream\n", marker) + len(b"stream\n")
    subset = zlib.decompress(pdf[start : pdf.index(b"\nendstream", start)])
    if len(subset) >= len(program):
        return False, (
            f"the embedded subset is {len(subset)} bytes, not smaller than the "
            f"{len(program)}-byte program"
        )
    if subset[:4] != b"\x00\x01\x00\x00":
        return False, "the embedded program is not an sfnt font"

    drawn = output.artifact(accepted, format="postscript")
    if b"/FontType 42" not in drawn or b"/sfnts [" not in drawn:
        return False, "the PostScript program does not embed the face as a Type 42 font"

    try:
        output.artifact({**accepted, "output": {"embed_fonts": False}})
    except output.OutputError:
        pass
    else:
        return False, "embed_fonts: false emitted a document with an unembedded custom font"

    if output.artifact(accepted) != pdf:
        return False, "two renders of the same document differ"

    return True, (
        f"the {len(program)}-byte program becomes a {len(subset)}-byte subset tagged "
        f"{tagged.group(1).decode()} in the PDF, PostScript embeds the face as Type 42, "
        "embed_fonts: false is rejected, and two renders are byte-identical"
    )


def renderspec_output_is_repeatable() -> tuple[bool, str]:
    """DT-101: two renders of one document are byte-identical."""

    document = _renderable_example()
    for target in ("pdf", "postscript"):
        if output.artifact(document, format=target) != output.artifact(document, format=target):
            return False, f"two {target} renders of one document differ"

    return True, "two PDF renders and two PostScript renders are byte-identical"


def renderspec_output_is_concurrency_safe() -> tuple[bool, str]:
    """DT-107: ten concurrent renders of one input are byte-identical."""

    document = renderspec.parse(_renderable_example())
    targets = ("pdf", "postscript")
    serial = {target: output.artifact(document, format=target) for target in targets}
    expected = {target: hashlib.sha256(artifact).hexdigest() for target, artifact in serial.items()}

    # Every render waits on one barrier, so all ten start together instead of running
    # one after another in the pool's queue.
    release = threading.Barrier(10)

    def render(index: int) -> tuple[str, str]:
        target = targets[index % len(targets)]
        release.wait(timeout=30)
        return target, hashlib.sha256(output.artifact(document, format=target)).hexdigest()

    with ThreadPoolExecutor(max_workers=10) as pool:
        concurrent = list(pool.map(render, range(10)))

    for target, digest in concurrent:
        if digest != expected[target]:
            return False, (
                f"a concurrent {target} render digests to {digest}, and the serial "
                f"render to {expected[target]}"
            )

    if {target: output.artifact(document, format=target) for target in targets} != serial:
        return False, "the artifact changed after the concurrent renders"

    return True, (
        f"ten simultaneous renders, five of each format, reproduce the serial digests "
        f"{expected['pdf'][:12]} and {expected['postscript'][:12]}, and a later serial "
        "render still does"
    )


def renderspec_output_rejects_invalid_document() -> tuple[bool, str]:
    """RO-101: a document that fails validation produces no artifact."""

    document = json.loads((FIXTURES / "invalid" / "missing_page.json").read_text(encoding="utf-8"))
    try:
        artifact = output.artifact(document)
    except renderspec.RenderSpecError as exc:
        return True, f"the fixture is rejected before rendering: {exc.diagnostics[0].render()}"

    return False, f"the invalid document produced {len(artifact)} bytes"


def _fill_box(fill: Fill) -> tuple[float, float, float, float]:
    """The page-millimetre box one plan fill covers."""

    points = [fill.matrix.apply(subpath.start) for subpath in fill.subpaths]
    points += [
        fill.matrix.apply(segment.end) for subpath in fill.subpaths for segment in subpath.segments
    ]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def renderspec_barcode_pattern() -> tuple[bool, str]:
    """RT-116: a code128 and an ean13 pattern span their declared millimetres."""

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
                    "draw_text": False,
                },
                {
                    "id": "ean_barcode",
                    "type": "barcode",
                    "y": 20.0,
                    "content": "4006381333931",
                    "symbology": "ean13",
                    "width": 33.0,
                    "height": 8.0,
                    "draw_text": False,
                },
            ]
        )
    )
    boxes = [
        _fill_box(op)
        for page in output.display_pages(accepted)
        for body in page.bodies
        for op in body.ops
        if isinstance(op, Fill)
    ]
    code128 = [box for box in boxes if box[1] < 15.0]
    ean13 = [box for box in boxes if box[1] >= 15.0]
    if not code128 or not ean13:
        return False, "the plan carries no bars for one of the two symbols"

    # Subset B of "ABC-123" is start, seven characters and the check character, each
    # 11 modules, plus the 13-module stop pattern; EAN-13 is 95 modules by the standard.
    expected = (
        ("code128", code128, (0.0, 0.0, 42.0, 12.0), 42.0 / 112),
        ("ean13", ean13, (0.0, 20.0, 33.0, 28.0), 33.0 / 95),
    )
    for name, group, declared, module in expected:
        measured = (
            min(box[0] for box in group),
            min(box[1] for box in group),
            max(box[2] for box in group),
            max(box[3] for box in group),
        )
        for observed, wanted in zip(measured, declared, strict=True):
            if abs(observed - wanted) > 0.1:
                return False, (
                    f"the {name} pattern spans {measured} mm, and its declared box is {declared}"
                )
        narrowest = min(box[2] - box[0] for box in group)
        if abs(narrowest - module) > 0.1:
            return False, (
                f"the {name} narrowest bar is {narrowest:.4f} mm, and one module of its "
                f"pattern is {module:.4f} mm"
            )

    return True, (
        "a 42 x 12 mm code128 spans 112 modules and a 33 x 8 mm ean13 spans 95, each "
        "with its narrowest bar within 0.1 mm of one module"
    )


def renderspec_barcode_caption() -> tuple[bool, str]:
    """RT-118: `draw_text` paints one centred caption in its defined band."""

    def caption(content: str, symbology: str, **props: Any) -> list[Text]:
        accepted = renderspec.parse(
            _probe_document(
                [
                    {
                        "id": "caption_barcode",
                        "type": "barcode",
                        "x": 6.0,
                        "y": 4.0,
                        "content": content,
                        "symbology": symbology,
                        "width": 40.0,
                        "height": 12.0,
                        **props,
                    }
                ]
            )
        )
        return [
            op
            for page in output.display_pages(accepted)
            for body in page.bodies
            for op in body.ops
            if isinstance(op, Text)
        ]

    em = 6.0 * 25.4 / 72.0
    runs = caption("ABC-123", "code128")
    if len(runs) != 1:
        return False, f"a draw_text code128 painted {len(runs)} text runs, expected one"
    (run,) = runs
    if run.content != "ABC-123":
        return False, f"the code128 caption carries {run.content!r}, expected 'ABC-123'"
    if abs(run.size - em) > 0.02:
        return False, f"the caption em size is {run.size:.4f} mm, expected {em:.4f} mm"
    if abs(run.baseline - 0.80 * em) > 0.02:
        return False, f"the caption baseline sits {run.baseline:.4f} mm below the em-box top"
    if abs(run.matrix.f - (4.0 + 12.0 + 0.5)) > 0.1:
        return False, (
            f"the caption em-box top is at y = {run.matrix.f:.4f} mm, expected 16.5 mm"
        )
    # The base-14 Helvetica advance of the payload, from the caption table's face.
    advance = 4057 / 1000.0 * em
    centre = run.matrix.e + advance / 2.0
    if abs(centre - 26.0) > 0.1:
        return False, (
            f"the code128 caption centres at x = {centre:.4f} mm, expected 26.0 mm"
        )

    runs = caption("9638507", "ean8")
    if [run.content for run in runs] != ["96385074"]:
        return False, f"the ean8 caption carries {[run.content for run in runs]}, expected its check digit"
    if abs(runs[0].matrix.f - 16.5) > 0.1:
        return False, f"the ean8 caption sits at y = {runs[0].matrix.f:.4f} mm, expected 16.5 mm"

    hidden = caption("ABC-123", "code128", draw_text=False)
    if hidden:
        return False, f"draw_text false painted {len(hidden)} text run(s)"

    return True, (
        "a draw_text code128 paints one 'ABC-123' run at 2.1167 mm, em-box top at "
        "y + 12.5 mm and centre line x + 20 mm, an ean8 caption carries its computed "
        "check digit, and draw_text false paints no run"
    )


def renderspec_qrcode_pattern() -> tuple[bool, str]:
    """RT-116: a qrcode's dark modules span exactly its declared millimetres."""

    accepted = renderspec.parse(
        _probe_document(
            [
                {
                    "id": "link_qrcode",
                    "type": "qrcode",
                    "x": 5.0,
                    "y": 5.0,
                    "content": "https://example.org",
                    "size": 18.0,
                }
            ]
        )
    )
    (entry,) = composition.draw_list(accepted)
    primitive = objects.primitive(entry.object)
    if not isinstance(primitive, objects.Qrcode):
        return False, "the qrcode did not resolve to a qrcode primitive"
    encoded = qrcode.encode(primitive.content, primitive.error_correction)
    declared = (5.0, 5.0, 5.0 + primitive.size, 5.0 + primitive.size)

    boxes = [
        _fill_box(op)
        for page in output.display_pages(accepted)
        for body in page.bodies
        for op in body.ops
        if isinstance(op, Fill)
    ]
    backdrop, *ink = boxes
    for observed, wanted in zip(backdrop, declared, strict=True):
        if abs(observed - wanted) > 0.1:
            return False, f"the qrcode background spans {backdrop} mm, expected {declared}"
    if not ink:
        return False, "the plan carries no dark modules"
    for box in ink:
        if (
            box[0] < declared[0] - 0.1
            or box[1] < declared[1] - 0.1
            or box[2] > declared[2] + 0.1
            or box[3] > declared[3] + 0.1
        ):
            return False, f"a dark run {box} leaves the declared 18 mm box"
    measured = (
        min(box[0] for box in ink),
        min(box[1] for box in ink),
        max(box[2] for box in ink),
        max(box[3] for box in ink),
    )
    for observed, wanted in zip(measured, declared, strict=True):
        if abs(observed - wanted) > 0.1:
            return False, f"the dark modules span {measured} mm, expected {declared}"

    module = primitive.size / encoded.module_count
    for row, line in enumerate(encoded.modules):
        for column, dark in enumerate(line):
            centre = (
                5.0 + (column + 0.5) * module,
                5.0 + (row + 0.5) * module,
            )
            painted = any(
                box[0] <= centre[0] <= box[2] and box[1] <= centre[1] <= box[3] for box in ink
            )
            if painted != dark:
                return False, (
                    f"module ({row}, {column}) is {'painted' if painted else 'clear'}, and the "
                    f"encoder has it {'dark' if dark else 'light'}"
                )

    return True, (
        f"an 18 mm qrcode paints its {encoded.module_count} x {encoded.module_count} "
        f"version {encoded.version}-{encoded.level} grid module for module inside the "
        "declared 5-23 mm square"
    )


def _barcode_family(
    name: str, symbols: list[tuple[str, str, int, float]], width: float, height: float
) -> tuple[bool, str]:
    """RT-116: draw each `(symbology, content, modules, y)` symbol and measure its box."""

    accepted = renderspec.parse(
        _probe_document(
            [
                {
                    "id": f"{symbology}_barcode",
                    "type": "barcode",
                    "x": 5.0,
                    "y": y,
                    "content": content,
                    "symbology": symbology,
                    "width": width,
                    "height": height,
                    "draw_text": False,
                }
                for symbology, content, _, y in symbols
            ]
        )
    )
    boxes = [
        _fill_box(op)
        for page in output.display_pages(accepted)
        for body in page.bodies
        for op in body.ops
        if isinstance(op, Fill)
    ]
    for symbology, _, modules, y in symbols:
        group = [box for box in boxes if abs(box[1] - y) < 0.1]
        if not group:
            return False, f"the plan carries no bars for the {symbology} symbol"
        declared = (5.0, y, 5.0 + width, y + height)
        measured = (
            min(box[0] for box in group),
            min(box[1] for box in group),
            max(box[2] for box in group),
            max(box[3] for box in group),
        )
        for observed, wanted in zip(measured, declared, strict=True):
            if abs(observed - wanted) > 0.1:
                return False, (
                    f"the {symbology} pattern spans {measured} mm, and its declared box is "
                    f"{declared}"
                )
        module = width / modules
        narrowest = min(box[2] - box[0] for box in group)
        if abs(narrowest - module) > 0.1:
            return False, (
                f"the {symbology} narrowest bar is {narrowest:.4f} mm, and one module of its "
                f"{modules}-module pattern is {module:.4f} mm"
            )

    return True, (
        f"the {name} symbols ({', '.join(symbology for symbology, *_ in symbols)}) each paint "
        f"their declared {width} x {height} mm box with a narrowest bar within 0.1 mm of one "
        "module of their published pattern"
    )


def renderspec_barcode_retail_symbols() -> tuple[bool, str]:
    """RT-116: the ean8, upca and upce patterns span their declared millimetres."""

    return _barcode_family(
        "retail",
        [
            ("ean8", "9638507", 67, 0.0),
            ("upca", "036000291452", 95, 12.0),
            ("upce", "123456", 51, 24.0),
        ],
        30.0,
        6.0,
    )


def renderspec_barcode_discrete_symbols() -> tuple[bool, str]:
    """RT-116: the code39, itf and codabar patterns span their declared millimetres."""

    return _barcode_family(
        "discrete",
        [
            ("code39", "ABC-123", 143, 0.0),
            ("itf", "12345678", 81, 16.0),
            ("codabar", "A1234B", 75, 32.0),
        ],
        40.0,
        8.0,
    )


def renderspec_pdf417_pattern() -> tuple[bool, str]:
    """RT-116: a pdf417 symbol paints its grid module for module in its box."""

    accepted = renderspec.parse(
        _probe_document(
            [
                {
                    "id": "stacked_barcode",
                    "type": "barcode",
                    "x": 5.0,
                    "y": 5.0,
                    "content": "PDF417",
                    "symbology": "pdf417",
                    "width": 42.0,
                    "height": 12.0,
                    "draw_text": False,
                }
            ]
        )
    )
    (entry,) = composition.draw_list(accepted)
    primitive = objects.primitive(entry.object)
    if not isinstance(primitive, objects.Barcode):
        return False, "the pdf417 did not resolve to a barcode primitive"
    encoded = pdf417.encode(primitive.content, primitive.width, primitive.height)
    declared = (5.0, 5.0, 5.0 + primitive.width, 5.0 + primitive.height)

    boxes = [
        _fill_box(op)
        for page in output.display_pages(accepted)
        for body in page.bodies
        for op in body.ops
        if isinstance(op, Fill)
    ]
    backdrop, *ink = boxes
    for observed, wanted in zip(backdrop, declared, strict=True):
        if abs(observed - wanted) > 0.1:
            return False, f"the pdf417 background spans {backdrop} mm, expected {declared}"
    if not ink:
        return False, "the plan carries no bars"

    module = primitive.width / encoded.module_count
    row_height = primitive.height / encoded.row_count
    for row, modules in enumerate(encoded.modules):
        for column, dark in enumerate(modules):
            centre = (
                5.0 + (column + 0.5) * module,
                5.0 + (row + 0.5) * row_height,
            )
            painted = any(
                box[0] <= centre[0] <= box[2] and box[1] <= centre[1] <= box[3] for box in ink
            )
            if painted != dark:
                return False, (
                    f"module ({row}, {column}) is {'painted' if painted else 'clear'}, and the "
                    f"encoder has it {'dark' if dark else 'light'}"
                )

    return True, (
        f"a 42 x 12 mm pdf417 paints its {encoded.columns}-column, {encoded.row_count}-row "
        f"grid of {encoded.module_count} modules per row module for module inside the "
        "declared 5-47 mm box"
    )


BARCODE_DPI = 600
BARCODE_X = 10.0
BARCODE_Y = 7.5

# One document per symbology. The EAN/UPC payloads are given without their check
# digit and are expected back with it; Codabar prints its own start and stop
# characters; PDF417's payload is sixteen bytes, so its byte compaction ends on a
# four-codeword run that the reader can tell from a six-byte group.
BARCODE_FIXTURES = (
    # symbology, content, decoded payload, width mm, height mm
    ("code128", "OL-RO107", "OL-RO107", 40.0, 15.0),
    ("code39", "OL-107", "OL-107", 40.0, 15.0),
    ("ean13", "400638133393", "4006381333931", 40.0, 15.0),
    ("ean8", "9638507", "96385074", 30.0, 12.0),
    ("upca", "03600029145", "036000291452", 40.0, 15.0),
    ("upce", "123456", "01234565", 25.0, 12.0),
    ("itf", "00123457", "00123457", 40.0, 15.0),
    ("codabar", "A1234B", "A1234B", 40.0, 15.0),
    ("pdf417", "OL-RO107-PDF417", "OL-RO107-PDF417", 45.0, 18.0),
)


def _barcode_document(symbology: str, content: str, width: float, height: float) -> dict[str, Any]:
    """A 60 x 30 mm page carrying one uncaptioned symbol from `(10, 7.5)` mm."""

    return {
        "renderspec": "1.0",
        "id": "barcode_probe",
        "name": "Barcode Probe",
        "page": {"width": 60.0, "height": 30.0},
        "layers": [
            _layer(
                "base",
                [
                    {
                        "id": "symbol",
                        "type": "barcode",
                        "x": BARCODE_X,
                        "y": BARCODE_Y,
                        "content": content,
                        "symbology": symbology,
                        "width": width,
                        "height": height,
                        "draw_text": False,
                    }
                ],
            )
        ],
    }


def renderspec_barcode_decode() -> tuple[bool, str]:
    """RO-107: every symbology decodes back to its content from the pixels.

    Nine documents -- the eight linear symbologies and the stacked `pdf417` -- are
    rendered to both artifacts, rasterized at 600 dpi and read back by
    `barcode_reader`. The reader inverts the published pattern tables but computes
    its own check digits, row indicators, byte decompaction and Reed-Solomon
    syndromes, so a wrong bar, a misplaced codeword or a skipped check digit
    cannot pass. Each symbol must decode to its payload, span the module count its
    symbology defines, and paint its declared box within 0.1 mm.
    """

    executable = _ghostscript()
    if executable is None:
        return False, (
            "Ghostscript rasterizes the symbols and was not found; install it "
            "or point OPENLABEL_GS at the executable"
        )

    summary: list[str] = []
    with tempfile.TemporaryDirectory() as directory:
        workspace = Path(directory)
        for symbology, content, payload, width, height in BARCODE_FIXTURES:
            accepted = renderspec.parse(_barcode_document(symbology, content, width, height))
            declared = (BARCODE_X, BARCODE_Y, BARCODE_X + width, BARCODE_Y + height)
            for target, suffix in (("pdf", "pdf"), ("postscript", "ps")):
                picture, failure = _symbol_raster(
                    executable, output.artifact(accepted, format=target), suffix, workspace
                )
                if picture is None:
                    return False, f"the {symbology} symbol: {failure}"
                try:
                    reading = barcode_reader.read(picture, symbology)
                except barcode_reader.ReaderError as exc:
                    return False, f"the {symbology} symbol in the {target} artifact: {exc}"

                if reading.content != payload:
                    return False, (
                        f"the {symbology} symbol in the {target} artifact decodes to "
                        f"{reading.content!r}, expected {payload!r}"
                    )
                if symbology == "pdf417":
                    if reading.modules != 17 * (reading.columns + 2) + 35:
                        return False, (
                            f"the pdf417 row spans {reading.modules} modules, and "
                            f"{reading.columns} columns frame it in "
                            f"{17 * (reading.columns + 2) + 35}"
                        )
                    if reading.rows < 3 or reading.error_codewords < 4:
                        return False, (
                            f"the pdf417 symbol reports {reading.rows} rows and "
                            f"{reading.error_codewords} error codewords"
                        )
                elif reading.modules != barcode.symbol(symbology, content).module_count:
                    return False, (
                        f"the {symbology} symbol spans {reading.modules} modules, and its "
                        f"pattern holds {barcode.symbol(symbology, content).module_count}"
                    )

                observed = tuple(
                    value * 25.4 / BARCODE_DPI
                    for value in (reading.left, reading.top, reading.right, reading.bottom)
                )
                for seen, wanted in zip(observed, declared, strict=True):
                    if abs(seen - wanted) > 0.1:
                        return False, (
                            f"the {symbology} symbol in the {target} artifact spans "
                            f"{tuple(round(value, 3) for value in observed)} mm, and its "
                            f"declared box is {declared}"
                        )
                summary.append(f"{symbology}/{target} {reading.modules} modules")

    return True, (
        "the eight linear symbologies and pdf417 decode back to their payloads from both "
        "artifacts, each with its check digits verified, its error codewords checked and "
        "its declared box painted: " + ", ".join(summary)
    )


def renderspec_pdf417_boxes() -> tuple[bool, str]:
    """RT-116: a wide and a tall pdf417 box each fill their declared millimetres."""

    shapes = [("wide", 42.0, 12.0, 0.0), ("tall", 20.0, 26.0, 16.0)]
    accepted = renderspec.parse(
        _probe_document(
            [
                {
                    "id": f"{name}_barcode",
                    "type": "barcode",
                    "x": 5.0,
                    "y": y,
                    "content": "PDF417",
                    "symbology": "pdf417",
                    "width": width,
                    "height": height,
                    "draw_text": False,
                }
                for name, width, height, y in shapes
            ]
        )
    )
    boxes = [
        _fill_box(op)
        for page in output.display_pages(accepted)
        for body in page.bodies
        for op in body.ops
        if isinstance(op, Fill)
    ]
    columns = []
    for name, width, height, y in shapes:
        group = [box for box in boxes if abs(box[1] - y) < 0.1]
        if not group:
            return False, f"the plan carries no bars for the {name} symbol"
        measured = (
            min(box[0] for box in group),
            min(box[1] for box in group),
            max(box[2] for box in group),
            max(box[3] for box in group),
        )
        declared = (5.0, y, 5.0 + width, y + height)
        for observed, wanted in zip(measured, declared, strict=True):
            if abs(observed - wanted) > 0.1:
                return False, (
                    f"the {name} pdf417 spans {measured} mm, and its declared box is {declared}"
                )
        symbol = pdf417.encode("PDF417", width, height)
        narrowest = min(box[2] - box[0] for box in group)
        if abs(narrowest - width / symbol.module_count) > 0.1:
            return False, (
                f"the {name} pdf417 narrowest bar is {narrowest:.4f} mm, and one module is "
                f"{width / symbol.module_count:.4f} mm"
            )
        columns.append(symbol.columns)
    if columns[0] <= columns[1]:
        return False, f"the wide box chose {columns[0]} columns and the tall one {columns[1]}"

    return True, (
        f"a 42 x 12 mm and a 20 x 26 mm pdf417 fill their declared boxes with {columns[0]} and "
        f"{columns[1]} columns, each with its narrowest bar within 0.1 mm of one module"
    )


# A symbol is read back at 600 dpi, where one 1 mm module spans 23.6 device
# pixels, so a module centre reads one colour rather than a blend.
QR_DPI = 600
QR_MM = 25.4 / QR_DPI

# Each payload is longer than its level's version 1 capacity and shorter than
# version 2's, so all four levels exercise the alignment pattern, the timing
# patterns and both format-information copies of a 25 x 25 module symbol.
QR_PAYLOADS = {
    "L": "OL-RO108-" + "L" * 10,
    "M": "OL-RO108-" + "M" * 6,
    "Q": "OL-RO108-" + "Q" * 3,
    "H": "OL-RO108-H",
}


def _qr_document(content: str, level: str) -> dict[str, Any]:
    """A 60 x 40 mm page carrying a 25 mm symbol from `(15, 7.5)` mm."""

    return {
        "renderspec": "1.0",
        "id": "qr_probe",
        "name": "QR Probe",
        "page": {"width": 60.0, "height": 40.0},
        "layers": [
            _layer(
                "base",
                [
                    {
                        "id": "symbol",
                        "type": "qrcode",
                        "x": 15.0,
                        "y": 7.5,
                        "content": content,
                        "size": 25.0,
                        "error_correction": level,
                    }
                ],
            )
        ],
    }


def _symbol_raster(
    executable: str, artifact: bytes, suffix: str, directory: Path
) -> tuple[assets.Picture | None, str]:
    """Rasterize one artifact at `QR_DPI`, and read its PNG back."""

    path = directory / f"symbol.{suffix}"
    path.write_bytes(artifact)
    raster = directory / f"symbol-{suffix}.png"
    result = subprocess.run(
        [
            executable,
            "-q",
            "-dNOPAUSE",
            "-dBATCH",
            "-dSAFER",
            "-sDEVICE=png16m",
            f"-r{QR_DPI}",
            f"-sOutputFile={raster}",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        return None, f"the {suffix} artifact does not render: {result.stderr.strip()}"
    try:
        return assets.picture(str(raster)), ""
    except assets.AssetError as exc:
        return None, f"the {suffix} rendering is not readable: {exc}"


def _png(width: int, height: int, rows: bytes) -> bytes:
    """A PNG from unfiltered RGB rows, so the case can repaint one module."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    body = b"".join(
        b"\x00" + rows[y * width * 3 : (y + 1) * width * 3] for y in range(height)
    )
    return (
        assets.PNG_SIGNATURE
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(body, 9))
        + chunk(b"IEND", b"")
    )


def _damage_error_codeword(
    picture: assets.Picture, reading: qr_reader.Reading, directory: Path
) -> tuple[assets.Picture | None, str]:
    """Flip the module carrying `reading`'s first error-codeword bit.

    The data codewords are untouched, so a reader that skipped the error codewords
    would still return the content; only the syndromes can tell that the block no
    longer matches its generator.
    """

    index = qr_reader.data_codewords(reading.version, reading.level) * 8
    row, column = qr_reader.module_order(reading.version)[index]
    module = (reading.right - reading.left) / reading.modules
    left = int(round(reading.left + column * module))
    right = int(round(reading.left + (column + 1) * module))
    top = int(round(reading.top + row * module))
    bottom = int(round(reading.top + (row + 1) * module))

    rows = bytearray(assets.samples(picture))
    stride = picture.width * 3
    start = top * stride + 3 * left
    dark = sum(rows[start : start + 3]) < 384
    paint = b"\xff\xff\xff" if dark else b"\x00\x00\x00"
    for y in range(top, bottom):
        for x in range(left, right):
            offset = y * stride + 3 * x
            rows[offset : offset + 3] = paint

    path = directory / "damaged.png"
    path.write_bytes(_png(picture.width, picture.height, bytes(rows)))
    try:
        return assets.picture(str(path)), ""
    except assets.AssetError as exc:
        return None, f"the damaged raster is not readable: {exc}"


def renderspec_qr_decode() -> tuple[bool, str]:
    """RO-108: a rendered QR symbol decodes to its content at every level.

    Each level's document is rendered to both artifacts, rasterized at 600 dpi
    and read back from its pixels by `qr_reader`, which shares no table with the
    encoder: the content, the level the format information names and the 25 x 25
    module grid must come back, and the symbol must paint its declared box. The
    reader also evaluates the Reed-Solomon syndromes, so the case asserts the
    error block was checked and then flips one error-codeword module: the data
    still decodes, so only the syndromes can reject it.
    """

    executable = _ghostscript()
    if executable is None:
        return False, (
            "Ghostscript rasterizes the symbols and was not found; install it "
            "or point OPENLABEL_GS at the executable"
        )

    x, y, size = 15.0, 7.5, 25.0
    declared = (x, y, x + size, y + size)
    summary: list[str] = []
    with tempfile.TemporaryDirectory() as directory:
        workspace = Path(directory)
        for level, content in QR_PAYLOADS.items():
            accepted = renderspec.parse(_qr_document(content, level))
            for target, suffix in (("pdf", "pdf"), ("postscript", "ps")):
                picture, failure = _symbol_raster(
                    executable, output.artifact(accepted, format=target), suffix, workspace
                )
                if picture is None:
                    return False, failure
                try:
                    reading = qr_reader.read(picture)
                except qr_reader.ReaderError as exc:
                    return False, f"the {level} symbol in the {target} artifact: {exc}"

                if reading.content != content:
                    return False, (
                        f"the {level} symbol in the {target} artifact decodes to "
                        f"{reading.content!r}, expected {content!r}"
                    )
                if reading.level != level:
                    return False, (
                        f"the {target} symbol requested {level} and its format "
                        f"information names {reading.level}"
                    )
                if (reading.version, reading.modules) != (2, 25):
                    return False, (
                        f"the {level} symbol is version {reading.version} with "
                        f"{reading.modules} modules, expected a 25 x 25 version 2"
                    )
                if reading.error_codewords != qr_reader.error_codewords(2, level):
                    return False, (
                        f"the {level} symbol checked {reading.error_codewords} error "
                        "codewords, expected "
                        f"{qr_reader.error_codewords(2, level)}"
                    )
                measured = (
                    reading.left * QR_MM,
                    reading.top * QR_MM,
                    reading.right * QR_MM,
                    reading.bottom * QR_MM,
                )
                for observed, wanted in zip(measured, declared, strict=True):
                    if abs(observed - wanted) > 0.1:
                        return False, (
                            f"the {level} symbol in the {target} artifact paints "
                            f"{measured} mm, declared {declared}"
                        )
                summary.append(f"{level}/{target} mask {reading.mask}")

                if level == "M" and target == "pdf":
                    damaged, failure = _damage_error_codeword(picture, reading, workspace)
                    if damaged is None:
                        return False, failure
                    try:
                        qr_reader.read(damaged)
                    except qr_reader.ReaderError as exc:
                        if "Reed-Solomon" not in str(exc):
                            return False, (
                                "a flipped error codeword was reported without a "
                                f"syndrome: {exc}"
                            )
                    else:
                        return False, (
                            "a symbol with a flipped error-codeword module decoded "
                            "without a syndrome"
                        )

    return True, (
        "25 mm symbols at every error-correction level decode back to their content "
        "from both artifacts, each a version 2 grid of 25 modules with its error "
        "codewords checked and painting its 15.0-40.0 x 7.5-32.5 mm box; a flipped "
        "error-codeword module is rejected by a nonzero syndrome: " + ", ".join(summary)
    )


def _svg_document(source: str) -> dict[str, Any]:
    """A document whose single image object draws the SVG asset at `source`."""

    document = _probe_document(
        [
            {
                "id": "logo",
                "type": "image",
                "x": 10.0,
                "y": 5.0,
                "asset_id": "mark",
                "width": 40.0,
                "height": 20.0,
            }
        ]
    )
    document["assets"] = [{"id": "mark", "type": "svg", "source": source}]
    return document


def renderspec_svg_artwork() -> tuple[bool, str]:
    """RO-103: an SVG asset paints vector subpaths clipped to its box."""

    accepted = renderspec.parse(_svg_document(str(FIXTURES / "assets" / "logo.svg")))
    ops = [
        op for page in output.display_pages(accepted) for body in page.bodies for op in body.ops
    ]
    if any(isinstance(op, Image) for op in ops):
        return False, "the plan carries a raster picture for the SVG asset"
    fills = [op for op in ops if isinstance(op, Fill)]
    strokes = [op for op in ops if isinstance(op, Stroke)]
    if not fills or not strokes:
        return False, f"the plan carries {[type(op).__name__ for op in ops]}, not a fill and a stroke"
    if len(ops) != 3:
        return False, f"the three-element fixture painted {len(ops)} operations"

    declared = (10.0, 5.0, 50.0, 25.0)
    corners = [
        op.matrix.apply(point)
        for op in ops
        for subpath in op.subpaths
        for point in (subpath.start, *(segment.end for segment in subpath.segments))
    ]
    measured = (
        min(x for x, _ in corners),
        min(y for _, y in corners),
        max(x for x, _ in corners),
        max(y for _, y in corners),
    )
    for observed, wanted in zip(measured, declared, strict=True):
        if abs(observed - wanted) > 0.1:
            return False, f"the artwork spans {measured} mm, and the image box is {declared}"

    pdf = output.artifact(accepted)
    content = _first_stream(pdf)
    if b"/Subtype /Image" in pdf or b"/XObject" in pdf or b" Do" in content:
        return False, "the PDF carries a raster copy of the artwork"
    for operator in (b" m", b" l", b" c"):
        if operator not in content:
            return False, f"the PDF content stream has no path operator {operator!r}"

    program = output.artifact(accepted, format="postscript")
    if b">> image" in program or b"%%DocumentData: Binary" in program:
        return False, "the PostScript program paints an image for the SVG asset"
    for operator in (b"moveto", b"lineto", b"curveto"):
        if operator not in program:
            return False, f"the PostScript program has no path operator {operator!r}"

    return True, (
        "a rect, a circle and a stroked path in a 0 0 20 10 viewBox fill the declared "
        "10-50 x 5-25 mm box, and both artifacts carry path operators with no raster copy"
    )


def renderspec_svg_profile_rejection() -> tuple[bool, str]:
    """RO-113: a construct outside the profile is reported, not approximated."""

    cases = (
        ("logo_text.svg", "<text>"),
        ("logo_gradient.svg", "url(#fade)"),
    )
    for name, expected in cases:
        accepted = renderspec.parse(_svg_document(str(FIXTURES / "assets" / name)))
        try:
            artifact = output.artifact(accepted)
        except output.OutputError as exc:
            if expected not in str(exc):
                return False, f"{name} was reported without naming {expected}: {exc}"
            continue
        return False, f"{name} produced {len(artifact)} bytes instead of a report"

    return True, (
        "an SVG text element and a gradient reference are each reported by name, and "
        "neither produces an artifact"
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
    "renderspec_group_inheritance": renderspec_group_inheritance,
    "renderspec_label_frame_origin": renderspec_label_frame_origin,
    "renderspec_font_size_points": renderspec_font_size_points,
    "renderspec_page_margin_ignored": renderspec_page_margin_ignored,
    "renderspec_text_bounds_validation": renderspec_text_bounds_validation,
    "renderspec_code_extents": renderspec_code_extents,
    "renderspec_barcode_pattern": renderspec_barcode_pattern,
    "renderspec_barcode_retail_symbols": renderspec_barcode_retail_symbols,
    "renderspec_barcode_discrete_symbols": renderspec_barcode_discrete_symbols,
    "renderspec_pdf417_pattern": renderspec_pdf417_pattern,
    "renderspec_pdf417_boxes": renderspec_pdf417_boxes,
    "renderspec_qrcode_pattern": renderspec_qrcode_pattern,
    "renderspec_barcode_caption": renderspec_barcode_caption,
    "renderspec_barcode_decode": renderspec_barcode_decode,
    "renderspec_qr_decode": renderspec_qr_decode,
    "renderspec_svg_artwork": renderspec_svg_artwork,
    "renderspec_svg_profile_rejection": renderspec_svg_profile_rejection,
    "renderspec_output_timestamps_are_inert": renderspec_output_timestamps_are_inert,
    "renderspec_output_page_size": renderspec_output_page_size,
    "renderspec_output_is_vector": renderspec_output_is_vector,
    "renderspec_output_has_no_timestamps": renderspec_output_has_no_timestamps,
    "renderspec_compression_is_deterministic": renderspec_compression_is_deterministic,
    "renderspec_identifiers_are_content_derived": renderspec_identifiers_are_content_derived,
    "renderspec_output_defaults": renderspec_output_defaults,
    "renderspec_golden_artifacts": renderspec_golden_artifacts,
    "renderspec_palette_pixels": renderspec_palette_pixels,
    "renderspec_font_embedding": renderspec_font_embedding,
    "renderspec_output_is_repeatable": renderspec_output_is_repeatable,
    "renderspec_output_is_concurrency_safe": renderspec_output_is_concurrency_safe,
    "renderspec_output_rejects_invalid_document": renderspec_output_rejects_invalid_document,
}
