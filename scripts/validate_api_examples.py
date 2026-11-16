#!/usr/bin/env python3
"""Validate the published examples and the JSON/YAML embedded in the documentation.

Three guarantees:

* every file in ``specs/api/examples`` validates against the OpenAPI component
  schema it publishes, so a fixture cannot contradict the contract;
* every example a specification embeds is identical to (or, for snippets, a
  subset of) its example file, so prose and fixture cannot drift apart;
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
from typing import Any
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

OPENAPI_URI = OPENAPI_PATH.as_uri()
FENCE_OPEN = re.compile(r"^```([A-Za-z]+)\s*$")
HEADING = re.compile(r"^#{2,4} (.+)$")
PARSERS = {"json": json.loads, "yaml": yaml.safe_load, "yml": yaml.safe_load}

# Documents whose embedded blocks must all be accounted for.
DOCS = (*sorted(SPECS.glob("*/specification.md")), ROOT / "README.md")

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

# (document, example file) -> how the embedded block must relate to the file:
# "equal" for a full copy, "subset" for a snippet that quotes part of it.
EMBEDDED = {
    ("specs/api/specification.md", "ambiguous_calibration_error.json"): "equal",
    ("specs/api/specification.md", "create_print_job.json"): "equal",
    ("specs/api/specification.md", "create_render_job.json"): "equal",
    ("specs/api/specification.md", "validation_error.json"): "equal",
    ("README.md", "specs/stockspec/examples/avery_5160.yaml"): "subset",
    (
        "specs/conformance/specification.md",
        "specs/conformance/examples/worked_transform.yaml",
    ): "equal",
}

# (document, section heading, fence language, block index in that section) ->
# OpenAPI component schema.
INLINE_BLOCKS = {
    ("specs/api/specification.md", "4.3 Token Issuance", "json", 0): "TokenResponse",
    ("specs/api/specification.md", "4.5 Principal Identity", "json", 0): "User",
    ("specs/api/specification.md", "6.2 Paginated Response Envelope", "json", 0): "ListEnvelope",
    ("specs/api/specification.md", "8.7 Render Jobs", "json", 1): "RenderJobCreateRequest",
}

# Blocks that deliberately have no file or schema, with the reason they are exempt.
EXEMPT_BLOCKS = {
    ("specs/conformance/specification.md", "16. Conformance Report Format", "json", 0): (
        "the report shape is validated by the CR-1-CR-7 checks in tests/conformance"
    ),
}


def example_path(name: str) -> Path:
    """Resolve a mapped example: a file name under the API examples or a repo path."""

    return ROOT / name if "/" in name else EXAMPLES_DIR / name


def load_example(name: str) -> Any:
    path = example_path(name)
    if path.suffix == ".yaml":
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    return json.loads(path.read_text(encoding="utf-8"))


def retrieve(uri: str) -> Resource:
    """Load a relative schema reference from disk, e.g. ../renderspec/schema.json."""

    path = Path(url2pathname(urlparse(uri).path))
    return Resource.from_contents(
        json.loads(path.read_text(encoding="utf-8")), default_specification=DRAFT202012
    )


def validator_for(schema_name: str, registry: Registry) -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(
        {"$ref": f"{OPENAPI_URI}#/components/schemas/{schema_name}"}, registry=registry
    )


def is_subset(part: Any, whole: Any) -> bool:
    """True when every key and value in ``part`` appears in ``whole``."""

    if isinstance(part, dict) and isinstance(whole, dict):
        return all(key in whole and is_subset(value, whole[key]) for key, value in part.items())
    if isinstance(part, list) and isinstance(whole, list):
        if len(part) != len(whole):
            return False
        return all(is_subset(left, right) for left, right in zip(part, whole, strict=True))
    return part == whole


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
            validator_for(schema_name, registry).validate(load_example(name))
            print(f"OK  {path.relative_to(ROOT)} against {schema_name}")
        except jsonschema.ValidationError as exc:
            location = "/".join(str(part) for part in exc.absolute_path) or "document"
            errors.append(f"{path.relative_to(ROOT)}: {location}: {exc.message}")
    return errors


def embedded_blocks(path: Path) -> tuple[list[tuple[str, str, int, Any]], list[str]]:
    """Return (heading, language, index in heading, parsed block) plus parse errors."""

    blocks: list[tuple[str, str, int, Any]] = []
    errors: list[str] = []
    heading = ""
    seen: dict[tuple[str, str], int] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    index = 0
    while index < len(lines):
        match = HEADING.match(lines[index])
        if match:
            heading = match.group(1).strip()
        fence = FENCE_OPEN.match(lines[index])
        if fence:
            language = fence.group(1).lower()
            end = index + 1
            while end < len(lines) and lines[end].strip() != "```":
                end += 1
            if language in PARSERS:
                position = seen.get((heading, language), 0)
                seen[(heading, language)] = position + 1
                raw = "\n".join(lines[index + 1 : end])
                try:
                    blocks.append((heading, language, position, PARSERS[language](raw)))
                except (json.JSONDecodeError, yaml.YAMLError) as exc:
                    errors.append(f"{heading} {language} block {position + 1}: {exc}")
            index = end
        index += 1
    return blocks, errors


def check_embedded(spec: dict) -> list[str]:
    errors: list[str] = []
    schemas = spec.get("components", {}).get("schemas", {})
    registry = Registry(retrieve=retrieve).with_resource(
        OPENAPI_URI, Resource.from_contents(spec, default_specification=DRAFT202012)
    )

    by_doc: dict[Path, list[tuple[str, str, int, Any]]] = {}
    for doc in DOCS:
        blocks, block_errors = embedded_blocks(doc)
        by_doc[doc.resolve()] = blocks
        errors.extend(f"{doc.relative_to(ROOT)}: {message}" for message in block_errors)

    for (doc_name, name), mode in sorted(EMBEDDED.items()):
        doc = (ROOT / doc_name).resolve()
        if not example_path(name).is_file():
            errors.append(f"{name}: embedded example file is missing")
            continue
        expected = load_example(name)
        found = any(
            block == expected or (mode == "subset" and is_subset(block, expected))
            for _, _, _, block in by_doc.get(doc, [])
        )
        if found:
            print(f"OK  {doc_name} embeds {name} ({mode})")
        else:
            errors.append(f"{doc_name}: no {mode} block matches {name}")

    pairs_by_doc: dict[str, list[tuple[Any, str]]] = {}
    for (doc_name, name), mode in EMBEDDED.items():
        pairs_by_doc.setdefault(doc_name, []).append((load_example(name), mode))

    for doc, blocks in by_doc.items():
        rel = doc.relative_to(ROOT).as_posix()
        for heading, language, position, block in blocks:
            key = (rel, heading, language, position)
            if key in INLINE_BLOCKS:
                schema_name = INLINE_BLOCKS[key]
                if schema_name not in schemas:
                    errors.append(f"{rel}: {heading}: schema {schema_name!r} does not exist")
                    continue
                try:
                    validator_for(schema_name, registry).validate(block)
                    print(
                        f"OK  {rel} {heading} {language} block {position + 1} against {schema_name}"
                    )
                except jsonschema.ValidationError as exc:
                    location = "/".join(str(part) for part in exc.absolute_path) or "document"
                    errors.append(f"{rel}: {heading}: {location}: {exc.message}")
                continue
            if key in EXEMPT_BLOCKS:
                print(f"SKIP {rel} {heading} {language} block {position + 1}: {EXEMPT_BLOCKS[key]}")
                continue
            if any(
                block == expected or (mode == "subset" and is_subset(block, expected))
                for expected, mode in pairs_by_doc.get(rel, [])
            ):
                continue
            errors.append(
                f"{rel}: {heading} {language} block {position + 1} is not covered; "
                "pair it in EMBEDDED, map it in INLINE_BLOCKS or EXEMPT_BLOCKS"
            )

    for key in sorted({*INLINE_BLOCKS, *EXEMPT_BLOCKS}):
        blocks = by_doc.get((ROOT / key[0]).resolve(), [])
        if not any(
            (heading, language, position) == (key[1], key[2], key[3])
            for heading, language, position, _ in blocks
        ):
            errors.append(f"{key[0]}: stale mapping for {key[1]} {key[2]} block {key[3] + 1}")
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
    print("\nAll mapped examples match their schemas and files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
