#!/usr/bin/env python3
"""Validate the published REST API examples and the JSON embedded in the specs.

Three guarantees:

* every file in ``specs/api/examples`` validates against the OpenAPI component
  schema it publishes, so a fixture cannot contradict the contract;
* every example a specification embeds as a ``json`` block is identical to its
  example file, so prose and fixture cannot drift apart;
* every other embedded block is either validated against its named OpenAPI
  schema or exempted with a reason, so no block escapes the check silently.

The mappings are explicit on purpose: adding an example without declaring its
schema, embedding a block without declaring what validates it, or leaving a
stale entry behind all fail rather than passing quietly.
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
API_SPEC = SPECS / "api" / "specification.md"

OPENAPI_URI = OPENAPI_PATH.as_uri()
JSON_OPEN = "```json"
HEADING = re.compile(r"^#{2,4} (.+)$")

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

# Example file -> the specification whose embedded block must equal it.
EMBEDDED = {
    "ambiguous_calibration_error.json": API_SPEC,
    "create_print_job.json": API_SPEC,
    "create_render_job.json": API_SPEC,
    "validation_error.json": API_SPEC,
}

# (specification, section heading, block index within that section) -> schema.
INLINE_BLOCKS = {
    ("specs/api/specification.md", "4.3 Token Issuance", 0): "TokenResponse",
    ("specs/api/specification.md", "4.5 Principal Identity", 0): "User",
    ("specs/api/specification.md", "6.2 Paginated Response Envelope", 0): "ListEnvelope",
    ("specs/api/specification.md", "8.7 Render Jobs", 1): "RenderJobCreateRequest",
}

# Blocks that deliberately have no schema, with the reason they are exempt.
EXEMPT_BLOCKS = {
    ("specs/conformance/specification.md", "16. Conformance Report Format", 0): (
        "the report shape is validated by the CR-1-CR-7 checks in tests/conformance"
    ),
}


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def retrieve(uri: str) -> Resource:
    """Load a relative schema reference from disk, e.g. ../renderspec/schema.json."""

    path = Path(url2pathname(urlparse(uri).path))
    return Resource.from_contents(load_json(path), default_specification=DRAFT202012)


def validator_for(schema_name: str, registry: Registry) -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(
        {"$ref": f"{OPENAPI_URI}#/components/schemas/{schema_name}"}, registry=registry
    )


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
        try:
            validator_for(schema_name, registry).validate(load_json(path))
            print(f"OK  {path.relative_to(ROOT)} against {schema_name}")
        except jsonschema.ValidationError as exc:
            location = "/".join(str(part) for part in exc.absolute_path) or "document"
            errors.append(f"{path.relative_to(ROOT)}: {location}: {exc.message}")
    return errors


def embedded_blocks(path: Path) -> tuple[list[tuple[str, int, object]], list[str]]:
    """Return (heading, index within heading, parsed block) plus parse errors."""

    blocks: list[tuple[str, int, object]] = []
    errors: list[str] = []
    heading = ""
    seen: dict[str, int] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    index = 0
    while index < len(lines):
        match = HEADING.match(lines[index])
        if match:
            heading = match.group(1).strip()
        if lines[index].strip() == JSON_OPEN:
            end = index + 1
            while end < len(lines) and lines[end].strip() != "```":
                end += 1
            raw = "\n".join(lines[index + 1 : end])
            position = seen.get(heading, 0)
            seen[heading] = position + 1
            try:
                blocks.append((heading, position, json.loads(raw)))
            except json.JSONDecodeError as exc:
                errors.append(f"{heading} block {position + 1}: {exc}")
            index = end
        index += 1
    return blocks, errors


def check_embedded(spec: dict) -> list[str]:
    errors: list[str] = []
    schemas = spec.get("components", {}).get("schemas", {})
    registry = Registry(retrieve=retrieve).with_resource(
        OPENAPI_URI, Resource.from_contents(spec, default_specification=DRAFT202012)
    )

    by_spec: dict[Path, list[tuple[str, int, object]]] = {}
    for spec_path in sorted(SPECS.glob("*/specification.md")):
        blocks, block_errors = embedded_blocks(spec_path)
        by_spec[spec_path] = blocks
        errors.extend(f"{spec_path.relative_to(ROOT)}: {message}" for message in block_errors)

    for name, spec_path in sorted(EMBEDDED.items()):
        example_path = EXAMPLES_DIR / name
        if not example_path.is_file():
            errors.append(f"{name}: embedded example file is missing")
            continue
        document = load_json(example_path)
        values = [block for _, _, block in by_spec.get(spec_path, [])]
        if document in values:
            print(f"OK  {spec_path.relative_to(ROOT)} embeds {name} unchanged")
        else:
            errors.append(f"{spec_path.relative_to(ROOT)}: no json block equals {name}")

    file_values = {
        spec_path: {json.dumps(load_json(EXAMPLES_DIR / name), sort_keys=True) for name in EMBEDDED}
        for spec_path in set(EMBEDDED.values())
    }

    for spec_path, blocks in by_spec.items():
        rel = spec_path.relative_to(ROOT)
        for heading, position, document in blocks:
            key = (rel.as_posix(), heading, position)
            if key in INLINE_BLOCKS:
                schema_name = INLINE_BLOCKS[key]
                if schema_name not in schemas:
                    errors.append(f"{rel}: {heading}: schema {schema_name!r} does not exist")
                    continue
                try:
                    validator_for(schema_name, registry).validate(document)
                    print(f"OK  {rel} {heading} block {position + 1} against {schema_name}")
                except jsonschema.ValidationError as exc:
                    location = "/".join(str(part) for part in exc.absolute_path) or "document"
                    errors.append(f"{rel}: {heading}: {location}: {exc.message}")
                continue
            if key in EXEMPT_BLOCKS:
                print(f"SKIP {rel} {heading} block {position + 1}: {EXEMPT_BLOCKS[key]}")
                continue
            if json.dumps(document, sort_keys=True) in file_values.get(spec_path, set()):
                continue
            errors.append(
                f"{rel}: {heading} block {position + 1} is not covered; "
                "map it in INLINE_BLOCKS or EXEMPT_BLOCKS"
            )

    for key in sorted({*INLINE_BLOCKS, *EXEMPT_BLOCKS}):
        spec_path = ROOT / key[0]
        blocks = by_spec.get(spec_path, [])
        if not any(heading == key[1] and position == key[2] for heading, position, _ in blocks):
            errors.append(f"{key[0]}: stale mapping for {key[1]} block {key[2] + 1}")
    return errors


def main() -> int:
    if not OPENAPI_PATH.is_file():
        print(f"OpenAPI file not found: {OPENAPI_PATH}", file=sys.stderr)
        return 1

    spec = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    errors = validate_examples(spec) + check_embedded(spec)

    for message in errors:
        print(f"FAIL {message}", file=sys.stderr)
    if errors:
        print(f"\nAPI example validation failed ({len(errors)} error(s)).", file=sys.stderr)
        return 1
    print("\nAll API examples validated against the OpenAPI contract.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
