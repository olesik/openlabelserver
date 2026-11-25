"""Tests for `renderer/svg.py`: the RenderSpec Section 7.2.1 artwork profile."""

from __future__ import annotations

from pathlib import Path

import pytest

from renderer import svg

ASSETS = Path(__file__).resolve().parent / "conformance" / "fixtures" / "renderspec" / "assets"
LOGO = ASSETS / "logo.svg"


def parse(
    markup: str, *, width: float = 20.0, height: float = 10.0, stretch: bool = False
) -> svg.Artwork:
    """Parse one inline SVG document into the shapes it paints."""

    return svg.parse(markup.encode("utf-8"), width=width, height=height, stretch=stretch)


def test_a_viewbox_is_fitted_and_centred_in_the_image_box() -> None:
    artwork = parse(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 20">'
        '<rect width="10" height="20" fill="#000000"/></svg>',
        width=30.0,
        height=30.0,
    )
    (shape,) = artwork.shapes
    assert shape.matrix.apply((0.0, 0.0)) == pytest.approx((7.5, 0.0))
    assert shape.matrix.apply((10.0, 20.0)) == pytest.approx((22.5, 30.0))


def test_preserve_aspect_ratio_none_stretches_each_axis() -> None:
    artwork = parse(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 20" '
        'preserveAspectRatio="none"><rect width="10" height="20"/></svg>',
        width=30.0,
        height=30.0,
    )
    (shape,) = artwork.shapes
    assert shape.matrix.apply((10.0, 20.0)) == pytest.approx((30.0, 30.0))


def test_the_image_preserve_aspect_ratio_overrides_the_root_attribute() -> None:
    markup = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 20">'
        '<rect width="10" height="20"/></svg>'
    )
    fitted = parse(markup, width=30.0, height=30.0).shapes[0]
    stretched = parse(markup, width=30.0, height=30.0, stretch=True).shapes[0]
    assert fitted.matrix.apply((10.0, 20.0)) == pytest.approx((22.5, 30.0))
    assert stretched.matrix.apply((10.0, 20.0)) == pytest.approx((30.0, 30.0))


def test_a_slice_alignment_fills_the_box_and_overflows_it() -> None:
    artwork = parse(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" '
        'preserveAspectRatio="xMidYMid slice"><rect width="10" height="10"/></svg>',
        width=20.0,
        height=10.0,
    )
    (shape,) = artwork.shapes
    assert shape.matrix.apply((0.0, 0.0)) == pytest.approx((0.0, -5.0))
    assert shape.matrix.apply((10.0, 10.0)) == pytest.approx((20.0, 15.0))


def test_without_a_viewbox_one_user_unit_is_one_millimetre() -> None:
    artwork = parse(
        '<svg xmlns="http://www.w3.org/2000/svg"><rect x="1" y="2" width="10" height="4"/></svg>'
    )
    (shape,) = artwork.shapes
    assert shape.matrix.apply((0.0, 0.0)) == pytest.approx((1.0, 2.0))
    assert shape.matrix.apply((10.0, 4.0)) == pytest.approx((11.0, 6.0))


def test_groups_inherit_paint_and_compose_their_transform() -> None:
    artwork = parse(
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<g fill="red" transform="translate(2 3)"><rect width="1" height="1"/></g></svg>'
    )
    (shape,) = artwork.shapes
    assert shape.fill == "#FF0000"
    assert shape.stroke is None
    assert shape.matrix.apply((0.0, 0.0)) == pytest.approx((2.0, 3.0))


def test_transform_functions_compose_in_the_order_they_are_written() -> None:
    artwork = parse(
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<rect width="1" height="1" transform="translate(10 0) scale(2)"/></svg>'
    )
    (shape,) = artwork.shapes
    assert shape.matrix.apply((1.0, 0.0)) == pytest.approx((12.0, 0.0))


def test_a_rotation_turns_about_its_own_centre() -> None:
    artwork = parse(
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<rect width="4" height="2" transform="rotate(90 2 1)"/></svg>'
    )
    (shape,) = artwork.shapes
    assert shape.matrix.apply((0.0, 0.0)) == pytest.approx((3.0, -1.0))


def test_a_style_declaration_wins_over_the_attribute() -> None:
    artwork = parse(
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<rect width="1" height="1" fill="red" style="fill:blue;stroke:#000"/></svg>'
    )
    (shape,) = artwork.shapes
    assert shape.fill == "#0000FF"
    assert shape.stroke == "#000"


