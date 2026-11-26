"""RenderSpec validation for the `/v1` API (API Spec §5.3 and §8.3).

The rules are the published schema at `specs/renderspec/schema.json` — the same
document the renderer and the conformance suite validate fixtures against — so
the API cannot grow a second, narrower definition of a RenderSpec. `format` is
an annotation here as it is there: neither validator asserts date-time spellings.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from functools import cache
from pathlib import Path
from typing import Any

import jsonschema

# The repository root, and `/app` in the image, where the build copies the schema.
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "specs" / "renderspec" / "schema.json"


@cache
def _validator() -> jsonschema.protocols.Validator:
    """The published schema's own validator, loaded once per process."""

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return jsonschema.validators.validator_for(schema)(schema)


def _field(path: Iterable[Any]) -> str:
    """Render a schema path as the dotted path API §5.3 shows: `layers[0].objects[1].width`."""

    text = ""
    for part in path:
        text += f"[{part}]" if isinstance(part, int) else (f".{part}" if text else str(part))
    return text


def errors_for(document: Any) -> list[dict[str, str]]:
    """The `errors` entries API §5.3 requires for a document that fails the schema."""

    found: list[dict[str, str]] = []
    for error in _validator().iter_errors(document):
        field = _field(error.absolute_path)
        if error.validator == "required":
            # The path names the object that lacks the property; jsonschema reports
            # one error per missing property, so the field is that property.
            missing = [name for name in error.validator_value if name not in error.instance]
            if len(missing) == 1:
                field = _field([*error.absolute_path, missing[0]])
        found.append({"field": field, "code": str(error.validator or ""), "message": error.message})
    return found
