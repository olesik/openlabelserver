# CalibrationSpec Specification v1.0

## Status of this Document

This document defines version 1.0 of the **CalibrationSpec** specification, the canonical format for describing printer-specific mechanical correction transforms within the OpenLabelServer ecosystem.

---

## 1. Introduction

### 1.1 Purpose

CalibrationSpec is a versioned, machine-readable declarative format (typically written in YAML or JSON) describing how rendered label output MUST be adjusted before submission to a physical printer. It provides a clean division of concerns in the printing pipeline:

- **RenderSpec** defines *what* is drawn inside a canvas (text, barcodes, shapes, and layout).
- **StockSpec** defines the *physical geometry* of label stock (page size, grid, pitch, and label boundaries).
- **CalibrationSpec** defines *how a specific printer deviates from ideal placement* and the compensating transform required to align rendered output with physical media.

By separating calibration from layout and design, the same RenderSpec and StockSpec documents MAY be reused across printers. Each printer profile captures only the mechanical correction needed for a given device and media combination.

### 1.2 Scope

CalibrationSpec v1.0 defines:

- **Printer profiles** that bind a calibration transform to a logical printer identity and optional media target.
- **Offsets** (translation) to correct horizontal and vertical misalignment.
- **Scaling** to correct dimensional stretch or shrink along each axis.
- **Rotation** to correct skew or angular misregistration.
- **Units** for all transform parameters.
- **Versioning** of the document format.
- **Validation** rules that parsers and calibration engines MUST enforce.

CalibrationSpec does NOT define:

- Label layout or graphical content (RenderSpec).
- Physical stock geometry (StockSpec).
- Printer discovery, job submission, or driver configuration.
- Print density, darkness, speed, or other device control parameters.

---

## 2. Conformance & Terminology

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT", "SHOULD", "SHOULD NOT", "RECOMMENDED", "MAY", and "OPTIONAL" in this document are to be interpreted as described in [RFC 2119](https://tools.ietf.org/html/rfc2119).

* **Calibration Parser**: A software component that reads a CalibrationSpec document and validates it against the schema and mathematical constraints.
* **Calibration Engine**: A software component that applies a validated calibration transform to rendered output coordinates before printing.
* **CalibrationSpec Document**: A JSON/YAML document adhering to the structural schema and validation rules defined in this specification.
* **Printer Profile**: A CalibrationSpec document representing one named set of correction parameters for a printer (and optionally a specific stock).
* **Transform Origin**: The pivot point in page coordinates about which scale and rotation are applied.
* **Ideal Coordinate**: A coordinate produced by a renderer operating on RenderSpec and StockSpec without printer correction.
* **Calibrated Coordinate**: A coordinate after CalibrationSpec transform application.

---

## 3. Units

All CalibrationSpec transform parameters MUST use the following canonical units:

| Parameter | Unit | Type | Description |
| :--- | :--- | :--- | :--- |
| `offset.x`, `offset.y` | **millimeters (mm)** | float | Translation along page axes. |
| `scale.x`, `scale.y` | **ratio (dimensionless)** | float | Multiplicative scale factor. `1.0` means no scaling. |
| `rotation.angle` | **degrees (deg)** | float | Clockwise rotation angle. |
| `rotation.origin.x`, `rotation.origin.y` | **millimeters (mm)** | float | Pivot point for scale and rotation. |

### 3.1 Coordinate System Alignment

CalibrationSpec MUST use the same coordinate system as RenderSpec and StockSpec:

1. The **X-axis** is horizontal, increasing from left to right.
2. The **Y-axis** is vertical, increasing from top to bottom.
3. The origin `(0.0, 0.0)` represents the **top-left corner** of the physical page.

Implementations MUST internalize coordinates as double-precision floating-point values to preserve deterministic transform composition.

---

## 4. Versioning

### 4.1 Document Version Field

Every CalibrationSpec document MUST contain a root-level `calibrationspec` property.

* The value MUST be exactly `"1.0"` for documents conforming to this specification.
* Parsers MUST reject documents whose `calibrationspec` value is unrecognized.

### 4.2 Schema Identifier

The JSON Schema for CalibrationSpec v1.0 is identified by:

```
https://openlabelserver.org/schemas/calibrationspec-v1.0.json
```

### 4.3 Forward Compatibility

Parsers SHOULD ignore unknown root-level properties only when explicitly operating in a forward-compatibility mode. In strict conformance mode, parsers MUST reject documents containing properties not defined by the schema.

---

## 5. Document Model

A CalibrationSpec document is a single root object (serialized as YAML or JSON). The root object MUST contain the following properties:

