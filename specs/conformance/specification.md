# ConformanceSpec Specification v1.0

## Status of this Document

This document defines version 1.0 of the **ConformanceSpec**, the specification that defines how an implementation proves compliance with the OpenLabelServer specifications: [RenderSpec](../renderspec/specification.md), [StockSpec](../stockspec/specification.md), [CalibrationSpec](../calibrationspec/specification.md), the [REST API](../api/specification.md) and renderer output.

ConformanceSpec introduces no new document format and no new public HTTP interface. It converts statements that are already normative in the domain specifications into **observable checks** with stable identifiers, and defines the evidence an implementation must publish to claim conformance.

---

## 1. Introduction

### 1.1 Purpose

The domain specifications say what is required. They do not say how a third party demonstrates that those requirements are met, how a failure is identified, or which subset of requirements applies to a partial implementation.

ConformanceSpec answers those questions:

- Which classes of implementation exist, and which requirements each must satisfy.
- How each requirement is observed and tested.
- What artifact set (fixtures, golden outputs, report) a conforming implementation must produce.
- How requirement identity survives specification evolution.

### 1.2 Scope

This specification covers:

- RenderSpec document validation and rendering semantics (Sections 6 and 7)
- StockSpec parsing, geometry validation and translation (Section 8)
- CalibrationSpec parsing, profile selection and transform application (Section 9)
- REST API v1.0 behavior (Section 10), including the three cases mandated by [RFC-0001](../../rfcs/RFC-0001-api-validation-and-idempotency-corrections.md)
- Renderer output fidelity, determinism and golden artifacts (Sections 11 and 12)
- Physical print accuracy (Section 13)
- Optional performance targets (Section 14)

It does not define:

- Any layout, geometry, calibration or HTTP behavior not already defined by the domain specifications.
- Internal architecture, code structure, language or library choice.
- Printer hardware requirements beyond the measurement procedure in Section 13.

### 1.3 Relationship to the domain specifications

The domain specifications remain authoritative. This document:

1. **MUST NOT** relax a `MUST` from a domain specification.
2. Preserves the normative strength of the source statement. A source `SHOULD` becomes a requirement marked **RECOMMENDED**, which is reported but does not affect a conformance claim; a source `MUST` becomes a requirement that does affect the claim.
3. Resolves statements that are normative in the domain specifications but not directly observable into an observable form. Every such resolution is recorded in Section 1.4.

### 1.4 Recorded interpretations

The following interpretations make existing normative statements testable. They add no new behavior. Changing any of them requires an RFC.

| ID | Source | Interpretation |
| :--- | :--- | :--- |
| IN-1 | RenderSpec §8.2 (`align`, `valign`, `wrap` "Requires `width` / `height` to be defined") | Setting `align` or `wrap` without `width`, or `valign` without `height`, is a validation failure, not a silent no-op. |
| IN-2 | RenderSpec §5.1 (`page.margin` "Safety margins") | `page.margin` has no normative coordinate effect in v1.0. A renderer MUST NOT translate or clip content using it; it is advisory for editors and layout warnings. |
| IN-3 | RenderSpec §4.1 (timestamps "MUST NOT affect deterministic rendering output") | A conforming output artifact contains no creation/modification timestamp of its own, including PDF `/CreationDate`, `/ModDate` and document identifiers derived from time. |
| IN-4 | RenderSpec §11 rule 6 ("unique within their scope") | Uniqueness is evaluated per `layers[i]` subtree: layer `id` values are unique across the document, and object `id` values (including inside nested `group.objects`) are unique within their layer. |
| IN-5 | CalibrationSpec §4.3 (strict conformance mode) | Strict mode is the default. Forward-compatibility mode is opt-in and MUST be requested explicitly by the implementation's configuration. |
| IN-6 | API §2 ("byte-identical output") | Determinism is verified as equality of output bytes, not of visually equivalent output. |
| IN-7 | RenderSpec §10 (interpolation is defined only for `text.content`, `barcode.content` and `qrcode.content`) | Substitution applies to those three fields only; `{{…}}` appearing in any other property is literal text. |

---

## 2. Conformance & Terminology

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT", "SHOULD", "SHOULD NOT", "RECOMMENDED", "MAY", and "OPTIONAL" in this document are to be interpreted as described in [RFC 2119](https://tools.ietf.org/html/rfc2119).

- **Implementation**: A software component, or a set of components acting together, that is evaluated against this specification.
- **Conformance profile**: A named set of requirements that applies to one class of implementation (Section 3).
- **Conformance claim**: A published statement that an implementation satisfies one or more profiles, accompanied by a conformance report (Section 16).
- **Requirement**: A single numbered, observable obligation in Sections 6 to 15.
- **Requirement ID**: The stable identifier of a requirement, for example `RT-103`. IDs are never reused or renumbered (Section 17).
- **Verification**: The procedure that decides whether an implementation satisfies a requirement. Every requirement has at least one automated verification unless marked otherwise.
- **Golden artifact**: A published reference output whose bytes are the expected result of a named input document.
- **Fixture**: An input document, request or environment definition used by verification.
- **Strict mode** / **Forward-compatibility mode**: Document parsing modes defined by CalibrationSpec §4.3 and applied uniformly by Section 5.3.
- **Result status**: One of `pass`, `fail`, `not-applicable`, `not-tested` (Section 16).

---

## 3. Conformance Profiles

An implementation claims conformance per profile. A claim MUST name every profile satisfied and the exact version of each domain specification and of this specification.

| Profile | Implementation class | Requirement prefixes |
| :--- | :--- | :--- |
| `CP-RS` | RenderSpec validator / parser | `CN-*`, `RS-*` |
| `CP-ST` | StockSpec parser | `CN-*`, `SS-*` |
| `CP-CAL` | CalibrationSpec parser | `CN-*`, `CS-101`–`CS-111`, `CS-120`–`CS-122` |
| `CP-CE` | Calibration engine | `CN-*`, `CS-112`–`CS-119` |
| `CP-RND` | Renderer (RenderSpec to PDF or PostScript) | `CN-*`, `RS-*`, `RT-*`, `RB-*`, `RO-*`, `DT-*` |
| `CP-API` | REST API server | `CN-*`, `AP-*`, `AR-*`, `AJ-*`, `AQ-*` |
| `CP-CLI` | API client | `AP-113` (client clause only) |
| `CP-PIPE` | Print pipeline (render, calibrate, submit) | `CP-RND` requirements plus `PL-*`, `PH-*` |
| `CP-PERF` | Performance claim (OPTIONAL) | `PF-*` |

Rules for claims:

1. A `CP-RND` claim MUST include `CP-RS`: a renderer that cannot validate its input cannot claim to render conformant documents.
2. A `CP-PIPE` claim MUST include `CP-CE`: the print path applies calibration.
3. A `CP-API` claim MUST include `CP-RS`, `CP-ST` and `CP-CAL`, because API §9 requires domain documents to be validated before persistence and job execution. For the internal validator, satisfying the requirement is equivalent whether implemented in-process or delegated to a conformant component.
4. A `CP-PERF` claim is additional to, never a substitute for, a functional profile.
5. Requirements marked **RECOMMENDED** are reported but never prevent a claim.

