"""RenderSpec data binding (Section 10): deterministic placeholder resolution.

ConformanceSpec Section 1.4 records the interpretation this module follows:

* `IN-7` — substitution applies to `text.content`, `barcode.content` and
  `qrcode.content` only; `{{...}}` anywhere else is literal text (`RB-104`).
* `RB-101` — those three fields resolve `{{variable}}` against the record.
* `RB-102` — an unresolved name resolves to the empty string or produces a
  configured alert; this module resolves to the empty string and never fails
  the document.
* `RB-103` — numeric and boolean values serialise to their string equivalents,
  here their JSON spelling: `3`, `1.5`, `true`, `false`.

Section 10.2 fixes where records go in stock-grid mode: record `i` fills frame
`i` in row-major order, records beyond the grid continue on further pages, and
frames without a record stay empty. `page_slots` returns that assignment with
`None` for an empty slot, so a renderer can leave a label blank instead of
drawing its layers with placeholder text.

Binding never mutates its input: `bind` copies the document, so the same
document and record always produce the same output.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from renderer import layout

# RenderSpec Section 10.1 defines the syntax as `{{variable_name}}`. The name is
# used verbatim as the record key, so no trimming or expression evaluation is
# invented.
PLACEHOLDER = re.compile(r"\{\{([^{}]*)\}\}")

# IN-7: the only object types whose `content` is a template.
CONTENT_TYPES = frozenset({"text", "barcode", "qrcode"})


def _value(value: Any) -> str:
    """RB-103: a record value as its deterministic string equivalent."""

    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    return str(value)


def resolve(template: str, record: Mapping[str, Any]) -> str:
    """Substitute every `{{name}}` in `template` from `record`."""

    return PLACEHOLDER.sub(lambda match: _value(record.get(match.group(1))), template)


def _resolve_objects(objects: Sequence[Mapping[str, Any]], record: Mapping[str, Any]) -> None:
    """Resolve the template content of `objects` in place, including groups."""

    for obj in objects:
        kind = obj.get("type")
        if kind in CONTENT_TYPES and isinstance(obj.get("content"), str):
            obj["content"] = resolve(obj["content"], record)
        elif kind == "group":
            _resolve_objects(obj.get("objects", ()), record)


def bind(document: Mapping[str, Any], record: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of `document` with its placeholders resolved from `record`.

    Only the three `content` fields are substituted (`RB-101`, `RB-104`), and a
    name the record does not carry resolves to the empty string (`RB-102`).
    """

    bound = copy.deepcopy(document)
    for layer in bound.get("layers", ()):
        _resolve_objects(layer.get("objects", ()), record)
    return bound


def page_slots(document: Mapping[str, Any]) -> tuple[tuple[dict[str, Any] | None, ...], ...]:
    """Records assigned to each stock-grid frame, one page at a time (`RT-105`, `RT-106`).

    Record `i` fills frame `i` in row-major order; records beyond the grid start
    another page that repeats the grid; a frame without a record is `None`, so it
    renders no layer objects. A page-absolute document has no label slots, so it
    is rejected rather than assigned a record mapping Section 10.2 does not
    define.
    """

    if document.get("stock") is None:
        raise ValueError(
            "Section 10.2 assigns records to stock-grid frames; "
            "a page-absolute document has no label slots"
        )

    slots = len(layout.document_frames(document))
    records = tuple(document.get("data") or ())
    pages: list[tuple[dict[str, Any] | None, ...]] = []
    for start in range(0, len(records), slots):
        page: list[dict[str, Any] | None] = list(records[start : start + slots])
        page += [None] * (slots - len(page))
        pages.append(tuple(page))
    return tuple(pages)