| Property | Type | Presence | Description |
| :--- | :--- | :--- | :--- |
| `calibrationspec` | `string` | **REQUIRED** | MUST be exactly `"1.0"`. |
| `metadata` | `object` | **REQUIRED** | Profile identification and lifecycle metadata. |
| `printer` | `object` | **REQUIRED** | Logical printer identity this profile applies to. |
| `target` | `object` | OPTIONAL | Media or stock target narrowing profile applicability. |
| `transform` | `object` | **REQUIRED** | Correction offsets, scaling, and rotation. |
| `scope` | `string` | OPTIONAL | Whether the transform applies per page or per label. Default `"page"`. |
| `enabled` | `boolean` | OPTIONAL | Whether this profile is active. Default `true`. |

---

## 6. Sub-Object Structure

### 6.1 Metadata Object (`metadata`)

Contains identification information for the printer profile.

* `id` (REQUIRED, string): A unique slug identifier. MUST match the regex `^[a-zA-Z0-9_-]+$`.
* `name` (REQUIRED, string): Human-readable profile name.
* `description` (OPTIONAL, string): Human-readable details about the calibration method or use case.
* `tags` (OPTIONAL, array of strings): Meta tags for categorized searching (e.g., `["laser", "office"]`).
* `created_at` (OPTIONAL, string): ISO 8601 UTC timestamp of creation.
* `updated_at` (OPTIONAL, string): ISO 8601 UTC timestamp of last update.
* `calibrated_by` (OPTIONAL, string): Person, system, or wizard that produced the profile.
* `calibration_method` (OPTIONAL, string): One of `"manual"`, `"wizard"`, `"measured"`, `"factory"`. Describes how the transform was derived.

### 6.2 Printer Object (`printer`)

Identifies the logical printer device this profile corrects. At least one identifying field beyond the object itself MUST be present; `identifier` is REQUIRED.

* `identifier` (REQUIRED, string): Stable logical printer name (e.g., CUPS queue name, IPP printer URI slug, or application-assigned ID). MUST match the regex `^[a-zA-Z0-9_.:-]+$`.
* `make` (OPTIONAL, string): Manufacturer name (e.g., `Zebra`, `Brother`).
* `model` (OPTIONAL, string): Device model name or number.
* `connection` (OPTIONAL, string): One of `"cups"`, `"ipp"`, `"usb"`, `"network"`, `"serial"`, `"other"`.
* `driver` (OPTIONAL, string): Driver or PPD identifier when known.

### 6.3 Target Object (`target`)

OPTIONAL narrowing of profile applicability to a specific stock layout or page format. When omitted, the profile applies to all jobs on the identified printer regardless of stock.

* `stock_id` (OPTIONAL, string): References the `metadata.id` of a StockSpec document. When present, this profile SHOULD be selected only when the job uses matching stock.
* `page_format` (OPTIONAL, string): Page format hint such as `"letter"`, `"a4"`, `"legal"`, or `"roll"`.
* `media_type` (OPTIONAL, string): Free-form media classification (e.g., `"thermal-direct"`, `"laser-sheet"`, `"inkjet-sheet"`).

When both `stock_id` and `page_format` are present, `stock_id` takes precedence for profile matching.

### 6.4 Transform Object (`transform`)

Defines the compensating affine correction applied to rendered output. All sub-properties are OPTIONAL; omitted values MUST be treated as identity (zero offset, unit scale, zero rotation).

#### 6.4.1 Offset Object (`transform.offset`)

Translates rendered content to compensate for positional error.

* `x` (OPTIONAL, float, default `0.0`): Horizontal shift in mm. Positive values shift content to the right.
* `y` (OPTIONAL, float, default `0.0`): Vertical shift in mm. Positive values shift content downward.

#### 6.4.2 Scale Object (`transform.scale`)

Scales rendered content to compensate for dimensional error.

* `x` (OPTIONAL, float, default `1.0`): Horizontal scale factor. MUST be greater than `0.0`.
* `y` (OPTIONAL, float, default `1.0`): Vertical scale factor. MUST be greater than `0.0`.
* `uniform` (OPTIONAL, float): When present, sets both `x` and `y` to the same value. MUST NOT be used together with explicit `x` or `y` in the same document.

#### 6.4.3 Rotation Object (`transform.rotation`)

Rotates rendered content to compensate for angular misregistration.

* `angle` (OPTIONAL, float, default `0.0`): Clockwise rotation in degrees.
* `origin` (OPTIONAL, object): Pivot point for scale and rotation. Defaults to `{ "x": 0.0, "y": 0.0 }` (top-left of page).
  * `x` (OPTIONAL, float, default `0.0`): Horizontal origin in mm.
  * `y` (OPTIONAL, float, default `0.0`): Vertical origin in mm.

### 6.5 Scope (`scope`)

Determines the coordinate space to which the transform is applied.

* `"page"` (default): The transform is applied once in page coordinates. This is the normal mode for sheet and roll printers.
* `"label"`: The transform is applied independently within each label cell of a stock grid. Use this when misregistration varies per label position or when calibrating at the label viewport level.