---

## 4. Requirement Identity and Test Layout

### 4.1 Identifiers

Requirement IDs have the form `<AREA>-<number>`, where `AREA` is one of `CN`, `RS`, `RT`, `RB`, `SS`, `CS`, `AP`, `AR`, `AJ`, `AQ`, `RO`, `PL`, `DT`, `PH`, `PF`.

Each requirement ID is also the identifier of its primary verification. Where a requirement needs more than one check, individual checks are addressed with a dotted suffix: `RT-103.1`, `RT-103.2`.

### 4.2 Test suite layout

The conformance suite lives under `tests/` and mirrors the profile boundaries described in [tests/README.md](../../tests/README.md):

```text
tests/
├── schema/          (existing CI schema + OpenAPI validation)
├── conformance/
│   ├── fixtures/    Published inputs: RenderSpec, StockSpec, CalibrationSpec, API requests
│   ├── renderspec/  RS-*, RT-*, RB-*
│   ├── stockspec/   SS-*
│   ├── calibration/ CS-*
│   ├── api/         AP-*, AR-*, AJ-*, AQ-*
│   ├── renderer/    RO-*, DT-*
│   ├── pipeline/    PL-*, PH-*
│   └── performance/ PF-*
├── regression/      Golden artifacts and hash comparison
└── performance/     Benchmarks
```

### 4.3 Suite requirements

1. The suite MUST be executable with one documented command and MUST report every requirement ID with a result status.
2. Verification MUST NOT require network access. Fixtures, fonts and images MUST be local files committed with the suite.
3. Physical-output verification (`PH-*`) is exempt from the network rule when it drives a real printer, and MUST be skippable, reporting `not-tested` with a reason.
4. A failure MUST report the requirement ID, the fixture used and the observed versus expected value.

---

## 5. Common Normative Rules

These rules apply to every requirement in this document.

### 5.1 Units and precision

1. All physical geometry is millimetres as floating-point values; typography sizes are points, where 1 pt = 1/72 inch = 0.352777… mm (`0.3527777777777778` mm).
2. Internal computation MUST use double-precision floating point.
3. Rounding to output units happens at emission only. Verification of intermediate geometry compares values with an absolute tolerance of `1e-6` mm unless a requirement states otherwise.
4. `CN-101` An implementation MUST reject geometric values that are `NaN`, infinite, or not representable as finite doubles.

### 5.2 Coordinates

`CN-102` Every profile MUST use the coordinate system defined by RenderSpec §3: X increasing rightwards, Y increasing downwards, origin at the top-left of the active canvas, millimetres.

### 5.3 Parsing modes and unknown properties

`CN-103` Document parsers MUST reject documents whose version field (`renderspec`, `stockspec`, `calibrationspec`) is absent or not exactly `"1.0"`.

`CN-104` In strict mode (the default, IN-5) parsers MUST reject properties not defined by the published schema, at every nesting level.

`CN-105` (RECOMMENDED) A forward-compatibility mode that ignores unknown properties is OPTIONAL and MUST NOT be the default; when it is enabled, parsers MUST still enforce every validation on the properties they recognize.

### 5.4 Validation outcomes

A requirement is observed through one of three outcomes:

| Outcome | Meaning | Verification assertion |
| :--- | :--- | :--- |
| **Reject** | The input is not accepted; no output is produced or persisted | Validation failure reported; no artifact written |
| **Accept** | The input is accepted and processed | Document loads; artifact or resource produced |
| **Warn** | The input is accepted; a diagnostic is reported | Acceptance plus a diagnostic mentioning the offending field |

A requirement that says an implementation MUST reject means that accepting the input is a conformance failure. A **RECOMMENDED** requirement with a `Warn` outcome records the diagnostic but does not fail a claim.

### 5.5 Error identity

`CN-106` Diagnostic reports produced for `Reject` and `Warn` outcomes MUST identify the offending location as a JSON Pointer or dotted path, so that failures are attributable to a field rather than to a document as a whole.

---

## 6. RenderSpec Conformance (`CP-RS`)

Verification uses the published examples in [renderspec/examples](../renderspec/examples/) plus the negative fixtures listed in Section 18.

### 6.1 Document structure

| ID | Requirement | Verification |
| :--- | :--- | :--- |
| `RS-101` | Root `renderspec` MUST be exactly `"1.0"`. | Reject when absent or `"1.1"`, `"2.0"`, `1.0` (number). |
| `RS-102` | `id` MUST match `^[a-zA-Z0-9_-]+$`; `name` MUST be present. | Reject `"bad id"`, `"a.b"`, empty; reject missing `name`. |
| `RS-103` | `page` MUST be present with `width` and `height` greater than `0.0`; `page.margin` defaults to `0.0` on all four sides. | Reject `width: 0`, `height: -10`; accept `page` without `margin`. |
| `RS-104` | When `stock` is present it MUST contain `width`, `height`, `rows`, `columns`, `margin_left`, `margin_top`, `horizontal_pitch`, `vertical_pitch`; `rows` and `columns` MUST be integers `>= 1`. | Reject missing `vertical_pitch`; reject `rows: 0`, `columns: 2.5`. |
| `RS-105` | `layers` MUST be present; each layer MUST have `id` and `name`; `visible` defaults to `true`; `opacity` defaults to `1.0` and MUST be within `[0.0, 1.0]`. | Reject `opacity: 1.5`, `-0.1`; accept layer without `visible`. |
| `RS-106` | Fonts registry entries MUST have `family` and `variants`; each variant MUST have `style` in `{normal, italic, oblique}`, `weight` and `source`. | Reject `style: "bold"`; accept `weight: "700"`. |
| `RS-107` | Asset registry entries MUST have `id`, `source` and `type` in `{svg, png, jpeg}`. | Reject `type: "gif"`. |
| `RS-108` | All documented color formats MUST be accepted: `#RRGGBB`, `#RGB`, `#RRGGBBAA`, `rgb()`, `rgba()`, `none` (fill and stroke only). | Accept each form on `rect.fill_color`; reject `"none"` on `text.color`. |
| `RS-109` | (RECOMMENDED) Malformed color strings SHOULD be rejected during validation. | Accept-warn or reject for `"#GGG"`, `"rgb(1,2)"`. |
| `RS-110` | Object `type` MUST be one of `text`, `rect`, `circle`, `ellipse`, `line`, `polyline`, `polygon`, `path`, `image`, `barcode`, `qrcode`, `group`, and each type MUST carry its required properties (Section 6.2). | Reject `type: "star"`; reject `circle` without `r`. |
| `RS-111` | Identifiers MUST be unique within their scope as defined by IN-4. | Reject two layers with `id: "foreground"`; reject duplicate object `id` in one layer; reject duplicate object `id` inside nested groups of one layer. |
| `RS-112` | Every `image` object's `asset_id` MUST resolve to an `id` in the root `assets` registry. | Reject `asset_id: "missing"`. |
| `RS-113` | (RECOMMENDED) An unresolved `font_family` SHOULD produce a diagnostic, and standard families Helvetica, Times and Courier MUST remain usable without a registry entry. | Warn for `font_family: "NoSuchFont"`; accept Helvetica. |
| `RS-114` | Repeated `id`s across different layers MUST be accepted (uniqueness is per layer). | Accept `rect` `id: "line-1"` in two layers. |
| `RS-115` | Unknown properties MUST be rejected in strict mode at every level (schema `additionalProperties: false`). | Reject extra `page.bleed`, `object.z`. |
| `RS-116` | The three published RenderSpec examples MUST validate unchanged. | Accept `simple_label.json`, `sheet_labels.json`, `barcode_label.json`. |
| `RS-117` | `output` MUST accept `format` in `{pdf, postscript}`, `color_space` in `{rgb, cmyk, grayscale}`, `resolution_dpi` integer `>= 72`, `pdf_version`, `embed_fonts`, `compress`; defaults are `rgb`, `300`, `"1.4"`, `true`, `true`. | Reject `resolution_dpi: 72.5` and `format: "svg"`; accept `output` omitted. |
| `RS-118` | (RECOMMENDED) Objects whose computed bounding box exceeds the active boundary SHOULD produce a diagnostic; boundary overflow alone MUST NOT invalidate the document. | A rect outside a 50 × 30 mm label is accepted and still processed (clipping is `RT-104`). |
| `RS-119` | `created_at` / `updated_at` MUST NOT influence rendering output. | Render the same document with two different timestamp pairs; artifacts MUST be byte-identical (see `DT-101`). |

