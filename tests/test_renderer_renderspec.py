"""Tests for `renderer/renderspec.py`, the schema-driven RenderSpec parser."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from renderer import renderspec  # noqa: E402

EXAMPLES = ROOT / "specs" / "renderspec" / "examples"
FIXTURES = ROOT / "tests" / "conformance" / "fixtures" / "renderspec"

EXAMPLES_UNDER_TEST = ("simple_label.json", "sheet_labels.json", "barcode_label.json")


def _minimal() -> dict:
    return {
        "renderspec": "1.0",
        "id": "minimal",
        "name": "Minimal",
        "page": {"width": 50.0, "height": 30.0},
        "layers": [{"id": "base", "name": "Base", "objects": []}],
    }


def _paths(exc: renderspec.RenderSpecError) -> list[str]:
    return [diagnostic.path for diagnostic in exc.diagnostics]


@pytest.mark.parametrize("name", EXAMPLES_UNDER_TEST)
def test_published_examples_parse(name: str) -> None:
    document = renderspec.load(EXAMPLES / name)
    assert document["renderspec"] == "1.0"


def test_accepts_the_minimal_fixture() -> None:
    document = renderspec.load(FIXTURES / "valid" / "minimal_valid.json")
    assert [layer["id"] for layer in document["layers"]] == ["base"]


def test_strict_mode_rejects_an_unknown_property_with_its_path() -> None:
    with pytest.raises(renderspec.RenderSpecError) as info:
        renderspec.load(FIXTURES / "invalid" / "unknown_property.json")
    assert _paths(info.value) == ["page"]


def test_strict_mode_rejects_a_version_other_than_1_0() -> None:
    with pytest.raises(renderspec.RenderSpecError) as info:
        renderspec.load(FIXTURES / "invalid" / "version_1_1.json")
    assert _paths(info.value) == ["renderspec"]


def test_missing_required_member_names_the_member() -> None:
    with pytest.raises(renderspec.RenderSpecError) as info:
        renderspec.load(FIXTURES / "invalid" / "missing_page.json")
    assert _paths(info.value) == ["page"]


def test_rejects_non_finite_geometry_with_its_path() -> None:
    with pytest.raises(renderspec.RenderSpecError) as info:
        renderspec.load(FIXTURES / "invalid" / "nonfinite_coordinate.json")
    assert _paths(info.value) == ["layers.0.objects.2.x"]
    assert "finite" in str(info.value)


def test_rejects_a_document_that_is_not_an_object() -> None:
    with pytest.raises(renderspec.RenderSpecError) as info:
        renderspec.parse([_minimal()])
    assert _paths(info.value) == [""]


def test_rejects_malformed_json_with_a_parse_diagnostic(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text('{"renderspec": "1.0",', encoding="utf-8")
    with pytest.raises(renderspec.RenderSpecError) as info:
        renderspec.load(broken)
    assert "not valid JSON" in str(info.value)


def test_strict_is_the_default_mode() -> None:
    document = json.loads((FIXTURES / "invalid" / "unknown_property.json").read_text())
    with pytest.raises(renderspec.RenderSpecError):
        renderspec.parse(document)


def test_forward_mode_drops_only_unknown_properties() -> None:
    document = renderspec.load(FIXTURES / "invalid" / "unknown_property.json", strict=False)
    assert "bleed" not in document["page"]
    assert document["page"]["width"] == 50.0
    assert document["layers"][0]["objects"][0]["content"] == "Hello"


def test_forward_mode_still_enforces_recognized_properties() -> None:
    with pytest.raises(renderspec.RenderSpecError) as info:
        renderspec.load(FIXTURES / "invalid" / "layer_opacity_out_of_range.json", strict=False)
    assert _paths(info.value) == ["layers.0.opacity"]


def test_forward_mode_drops_unknown_members_at_the_root() -> None:
    document = _minimal()
    document["unknown"] = {"anything": True}
    parsed = renderspec.parse(document, strict=False)
    assert "unknown" not in parsed
