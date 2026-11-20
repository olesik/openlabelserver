"""Tests for the RenderSpec Section 10 data binding."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from renderer import binding, layout, renderspec

STOCK = {
    "width": 40.0,
    "height": 30.0,
    "rows": 2,
    "columns": 3,
    "margin_left": 10.0,
    "margin_top": 10.0,
    "horizontal_pitch": 55.0,
    "vertical_pitch": 40.0,
}


def text(object_id: str, content: str) -> dict[str, Any]:
    return {"id": object_id, "type": "text", "x": 1.0, "y": 1.0, "content": content}


def document(objects: list[dict[str, Any]], data: list[dict[str, Any]] | None = None) -> dict:
    spec: dict[str, Any] = {
        "renderspec": "1.0",
        "id": "binding_probe",
        "name": "Binding Probe",
        "page": {"width": 100.0, "height": 50.0},
        "layers": [{"id": "base", "name": "Base", "objects": objects}],
    }
    if data is not None:
        spec["data"] = data
    return spec


def stock_document(records: list[dict[str, Any]]) -> dict:
    spec = document([text("probe", "{{n}}")], records)
    spec["page"] = {"width": 200.0, "height": 100.0}
    spec["stock"] = dict(STOCK)
    return spec


def contents(spec: dict) -> list[tuple[str, str]]:
    """Every `(type, content)` pair in drawing order, through groups."""

    found: list[tuple[str, str]] = []

    def walk(objects: list[dict[str, Any]]) -> None:
        for obj in objects:
            if obj.get("type") in binding.CONTENT_TYPES:
                found.append((obj["type"], obj["content"]))
            walk(obj.get("objects", ()))

    for layer in spec["layers"]:
        walk(layer["objects"])
    return found


def test_text_content_resolves_placeholders() -> None:
    spec = document([text("greeting", "Hi {{name}}, welcome to {{city}}")])
    bound = binding.bind(spec, {"name": "Alice", "city": "Springfield"})
    assert contents(bound) == [("text", "Hi Alice, welcome to Springfield")]


def test_barcode_and_qrcode_content_resolve() -> None:
    spec = document(
        [
            {
                "id": "barcode",
                "type": "barcode",
                "x": 1.0,
                "y": 1.0,
                "content": "{{sku}}",
                "symbology": "code128",
                "width": 20.0,
                "height": 10.0,
            },
            {
                "id": "qrcode",
                "type": "qrcode",
                "x": 1.0,
                "y": 20.0,
                "content": "https://openlabelserver.org/{{sku}}",
                "size": 15.0,
            },
        ]
    )
    bound = binding.bind(spec, {"sku": "ABC-123"})
    assert contents(bound) == [
        ("barcode", "ABC-123"),
        ("qrcode", "https://openlabelserver.org/ABC-123"),
    ]


def test_other_properties_keep_their_literal_text() -> None:
    spec = document(
        [
            {
                "id": "outline",
                "type": "path",
                "x": 0.0,
                "y": 0.0,
                "d": "M 0 0 L {{x}} 10 Z",
            },
            text("label", "{{x}}"),
        ]
    )
    original = copy.deepcopy(spec)
    bound = binding.bind(spec, {"x": 7})
    assert contents(bound) == [("text", "7")]
    assert bound["layers"][0]["objects"][0]["d"] == "M 0 0 L {{x}} 10 Z"
    assert spec == original


def test_unresolved_placeholders_resolve_to_the_empty_string() -> None:
    spec = document([text("label", "{{missing}} tail")], [{}])
    bound = binding.bind(spec, spec["data"][0])
    assert contents(bound) == [("text", " tail")]
    assert renderspec.parse(bound)["layers"][0]["objects"][0]["content"] == " tail"


def test_numbers_and_booleans_serialise_to_their_json_spelling() -> None:
    spec = document([text("label", "{{qty}}|{{price}}|{{flag}}|{{off}}")])
    bound = binding.bind(spec, {"qty": 3, "price": 1.5, "flag": True, "off": False})
    assert contents(bound) == [("text", "3|1.5|true|false")]


def test_group_children_resolve_too() -> None:
    spec = document(
        [
            {
                "id": "group",
                "type": "group",
                "x": 5.0,
                "y": 5.0,
                "objects": [text("nested", "{{name}}")],
            }
        ]
    )
    bound = binding.bind(spec, {"name": "Alice"})
    assert contents(bound) == [("text", "Alice")]


def test_page_slots_fill_the_grid_in_row_major_order() -> None:
    spec = renderspec.parse(stock_document([{"n": index} for index in range(6)]))
    slots = binding.page_slots(spec)
    assert [slot["n"] for slot in slots[0]] == [0, 1, 2, 3, 4, 5]

    frames = layout.document_frames(spec)
    observed = [(slot["n"], frame.column, frame.row) for slot, frame in zip(slots[0], frames)]
    assert observed == [
        (0, 0, 0),
        (1, 1, 0),
        (2, 2, 0),
        (3, 0, 1),
        (4, 1, 1),
        (5, 2, 1),
    ]


def test_page_slots_repeat_the_grid_on_further_pages() -> None:
    seven = renderspec.parse(stock_document([{"n": index} for index in range(7)]))
    pages = binding.page_slots(seven)
    assert [len(page) for page in pages] == [6, 6]
    assert [slot["n"] for slot in pages[0]] == [0, 1, 2, 3, 4, 5]
    assert [pages[1][0]["n"]] == [6]
    assert pages[1][1:] == (None,) * 5

    two = renderspec.parse(stock_document([{"n": 0}, {"n": 1}]))
    (page,) = binding.page_slots(two)
    assert [slot["n"] for slot in page[:2]] == [0, 1]
    assert page[2:] == (None,) * 4


def test_page_slots_reject_page_absolute_documents() -> None:
    with pytest.raises(ValueError, match="page-absolute"):
        binding.page_slots(document([text("label", "{{n}}")], [{"n": 1}]))