### 6.2 Required properties per object type

`RS-110` verifies the following minimum sets.

| `type` | Required properties |
| :--- | :--- |
| `text` | `content` |
| `rect` | `width`, `height` |
| `circle` | `r` |
| `ellipse` | `rx`, `ry` |
| `line` | `x2`, `y2` |
| `polyline` | `points` |
| `polygon` | `points` |
| `path` | `d` |
| `image` | `asset_id`, `width`, `height` |
| `barcode` | `content`, `symbology`, `width`, `height` |
| `qrcode` | `content`, `size` |
| `group` | `objects` |

---

## 7. RenderSpec Layout Semantics (`CP-RND`)

Verification of this section requires a renderer, because the outcomes are geometric.

### 7.1 Modes and grid

| ID | Requirement | Verification |
| :--- | :--- | :--- |
| `RT-101` | With `stock` absent the document is page-absolute: origin `(0,0)` is the page top-left and content is rendered once. | Render `simple_label.json`; assert no repetition. |
| `RT-102` | With `stock` present the document is stock-grid mode: origin `(0,0)` is the top-left of each label, and layers are replicated across the grid. | Render a 1 × 2 grid; assert two identical label bodies. |
| `RT-103` | The label frame origin MUST be `X = margin_left + c * horizontal_pitch`, `Y = margin_top + r * vertical_pitch` for 0-indexed `(c, r)`. | Fixture with `rows: 2`, `columns: 3`, `margin_left: 4.5`, `margin_top: 12.7`, pitches `66.7` / `25.4`; assert each frame origin within `1e-6` mm. |
| `RT-104` | Each label MUST be clipped to `(X, Y, width, height)`; objects MUST NOT bleed into neighbouring labels. | Label with a filled rect larger than the label; assert no ink outside the frame in a 600 dpi rasterization or content-stream analysis. |
| `RT-105` | In stock-grid mode, `data` records fill frames in row-major order (row 0 column 0 first). | 6 records over a 2 × 3 grid; assert record `i` appears at `(i mod 3, floor(i / 3))`. |
| `RT-106` | More records than frames MUST produce additional pages repeating the grid; fewer records than frames MUST leave the remaining frames empty with no layer content. | 7 records over a 6-frame grid: two pages with the second carrying one record; also 2 records over 6 frames: four empty frames containing no objects. |
| `RT-107` | `visible: false` on a layer or object MUST suppress drawing entirely. | Hidden layer; assert no operator for its objects. |
| `RT-108` | Layer `opacity` MUST apply recursively to every element in the layer; final alpha is the product of layer and object alpha, including ancestor groups. | Layer `0.5` with object `0.5` renders at `0.25`. |

### 7.2 Transforms

| ID | Requirement | Verification |
| :--- | :--- | :--- |
| `RT-109` | The transformation matrix MUST be `M = M_parent × T(x, y) × R(θ) × S(sx, sy) × M_custom`, with `R(θ) = [[cos θ, −sin θ], [sin θ, cos θ]]` for clockwise rotation in the Y-down coordinate system (the convention RenderSpec §9 and CalibrationSpec §7 share). | Object with `x`, `y`, `rotation`, `scale_x`, `scale_y` and a `transforms` array; assert a corner point maps to the value produced by the ordered product. |
| `RT-110` | `rotation` is clockwise in degrees, applied about the object anchor `(x, y)`: a point on the positive X-axis rotates toward positive Y. | 90° rotation of a 10 × 20 mm rect; assert resulting bounding box is 20 × 10 mm and that its anchor-relative corner moved toward positive Y. |
| `RT-111` | `transforms` entries are applied sequentially in array order: `translate{x,y}`, `scale{sx,sy}`, `rotate{angle,cx,cy}` (default centre `(0,0)`), `matrix{[a,b,c,d,e,f]}` mapping to `[[a,c,e],[b,d,f],[0,0,1]]`. | Two-entry array whose result differs from the reversed order; assert sequential order. |
| `RT-112` | `x` / `y` are offsets relative to the parent context: page, label, or containing group. | Rect at `(10, 10)` inside a group at `(5, 5)` lands at `(15, 15)`. |
| `RT-113` | `font_size` is in points and MUST convert to millimetres at `1 pt = 1/72 in = 0.352777…` mm, so a `10 pt` run has a nominal em size of `3.5278` mm on the page. | Rasterize a `10 pt` single-line `text` object at 1200 dpi; the measured em box is `3.5278` mm ± `0.02` mm. |
| `RT-114` | `page.margin` MUST NOT translate or clip rendered content (IN-2). | 10 mm margin with a rect at `(0, 0)`; content stream origin unchanged. |
| `RT-115` | `align` or `wrap` without `width`, and `valign` without `height`, MUST fail validation (IN-1). | Reject `align: "center"` with no `width`. |
| `RT-116` | `barcode.width` / `barcode.height` define the drawn pattern size; `draw_text` defaults to `true` and renders human-readable text; `qrcode.size` defines both grid dimensions. | Assert measured module extents against declared millimetres within `0.1` mm. |
| `RT-117` | `group` children MUST inherit the group's transform, visibility and opacity. | Invisible group suppresses children; group `x`/`y` shifts children. |

### 7.3 Data binding

