"""Tests for `renderer/coordinates.py`: RenderSpec Section 3 units and Section 9 transforms."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from renderer import coordinates  # noqa: E402

TOLERANCE = 1e-9


def assert_point(observed: tuple[float, float], expected: tuple[float, float]) -> None:
    assert observed[0] == pytest.approx(expected[0], abs=TOLERANCE)
    assert observed[1] == pytest.approx(expected[1], abs=TOLERANCE)


def test_identity_leaves_points_unchanged() -> None:
    assert_point(coordinates.IDENTITY.apply((3.5, -2.0)), (3.5, -2.0))


def test_translation_moves_along_the_axes() -> None:
    assert_point(coordinates.Affine.translation(10.0, 20.0).apply((1.0, 2.0)), (11.0, 22.0))


def test_rotation_is_clockwise_on_a_y_down_page() -> None:
    rotated = coordinates.Affine.rotation(90.0)
    assert_point(rotated.apply((10.0, 0.0)), (0.0, 10.0))
    assert_point(rotated.apply((0.0, 10.0)), (-10.0, 0.0))


def test_object_transform_order_is_translate_rotate_scale() -> None:
    obj = {"x": 100.0, "y": 0.0, "rotation": 90.0, "scale_x": 2.0, "scale_y": 2.0}
    assert_point(coordinates.transform_point(obj, (10.0, 0.0)), (100.0, 20.0))


def test_scale_applies_before_rotation() -> None:
    obj = {"rotation": 90.0, "scale_x": 2.0, "scale_y": 3.0}
    assert_point(coordinates.transform_point(obj, (10.0, 10.0)), (-30.0, 20.0))


def test_custom_transforms_compose_in_list_order() -> None:
    obj = {
        "transforms": [
            {"type": "translate", "x": 5.0, "y": 0.0},
            {"type": "rotate", "angle": 90.0},
        ]
    }
    assert_point(coordinates.transform_point(obj, (10.0, 0.0)), (5.0, 10.0))


def test_rotate_operation_can_name_its_centre() -> None:
    obj = {"transforms": [{"type": "rotate", "angle": 90.0, "cx": 10.0, "cy": 10.0}]}
    assert_point(coordinates.transform_point(obj, (20.0, 10.0)), (10.0, 20.0))


def test_matrix_operation_uses_the_six_documented_values() -> None:
    obj = {"transforms": [{"type": "matrix", "matrix": [1.0, 0.0, 0.0, 1.0, 5.0, 7.0]}]}
    assert_point(coordinates.transform_point(obj, (1.0, 1.0)), (6.0, 8.0))


def test_parent_matrix_composes_with_the_object() -> None:
    group = coordinates.object_matrix({"x": 10.0, "y": 5.0})
    child = {"x": 2.0, "y": 2.0}
    assert_point(coordinates.transform_point(child, (0.0, 0.0), group), (12.0, 7.0))


def test_points_convert_to_millimetres() -> None:
    assert coordinates.points_to_mm(72.0) == pytest.approx(25.4, abs=TOLERANCE)
    assert coordinates.points_to_mm(10.0) == pytest.approx(3.5277777777777777, abs=1e-12)


def test_unknown_transform_operation_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown transform operation"):
        coordinates.object_matrix({"transforms": [{"type": "skew"}]})
