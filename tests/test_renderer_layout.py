"""Tests for `renderer/layout.py`: StockSpec grid frames and RenderSpec boundaries."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from renderer import layout  # noqa: E402

TOLERANCE = 1e-9
EXAMPLE = ROOT / "specs" / "stockspec" / "examples" / "avery_5160.yaml"


def load_example() -> dict:
    return yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))


def rect(object_id: str, **fields: float) -> dict:
    return {"id": object_id, "type": "rect", **fields}


def page_document(*objects: dict) -> dict:
    """A page-absolute RenderSpec carrying the given objects in one layer."""

    return {
        "page": {"width": 100.0, "height": 50.0},
        "layers": [{"id": "base", "name": "Base", "objects": list(objects)}],
    }


def label_document(*objects: dict, **stock: float) -> dict:
    """A stock-grid RenderSpec whose active boundary is a 50 x 30 mm label."""

    return {
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
            **stock,
        },
        "layers": [{"id": "base", "name": "Base", "objects": list(objects)}],
    }


def test_frame_origins_follow_the_published_formula() -> None:
    frames = layout.grid_frames(
        rows=2,
        columns=3,
        margin_left=4.5,
        margin_top=12.7,
        horizontal_pitch=66.7,
        vertical_pitch=25.4,
        width=66.0,
        height=25.0,
    )
    assert [(frame.column, frame.row) for frame in frames] == [
        (0, 0),
        (1, 0),
        (2, 0),
        (0, 1),
        (1, 1),
        (2, 1),
    ]
    assert frames[0].x == pytest.approx(4.5, abs=TOLERANCE)
    assert frames[0].y == pytest.approx(12.7, abs=TOLERANCE)
    assert frames[2].x == pytest.approx(4.5 + 2 * 66.7, abs=TOLERANCE)
    assert frames[4].y == pytest.approx(12.7 + 25.4, abs=TOLERANCE)


def test_frames_are_filled_row_major() -> None:
    frames = layout.grid_frames(
        rows=2,
        columns=3,
        margin_left=0.0,
        margin_top=0.0,
        horizontal_pitch=10.0,
        vertical_pitch=10.0,
        width=9.0,
        height=9.0,
    )
    assert [frame.index for frame in frames] == list(range(6))
    # Column increases first: slot 1 is the second column of the first row.
    assert (frames[1].column, frames[1].row) == (1, 0)
    assert (frames[3].column, frames[3].row) == (0, 1)


def test_frame_extent_is_the_label_size() -> None:
    frames = layout.grid_frames(
        rows=1,
        columns=2,
        margin_left=3.0,
        margin_top=4.0,
        horizontal_pitch=20.0,
        vertical_pitch=10.0,
        width=18.0,
        height=9.0,
    )
    assert frames[1].right == pytest.approx(3.0 + 20.0 + 18.0, abs=TOLERANCE)
    assert frames[1].bottom == pytest.approx(4.0 + 9.0, abs=TOLERANCE)


def test_stock_frames_reads_the_published_stockspec() -> None:
    frames = layout.stock_frames(load_example())
    assert len(frames) == 30
    first, last = frames[0], frames[-1]
    assert (first.column, first.row) == (0, 0)
    assert (last.column, last.row) == (2, 9)
    assert first.x == pytest.approx(4.76, abs=TOLERANCE)
    assert first.y == pytest.approx(12.7, abs=TOLERANCE)
    assert last.x == pytest.approx(4.76 + 2 * 69.85, abs=TOLERANCE)
    assert last.y == pytest.approx(12.7 + 9 * 25.4, abs=TOLERANCE)
    assert last.right == pytest.approx(4.76 + 2 * 69.85 + 66.675, abs=TOLERANCE)


def test_page_absolute_document_renders_once_at_the_page_origin() -> None:
    frames = layout.document_frames(page_document(rect("r", x=5.0, y=6.0, width=10.0, height=4.0)))
    assert len(frames) == 1
    frame = frames[0]
    assert (frame.x, frame.y) == (0.0, 0.0)
    assert (frame.width, frame.height) == (100.0, 50.0)
    assert (frame.column, frame.row, frame.index) == (0, 0, 0)


def test_stock_grid_document_replicates_across_frames() -> None:
    document = label_document(
        rect("r", x=5.0, y=6.0, width=10.0, height=4.0),
        width=40.0,
        columns=2,
        horizontal_pitch=45.0,
    )
    frames = layout.document_frames(document)
    assert [(frame.column, frame.x, frame.y) for frame in frames] == [
        (0, 10.0, 10.0),
        (1, 55.0, 10.0),
    ]
    assert {(frame.width, frame.height) for frame in frames} == {(40.0, 30.0)}

    bounds = layout.object_bounds(document["layers"][0]["objects"][0])
    bodies = [
        (bounds.x + frame.x, bounds.y + frame.y, bounds.width, bounds.height) for frame in frames
    ]
    assert bodies == [(15.0, 16.0, 10.0, 4.0), (60.0, 16.0, 10.0, 4.0)]


def test_page_box_is_anchored_at_the_page_origin() -> None:
    box = layout.page_box({"page": {"width": 90.0, "height": 29.0}})
    assert (box.x, box.y, box.width, box.height) == (0.0, 0.0, 90.0, 29.0)


def test_active_boundary_is_the_page_without_stock() -> None:
    boundary = layout.active_boundary(page_document())
    assert (boundary.width, boundary.height) == (100.0, 50.0)


def test_active_boundary_is_the_label_with_stock() -> None:
    boundary = layout.active_boundary(label_document())
    assert (boundary.x, boundary.y, boundary.width, boundary.height) == (
        0.0,
        0.0,
        50.0,
        30.0,
    )


def test_object_bounds_apply_the_translation() -> None:
    bounds = layout.object_bounds(rect("r", x=5.0, y=6.0, width=10.0, height=4.0))
    assert (bounds.x, bounds.y, bounds.right, bounds.bottom) == (5.0, 6.0, 15.0, 10.0)


def test_rotation_yields_the_axis_aligned_envelope() -> None:
    bounds = layout.object_bounds(rect("r", width=10.0, height=20.0, rotation=90.0))
    assert bounds.width == pytest.approx(20.0, abs=TOLERANCE)
    assert bounds.height == pytest.approx(10.0, abs=TOLERANCE)


def test_a_group_has_no_geometry_of_its_own() -> None:
    group = {
        "id": "g",
        "type": "group",
        "x": 5.0,
        "y": 5.0,
        "objects": [rect("a", width=10.0, height=2.0)],
    }
    assert layout.object_bounds(group) is None


def test_text_without_an_extent_is_not_measured() -> None:
    assert layout.object_bounds({"id": "t", "type": "text", "content": "hi"}) is None
    measured = layout.object_bounds(
        {"id": "t", "type": "text", "content": "hi", "width": 20.0, "height": 5.0}
    )
    assert (measured.width, measured.height) == (20.0, 5.0)


def test_shapes_without_a_documented_extent_are_not_measured() -> None:
    for obj in (
        {"id": "c", "type": "circle", "r": 5.0},
        {"id": "e", "type": "ellipse", "rx": 5.0, "ry": 3.0},
        {"id": "p", "type": "path", "d": "M 0 0 L 10 10 Z"},
        # The schema calls these relative to the anchor, Section 8.2.7 absolute.
        {"id": "l", "type": "polyline", "points": [[0.0, 0.0], [10.0, 10.0]]},
        {"id": "y", "type": "polygon", "points": [[0.0, 0.0], [10.0, 0.0], [5.0, 8.0]]},
    ):
        assert layout.object_bounds(obj) is None


def test_hidden_content_is_not_measured() -> None:
    document = page_document(rect("r", x=200.0, y=200.0, width=10.0, height=10.0))
    document["layers"][0]["objects"][0]["visible"] = False
    assert layout.overflow_warnings(document) == ()


def test_overflow_reports_the_object_past_the_boundary() -> None:
    document = label_document(
        rect("inside", x=5.0, y=5.0, width=10.0, height=10.0),
        rect("outside", x=45.0, y=25.0, width=20.0, height=20.0),
    )
    warnings = layout.overflow_warnings(document)
    assert len(warnings) == 1
    assert warnings[0].path == "layers.0.objects.1"
    assert warnings[0].object_id == "outside"
    assert warnings[0].edges == ("right", "bottom")
    assert "50.0 x 30.0 mm" in warnings[0].render()


def test_content_exactly_on_the_boundary_is_not_overflow() -> None:
    document = label_document(rect("flush", x=0.0, y=0.0, width=50.0, height=30.0))
    assert layout.overflow_warnings(document) == ()

    negative = label_document(rect("left", x=-5.0, width=10.0, height=10.0))
    assert layout.overflow_warnings(negative)[0].edges == ("left",)


def test_page_absolute_documents_measure_against_the_page() -> None:
    document = page_document(rect("wide", x=90.0, width=20.0, height=10.0))
    warnings = layout.overflow_warnings(document)
    assert len(warnings) == 1
    assert warnings[0].edges == ("right",)
    assert warnings[0].boundary.width == 100.0


def test_overflow_is_a_warning_not_a_rejection() -> None:
    document = label_document(rect("outside", x=60.0, width=10.0, height=10.0))
    before = repr(document)
    warnings = layout.overflow_warnings(document)
    assert len(warnings) == 1
    assert repr(document) == before


def test_group_overflow_names_the_nested_path() -> None:
    document = label_document(
        {
            "id": "g",
            "type": "group",
            "x": 40.0,
            "objects": [rect("child", width=20.0, height=5.0)],
        }
    )
    warnings = layout.overflow_warnings(document)
    assert [warning.path for warning in warnings] == ["layers.0.objects.0.objects.0"]