| ID | Requirement | Verification |
| :--- | :--- | :--- |
| `RB-101` | `{{variable}}` MUST be substituted in `text.content`, `barcode.content` and `qrcode.content`. | Record `{ "sku": "ABC-123" }` renders `ABC-123`. |
| `RB-102` | Unresolved variables MUST resolve to the empty string, or produce a configured validation alert. | Accept either behavior; the document MUST not fail hard. |
| `RB-103` | Numeric and boolean record values MUST be serialized to their string equivalents. | `1` renders `1`; `true` renders a non-empty string representation of true. |
| `RB-104` | Substitution MUST NOT apply to properties other than the three `content` fields. | `path.d` containing `{{x}}` is rendered literally. |

---

## 8. StockSpec Conformance (`CP-ST`)

| ID | Requirement | Verification |
| :--- | :--- | :--- |
| `SS-101` | `stockspec` MUST be exactly `"1.0"`; canonical serialization is YAML 1.2 and equivalent JSON MUST be accepted with the same object model. | Reject `"1.1"`; accept the same document as JSON. |
| `SS-102` | Root MUST contain `metadata`, `page`, `label`, `grid`, `margins`, `pitch`; `printable_area` is OPTIONAL. | Reject missing `pitch`. |
| `SS-103` | `page.width`, `page.height`, `label.width`, `label.height` MUST be `> 0.0`; `grid.rows` and `grid.columns` MUST be integers `>= 1`; `pitch.horizontal` and `pitch.vertical` MUST be `> 0.0`. | Reject each violation individually. |
| `SS-104` | Label frame origins MUST follow `X = margins.left + c × pitch.horizontal`, `Y = margins.top + r × pitch.vertical`. | Assert all 30 frames of `avery_5160.yaml` within `1e-6` mm. |
| `SS-105` | `pitch.horizontal >= label.width` and `pitch.vertical >= label.height`. | Reject a stock whose pitches are smaller than its labels. |
| `SS-106` | Enclosure: `margins.left + (columns − 1) × pitch.horizontal + label.width <= page.width`, and the equivalent vertical inequality. | Reject a 3-column grid overflowing a 100 mm page by 1 mm; accept an exactly fitting grid. |
| `SS-107` | When present, `margins.right` and `margins.bottom` MUST equal the remaining sheet space within `±0.1` mm. | Reject a deviation of `0.2` mm; accept `0.05` mm. |
| `SS-108` | `label.shape: "round"` requires `label.width == label.height`. | Reject 50 × 40 mm round label. |
| `SS-109` | `corner_radius` MUST be present only with `shape: "rounded-rectangle"` and MUST be `<= min(width, height) / 2`. | Reject `corner_radius` on a `rectangle`; reject `corner_radius` above half the smaller side. |
| `SS-110` | When `printable_area` is present, `left + right < label.width` and `top + bottom < label.height`; omitted sides default to `0.0`. | Reject a 30 mm inset on a 25 mm label along one axis. |
| `SS-111` | `margins.left`, `margins.top` and, when present, `margins.right`, `margins.bottom` MUST be `>= 0.0`; `printable_area` sides MUST be `>= 0.0`. | Reject `margins.left: -1`. |
| `SS-112` | Clipping MUST follow the declared shape: rectangle to the bounding box; rounded-rectangle to the radius; round to a circle of diameter `width` centred in the box; oval to the inscribed ellipse. | Four fixtures with a full-bleed rect; assert corner pixels are blank outside the shape. |
| `SS-113` | Labels MUST be filled row-major: column index increases first. | 4 records over a 2 × 2 grid; assert ordering. |
| `SS-114` | A single-label stock MUST declare `rows: 1` and `columns: 1`; when `page.format` is `"roll"`, `page.width` and `page.height` describe one label frame, not an unbounded roll length. | Accept `shipping_4x6.yaml`; reject a document with `page.format: "roll"` and `columns: 2`. |
| `SS-115` | `page.format` MUST be treated as informational; `page.width` and `page.height` are authoritative for geometry. | Stock declaring `format: "a4"` with letter dimensions lays out using the declared numbers. |
| `SS-116` | The StockSpec to RenderSpec mapping MUST be exactly: `page.width/height`, `label.width/height → stock.width/height`, `grid → stock.rows/columns`, `margins.left/top → stock.margin_left/margin_top`, `pitch → stock.horizontal_pitch/vertical_pitch`, with no additional fields. | Assert the translated document contains no `shape`, `corner_radius`, `printable_area`, `metadata` or `page.format`. |
| `SS-117` | When a RenderSpec carries inline `stock` and a StockSpec is supplied, disagreements beyond `±0.1` mm MUST be rejected rather than resolved silently. | Reject mismatched `label.width`; accept a `0.05` mm difference. |
| `SS-118` | Timestamps MUST NOT affect layout calculations. | Layout identical with different `created_at` values. |
| `SS-119` | The three published stock examples MUST validate unchanged. | Accept `avery_5160.yaml`, `round_2inch.yaml`, `shipping_4x6.yaml`. |
| `SS-120` | `metadata.id` MUST be unique within a stock catalog. | Creating a second stock with an existing `metadata.id` against a conformant API is rejected (`AR-104`). |

---

## 9. CalibrationSpec Conformance

### 9.1 Parsing (`CP-CAL`)

| ID | Requirement | Verification |
| :--- | :--- | :--- |
| `CS-101` | `calibrationspec` MUST be exactly `"1.0"`; an unrecognized value MUST be rejected. | Reject `"2.0"` and missing. |
| `CS-102` | Root MUST contain `metadata`, `printer`, `transform`; `target`, `scope` and `enabled` are OPTIONAL. | Reject missing `transform`. |
| `CS-103` | `metadata.id` MUST match `^[a-zA-Z0-9_-]+$`; `printer.identifier` MUST match `^[a-zA-Z0-9_.:-]+$`. | Reject `printer.identifier: "zebra/1"`. |
| `CS-104` | `printer.identifier` is REQUIRED within `printer`. | Reject `printer` without `identifier`. |
| `CS-105` | `transform.scale.x` and `.y` MUST be `> 0.0`; `scale.uniform` MUST be `> 0.0` and MUST NOT coexist with explicit `x` or `y`. | Reject `scale.x: 0`; reject `uniform` plus `x`; accept `uniform: 1.01`. |
| `CS-106` | `rotation.angle` MAY be any finite value and MUST be normalized for trigonometric evaluation without requiring input ranges. | Accept `angle: 450` and `-395.5`; assert result equals the normalized angle. |
| `CS-107` | Omitted transform members MUST be treated as identity: offset `(0,0)`, scale `(1,1)`, angle `0`, origin `(0,0)`. | Empty `transform: {}` is accepted and yields identical coordinates. |
| `CS-108` | `scope` MUST be `page` (default) or `label`; with `label`, origin coordinates are relative to each label cell. | Reject `scope: "sheet"`; assert per-cell origin behavior. |
| `CS-109` | `enabled: false` MUST NOT modify coordinates, yet the document MUST still be fully validated. | Disabled invalid profile (e.g. `scale.x: 0`) is still rejected. |
| `CS-110` | Strict mode MUST reject unknown properties, including unknown root-level ones (IN-5). | Reject `transform.skew`. |
| `CS-111` | The three published calibration examples MUST validate unchanged. | Accept `identity.yaml`, `thermal_roll_offset.yaml`, `laser_sheet_full.yaml`. |
| `CS-120` | CalibrationSpec MUST use YAML 1.2 as its canonical serialization and MUST accept equivalent JSON with the same object model, validated against the same Draft-07 schema. | The same profile as YAML and as JSON parses to identical coordinates. |
| `CS-121` | `target.page_format`, when present, MUST be one of `letter`, `a4`, `legal`, `a5`, `roll`, `custom`. | Reject `page_format: "tabloid"`; accept `"a5"`. |
| `CS-122` | `target.media_type` is informational and MUST NOT be used for profile selection in v1.0. | Two profiles differing only in `media_type` resolve to the same profile regardless of media type. |

