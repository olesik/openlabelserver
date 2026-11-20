"""RenderSpec parser driven by the published JSON Schema.

RenderSpec Section 11 requires structural validation against
``specs/renderspec/schema.json`` before rendering, and ConformanceSpec Section
5.3 fixes the parser modes: strict is the default (`CN-104`), a
forward-compatibility mode that drops unknown properties is OPTIONAL and must
not be the default (`CN-105`), and diagnostics identify the offending location
(`CN-106`). This module implements those modes and delegates the structural
rules to the published schema, adding only Section 5.1's finite-number rule
(`CN-101`) and the Section 8.2.1 text-bounding-box rule a schema cannot express
(`IN-1`, `RT-115`), so the schema stays the contract.

The parser validates; it does not lay out or render. Coordinate interpretation
lives in `renderer.coordinates`.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "specs" / "renderspec" / "schema.json"

# Forward-compatibility pruning is driven by the schema's own errors. Each pass
# removes the properties one validation round reports as unknown, and the next
# pass exposes any that were nested behind a rejected branch.
MAX_PRUNE_PASSES = 4


@dataclass(frozen=True)
class Diagnostic:
    """One rejection, attributed to a dotted path (`CN-106`)."""

    path: str
    message: str

    def render(self) -> str:
        return f"{self.path or '<root>'}: {self.message}"


class RenderSpecError(ValueError):
    """A document was rejected; `diagnostics` carries every finding."""

    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        self.diagnostics = tuple(diagnostics)
        super().__init__("; ".join(diagnostic.render() for diagnostic in diagnostics))


def load_schema(path: Path = SCHEMA_PATH) -> dict[str, Any]:
    """Load the published RenderSpec schema that drives every check."""

    return json.loads(Path(path).read_text(encoding="utf-8"))


def _validator(schema: Mapping[str, Any]) -> jsonschema.Draft7Validator:
    schema = dict(schema)
    cls = jsonschema.validators.validator_for(schema)
    cls.check_schema(schema)
    return cls(schema)


def _schema_path(error: jsonschema.ValidationError) -> str:
    """Return the dotted location of a violation, naming a missing property.

    A `required` failure is reported against its parent object, so the missing
    property is appended: `page` at the root, `page.width` when nested.
    """

    location = ".".join(str(part) for part in error.absolute_path)
    if error.validator == "required" and isinstance(error.instance, dict):
        required = error.validator_value if isinstance(error.validator_value, list) else []
        missing = [name for name in required if name not in error.instance]
        if missing:
            return f"{location}.{missing[0]}" if location else str(missing[0])
    return location


def _reject(errors: list[jsonschema.ValidationError]) -> None:
    diagnostics = sorted(
        {Diagnostic(_schema_path(error), error.message) for error in errors},
        key=lambda diagnostic: (diagnostic.path, diagnostic.message),
    )
    raise RenderSpecError(diagnostics)


def _non_finite(value: Any, path: str = "") -> list[Diagnostic]:
    """CN-101: geometry must not contain NaN or infinite values."""

    diagnostics: list[Diagnostic] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            diagnostics.extend(_non_finite(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            diagnostics.extend(_non_finite(item, f"{path}.{index}"))
    elif isinstance(value, float) and not math.isfinite(value):
        diagnostics.append(Diagnostic(path, "value must be a finite number, not NaN or infinity"))
    return diagnostics


def _descend(document: Any, path: list[Any]) -> Any:
    current = document
    for part in path:
        current = current[part]
    return current


def _drop_unknown(document: Mapping[str, Any], validator: jsonschema.Draft7Validator) -> dict:
    """CN-105: accept a document by dropping properties the schema does not define.

    Only properties reported as unknown are removed; the pruned document is then
    validated in full, so every rule on the properties the parser recognizes
    still applies.
    """

    current = json.loads(json.dumps(document))
    for _ in range(MAX_PRUNE_PASSES):
        unknown = [
            error
            for error in validator.iter_errors(current)
            if error.validator == "additionalProperties"
        ]
        if not unknown:
            break
        changed = False
        for error in unknown:
            container = _descend(current, list(error.path))
            defined = (error.schema or {}).get("properties") or {}
            if not isinstance(container, dict) or not defined:
                continue
            for key in [key for key in container if key not in defined]:
                del container[key]
                changed = True
        if not changed:
            break
    return current


def _walk_objects(
    objects: Iterable[Mapping[str, Any]], path: str
) -> Iterator[tuple[str, Mapping[str, Any]]]:
    """Yield every object of a layer subtree with its dotted path (Section 8)."""

    for index, obj in enumerate(objects):
        child = f"{path}.{index}"
        yield child, obj
        yield from _walk_objects(obj.get("objects") or (), f"{child}.objects")


def _text_bounds(document: Mapping[str, Any]) -> list[Diagnostic]:
    """IN-1: `align` and `wrap` need `width`; `valign` needs `height`.

    RenderSpec Section 8.2.1 documents each of those properties as requiring the
    matching bounding-box dimension, and ConformanceSpec IN-1 (`RT-115`) makes
    the omission a validation failure rather than a silent no-op.
    """

    diagnostics: list[Diagnostic] = []
    for layer_index, layer in enumerate(document.get("layers") or ()):
        root = f"layers.{layer_index}.objects"
        for path, obj in _walk_objects(layer.get("objects") or (), root):
            if obj.get("type") != "text":
                continue
            for key, dimension in (("align", "width"), ("wrap", "width"), ("valign", "height")):
                if key in obj and dimension not in obj:
                    diagnostics.append(
                        Diagnostic(f"{path}.{key}", f"{key} requires {dimension} to be defined")
                    )
    return diagnostics


def parse(
    document: Any,
    *,
    strict: bool = True,
    schema: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate one RenderSpec document and return it.

    Strict mode (the default) rejects every schema violation. With
    ``strict=False`` the OPTIONAL forward-compatibility mode drops unknown
    properties first and still enforces every other rule.
    """

    if not isinstance(document, dict):
        raise RenderSpecError([Diagnostic("", "document must be a JSON object")])
    validator = _validator(schema if schema is not None else load_schema())

    non_finite = _non_finite(document)
    if non_finite:
        raise RenderSpecError(non_finite)

    candidate = document if strict else _drop_unknown(document, validator)
    errors = list(validator.iter_errors(candidate))
    if errors:
        _reject(errors)
    unbounded = _text_bounds(candidate)
    if unbounded:
        raise RenderSpecError(unbounded)
    return candidate


def load(
    path: Path,
    *,
    strict: bool = True,
    schema: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Parse and validate one RenderSpec JSON file."""

    path = Path(path)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        try:
            shown = path.relative_to(ROOT).as_posix()
        except ValueError:
            shown = str(path)
        raise RenderSpecError(
            [Diagnostic("", f"{shown} is not valid JSON: {exc.msg} (line {exc.lineno})")]
        ) from exc
    return parse(document, strict=strict, schema=schema)
