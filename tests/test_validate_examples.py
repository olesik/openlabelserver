"""Regression tests for `scripts/validate_examples.py`.

Each test builds a miniature repository in `tmp_path` and points the validator's
module-level mappings at it, so the coverage rules can be exercised without
editing the real specifications.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_examples.py"
SPEC_REL = "specs/example/specification.md"

OPENAPI: dict[str, Any] = {
    "openapi": "3.1.0",
    "info": {"title": "Test contract", "version": "1.0"},
    "components": {
        "schemas": {
            "Thing": {
                "type": "object",
                "properties": {"a": {"type": "integer"}},
                "required": ["a"],
            }
        }
    },
}


def load_validator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("validate_examples", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def validator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    module = load_validator()

    examples = tmp_path / "examples"
    examples.mkdir()
    (examples / "thing.json").write_text(json.dumps({"a": 1}), encoding="utf-8")

    spec_file = tmp_path / SPEC_REL
    spec_file.parent.mkdir(parents=True)
    spec_file.write_text('## Example\n\n```json\n{"a": 1}\n```\n', encoding="utf-8")

    openapi_path = tmp_path / "openapi.yaml"
    openapi_path.write_text(yaml.safe_dump(OPENAPI), encoding="utf-8")

    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "EXAMPLES_DIR", examples)
    monkeypatch.setattr(module, "OPENAPI_PATH", openapi_path)
    monkeypatch.setattr(module, "OPENAPI_URI", openapi_path.as_uri())
    monkeypatch.setattr(module, "DOCS", (spec_file,))
    monkeypatch.setattr(module, "EXAMPLE_SCHEMAS", {"thing.json": "Thing"})
    monkeypatch.setattr(module, "EMBEDDED", {(SPEC_REL, "thing.json"): "equal"})
    monkeypatch.setattr(module, "INLINE_BLOCKS", {})
    monkeypatch.setattr(module, "EXEMPT_BLOCKS", {})
    monkeypatch.setattr(module, "FRAGMENT_BLOCKS", {})
    monkeypatch.setattr(module, "SPEC_SCHEMAS", {})
    return module


def spec_text(validator: ModuleType) -> Path:
    return Path(validator.ROOT) / SPEC_REL


def append_block(validator: ModuleType, heading: str, body: str) -> None:
    with spec_text(validator).open("a", encoding="utf-8") as handle:
        handle.write(f"\n## {heading}\n\n```yaml\n{body}\n```\n")


def errors(validator: ModuleType) -> list[str]:
    return validator.validate_examples(OPENAPI) + validator.check_embedded(OPENAPI)


def test_valid_run_passes(validator: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    assert errors(validator) == []
    assert validator.main() == 0
    assert "All mapped examples match their schemas and files." in capsys.readouterr().out


def test_uncovered_block_fails(validator: ModuleType) -> None:
    append_block(validator, "Extra", "printer: { identifier: x }")

    problems = errors(validator)

    assert any("Extra yaml block 1 is not covered" in problem for problem in problems)


def test_drifted_example_file_fails(validator: ModuleType) -> None:
    example = Path(validator.EXAMPLES_DIR) / "thing.json"
    example.write_text(json.dumps({"a": 2}), encoding="utf-8")

    problems = errors(validator)

    assert any("no equal block matches thing.json" in problem for problem in problems)


def test_unknown_fragment_schema_fails_clearly(
    validator: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    append_block(validator, "Fragment", "printer: { identifier: x }")
    monkeypatch.setattr(
        validator, "FRAGMENT_BLOCKS", {(SPEC_REL, "Fragment", "yaml", 0): "NoSuchSpec"}
    )

    problems = errors(validator)

    assert any("fragment schema 'NoSuchSpec' is not defined" in problem for problem in problems)
    assert any("known schemas:" in problem for problem in problems)


def test_missing_fragment_schema_file_fails_clearly(
    validator: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    append_block(validator, "Fragment", "printer: { identifier: x }")
    monkeypatch.setattr(
        validator, "FRAGMENT_BLOCKS", {(SPEC_REL, "Fragment", "yaml", 0): "CalibrationSpec"}
    )
    monkeypatch.setattr(
        validator, "SPEC_SCHEMAS", {"CalibrationSpec": Path(validator.ROOT) / "missing-schema.json"}
    )

    problems = errors(validator)

    assert any(
        "fragment schema 'CalibrationSpec' is missing at missing-schema.json" in problem
        for problem in problems
    )


def test_missing_mapped_example_file_fails(validator: ModuleType) -> None:
    (Path(validator.EXAMPLES_DIR) / "thing.json").unlink()

    problems = errors(validator)

    assert any("thing.json: mapped example file is missing" in problem for problem in problems)


def test_unknown_example_schema_fails(validator: ModuleType) -> None:
    validator.EXAMPLE_SCHEMAS = {"thing.json": "NoSuchOpenApiSchema"}

    problems = errors(validator)

    assert any(
        "thing.json: OpenAPI schema 'NoSuchOpenApiSchema' does not exist" in problem
        for problem in problems
    )


def test_fragment_that_is_not_a_mapping_fails(
    validator: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    schema_path = Path(validator.ROOT) / "thing-schema.json"
    schema_path.write_text(json.dumps({"type": "object", "properties": {}}), encoding="utf-8")
    append_block(validator, "Fragment", "- offset\n- scale")
    monkeypatch.setattr(validator, "FRAGMENT_BLOCKS", {(SPEC_REL, "Fragment", "yaml", 0): "Thing"})
    monkeypatch.setattr(validator, "SPEC_SCHEMAS", {"Thing": schema_path})

    problems = errors(validator)

    assert any("snippet is list, expected a mapping" in problem for problem in problems)


def test_stale_mapping_fails(validator: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        validator, "INLINE_BLOCKS", {(SPEC_REL, "Missing Section", "json", 0): "Thing"}
    )

    problems = errors(validator)

    assert any("stale mapping for Missing Section json block 1" in problem for problem in problems)
