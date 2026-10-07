#!/usr/bin/env python3
"""Validate the published OpenAPI specification."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from openapi_spec_validator import validate
from openapi_spec_validator.readers import read_from_filename

ROOT = Path(__file__).resolve().parents[1]
OPENAPI_PATH = ROOT / "specs" / "api" / "openapi.yaml"


def main() -> int:
    if not OPENAPI_PATH.is_file():
        print(f"OpenAPI file not found: {OPENAPI_PATH}", file=sys.stderr)
        return 1

    print(f"Validating {OPENAPI_PATH.relative_to(ROOT)}...")
    spec = read_from_filename(str(OPENAPI_PATH))
    validate(spec)
    print("OpenAPI specification is valid.")

    examples_dir = OPENAPI_PATH.parent / "examples"
    if examples_dir.is_dir():
        for example in sorted(examples_dir.glob("*.json")):
            try:
                json.loads(example.read_text(encoding="utf-8"))
                print(f"OK  {example.relative_to(ROOT)} (parseable JSON)")
            except json.JSONDecodeError as exc:
                print(f"FAIL {example.relative_to(ROOT)}: {exc}", file=sys.stderr)
                return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
