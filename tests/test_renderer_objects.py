"""Tests for `renderer/objects.py`: RenderSpec Section 8.2 object primitives."""

from __future__ import annotations

from typing import Any

import pytest

from renderer import objects
from renderer.coordinates import points_to_mm


def obj(**props: Any) -> dict[str, Any]:
    """One object as a layer carries it."""

    return {"id": "probe", **props}


def test_text_defaults_follow_section_8_2_1() -> None:
    text = objects.primitive(obj(type="text", content="Open Label"))
    assert isinstance(text, objects.Text)
    assert text.content == "Open Label"
    assert text.size == pytest.approx(points_to_mm(10.0), abs=1e-12)
    assert text.font_family is None
    assert (text.font_weight, text.font_style) == ("normal", "normal")
    assert text.color == "#000000"
    assert (text.align, text.valign) == ("left", "top")
    assert text.line_spacing == 1.0
    assert text.wrap is False
    assert text.width is None and text.height is None


def test_font_size_converts_points_to_millimetres() -> None:
    text = objects.primitive(obj(type="text", content="x", font_size=10.0))
    assert text.size == pytest.approx(3.5277777777777777, abs=1e-12)
    assert text.size == pytest.approx(10.0 * 25.4 / 72.0, abs=1e-12)


def test_text_keeps_its_bounding_box_and_alignment() -> None:
    text = objects.primitive(
        obj(
            type="text",
            content="x",
            width=30.0,
            height=6.0,
            align="center",
            valign="middle",
            wrap=True,
            line_spacing=1.2,
            font_family="Inter",
            color="#333333",
        )
    )
    assert (text.width, text.height) == (30.0, 6.0)
    assert (text.align, text.valign) == ("center", "middle")
    assert text.wrap is True
    assert text.line_spacing == 1.2
    assert text.font_family == "Inter"
    assert text.color == "#333333"


def test_rect_defaults_to_no_fill_and_no_stroke() -> None:
    rect = objects.primitive(obj(type="rect", width=10.0, height=20.0))
    assert isinstance(rect, objects.Rect)
    assert (rect.width, rect.height, rect.rx, rect.ry) == (10.0, 20.0, 0.0, 0.0)
    assert rect.paint == objects.Paint()


def test_rect_keeps_colours_stroke_width_and_corner_radii() -> None:
    rect = objects.primitive(
        obj(
            type="rect",
            width=10.0,
            height=20.0,
            fill_color="#ff0000",
            stroke_color="rgb(0, 0, 255)",
            stroke_width=0.3,
            rx=1.0,
            ry=2.0,
        )
    )
    assert (rect.paint.fill, rect.paint.stroke) == ("#ff0000", "rgb(0, 0, 255)")
    assert rect.paint.width == 0.3
    assert (rect.rx, rect.ry) == (1.0, 2.0)


def test_none_colour_means_that_paint_is_absent() -> None:
    rect = objects.primitive(
        obj(type="rect", width=1.0, height=1.0, fill_color="none", stroke_color="none")
    )
    assert rect.paint.fill is None
    assert rect.paint.stroke is None


def test_circle_and_ellipse_keep_their_radii() -> None:
    circle = objects.primitive(obj(type="circle", r=4.0, fill_color="#000000"))
    assert isinstance(circle, objects.Circle)
    assert circle.r == 4.0
    assert circle.paint.fill == "#000000"

    ellipse = objects.primitive(obj(type="ellipse", rx=3.0, ry=5.0))
    assert isinstance(ellipse, objects.Ellipse)
    assert (ellipse.rx, ellipse.ry) == (3.0, 5.0)


def test_line_is_a_two_point_segment_with_a_black_stroke() -> None:
    line = objects.primitive(obj(type="line", x2=10.0, y2=-4.0))
    assert isinstance(line, objects.Segment)
    assert line.points == ((0.0, 0.0), (10.0, -4.0))
    assert line.closed is False
    assert line.paint.stroke == "#000000"
    assert line.paint.width == 1.0
    assert line.paint.dash == ()


def test_line_keeps_its_dash_pattern() -> None:
    line = objects.primitive(obj(type="line", x2=1.0, y2=1.0, stroke_dasharray=[2.0, 0.5]))
    assert line.paint.dash == (2.0, 0.5)


def test_polyline_is_open_and_unfilled() -> None:
    polyline = objects.primitive(obj(type="polyline", points=[[0, 0], [1, 2], [3, 4]]))
    assert isinstance(polyline, objects.Segment)
    assert polyline.points == ((0.0, 0.0), (1.0, 2.0), (3.0, 4.0))
    assert polyline.closed is False
    assert polyline.paint.fill is None
    assert polyline.paint.stroke == "#000000"


def test_polygon_is_closed_and_keeps_its_fill() -> None:
    polygon = objects.primitive(
        obj(type="polygon", points=[[0, 0], [10, 0], [0, 10]], fill_color="#00ff00")
    )
    assert polygon.closed is True
    assert polygon.paint.fill == "#00ff00"
    assert polygon.paint.stroke is None


def test_path_keeps_its_command_string() -> None:
    path = objects.primitive(obj(type="path", d="M 0 0 L 10 10 Z", stroke_color="#000000"))
    assert isinstance(path, objects.Path)
    assert path.d == "M 0 0 L 10 10 Z"
    assert path.paint.stroke == "#000000"


def test_image_keeps_its_asset_and_scaled_box() -> None:
    image = objects.primitive(obj(type="image", asset_id="logo", width=20.0, height=10.0))
    assert isinstance(image, objects.Image)
    assert image.asset_id == "logo"
    assert (image.width, image.height) == (20.0, 10.0)
    assert image.preserve_aspect_ratio is True


def test_barcode_extents_and_human_readable_text_default() -> None:
    barcode = objects.primitive(
        obj(type="barcode", content="ABC-123", symbology="code128", width=42.0, height=12.0)
    )
    assert isinstance(barcode, objects.Barcode)
    assert (barcode.width, barcode.height) == (42.0, 12.0)
    assert barcode.draw_text is True
    assert (barcode.color, barcode.background) == ("#000000", "#ffffff")


def test_barcode_can_suppress_the_human_readable_text() -> None:
    barcode = objects.primitive(
        obj(
            type="barcode",
            content="123456789012",
            symbology="ean13",
            width=30.0,
            height=10.0,
            draw_text=False,
        )
    )
    assert barcode.draw_text is False


def test_qrcode_size_is_both_grid_dimensions() -> None:
    qrcode = objects.primitive(obj(type="qrcode", content="https://example.org", size=18.0))
    assert isinstance(qrcode, objects.Qrcode)
    assert qrcode.size == 18.0
    assert qrcode.error_correction == "M"
    assert (qrcode.color, qrcode.background) == ("#000000", "#ffffff")


def test_group_and_unknown_types_have_no_primitive() -> None:
    with pytest.raises(ValueError):
        objects.primitive(obj(type="group", objects=[]))
    with pytest.raises(ValueError):
        objects.primitive(obj(type="hexagon"))
