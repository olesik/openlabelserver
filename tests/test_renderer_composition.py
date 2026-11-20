"""Tests for `renderer/composition.py`: RenderSpec Sections 6, 8.1 and 9."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from renderer import composition

TOLERANCE = 1e-9


def document(layers: list[dict[str, Any]]) -> dict[str, Any]:
    """A minimal page-absolute document carrying `layers`."""

    return {
        "renderspec": "1.0",
        "id": "composition_probe",
        "name": "Composition Probe",
        "page": {"width": 100.0, "height": 50.0},
        "layers": layers,
    }


def layer(layer_id: str, objects: list[dict[str, Any]], **props: Any) -> dict[str, Any]:
    return {"id": layer_id, "name": layer_id.title(), "objects": objects, **props}


def rect(object_id: str, **props: Any) -> dict[str, Any]:
    return {"id": object_id, "type": "rect", "width": 10.0, "height": 20.0, **props}


def group(object_id: str, objects: list[dict[str, Any]], **props: Any) -> dict[str, Any]:
    return {"id": object_id, "type": "group", "objects": objects, **props}


def assert_point(observed: tuple[float, float], expected: tuple[float, float]) -> None:
    assert observed[0] == pytest.approx(expected[0], abs=TOLERANCE)
    assert observed[1] == pytest.approx(expected[1], abs=TOLERANCE)


def test_objects_are_emitted_in_layer_then_object_order() -> None:
    spec = document(
        [
            layer("background", [rect("bg")]),
            layer("foreground", [rect("first"), rect("second")]),
        ]
    )
    drawn = composition.draw_list(spec)
    assert [entry.object["id"] for entry in drawn] == ["bg", "first", "second"]
    assert [entry.path for entry in drawn] == [
        "layers.0.objects.0",
        "layers.1.objects.0",
        "layers.1.objects.1",
    ]


def test_hidden_layer_contributes_nothing() -> None:
    spec = document(
        [
            layer("base", [rect("shown")]),
            layer("overlay", [rect("hidden_by_layer")], visible=False),
        ]
    )
    assert [entry.object["id"] for entry in composition.draw_list(spec)] == ["shown"]


def test_hidden_object_and_hidden_group_contribute_nothing() -> None:
    spec = document(
        [
            layer(
                "base",
                [
                    rect("shown"),
                    rect("hidden_object", visible=False),
                    group("hidden_group", [rect("inside")], visible=False),
                ],
            )
        ]
    )
    assert [entry.object["id"] for entry in composition.draw_list(spec)] == ["shown"]


def test_visibility_defaults_to_true() -> None:
    spec = document([layer("base", [rect("drawn")])])
    assert [entry.object["id"] for entry in composition.draw_list(spec)] == ["drawn"]


def test_layer_opacity_multiplies_object_opacity() -> None:
    spec = document([layer("base", [rect("probe", opacity=0.5)], opacity=0.5)])
    (entry,) = composition.draw_list(spec)
    assert entry.alpha == pytest.approx(0.25, abs=TOLERANCE)


def test_group_opacity_multiplies_into_children() -> None:
    spec = document(
        [
            layer(
                "base",
                [
                    group(
                        "shade",
                        [rect("nested", opacity=0.5), rect("plain")],
                        opacity=0.5,
                    )
                ],
                opacity=0.5,
            )
        ]
    )
    alphas = {entry.object["id"]: entry.alpha for entry in composition.draw_list(spec)}
    assert alphas["nested"] == pytest.approx(0.125, abs=TOLERANCE)
    assert alphas["plain"] == pytest.approx(0.25, abs=TOLERANCE)


def test_opacity_defaults_to_one() -> None:
    spec = document([layer("base", [rect("probe")])])
    (entry,) = composition.draw_list(spec)
    assert entry.alpha == pytest.approx(1.0, abs=TOLERANCE)
    assert entry.matrix == composition.IDENTITY


def test_matrix_is_translate_rotate_scale_custom() -> None:
    spec = document(
        [
            layer(
                "base",
                [
                    rect(
                        "probe",
                        x=10.0,
                        y=20.0,
                        rotation=90.0,
                        scale_x=2.0,
                        scale_y=3.0,
                        transforms=[{"type": "translate", "x": 5.0, "y": 5.0}],
                    )
                ],
            )
        ]
    )
    (entry,) = composition.draw_list(spec)
    # M_custom is the innermost factor: (1, 0) -> custom translate (6, 5) ->
    # scale (12, 15) -> rotation (-15, 12) -> anchor (10, 20) = (-5, 32).
    assert_point(entry.matrix.apply((1.0, 0.0)), (-5.0, 32.0))


def test_rotation_is_clockwise_about_the_anchor() -> None:
    spec = document([layer("base", [rect("probe", x=30.0, y=40.0, rotation=90.0)])])
    (entry,) = composition.draw_list(spec)
    assert_point(entry.matrix.apply((0.0, 0.0)), (30.0, 40.0))
    # A point on the positive X-axis moves toward positive Y, as Y increases down.
    assert_point(entry.matrix.apply((10.0, 0.0)), (30.0, 50.0))


def test_transform_array_applies_in_array_order() -> None:
    def probe(transforms: list[dict[str, Any]]) -> tuple[float, float]:
        spec = document([layer("base", [rect("probe", transforms=transforms)])])
        (entry,) = composition.draw_list(spec)
        return entry.matrix.apply((10.0, 0.0))

    # Each entry is expressed in the frame the previous entries establish, so
    # `translate` then `rotate` turns the object's own coordinates first.
    assert_point(
        probe([{"type": "translate", "x": 5.0, "y": 0.0}, {"type": "rotate", "angle": 90.0}]),
        (5.0, 10.0),
    )
    assert_point(
        probe([{"type": "rotate", "angle": 90.0}, {"type": "translate", "x": 5.0, "y": 0.0}]),
        (0.0, 15.0),
    )


def test_offsets_are_relative_to_the_containing_group() -> None:
    spec = document(
        [layer("base", [group("container", [rect("probe", x=10.0, y=10.0)], x=5.0, y=5.0)])]
    )
    (entry,) = composition.draw_list(spec)
    assert entry.path == "layers.0.objects.0.objects.0"
    assert_point(entry.matrix.apply((0.0, 0.0)), (15.0, 15.0))


def test_draw_list_does_not_mutate_the_document() -> None:
    spec = document(
        [
            layer(
                "base",
                [rect("probe", x=1.0, rotation=45.0), group("wrap", [rect("child")], opacity=0.5)],
                opacity=0.75,
                visible=True,
            )
        ]
    )
    original = copy.deepcopy(spec)
    composition.draw_list(spec)
    assert spec == original
