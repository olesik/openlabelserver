"""Conformance checks for OpenLabelServer specifications.

Each check maps to a requirement ID from specs/conformance/specification.md.
Structural requirements are enforced by the published JSON Schemas; this module
adds the semantic rules that a schema cannot express (identifier uniqueness,
malformed colors, asset resolution, StockSpec inequalities, calibration scale
exclusivity, and non-finite numeric values).

Diagnostics carry the requirement ID and a dotted path so a failure is
attributable to a field rather than to a whole document (CN-106).
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[2]

SCHEMAS = {
    "renderspec": ROOT / "specs" / "renderspec" / "schema.json",
    "stockspec": ROOT / "specs" / "stockspec" / "schema.json",
    "calibrationspec": ROOT / "specs" / "calibrationspec" / "schema.json",
}

STANDARD_FONTS = {"Helvetica", "Times", "Courier"}

COLOR_KEYS = ("color", "fill_color", "stroke_color", "background_color")
NONE_ALLOWED_KEYS = {"fill_color", "stroke_color"}

HEX3 = "^#[0-9a-fA-F]{3}$"
HEX6 = "^#[0-9a-fA-F]{6}$"
HEX8 = "^#[0-9a-fA-F]{8}$"
RGB = "^rgb\\(\\s*(\\d{1,3})\\s*,\\s*(\\d{1,3})\\s*,\\s*(\\d{1,3})\\s*\\)$"
RGBA = (
    "^rgba\\(\\s*(\\d{1,3})\\s*,\\s*(\\d{1,3})\\s*,"
    "\\s*(\\d{1,3})\\s*,\\s*(0(?:\\.\\d+)?|1(?:\\.0+)?|\\.\\d+)\\s*\\)$"
)

# 1 pt = 1/72 in, and 1 in = 25.4 mm (RenderSpec §3.1, CS-independent).
MM_PER_POINT = 25.4 / 72.0


@dataclass(frozen=True)
class Diagnostic:
    """One conformance finding, attributed to a requirement and a location."""

    requirement: str
    path: str
    message: str
    severity: str = "error"

    def render(self) -> str:
        return f"{self.requirement} [{self.severity}] {self.path or '<root>'}: {self.message}"


def load_document(path: Path) -> Any:
    """Load a JSON or YAML fixture, preserving non-finite numbers for CN-101."""

    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        return yaml.safe_load(text)
    return json.loads(text)


def _dotted(parts: Iterable[Any]) -> str:
    return ".".join(str(part) for part in parts)


def _schema_location(error: jsonschema.ValidationError) -> str:
    """Return the dotted location of a schema violation (CN-106).

    A `required` failure is reported against its parent object, so the missing
    property is appended: `pitch` at the root, `metadata.name` when nested.
    A violation of the root object itself reports the root, which renders as
    `<root>`.
    """

    location = _dotted(error.path)
    if error.validator == "required" and isinstance(error.instance, dict):
        required = error.validator_value if isinstance(error.validator_value, list) else []
        missing = [name for name in required if name not in error.instance]
        if missing:
            return f"{location}.{missing[0]}" if location else str(missing[0])
    return location


def _schema_diagnostics(kind: str, document: Any) -> list[Diagnostic]:
    schema = json.loads(SCHEMAS[kind].read_text(encoding="utf-8"))
    validator = jsonschema.Draft7Validator(schema)
    diagnostics: list[Diagnostic] = []
    for error in sorted(validator.iter_errors(document), key=_schema_location):
        diagnostics.append(Diagnostic(f"{kind}-schema", _schema_location(error), error.message))
    return diagnostics


def _check_finite(document: Any, path: str = "") -> list[Diagnostic]:
    """CN-101: geometry must not contain NaN or infinite values."""

    diagnostics: list[Diagnostic] = []
    if isinstance(document, dict):
        for key, value in document.items():
            diagnostics.extend(_check_finite(value, f"{path}.{key}" if path else str(key)))
    elif isinstance(document, list):
        for index, value in enumerate(document):
            diagnostics.extend(_check_finite(value, f"{path}.{index}"))
    elif isinstance(document, float) and not math.isfinite(document):
        diagnostics.append(
            Diagnostic("CN-101", path, "value must be a finite number, not NaN or infinity")
        )
    return diagnostics


def _parse_color(value: Any) -> bool:
    """Return True when a color string uses a RenderSpec §7.3.1 format."""

    import re

    if not isinstance(value, str):
        return False
    if value == "none":
        return True
    if re.match(HEX3, value) or re.match(HEX6, value) or re.match(HEX8, value):
        return True
    match = re.match(RGB, value)
    if match:
        return all(0 <= int(channel) <= 255 for channel in match.groups())
    match = re.match(RGBA, value)
    if match:
        channels = [int(channel) for channel in match.groups()[:3]]
        alpha = float(match.groups()[3])
        return all(0 <= channel <= 255 for channel in channels) and 0.0 <= alpha <= 1.0
    return False


def _iter_object_tree(obj: Any, path: str) -> Iterable[tuple[str, dict]]:
    """Yield an object and its `group.objects` descendants with dotted paths."""

    if not isinstance(obj, dict):
        return
    yield path, obj
    for index, child in enumerate(obj.get("objects") or []):
        yield from _iter_object_tree(child, f"{path}.objects.{index}")


def _layer_objects(layer: dict, layer_index: int) -> Iterable[tuple[str, dict]]:
    for index, obj in enumerate(layer.get("objects") or []):
        yield from _iter_object_tree(obj, f"layers.{layer_index}.objects.{index}")


def _renderspec_semantics(document: Any) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if not isinstance(document, dict):
        return diagnostics

    # RS-108: documented color formats are accepted and "none" is valid only
    # for fill and stroke; RS-109 (RECOMMENDED) rejects malformed values.
    for layer_index, layer in enumerate(document.get("layers") or []):
        if not isinstance(layer, dict):
            continue
        for object_path, obj in _layer_objects(layer, layer_index):
            for key in COLOR_KEYS:
                if key not in obj:
                    continue
                value = obj[key]
                if not _parse_color(value):
                    diagnostics.append(
                        Diagnostic(
                            "RS-109",
                            f"{object_path}.{key}",
                            f"malformed color value {value!r}",
                        )
                    )
                elif value == "none" and key not in NONE_ALLOWED_KEYS:
                    diagnostics.append(
                        Diagnostic(
                            "RS-108",
                            f"{object_path}.{key}",
                            f'"none" is not valid for {key}',
                        )
                    )

    # RS-111: object identifiers are unique within their layer (IN-4).
    for layer_index, layer in enumerate(document.get("layers") or []):
        if not isinstance(layer, dict):
            continue
        seen: dict[str, str] = {}
        for object_path, obj in _layer_objects(layer, layer_index):
            object_id = obj.get("id")
            if object_id is None:
                continue
            if object_id in seen:
                diagnostics.append(
                    Diagnostic(
                        "RS-111",
                        f"{object_path}.id",
                        f"duplicate object id {object_id!r} already used at {seen[object_id]}",
                    )
                )
            else:
                seen[object_id] = object_path

    # RS-112: every image reference resolves in the asset registry.
    asset_ids = {
        asset.get("id") for asset in document.get("assets") or [] if isinstance(asset, dict)
    }
    for layer_index, layer in enumerate(document.get("layers") or []):
        if not isinstance(layer, dict):
            continue
        for object_path, obj in _layer_objects(layer, layer_index):
            if obj.get("type") == "image" and obj.get("asset_id") not in asset_ids:
                diagnostics.append(
                    Diagnostic(
                        "RS-112",
                        f"{object_path}.asset_id",
                        f"asset_id {obj.get('asset_id')!r} is not declared in assets",
                    )
                )

    # RS-113 (RECOMMENDED): an unresolved font family produces a warning.
    families = {
        font.get("family") for font in document.get("fonts") or [] if isinstance(font, dict)
    }
    for layer_index, layer in enumerate(document.get("layers") or []):
        if not isinstance(layer, dict):
            continue
        for object_path, obj in _layer_objects(layer, layer_index):
            family = obj.get("font_family")
            if family and family not in families and family not in STANDARD_FONTS:
                diagnostics.append(
                    Diagnostic(
                        "RS-113",
                        f"{object_path}.font_family",
                        f"font family {family!r} is not registered and not a standard family",
                        severity="warning",
                    )
                )
    return diagnostics


def _stock_semantics(document: Any) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if not isinstance(document, dict):
        return diagnostics

    page = document.get("page") or {}
    label = document.get("label") or {}
    grid = document.get("grid") or {}
    margins = document.get("margins") or {}
    pitch = document.get("pitch") or {}
    print_area = document.get("printable_area") or {}

    try:
        page_w, page_h = float(page["width"]), float(page["height"])
        label_w, label_h = float(label["width"]), float(label["height"])
        columns, rows = int(grid["columns"]), int(grid["rows"])
        left, top = float(margins["left"]), float(margins["top"])
        pitch_h, pitch_v = float(pitch["horizontal"]), float(pitch["vertical"])
    except (KeyError, TypeError, ValueError):
        return diagnostics

    # SS-105: pitches may not be smaller than the label they repeat.
    if pitch_h < label_w:
        diagnostics.append(
            Diagnostic(
                "SS-105", "pitch.horizontal", f"{pitch_h} is smaller than label.width {label_w}"
            )
        )
    if pitch_v < label_h:
        diagnostics.append(
            Diagnostic(
                "SS-105", "pitch.vertical", f"{pitch_v} is smaller than label.height {label_h}"
            )
        )

    # SS-106: the label grid fits inside the page.
    right_edge = left + (columns - 1) * pitch_h + label_w
    bottom_edge = top + (rows - 1) * pitch_v + label_h
    if right_edge > page_w + 1e-9:
        diagnostics.append(
            Diagnostic(
                "SS-106",
                "grid.columns",
                f"grid right edge {right_edge} exceeds page.width {page_w}",
            )
        )
    if bottom_edge > page_h + 1e-9:
        diagnostics.append(
            Diagnostic(
                "SS-106",
                "grid.rows",
                f"grid bottom edge {bottom_edge} exceeds page.height {page_h}",
            )
        )

    # SS-107: explicit outer margins match the remaining sheet space (±0.1 mm).
    remaining_width = page_w - right_edge
    remaining_height = page_h - bottom_edge
    if "right" in margins and abs(float(margins["right"]) - remaining_width) > 0.1:
        diagnostics.append(
            Diagnostic(
                "SS-107",
                "margins.right",
                f"{margins['right']} mm does not match the remaining width "
                f"{remaining_width:.3f} mm",
            )
        )
    if "bottom" in margins and abs(float(margins["bottom"]) - remaining_height) > 0.1:
        diagnostics.append(
            Diagnostic(
                "SS-107",
                "margins.bottom",
                f"{margins['bottom']} mm does not match the remaining height "
                f"{remaining_height:.3f} mm",
            )
        )

    # SS-108: round labels are square.
    shape = label.get("shape", "rectangle")
    if shape == "round" and abs(label_w - label_h) > 1e-9:
        diagnostics.append(
            Diagnostic(
                "SS-108", "label.shape", f"round label must be square, got {label_w} x {label_h}"
            )
        )

    # SS-109: corner radius applies only to rounded rectangles, within half the shorter side.
    if "corner_radius" in label:
        radius = float(label["corner_radius"])
        if shape != "rounded-rectangle":
            diagnostics.append(
                Diagnostic(
                    "SS-109",
                    "label.corner_radius",
                    f"corner_radius is only valid for rounded-rectangle, not {shape}",
                )
            )
        elif radius > min(label_w, label_h) / 2.0 + 1e-9:
            diagnostics.append(
                Diagnostic(
                    "SS-109",
                    "label.corner_radius",
                    f"{radius} mm exceeds half the smaller label side",
                )
            )

    # SS-110: the printable inset stays inside the label.
    if print_area:
        if float(print_area.get("left", 0.0)) + float(print_area.get("right", 0.0)) >= label_w:
            diagnostics.append(
                Diagnostic(
                    "SS-110", "printable_area", "horizontal inset is not smaller than label.width"
                )
            )
        if float(print_area.get("top", 0.0)) + float(print_area.get("bottom", 0.0)) >= label_h:
            diagnostics.append(
                Diagnostic(
                    "SS-110", "printable_area", "vertical inset is not smaller than label.height"
                )
            )

    # SS-114: single-label stock is one-up, and a roll page is one label frame.
    if page.get("format") == "roll" and (rows != 1 or columns != 1):
        diagnostics.append(
            Diagnostic(
                "SS-114",
                "grid",
                f"page.format 'roll' requires a 1x1 grid, "
                f"got {columns} column(s) and {rows} row(s)",
            )
        )
    return diagnostics


def _calibration_semantics(document: Any) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if not isinstance(document, dict):
        return diagnostics

    transform = document.get("transform")
    if isinstance(transform, dict):
        scale = transform.get("scale")
        if isinstance(scale, dict):
            # CS-105: uniform scaling excludes explicit per-axis factors.
            has_axis = "x" in scale or "y" in scale
            if "uniform" in scale and has_axis:
                diagnostics.append(
                    Diagnostic(
                        "CS-105",
                        "transform.scale",
                        "scale.uniform must not be combined with scale.x or scale.y",
                    )
                )
    return diagnostics


def validate(kind: str, document: Any) -> list[Diagnostic]:
    """Run every check for one specification kind: schema, then semantics."""

    diagnostics = _schema_diagnostics(kind, document)
    if kind == "renderspec":
        diagnostics += _check_finite(document)
        diagnostics += _renderspec_semantics(document)
    elif kind == "stockspec":
        diagnostics += _check_finite(document)
        diagnostics += _stock_semantics(document)
    elif kind == "calibrationspec":
        diagnostics += _check_finite(document)
        diagnostics += _calibration_semantics(document)
    else:  # pragma: no cover - guarded by callers
        raise ValueError(f"unknown specification kind: {kind}")
    return diagnostics


def apply_calibration(
    point: tuple[float, float],
    transform: dict | None,
    *,
    origin_offset: tuple[float, float] = (0.0, 0.0),
) -> tuple[float, float]:
    """Apply CalibrationSpec §7 (page-clockwise, Y down) to one point."""

    transform = transform or {}
    offset = transform.get("offset") or {}
    scale = transform.get("scale") or {}
    rotation = transform.get("rotation") or {}
    origin = rotation.get("origin") or {}

    if "uniform" in scale:
        sx = sy = float(scale["uniform"])
    else:
        sx, sy = float(scale.get("x", 1.0)), float(scale.get("y", 1.0))

    ox = float(origin.get("x", 0.0)) + origin_offset[0]
    oy = float(origin.get("y", 0.0)) + origin_offset[1]
    angle = math.radians(float(rotation.get("angle", 0.0)))

    x, y = point[0] - ox, point[1] - oy
    x, y = sx * x, sy * y
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    rotated_x = x * cos_a - y * sin_a
    rotated_y = x * sin_a + y * cos_a
    return (
        rotated_x + ox + float(offset.get("x", 0.0)),
        rotated_y + oy + float(offset.get("y", 0.0)),
    )
