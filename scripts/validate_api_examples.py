#!/usr/bin/env python3
"""Validate the published REST API examples and the JSON embedded in the specs.

Two guarantees:

* every file in ``specs/api/examples`` validates against the OpenAPI component
  schema it publishes, so a fixture cannot contradict the contract;
* every example a specification embeds as a ``json`` block is identical to its
  example file, so prose and fixture cannot drift apart.

The mappings are explicit on purpose: adding an example without declaring its
schema, or embedding one without declaring the pair, fails rather than passing
silently.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

import jsonschema
import yaml
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "specs"
OPENAPI_PATH = SPECS / "api" / "openapi.yaml"
EXAMPLES_DIR = SPECS / "api" / "examples"

# Example file -> the OpenAPI component schema it must satisfy.
EXAMPLE_SCHEMAS = {
    "ambiguous_calibration_error.json": "ProblemDetails",
    "create_print_job.json": "PrintJobCreateRequest",
    "create_render_job.json": "RenderJobCreateRequest",
    "render_job_response.json": "RenderJob",
    "template_list_response.json": "TemplateList",
    "token_request.json": "TokenRequest",
    "validation_error.json": "ProblemDetails",
}

# Example file -> the specification whose embedded ``json`` block must equal it.
EMBEDDED = {
    "ambiguous_calibration_error.json": SPECS / "api" / "specification.md",
    "create_print_job.json": SPECS / "api" / "specification.md",
    "create_render_job.json": SPECS / "api" / "specification.md",
    "validation_error.json": SPECS / "api" / "specification.md",
}

OPENAPI_URI = OPENAPI_PATH.as_uri()
JSON_BLOCK = re.compile(r"```json\n(.*?)```", re.S)


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def retrieve(uri: str) -> Resource:
    """Load a relative schema reference from disk, e.g. ../renderspec/schema.json."""

    path = Path(url2pathname(urlparse(uri).path))
    return Resource.from_contents(load_json(path), default_specification=DRAFT202012)


def validate_examples(spec: dict) -> list[str]:
    errors: list[str] = []
    schemas = spec.get("components", {}).get("schemas", {})
    registry = Registry(retrieve=retrieve).with_resource(
        OPENAPI_URI, Resource.from_contents(spec, default_specification=DRAFT202012)
    )

    published = {path.name for path in EXAMPLES_DIR.glob("*.json")}
    for name in sorted(published - set(EXAMPLE_SCHEMAS)):
        errors.append(f"{name}: no OpenAPI schema mapped; add it to EXAMPLE_SCHEMAS")

    for name, schema_name in sorted(EXAMPLE_SCHEMAS.items()):
        path = EXAMPLES_DIR / name
        if not path.is_file():
            errors.append(f"{name}: mapped example file is missing")
            continue
        if schema_name not in schemas:
            errors.append(f"{name}: OpenAPI schema {schema_name!r} does not exist")
            continue
        validator = jsonschema.Draft202012Validator(
            {"$ref": f"{OPENAPI_URI}#/components/schemas/{schema_name}"}, registry=registry
        )
        try:
            validator.validate(load_json(path))
            print(f"OK  {path.relative_to(ROOT)} against {schema_name}")
        except jsonschema.ValidationError as exc:
            location = "/".join(str(part) for part in exc.absolute_path) or "document"
            errors.append(f"{path.relative_to(ROOT)}: {location}: {exc.message}")
    return errors


def check_embedded() -> list[str]:
    errors: list[str] = []
    cache: dict[Path, list[object]] = {}

    def blocks(path: Path) -> list[object]:
        if path not in cache:
            parsed: list[object] = []
            for index, raw in enumerate(JSON_BLOCK.findall(path.read_text(encoding="utf-8"))):
                try:
                    parsed.append(json.loads(raw))
                except json.JSONDecodeError as exc:
                    errors.append(f"{path.relative_to(ROOT)}: json block {index + 1}: {exc}")
            cache[path] = parsed
        return cache[path]

    for spec_path in sorted(SPECS.glob("*/specification.md")):
        blocks(spec_path)

    for name, spec_path in sorted(EMBEDDED.items()):
        example_path = EXAMPLES_DIR / name
        if not example_path.is_file():
            errors.append(f"{name}: embedded example file is missing")
            continue
        if not blocks(spec_path) or load_json(example_path) not in blocks(spec_path):
            errors.append(f"{spec_path.relative_to(ROOT)}: no json block equals {name}")
        else:
            print(f"OK  {spec_path.relative_to(ROOT)} embeds {name} unchanged")
    return errors


def main() -> int:
    if not OPENAPI_PATH.is_file():
        print(f"OpenAPI file not found: {OPENAPI_PATH}", file=sys.stderr)
        return 1

    spec = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    errors = validate_examples(spec) + check_embedded()

    for message in errors:
        print(f"FAIL {message}", file=sys.stderr)
    if errors:
        print(f"\nAPI example validation failed ({len(errors)} error(s)).", file=sys.stderr)
        return 1
    print("\nAll API examples validated against the OpenAPI contract.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