### 9.2 Application (`CP-CE`)

| ID | Requirement | Verification |
| :--- | :--- | :--- |
| `CS-112` | A point `P` MUST map to `P' = ((scale · (P − O)) rotated clockwise by θ) + O + offset`, applied in exactly this order. Clockwise in a Y-down plane is `P3x = P2x·cos θ − P2y·sin θ`, `P3y = P2x·sin θ + P2y·cos θ`, matching CalibrationSpec §7 and RenderSpec §9. | Normative worked example (Section 9.3). A profile carrying only `offset: { x: 2.0, y: -1.0 }` moves a sampled point to `(Px + 2.0, Py − 1.0)`. |
| `CS-113` | Transform application MUST occur after layout and grid placement, and before print-ready output is emitted. | Assert the calibrated coordinate equals the calibrated output position, not a pre-layout one. |
| `CS-114` | Profile selection MUST follow the precedence: enabled profile matching `printer.identifier` and `target.stock_id`; then matching `printer.identifier` with `target.stock_id` absent and `target.page_format` matching; then matching `printer.identifier` with no `target` or one carrying only informational fields; then identity. | Four-profile fixture resolved at each level. |
| `CS-115` | When several enabled profiles match at the same precedence level, the implementation MUST reject with an ambiguous-profile error instead of choosing arbitrarily. | Two identical-level profiles; assert rejection and `AJ-108`. |
| `CS-116` | A profile that sets `target.stock_id` MUST NOT match a job for a different stock that happens to share the same `page_format`. | A profile targeting stock A with `page_format: "a4"` is not selected for a stock B job whose page format is `a4`. |
| `CS-117` | Recomputed parameters outside the recommended ranges MUST warn without failing. | Warn for `offset.x: 60`, `rotation.angle: 8`; document still accepted. |
| `CS-118` | A zero-offset, unit-scale, zero-rotation profile MUST be valid and MUST leave coordinates unchanged. | `identity.yaml` maps every sampled point to itself. |
| `CS-119` | Given identical input, calibrated coordinates MUST be identical across implementations; composition order MUST NOT be altered (IN-6 applies to artifacts). | Two independent engines compared on the Section 9.3 example within `1e-6` mm. |

### 9.3 Normative worked example

Transform:

```yaml
transform:
  offset: { x: 2.0, y: -1.0 }
  scale: { x: 1.02, y: 0.98 }
  rotation: { angle: 1.5, origin: { x: 100.0, y: 50.0 } }
```

For ideal point `P = (30.0, 40.0)`:

1. Reposition: `P1 = (−70.0, −10.0)`
2. Scale: `P2 = (−71.4, −9.8)`
3. Rotate clockwise on the page by 1.5° with `P3x = P2x·cos θ − P2y·sin θ`, `P3y = P2x·sin θ + P2y·cos θ`: `P3 ≈ (−71.118999, −11.665676)`
4. Restore origin: `P4 ≈ (28.881001, 38.334324)`
5. Translate: `P' ≈ (30.881001, 37.334324)`

A conforming engine MUST produce `(30.881001, 37.334324)` with tolerance `1e-4` mm.

Convention check, taken from CalibrationSpec §7: with origin `(0, 0)`, unit scale and zero offset, `angle = 90` maps `(10, 0)` to `(0, 10)` — downward on the page, which is clockwise when viewing the sheet.

---

## 10. REST API Conformance (`CP-API`)

### 10.1 Protocol and error model

| ID | Requirement | Verification |
| :--- | :--- | :--- |
| `AP-101` | Every resource URI MUST be under the `/v1` prefix. | `GET /v1/templates` succeeds; an unversioned `GET /templates` MUST NOT return a success response. |
| `AP-102` | Responses MUST carry `X-API-Version: 1.0`, and `GET /v1/info` MUST report `api_version: "1.0"`. | Header and body asserted. |
| `AP-103` | `GET /v1/health` MUST return `200` with a JSON body containing `status: "ok"`. | Body asserted. |
| `AP-104` | Error responses MUST use `application/problem+json` and contain `type`, `title` and `status`, with `status` equal to the HTTP status. | Assert on `404` and `422` cases. |
| `AP-105` | Error `type` URIs MUST correspond to the failing condition per API §5.2. | `400`, `401`, `403`, `404`, `409`, `422` fixtures each assert their `type`. |
| `AP-106` | `422` validation responses MUST include an `errors` array whose entries carry `field` and `message`. | Assert on a schema-invalid RenderSpec submission. |
| `AP-107` | Business-rule failures MUST use the stable codes `ambiguous-calibration-profile`, `stock-translation-failed`, `missing-template-or-document`, `printer-not-found`, `stock-not-found` with status `422`. | One fixture per code. |
| `AP-108` | Missing or invalid credentials MUST return `401` with `WWW-Authenticate: Bearer realm="OpenLabelServer"`; insufficient role MUST return `403`. | Viewer creating a template returns `403`; anonymous request returns `401`. |
| `AP-109` | When both `Authorization: Bearer` and `X-API-Key` are present, the Bearer token MUST be evaluated first. | Valid Bearer plus invalid key succeeds; invalid Bearer plus valid key returns `401`. |
| `AP-110` | Collections MUST support `page` (default `1`, `>= 1`) and `page_size` (default `20`, `1`–`100`), and MUST return the pagination envelope with `object: "list"`, `data`, `pagination.page`, `page_size`, `total_items`, `total_pages = ceil(total_items / page_size)`, `has_next`, `has_previous`. | Seed 127 items; assert `page=3&page_size=50` yields `total_pages: 3`, `has_next: false`, `has_previous: true`. |
| `AP-111` | (RECOMMENDED) Paginated responses SHOULD include `Link` headers for `next` and `first`. | Header presence and relations. |
| `AP-112` | Every resource object MUST include `id`, `object`, `created_at`; `updated_at` is included when known. | Assert on each resource type retrieved. |
| `AP-113` | An API client MUST tolerate unknown JSON properties in responses and SHOULD ignore undocumented headers. | Feed a response with an extra property to the client; it MUST NOT fail. |
| `AP-114` | When rate limiting is enforced, the response MUST be `429` with `Retry-After` and a `problem+json` body. | Enforce a low limit; assert `429`, header and body. |
| `AP-115` | Errors MUST be returned as `application/problem+json` even when the client sends `Accept: application/json`. | Content type asserted. |

### 10.2 Resources