def test_keywords_none_dashes_and_the_even_odd_rule_reach_the_shape() -> None:
    artwork = parse(
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<path d="M 0 0 L 4 0 L 4 4 Z" fill="white" stroke="black" stroke-width="0.25" '
        'stroke-dasharray="1 2 3" fill-rule="evenodd"/></svg>'
    )
    (shape,) = artwork.shapes
    assert shape.fill == "#FFFFFF"
    assert shape.stroke == "#000000"
    assert shape.width == 0.25
    assert shape.dash == (1.0, 2.0, 3.0, 1.0, 2.0, 3.0)
    assert shape.evenodd is True


def test_opacity_multiplies_down_the_tree_and_paints_multiply_their_own() -> None:
    artwork = parse(
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<g opacity="0.5"><rect width="1" height="1" opacity="0.5" fill-opacity="0.5" '
        'stroke-opacity="0.25" stroke="#000"/></g></svg>'
    )
    (shape,) = artwork.shapes
    assert shape.opacity == pytest.approx(0.25)
    assert shape.fill_opacity == 0.5
    assert shape.stroke_opacity == 0.25


def test_fill_none_paints_no_fill_and_no_stroke_paints_nothing() -> None:
    artwork = parse(
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<rect width="1" height="1" fill="none"/>'
        '<rect width="1" height="1" fill="none" stroke="none"/></svg>'
    )
    assert artwork.shapes == ()


def test_a_zero_sized_rectangle_and_a_zero_stroke_paint_nothing() -> None:
    artwork = parse(
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<rect width="0" height="4"/>'
        '<rect width="4" height="4" fill="none" stroke="black" stroke-width="0"/></svg>'
    )
    assert artwork.shapes == ()


def test_an_unsupported_element_is_reported_by_name() -> None:
    with pytest.raises(svg.SvgError, match="<text>"):
        parse('<svg xmlns="http://www.w3.org/2000/svg"><text x="0" y="0">OL</text></svg>')


@pytest.mark.parametrize("element", ["linearGradient", "use", "image", "filter", "mask", "script"])
def test_every_element_outside_the_profile_is_reported(element: str) -> None:
    with pytest.raises(svg.SvgError, match=element):
        parse(f'<svg xmlns="http://www.w3.org/2000/svg"><{element}/></svg>')


def test_a_paint_server_reference_is_reported() -> None:
    with pytest.raises(svg.SvgError, match="paint"):
        parse(
            '<svg xmlns="http://www.w3.org/2000/svg">'
            '<rect width="1" height="1" fill="url(#grad)"/></svg>'
        )


@pytest.mark.parametrize("value", ["50%", "2mm", "3pt", "1em"])
def test_a_percentage_or_a_physical_length_is_reported(value: str) -> None:
    with pytest.raises(svg.SvgError, match="user-unit"):
        parse(f'<svg xmlns="http://www.w3.org/2000/svg"><rect width="{value}" height="1"/></svg>')


def test_a_doctype_is_rejected_before_any_entity_is_expanded() -> None:
    markup = (
        '<!DOCTYPE svg [<!ENTITY mark "x">]>'
        '<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>'
    )
    with pytest.raises(svg.SvgError, match="document type declaration"):
        parse(markup)


def test_malformed_xml_and_a_foreign_root_are_reported() -> None:
    with pytest.raises(svg.SvgError, match="well-formed"):
        parse("<svg><rect></svg>")
    with pytest.raises(svg.SvgError, match="root element"):
        parse('<html xmlns="http://www.w3.org/1999/xhtml"/>')


def test_an_elliptical_arc_is_reported_as_the_path_object_reports_it() -> None:
    with pytest.raises(svg.SvgError, match="elliptical arc"):
        parse(
            '<svg xmlns="http://www.w3.org/2000/svg">'
            '<path d="M 0 0 A 5 5 0 0 1 10 10"/></svg>'
        )


def test_an_unknown_transform_function_is_reported() -> None:
    with pytest.raises(svg.SvgError, match="translate3d"):
        parse(
            '<svg xmlns="http://www.w3.org/2000/svg">'
            '<rect width="1" height="1" transform="translate3d(1, 2, 3)"/></svg>'
        )


def test_the_workspace_logo_fixture_paints_a_group_and_a_stroked_path() -> None:
    artwork = svg.parse(LOGO.read_bytes(), width=20.0, height=10.0)
    assert [shape.fill for shape in artwork.shapes] == ["#0066cc", "#FFFFFF", None]
    assert artwork.shapes[2].stroke == "#000000"
    assert artwork.shapes[2].width == 0.5