When `scope` is `"label"`, the transform origin coordinates are relative to the top-left corner of each label cell, not the page.

---

## 7. Transform Application

Calibration engines MUST apply transforms deterministically using the following algorithm.

Given an ideal point $P = (P_x, P_y)$ in the active coordinate space (page or label):

1. **Reposition to origin**: $P_1 = P - O$, where $O = (\text{origin.x}, \text{origin.y})$.
2. **Scale**: $P_2 = (\text{scale.x} \times P_{1x},\; \text{scale.y} \times P_{1y})$.
3. **Rotate clockwise** by $\theta = \text{rotation.angle}$ degrees:
   $$P_{3x} = P_{2x} \cos(\theta) + P_{2y} \sin(\theta)$$
   $$P_{3y} = -P_{2x} \sin(\theta) + P_{2y} \cos(\theta)$$
4. **Restore origin**: $P_4 = P_3 + O$.
5. **Translate**: $P' = P_4 + (\text{offset.x},\; \text{offset.y})$.

When `enabled` is `false`, the calibration engine MUST NOT modify coordinates (identity transform).

Transform application MUST occur after RenderSpec layout and StockSpec grid placement are resolved, and before the final print-ready output is emitted.

---

## 8. Printer Profile Selection

Implementations that maintain multiple CalibrationSpec profiles SHOULD select a profile using the following precedence:

1. Enabled profile where `printer.identifier` matches the job printer AND `target.stock_id` matches the job stock.
2. Enabled profile where `printer.identifier` matches AND `target.page_format` matches.
3. Enabled profile where `printer.identifier` matches AND `target` is absent.
4. No calibration (identity transform).

When multiple profiles match at the same precedence level, implementations SHOULD prefer the profile with the most recent `updated_at` timestamp. If timestamps are equal or absent, implementations MUST reject the job with an ambiguous-profile error rather than choose arbitrarily.

---

## 9. Validation Rules

To ensure a CalibrationSpec document represents a physically meaningful and rendering-safe correction, parsers and calibration engines MUST enforce the following validation rules. A document is considered **non-conformant** if any rule is violated.

### 9.1 Schema Validation

Documents MUST validate against the CalibrationSpec v1.0 JSON Schema.

### 9.2 Identifier Validity

$$\text{metadata.id} \text{ MUST match } ^[a-zA-Z0-9_-]+$$
$$\text{printer.identifier} \text{ MUST match } ^[a-zA-Z0-9_.:-]+$$

### 9.3 Scale Factor Validity

$$\text{transform.scale.x} > 0.0$$
$$\text{transform.scale.y} > 0.0$$

If `transform.scale.uniform` is present:

$$\text{transform.scale.uniform} > 0.0$$

A document MUST NOT define `transform.scale.uniform` together with `transform.scale.x` or `transform.scale.y`.

### 9.4 Rotation Validity

`rotation.angle` MAY be any finite floating-point value. Implementations MUST normalize angles for trigonometric evaluation without requiring authors to constrain input to a specific range.

### 9.5 Origin Validity

When `target.stock_id` is present and `scope` is `"page"`, implementations SHOULD warn if `rotation.origin` lies outside the referenced stock page bounds. This is a RECOMMENDED diagnostic, not a conformance failure.

When `scope` is `"label"` and `target.stock_id` is present, implementations SHOULD warn if `rotation.origin` lies outside the referenced label bounds.

### 9.6 Recommended Operating Ranges

The following ranges are RECOMMENDED for profiles produced by manual or wizard calibration. Values outside these ranges SHOULD generate warnings but MUST NOT alone cause conformance failure:

| Parameter | Recommended Range |
| :--- | :--- |
| `offset.x`, `offset.y` | $[-50.0,\; 50.0]$ mm |
| `scale.x`, `scale.y`, `scale.uniform` | $[0.950,\; 1.050]$ |
| `rotation.angle` | $[-5.0,\; 5.0]$ degrees |

### 9.7 Identity Profile Validity

A profile with zero offset, unit scale, and zero rotation is valid and represents an explicitly verified identity (no correction) calibration.

### 9.8 Enabled Flag

When `enabled` is `false`, parsers MUST still validate the full document. Disabled profiles are excluded from profile selection but remain storable and exchangeable.

---

## 10. Determinism Requirements

1. Given identical CalibrationSpec input and identical ideal coordinates, all conforming calibration engines MUST produce identical calibrated coordinates.
2. Calibration engines MUST NOT introduce randomness, device-specific rounding, or vendor-specific hidden adjustments.
3. Transform composition order defined in Section 7 is normative and MUST NOT be altered by implementations.

---

## 11. Examples

See the `examples/` directory for conformant CalibrationSpec documents:

* `identity.yaml` — verified no-correction profile.
* `thermal_roll_offset.yaml` — roll printer with positional offset correction.
* `laser_sheet_full.yaml` — sheet printer with offset, scale, and rotation correction.