| ID | Requirement | Verification |
| :--- | :--- | :--- |
| `AR-101` | Templates MUST expose list, create, retrieve, replace, metadata patch, delete and stateless validate. | Each operation exercised. |
| `AR-102` | A template's `id` MUST equal `document.id`; a disagreement MUST return `409 Conflict`. | `POST /v1/templates` with `id` mismatch; `PUT /v1/templates/other` for a stored document. |
| `AR-103` | Creating a template whose `id` already exists MUST return `409 Conflict`. | Duplicate create. |
| `AR-104` | Stocks and calibrations MUST normalize `id` from `document.metadata.id`, returning `409 Conflict` on disagreement, and MUST enforce catalog uniqueness of `metadata.id`. | Mismatch and duplicate fixtures. |
| `AR-105` | Assets MUST be created by `multipart/form-data` with a REQUIRED `file` field, return `201 Created`, use opaque `ast_` identifiers, accept the documented content types, and serve bytes from `/v1/assets/{asset_id}/content`. | Upload a PNG; assert status, prefix, byte equality on download, and rejection of an unsupported content type. |
| `AR-106` | Domain documents submitted to template, stock and calibration endpoints MUST be validated before persistence; invalid documents MUST return `422` and MUST NOT be stored. | Submit an invalid RenderSpec, then assert retrieval returns `404`. |
| `AR-107` | Job submission MUST accept exactly one of `template_id` or `document`; neither or both MUST return `422` with `missing-template-or-document`. | Three fixtures covering the rule. |
| `AR-108` | Job `output.format` MUST accept `pdf` and `postscript`, and reject other values. | `format: "svg"` rejected. |
| `AR-109` | Render job identifiers MUST be `rnd_`-prefixed and print job identifiers `prt_`-prefixed; both MUST be opaque. | Prefix assertions. |
| `AR-110` | Render job status MUST use only `queued`, `processing`, `completed`, `failed`, `cancelled`; print job status MUST use only `queued`, `rendering`, `printing`, `completed`, `failed`, `cancelled`. | Imported/queried states asserted. |
| `AR-111` | `DELETE` on a pending job MUST cancel it. Deleting an already-cancelled or completed job is implementation-defined, but MUST NOT produce a `5xx` response. | Cancel a pending job, then repeat the request; no server error is reported. |
| `AR-112` | Printers MUST be listed, discoverable, retrievable with capabilities, and a printer `id` MUST equal the calibration `printer.identifier` when both exist. | Discovery fixture; identifier equality asserted. |
| `AR-113` | A print job with an unknown `printer_id` MUST return `422` with `printer-not-found`. | Unknown printer fixture. |
| `AR-114` | When `calibration_id` is supplied, the server MUST use that profile and MUST NOT run automatic selection. | Ambiguous profiles plus explicit `calibration_id` succeeds. |

### 10.3 Cross-specification behavior

| ID | Requirement | Verification |
| :--- | :--- | :--- |
| `AJ-101` | When `stock_id` is present, the effective RenderSpec MUST be built in the order: start from template or inline document; apply StockSpec translation replacing `page` and `stock`; override `data` with job payload; validate; render. | Fixture where the template `page` differs from the stock `page`; assert effective `page` came from StockSpec. |
| `AJ-102` | StockSpec translation MUST use exactly the mapping in `SS-116`, and `stock_id` MUST take precedence over inline `stock`, with inline `stock` discarded after merge. | Template with inline stock plus `stock_id`; assert translated values win. |
| `AJ-103` | A StockSpec that is valid but translates into an invalid RenderSpec MUST return `422` with `stock-translation-failed`. | Fixture constructed to fail after translation. |
| `AJ-104` | All render and print pipelines MUST validate the effective RenderSpec against the published schema before execution. | Effective document mutated to violate the schema; assert rejection. |
| `AJ-105` | Print jobs MUST apply calibration after layout resolution and before print submission, and MUST reject synchronously when profile selection is ambiguous. | Ambiguous fixture asserts `422` and `ambiguous-calibration-profile`. |
| `AJ-106` | A print job whose `stock_id` does not match a stored stock MUST return `422` with `stock-not-found`. | Unknown stock fixture. |
| `AJ-107` | Asset references in stored templates MUST use one of the three documented forms — an API asset URI, an external HTTPS URL, or a base64 data URI — and an API asset URI MUST serve the stored bytes. | Store a template referencing an uploaded asset by its API URI; render succeeds and the fetched bytes equal the uploaded bytes. |
| `AJ-108` | Ambiguous calibration selection MUST produce an `errors[]` entry whose `field` identifies the selection input and whose `code` is `ambiguous-calibration-profile`. | Body asserted against the published example `ambiguous_calibration_error.json`. |

### 10.4 RFC-0001 mandated cases

These three cases are required by [RFC-0001](../../rfcs/RFC-0001-api-validation-and-idempotency-corrections.md) and MUST be covered by any `CP-API` claim. They are reproduced here as normative verifications so that they remain discoverable from this specification.

| ID | RFC-0001 case | Requirement | Verification |
| :--- | :--- | :--- | :--- |
| `AQ-101` | Case 1 — stateless validation | `POST /v1/templates/{template_id}/validate` MUST NOT load or persist a stored template and MUST NOT return `404`. When `document.id` differs from `template_id`, it MUST return `409 Conflict` with the conflict `type`. | Valid document whose `id` equals the path: `200` with a `ValidationSuccess` body per [openapi.yaml](../api/openapi.yaml), and no template is created (`GET /v1/templates/{id}` returns `404`). Document whose `id` differs: `409`, `application/problem+json`, `type` = `.../errors/conflict`. The operation MUST never return `404` for either input. |
| `AQ-102` | Case 2 — idempotent asset replay | A duplicate `Idempotency-Key` with an identical body within 24 hours MUST replay the stored `201 Created` response and create no second asset. | Upload with key `K`; repeat with the same key and bytes; assert status `201`, identical body including the same `ast_` identifier, and unchanged asset count. A different body under key `K` MUST return `409`. |
| `AQ-103` | Case 3 — idempotent job replay | Duplicate keys on `POST /v1/render-jobs` and `POST /v1/print-jobs` MUST replay the stored `202 Accepted` response and create no second job. | Submit with key `K`; repeat; assert `202`, identical body with the same `rnd_`/`prt_` identifier, and unchanged job count. Different body under key `K` MUST return `409`. |

`AQ-104` Corresponding negative control: a duplicate request without an `Idempotency-Key` MUST create a second resource. This confirms that replay is key-driven and not an accident of deduplication.

---

## 11. Renderer Output Conformance (`CP-RND`)

