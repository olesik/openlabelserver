"""Tests for `renderer/geometry.py`: Section 8.2 shapes as subpaths."""

from __future__ import annotations

import pytest

from renderer import geometry
from renderer.geometry import Curve, Line


def test_rectangle_is_one_closed_subpath_of_four_lines() -> None:
    (subpath,) = geometry.rectangle(10.0, 20.0)
    assert subpath.start == (0.0, 0.0)
    assert subpath.segments == (Line((10.0, 0.0)), Line((10.0, 20.0)), Line((0.0, 20.0)))
    assert subpath.closed is True
    assert subpath.end == (0.0, 20.0)


def test_rounded_rectangle_replaces_each_corner_with_a_curve() -> None:
    (subpath,) = geometry.rectangle(10.0, 20.0, rx=2.0, ry=1.0)
    assert subpath.closed is True
    curves = [segment for segment in subpath.segments if isinstance(segment, Curve)]
    assert len(curves) == 4
    assert subpath.segments[0] == Line((8.0, 0.0))
    assert curves[0].end == (10.0, 1.0)
    assert curves[0].control1 == pytest.approx((8.0 + 2.0 * geometry.KAPPA, 0.0))
    assert curves[0].control2 == pytest.approx((10.0, 1.0 - 1.0 * geometry.KAPPA))


def test_corner_radius_is_bounded_by_half_the_side() -> None:
    (subpath,) = geometry.rectangle(10.0, 20.0, rx=40.0, ry=40.0)
    assert subpath.segments[0] == Line((5.0, 0.0))
    assert subpath.segments[1].end == pytest.approx((10.0, 10.0))


def test_a_zero_radius_falls_back_to_the_plain_rectangle() -> None:
    assert geometry.rectangle(4.0, 4.0, rx=0.0, ry=2.0) == geometry.rectangle(4.0, 4.0)


def test_circle_is_four_quarter_curves_about_the_anchor() -> None:
    (subpath,) = geometry.circle(5.0)
    assert subpath.start == (5.0, 0.0)
    assert subpath.closed is True
    ends = [segment.end for segment in subpath.segments]
    assert ends == [(0.0, 5.0), (-5.0, 0.0), (0.0, -5.0), (5.0, 0.0)]
    assert subpath.segments[0].control1 == pytest.approx((5.0, 5.0 * geometry.KAPPA))


def test_ellipse_uses_its_own_two_radii() -> None:
    (subpath,) = geometry.ellipse(4.0, 2.0)
    assert subpath.start == (4.0, 0.0)
    assert subpath.segments[0].end == (0.0, 2.0)
    assert subpath.segments[1].end == (-4.0, 0.0)


def test_polyline_keeps_its_vertices_and_open_or_closed_state() -> None:
    (open_path,) = geometry.polyline([[0, 0], [1, 2], [3, 4]])
    assert open_path.start == (0.0, 0.0)
    assert open_path.segments == (Line((1.0, 2.0)), Line((3.0, 4.0)))
    assert open_path.closed is False

    (polygon,) = geometry.polyline([[0, 0], [10, 0], [0, 10]], closed=True)
    assert polygon.closed is True


def test_a_polyline_needs_two_vertices() -> None:
    assert geometry.polyline([[1, 1]]) == ()


def test_svg_path_handles_absolute_commands() -> None:
    (subpath,) = geometry.svg_path("M 0 0 L 10 0 H 20 V 5 Z")
    assert subpath.start == (0.0, 0.0)
    assert subpath.segments == (
        Line((10.0, 0.0)),
        Line((20.0, 0.0)),
        Line((20.0, 5.0)),
    )
    assert subpath.closed is True


def test_svg_path_handles_relative_commands_and_implicit_repetition() -> None:
    (subpath,) = geometry.svg_path("m 1 1 2 0 0 2")
    assert subpath.start == (1.0, 1.0)
    assert subpath.segments == (Line((3.0, 1.0)), Line((3.0, 3.0)))


def test_svg_path_converts_cubics_and_their_smooth_continuation() -> None:
    (subpath,) = geometry.svg_path("M 0 0 C 1 0 2 1 3 1 S 5 2 6 2")
    first, second = subpath.segments
    assert first == Curve((1.0, 0.0), (2.0, 1.0), (3.0, 1.0))
    assert second.control1 == (4.0, 1.0)
    assert second.end == (6.0, 2.0)


def test_svg_path_opens_separate_subpaths_and_breaks_the_smooth_chain() -> None:
    first, second = geometry.svg_path("M 0 0 S 1 1 2 2 M 5 5 L 6 6")
    assert first.start == (0.0, 0.0)
    assert first.segments[0].control1 == (0.0, 0.0)
    assert second.start == (5.0, 5.0)
    assert second.segments == (Line((6.0, 6.0)),)


def test_svg_path_converts_quadratics_and_their_reflection() -> None:
    (subpath,) = geometry.svg_path("M 0 0 Q 2 4 4 0 T 8 0")
    first, second = subpath.segments
    assert first.control1 == pytest.approx((4.0 / 3.0, 8.0 / 3.0))
    assert first.control2 == pytest.approx((4.0 - 4.0 / 3.0, 8.0 / 3.0))
    assert second.control1 == pytest.approx((4.0 + 4.0 / 3.0, -8.0 / 3.0))


def test_svg_path_reports_commands_it_cannot_express() -> None:
    with pytest.raises(geometry.GeometryError, match="arc"):
        geometry.svg_path("M 0 0 A 5 5 0 0 1 10 10")
    with pytest.raises(geometry.GeometryError, match="needs 2"):
        geometry.svg_path("M 0")


def test_empty_path_data_has_no_geometry() -> None:
    assert geometry.svg_path("") == ()
