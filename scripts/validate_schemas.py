#!/usr/bin/env python3
"""Validate specification examples against published JSON Schemas."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "specs"

SPEC_MAP = {
    "renderspec": {
        "schema": SPECS / "renderspec" / "schema.json",
        "examples_glob": "*.json",
    },
    "stockspec": {
        "schema": SPECS / "stockspec" / "schema.json",
        "examples_glob": "*.yaml",
    },
    "calibrationspec": {
        "schema": SPECS / "calibrationspec" / "schema.json",
        "examples_glob": "*.yaml",
    },
}


def load_document(path: Path) -> object:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        return yaml.safe_load(text)
    return json.loads(text)


def validate_spec(name: str, config: dict[str, object]) -> list[str]:
    errors: list[str] = []
    schema_path = Path(str(config["schema"]))
    examples_dir = schema_path.parent / "examples"
    glob_pattern = str(config["examples_glob"])

    if not schema_path.is_file():
        return [f"{name}: schema not found at {schema_path}"]

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft7Validator(schema)

    if not examples_dir.is_dir():
        return [f"{name}: examples directory not found at {examples_dir}"]

    example_files = sorted(examples_dir.glob(glob_pattern))
    if not example_files:
        return [f"{name}: no example files matching {glob_pattern}"]

    for example in example_files:
        try:
            document = load_document(example)
            validator.validate(document)
            print(f"OK  {example.relative_to(ROOT)}")
        except jsonschema.ValidationError as exc:
            rel = example.relative_to(ROOT)
            errors.append(f"{rel}: {exc.message}")
            print(f"FAIL {rel}: {exc.message}", file=sys.stderr)
        except (json.JSONDecodeError, yaml.YAMLError) as exc:
            rel = example.relative_to(ROOT)
            errors.append(f"{rel}: parse error: {exc}")
            print(f"FAIL {rel}: parse error: {exc}", file=sys.stderr)

    return errors


def main() -> int:
    all_errors: list[str] = []
    for name, config in SPEC_MAP.items():
        print(f"Validating {name} examples...")
        all_errors.extend(validate_spec(name, config))

    if all_errors:
        print(f"\nSchema validation failed ({len(all_errors)} error(s)).", file=sys.stderr)
        return 1

    print("\nAll specification examples validated successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