| ID | Requirement | Verification |
| :--- | :--- | :--- |
| `RO-101` | No output artifact MUST be produced for a document that fails validation. | Invalid fixture; assert no file is written and an error is reported. |
| `RO-102` | Output MUST be vector: text MUST be emitted as text with fonts, and shapes as path or curve operators, not as embedded page bitmaps. | Parse the artifact: font objects present; no full-page image XObject for shape-only fixtures. |
| `RO-103` | SVG assets MUST be preserved as vector operations and MUST NOT be rasterized unless an output limit explicitly requires it. | SVG fixture; assert vector path operators and absence of a raster copy of the artwork. |
| `RO-104` | Fonts MUST be embedded in vector output; `embed_fonts` MUST default to `true`, and a renderer MUST NOT emit unembedded custom fonts — it MUST either reject `embed_fonts: false` for a document with custom fonts or emit with embedding enabled. | Assert embedded, subset font names in the artifact; a request that disables embedding for a custom-font document either fails or still yields embedded fonts. |
| `RO-105` | `output.color_space` MUST be honored (`rgb`, `cmyk`, `grayscale`), and the CMYK conversion an implementation applies MUST be documented and MUST match the emitted values. | Automated: assert color operators and channel values for each setting against a fixed swatch fixture. Attested: documentation names the conversion algorithm (a manual review item in the report, not an automated check). |
| `RO-106` | With `output` omitted, the defaults MUST apply: sRGB, 300 dpi for any rasterization, PDF 1.4, font embedding on, compression on. | Header and resource assertions. |
| `RO-107` | Barcodes MUST render for `code128`, `code39`, `ean13`, `ean8`, `upca`, `upce`, `itf`, `codabar` and `pdf417`, and MUST decode back to `content`. | Rasterize at 600 dpi and decode each symbology. |
| `RO-108` | QR codes MUST render and decode to `content` at every `error_correction` level (`L`, `M`, `Q`, `H`), with a square symbol of `size` mm. | Four fixtures decoded; measured extent asserted. |
| `RO-109` | The artifact page size MUST equal the effective `page` (or StockSpec page) dimensions within `0.01` mm. | PDF `MediaBox` converted to millimetres. |
| `RO-110` | The artifact MUST NOT contain creation or modification timestamps, and any document identifier MUST be derived from content, not from time (IN-3). | Scan the artifact for PDF `/CreationDate` / `/ModDate` or PostScript `%%CreationDate`; render twice under different clocks and compare identifiers. |
| `RO-111` | Golden artifacts MUST be published with a SHA-256 digest of the exact expected bytes. | Digest comparison (Section 12). |
| `RO-112` | Content MUST NOT be drawn outside the active boundary (page or label), including stroke width. | High-resolution raster inspection of a full-bleed fixture. |

---

## 12. Determinism and Reproducibility (`CP-RND`)

Determinism is the property the platform exists to guarantee. These requirements are mandatory for any profile that emits artifacts.

| ID | Requirement | Verification |
| :--- | :--- | :--- |
| `DT-101` | Rendering the same input twice MUST produce byte-identical output. | Two runs; SHA-256 equality. |
| `DT-102` | Rendering the same input on two different operating systems or CPU architectures MUST produce byte-identical output. | Two environments in CI; digest equality. |
| `DT-103` | Font subsetting MUST be deterministic: identical subsets produce identical font programs. | Compare embedded font streams across runs. |
| `DT-104` | Stream compression MUST be deterministic and MUST NOT encode time or environment data. | Compare compressed streams; assert no timestamp fields. |
| `DT-105` | No identifier in the output MAY be random or time-derived; document identifiers MUST be content-derived. | Repeat with a fixed clock and a changed clock; digests match. |
| `DT-106` | Output MUST NOT depend on locale, timezone, environment variables, working directory or path separators. | Run under `TZ`, `LANG` and cwd variations; digests match. |
| `DT-107` | Concurrent renders of the same input MUST produce byte-identical output. | 10 parallel renders; identical digests. |
| `DT-108` | Calibrated coordinates MUST be deterministic for identical calibration input (see `CS-119`). | Reported coordinate equality within `1e-6` mm. |
| `DT-109` | The declared output ordering of content (page order, layer order, object order) MUST be stable across runs and environments. | Operator sequence comparison. |

---

## 13. Pipeline and Physical Output Conformance (`CP-PIPE`)

### 13.1 Pipeline

| ID | Requirement | Verification |
| :--- | :--- | :--- |
| `PL-101` | The pipeline order MUST be: resolve effective document, validate, layout and grid placement, apply calibration, emit or submit. | Instrumented pipeline trace for one job. |
| `PL-102` | Calibration MUST NOT modify the stored RenderSpec, StockSpec or CalibrationSpec document. | Compare stored documents before and after a job. |
| `PL-103` | (RECOMMENDED) When a StockSpec with a non-rectangular `label.shape` is attached, clipping SHOULD follow that shape even though the translated RenderSpec carries no shape field. | Round-label fixture; corners blank. |

### 13.2 Physical output

Physical verification requires a real printer and is reported as `not-tested` with a reason when unavailable. Measurement method: print the published registration fixture (a 100.0 mm crosshair and a full-label border) on the stock under test, condition the output, then measure five samples with a device accurate to `0.1` mm and report the median.

| ID | Requirement | Verification |
| :--- | :--- | :--- |
| `PH-101` | Registration error MUST NOT exceed `0.5` mm in X or Y relative to the nominal layout. | Median measured offset. |
| `PH-102` | Dimensional scale error MUST NOT exceed `0.5%` of the nominal measured length over 100 mm. | Measured `100.0` mm target. |
| `PH-103` | Angular skew MUST NOT exceed `0.2`° relative to the media edge. | Measured edge-to-target angle. |
| `PH-104` | Feed repeatability MUST NOT exceed `0.3` mm across ten consecutive labels. | Spread of measured Y positions. |
| `PH-105` | After a calibration profile is applied, the residual registration error MUST NOT exceed `0.5` mm. | Measure before and after applying `laser_sheet_full.yaml`-style correction. |

The numeric limits in this section are established by ConformanceSpec v1.0 as conformance limits; they may be revised only through the RFC process.

---

## 14. Performance Conformance (`CP-PERF`, OPTIONAL)

Measured on reference hardware of 4 vCPU and 8 GB RAM, with the published example documents, after a warm-up run, reporting the median of five runs.

| ID | Requirement | Verification |
| :--- | :--- | :--- |
| `PF-101` | Render of a single-label RenderSpec to PDF MUST complete in under `500` ms. | Timed runs. |
| `PF-102` | Preview generation MUST complete in under `250` ms. | Timed runs against the preview output. |
| `PF-103` | Peak resident memory per render process MUST stay under `512` MB. | Measured peak RSS. |
| `PF-104` | Ten concurrent clients reading template resources MUST all succeed, with every response completing in under `1` s. | Concurrent read load; assert status and per-response latency. |
| `PF-105` | One hundred concurrent queued jobs MUST be accepted and completed without loss or duplication. | Queue load; assert exactly one artifact per job. |

---

## 15. Publishing a Conformance Claim

A claim MUST be published as a document (for example `CONFORMANCE.md` in the implementation repository) containing:

1. Implementation name and version, and the version of each component evaluated.
2. The list of profiles claimed, for example `CP-RS`, `CP-ST`, `CP-CAL`, `CP-CE`, `CP-RND`, `CP-API`.
3. The domain specification versions and this specification's version.
4. The conformance report (Section 16), either inline or by URL, with the suite version used.
5. The environments used for `DT-102`, identified by operating system and architecture.
6. Every result with status `not-tested` or `not-applicable`, with the reason.
7. A statement of limitations, including any requirement not verified.

