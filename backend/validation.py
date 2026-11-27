"""Domain document validation for the `/v1` API (API Spec §5.3 and §8.3 to §8.5).

The rules are the published schemas — the same documents the renderer, the printing
engine and the conformance suite validate fixtures against — so the API cannot grow a
second, narrower definition of a RenderSpec, a StockSpec or a CalibrationSpec.
`format` is an annotation here as it is there: neither validator asserts date-time
spellings.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from functools import cache
from pathlib import Path
from typing import Any

import jsonschema

# The repository root, and `/app` in the image, where the build copies the schemas.
SCHEMAS = Path(__file__).resolve().parents[1] / "specs"


@cache
def _schema(name: str) -> dict[str, Any]:
    """The published `name` schema, read once per process."""

    return json.loads((SCHEMAS / name / "schema.json").read_text(encoding="utf-8"))


@cache
def _validator(name: str) -> jsonschema.protocols.Validator:
    """The published `name` schema's own validator."""

    schema = _schema(name)
    return jsonschema.validators.validator_for(schema)(schema)


def document_name(name: str) -> str:
    """The document name the `name` schema gives itself: `RenderSpec`, `StockSpec`, …

    It comes from the published schema rather than from the caller, so a `422` detail
    cannot name a document the schema does not call that.
    """

    return _schema(name)["title"]


def _field(path: Iterable[Any]) -> str:
    """Render a schema path as the dotted path API §5.3 shows: `layers[0].objects[1].width`."""

    text = ""
    for part in path:
        text += f"[{part}]" if isinstance(part, int) else (f".{part}" if text else str(part))
    return text


def errors_for(document: Any, schema: str = "renderspec") -> list[dict[str, str]]:
    """The `errors` entries API §5.3 requires for a document that fails `schema`."""

    found: list[dict[str, str]] = []
    for error in _validator(schema).iter_errors(document):
        path = list(error.absolute_path)
        if error.validator == "required":
            # jsonschema reports one error per missing property and its path names the
            # object that lacks it; API §5.3 names the property instead, as in `page.height`.
            path.append(next(name for name in error.validator_value if name not in error.instance))
        found.append(
            {"field": _field(path), "code": error.validator or "", "message": error.message}
        )
    return found