A claim MUST NOT be made for a profile whose mandatory requirements include any `fail` or unjustified `not-tested` result.

Example claim statement:

> Acme Label Service 2.3 conforms to OpenLabelServer ConformanceSpec 1.0 profiles CP-RS, CP-ST, CP-CAL, CP-CE, CP-RND and CP-API for RenderSpec 1.0, StockSpec 1.0, CalibrationSpec 1.0 and REST API 1.0, with the attached report. `PH-*` was not tested: no printer was available in the reporting environment.

---

## 16. Conformance Report Format

Reports are JSON documents with the following members. This is the only structure this specification defines; it is a reporting format, not a new domain document.

```json
{
  "conformance": "1.0",
  "profiles": ["CP-RS", "CP-RND"],
  "implementation": { "name": "Acme Renderer", "version": "2.3.0" },
  "specifications": {
    "renderspec": "1.0",
    "stockspec": "1.0",
    "calibrationspec": "1.0",
    "api": "1.0"
  },
  "suite": { "name": "openlabelserver-conformance", "version": "1.0.0" },
  "environment": { "os": "linux", "arch": "x86_64", "runtime": "python 3.12" },
  "results": [
    { "requirement": "RS-101", "status": "pass" },
    { "requirement": "RT-103", "status": "pass", "details": "6 frames within 1e-6 mm" },
    { "requirement": "PH-101", "status": "not-tested", "reason": "no printer available" }
  ],
  "summary": {
    "total": 3,
    "passed": 2,
    "failed": 0,
    "not_applicable": 0,
    "not_tested": 1
  },
  "generated_at": "2026-11-14T12:00:00Z"
}
```

This example is abridged for readability: `results` shows three entries, while `CR-2` requires one entry per requirement of every claimed profile in a real report.

Rules:

| Rule | Statement |
| :--- | :--- |
| `CR-1` | `conformance` MUST be `"1.0"` for reports produced against this specification. |
| `CR-2` | `results` MUST contain one entry per requirement in every claimed profile. |
| `CR-3` | `status` MUST be one of `pass`, `fail`, `not-applicable`, `not-tested`. |
| `CR-4` | `not-applicable` MUST include a `reason`; a requirement in a claimed profile is not-applicable only when the requirement's text explicitly allows it. |
| `CR-5` | `not-tested` MUST include a `reason`. |
| `CR-6` | `summary` MUST be consistent with `results`. |
| `CR-7` | A `fail` MUST include `details` describing observed and expected values. |

---

## 17. Change Control

1. Requirement IDs are permanent. A removed requirement is retired and its ID is never reused.
2. Adding a requirement, raising a `RECOMMENDED` to mandatory, or changing a limit such as `PH-101` requires an RFC.
3. Clarifying wording without changing an observable outcome is editorial and does not require an RFC.
4. This specification is versioned independently of the domain specifications. A new major version of a domain specification requires a corresponding revision of this document.
5. Conformance to ConformanceSpec 1.0 is bound to RenderSpec 1.0, StockSpec 1.0, CalibrationSpec 1.0 and REST API 1.0.

---

## 18. Required Fixtures

The suite MUST publish at least the following negative fixtures, in addition to the conformant examples that already ship with each specification.

| Area | Fixtures |
| :--- | :--- |
| RenderSpec | invalid version; invalid `id`; zero page dimension; stock missing a pitch; `rows: 0`; duplicate layer ids; duplicate object ids in one layer; unresolved `asset_id`; `type: "star"`; `circle` without `r`; `"none"` used as a text color; unknown property; NaN coordinate; `align` without `width` |
| StockSpec | invalid version; missing `pitch`; non-positive dimension; pitch smaller than label; grid overflowing the page; outer margin off by `0.2` mm; round label with unequal sides; `corner_radius` on a rectangle; printable area exceeding the label; negative margin; conflicting inline stock |
| CalibrationSpec | invalid version; missing `transform`; bad `printer.identifier`; zero scale; `uniform` with explicit axis; unknown property; `scope: "sheet"`; disabled but invalid |
| API | invalid RenderSpec (`422` with `errors[]`); id mismatch (`409`); unknown printer (`printer-not-found`); unknown stock (`stock-not-found`); neither/both template and document; ambiguous calibration; unsupported asset content type; pagination boundary (`page_size: 101`); anonymous request (`401`); viewer mutation (`403`); rate-limited (`429`) |
| RFC-0001 | stateless validate success, validate identity mismatch (`409`), validate MUST NOT return `404`; asset replay (`201`), asset replay with changed body (`409`), duplicate upload without key (two assets); job replay (`202`), job replay with changed body (`409`), duplicate submission without key (two jobs) |

---

## Appendix A — Requirement Index

| Prefix | Area | Section | Count |
| :--- | :--- | :--- | :--- |
| `CN` | Common rules | 5 | 6 |
| `RS` | RenderSpec document | 6 | 19 |
| `RT` | RenderSpec layout and transforms | 7.1–7.2 | 17 |
| `RB` | RenderSpec data binding | 7.3 | 4 |
| `SS` | StockSpec | 8 | 20 |
| `CS` | CalibrationSpec | 9 | 22 |
| `AP` | API protocol and errors | 10.1 | 15 |
| `AR` | API resources | 10.2 | 14 |
| `AJ` | API cross-specification | 10.3 | 8 |
| `AQ` | RFC-0001 cases | 10.4 | 4 |
| `RO` | Renderer output | 11 | 12 |
| `DT` | Determinism | 12 | 9 |
| `PL` | Pipeline | 13.1 | 3 |
| `PH` | Physical output | 13.2 | 5 |
| `PF` | Performance (OPTIONAL) | 14 | 5 |

## Appendix B — Traceability to RFC-0001

| RFC-0001 requirement | Conformance requirement | Notes |
| :--- | :--- | :--- |
| Validate MUST NOT return `404` | `AQ-101` | Asserts `409` on identity mismatch and absence of persistence |
| Validate identity mismatch returns `409` | `AQ-101` | Body validated as `application/problem+json` with conflict `type` |
| Asset replay returns original `201` and body | `AQ-102` | Asset count unchanged |
| Job replay returns original `202` | `AQ-103` | Render and print jobs, count unchanged |
| Key reuse with a different body returns `409` | `AQ-102`, `AQ-103` | Both resource types |

## Appendix C — Related Documents

- [RenderSpec](../renderspec/specification.md)
- [StockSpec](../stockspec/specification.md)
- [CalibrationSpec](../calibrationspec/specification.md)
- [REST API](../api/specification.md) and [OpenAPI contract](../api/openapi.yaml)
- [RFC-0001](../../rfcs/RFC-0001-api-validation-and-idempotency-corrections.md)
- [tests/README.md](../../tests/README.md) — test layers and layout
- [CHECKLIST.md](../../CHECKLIST.md) — completion tracking
