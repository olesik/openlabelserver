# StockSpec Specification v1.0

## Status of this Document

This document defines version 1.0 of the **StockSpec** specification, the canonical format for defining physical label stock layouts (dimensions, repeating grids, margins, shapes, and boundaries) within the OpenLabelServer ecosystem.

---

## 1. Introduction

### 1.1 Purpose
StockSpec is a versioned, machine-readable declarative format (typically written in YAML) describing the physical geometry of sheet-fed or roll-fed label stock. It provides a clean division of concerns in the printing pipeline:
- **RenderSpec** defines *what* is drawn inside a canvas (e.g. text, barcodes, shapes) and may reference a stock layout to repeat content.
- **StockSpec** defines the *canvas layout itself*—its boundaries, shapes, positions on a page, and repeating grid structure.
- **CalibrationSpec** (defined separately) handles printer-specific mechanical offsets (e.g., margins, alignment shifts, or print density profiles).

By separating layout geometry from design assets and calibration parameters, label stocks can be reused across different label designs, and designs can be rendered on varying physical stocks.

### 1.2 Scope
StockSpec defines **physical stock geometry only**: page size, label shape, grid, margins, and pitch.

StockSpec does **not** define:
- Label artwork, text, barcodes, or assets (see [RenderSpec](../renderspec/specification.md))
- Printer mechanical offsets, scaling, or rotation (see [CalibrationSpec](../calibrationspec/specification.md))

All physical dimensions, coordinates, sizes, offsets, and pitches MUST be defined in **millimeters (mm)** as floating-point numbers.

### 1.3 Serialization
The canonical serialization for StockSpec documents is **YAML 1.2**. Implementations MUST also accept equivalent JSON.

The published machine schema is [schema.json](schema.json) (JSON Schema Draft-07). YAML documents MUST be parsed into the same object model and validated against that schema. There is no separate YAML Schema dialect; `schema.json` is the YAML schema for StockSpec.

---

## 2. Conformance & Terminology

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT", "SHOULD", "SHOULD NOT", "RECOMMENDED", "MAY", and "OPTIONAL" in this document are to be interpreted as described in [RFC 2119](https://tools.ietf.org/html/rfc2119).

* **Stock Parser**: A software component that reads a StockSpec document and validates it against the schema and mathematical constraints.
* **Layout Renderer**: A software component that consumes a StockSpec layout to position rendering viewports on an output canvas.
* **StockSpec Document**: A JSON/YAML document adhering to the structural schema and validation rules defined in this specification.
* **Active Boundary**: The physical boundary of an individual label.

---

## 3. Physical Dimensions & Coordinates

### 3.1 Millimeter Canonical Coordinate System
1. All physical dimensions, coordinates, sizes, offsets, and pitches MUST be defined in **millimeters (mm)** as floating-point numbers.
2. The coordinate system uses a two-dimensional Cartesian plane:
   - The **X-axis** is horizontal, increasing from left to right.
   - The **Y-axis** is vertical, increasing from top to bottom.
3. The origin `(0.0, 0.0)` of a page represents the **top-left corner** of the physical sheet or paper.
4. The origin `(0.0, 0.0)` of a label represents the **top-left corner** of the individual active boundary for that label.

This coordinate system MUST match [RenderSpec](../renderspec/specification.md) Section 3.

---

## 4. Document Model

A StockSpec document is a single root object (serialized as YAML or JSON). The root object MUST contain the following properties:

| Property | Type | Presence | Description |
| :--- | :--- | :--- | :--- |
| `stockspec` | `string` | **REQUIRED** | MUST be exactly `"1.0"`. |
| `metadata` | `object` | **REQUIRED** | Meta information identifying the stock and its origin. |
| `page` | `object` | **REQUIRED** | Bounding physical dimensions of the output sheet/paper. |
| `label` | `object` | **REQUIRED** | Shape and dimensions of an individual label boundary. |
| `grid` | `object` | **REQUIRED** | Repeating grid layout counts (rows and columns). |
| `margins` | `object` | **REQUIRED** | Physical edge offsets of the grid on the sheet/paper. |
| `pitch` | `object` | **REQUIRED** | Distance between the starts of adjacent rows and columns. |
| `printable_area` | `object` | OPTIONAL | Inner safe margins within each label. |

---

## 5. Sub-Object Structure & Geometry

### 5.1 Metadata Object (`metadata`)
Contains identification information.
* `id` (REQUIRED, string): A unique slug identifier. MUST match the regex `^[a-zA-Z0-9_-]+$`.
* `name` (REQUIRED, string): Human-readable descriptive name.
* `description` (OPTIONAL, string): Human-readable details.
* `manufacturer` (OPTIONAL, string): Brand/Manufacturer name (e.g. `Avery`).
* `part_number` (OPTIONAL, string): Manufacturer catalog number (e.g. `5160`).
* `tags` (OPTIONAL, array of strings): Meta tags for categorized searching (e.g., `["address", "letter"]`).
* `created_at` (OPTIONAL, string): ISO 8601 UTC timestamp of creation.
* `updated_at` (OPTIONAL, string): ISO 8601 UTC timestamp of last update.

Timestamps exist for catalog management only. Stock parsers MUST NOT use them in layout calculations.

### 5.2 Page Object (`page`)
Defines the overall physical sheet or roll target.
* `width` (REQUIRED, float): Physical page width in mm. MUST be greater than `0.0`.
* `height` (REQUIRED, float): Physical page height in mm. MUST be greater than `0.0`.
* `format` (OPTIONAL, string): Page format classification. MUST be one of `"letter"`, `"a4"`, `"legal"`, `"a5"`, `"roll"`, `"custom"`.

`format` is informational metadata for catalogs and UIs. Renderers MUST use `width` and `height` as the authoritative page size. For roll stock, `page.width` and `page.height` describe one label frame (typically matching the single label), not an unbounded roll length.

### 5.3 Label Object (`label`)
Defines the dimensions and geometry of a single label viewport. `width` and `height` describe the **axis-aligned bounding box** of the die-cut.
* `width` (REQUIRED, float): Width of a single label in mm. MUST be greater than `0.0`.
* `height` (REQUIRED, float): Height of a single label in mm. MUST be greater than `0.0`.
* `shape` (OPTIONAL, string): One of `"rectangle"`, `"rounded-rectangle"`, `"round"`, `"oval"`. Default is `"rectangle"`.
* `corner_radius` (OPTIONAL, float): Physical radius of the corners in mm. MUST be ≥ `0.0`. ONLY applicable if `shape` is `"rounded-rectangle"`. MUST NOT be present for other shapes.

Shape clipping:
* `"rectangle"` — clip to the bounding box.
* `"rounded-rectangle"` — clip to a rounded rectangle of `width` × `height` with radius `corner_radius`.
* `"round"` — clip to a circle of diameter `width` centered in the bounding box. `width` MUST equal `height`.
* `"oval"` — clip to an ellipse inscribed in the bounding box.

Renderers MUST clip RenderSpec objects to the active label shape. Artwork MUST NOT bleed into neighboring labels or the sheet waste.

### 5.4 Grid Object (`grid`)
Specifies repeating grid density.
* `rows` (REQUIRED, integer): Number of rows on the sheet. MUST be ≥ `1`.
* `columns` (REQUIRED, integer): Number of columns on the sheet. MUST be ≥ `1`.

A single-label stock (thermal roll, one-up sheet) MUST use `rows: 1` and `columns: 1`. Labels are filled in **row-major** order: column index increases first, then row index.

### 5.5 Margins Object (`margins`)
Specifies the physical start coordinates of the first grid cell relative to the top-left edge of the page.
* `left` (REQUIRED, float): Distance from the left edge of the page to the left edge of the first column in mm. MUST be ≥ `0.0`.
* `top` (REQUIRED, float): Distance from the top edge of the page to the top edge of the first row in mm. MUST be ≥ `0.0`.
* `right` (OPTIONAL, float): Distance from the right edge of the last label column to the right edge of the page in mm. MUST be ≥ `0.0`.
* `bottom` (OPTIONAL, float): Distance from the bottom edge of the last label row to the bottom edge of the page in mm. MUST be ≥ `0.0`.

`left` and `top` are the origin of the grid. `right` and `bottom`, when present, MUST be consistent with remaining page space (Section 6.5). They MUST NOT be used as additional offsets on top of `left`/`top`.

### 5.6 Pitch Object (`pitch`)
Specifies the repeating distance between adjacent labels (left-to-left and top-to-top).
* `horizontal` (REQUIRED, float): Distance from the left edge of one label to the left edge of the next column in mm. MUST be greater than `0.0`.
* `vertical` (REQUIRED, float): Distance from the top edge of one label to the top edge of the next row in mm. MUST be greater than `0.0`.

If adjacent labels share a cut with no gap, pitch equals the corresponding label dimension. If a physical gap exists, pitch is label size plus gap.

### 5.7 Printable Area Object (`printable_area`)
Defines an optional safety buffer zone inside each label boundary where content is guaranteed safe to print (i.e. to account for minor feed variations or die-cut tolerance).
* `left` (OPTIONAL, float): Safe offset from the left edge of the label in mm. Default is `0.0`. MUST be ≥ `0.0`.
* `top` (OPTIONAL, float): Safe offset from the top edge of the label in mm. Default is `0.0`. MUST be ≥ `0.0`.
* `right` (OPTIONAL, float): Safe offset from the right edge of the label in mm. Default is `0.0`. MUST be ≥ `0.0`.
* `bottom` (OPTIONAL, float): Safe offset from the bottom edge of the label in mm. Default is `0.0`. MUST be ≥ `0.0`.

---

## 6. Mathematical Validation Rules

To ensure a StockSpec file represents a physically valid and rendering-safe layout, parsers and renderers MUST enforce the following mathematical validation rules. A document is considered **non-conformant** if any of these rules are violated.

### 6.1 Basic Dimension Validity
All basic dimension fields MUST be positive numbers:

- `page.width` > 0.0
- `page.height` > 0.0
- `label.width` > 0.0
- `label.height` > 0.0
- `grid.rows` ≥ 1
- `grid.columns` ≥ 1
- `pitch.horizontal` > 0.0
- `pitch.vertical` > 0.0

### 6.2 Label Grid Layout Formula
For any cell at 0-indexed column `c` in `[0, grid.columns - 1]` and row `r` in `[0, grid.rows - 1]`, the top-left physical coordinate on the page `(X_col(c), Y_row(r))` MUST be computed as:

- `X_col(c) = margins.left + c × pitch.horizontal`
- `Y_row(r) = margins.top + r × pitch.vertical`

### 6.3 Overlap Prevention
To prevent physical layout definitions where labels overlap, the repeating pitches MUST be equal to or greater than the corresponding label sizes:

- `pitch.horizontal` ≥ `label.width`
- `pitch.vertical` ≥ `label.height`

### 6.4 Sheet Boundary Enclosure
The grid of labels MUST fit entirely within the physical dimensions of the page.

1. **Horizontal Bound**: The right edge of the rightmost column MUST be less than or equal to the page width:

   `margins.left + (grid.columns - 1) × pitch.horizontal + label.width ≤ page.width`

2. **Vertical Bound**: The bottom edge of the bottommost row MUST be less than or equal to the page height:

   `margins.top + (grid.rows - 1) × pitch.vertical + label.height ≤ page.height`

### 6.5 Outer Margin Consistency
If the optional `margins.right` and `margins.bottom` values are explicitly provided, they MUST match the physical remaining spacing on the sheet within an arithmetic tolerance of ±0.1 mm (to account for floating-point representation limits):

- `|margins.right − (page.width − [margins.left + (grid.columns − 1) × pitch.horizontal + label.width])| ≤ 0.1`
- `|margins.bottom − (page.height − [margins.top + (grid.rows − 1) × pitch.vertical + label.height])| ≤ 0.1`

### 6.6 Shape Constraints
1. **Round Shape Consistency**: If `label.shape` is `"round"`, the label width and label height MUST be equal (`label.width == label.height`).
2. **Corner Radius Limit**: If `label.shape` is `"rounded-rectangle"`, the corner radius MUST NOT exceed half of the smaller label dimension: `label.corner_radius ≤ min(label.width, label.height) / 2.0`.
3. **Corner Radius Applicability**: `corner_radius` MUST NOT be present unless `label.shape` is `"rounded-rectangle"`.

### 6.7 Printable Area Inner Bounds
If the `printable_area` object is defined, the total margin padding inset MUST NOT exceed the physical size of the label:

- `printable_area.left + printable_area.right < label.width`
- `printable_area.top + printable_area.bottom < label.height`

### 6.8 Identifier Uniqueness
`metadata.id` MUST be unique within a stock catalog. Timestamps MUST NOT affect layout calculations or rendered output.

---

## 7. Mapping to RenderSpec

A StockSpec document MAY be applied to a RenderSpec that omits the inline `stock` object. Implementations MUST map fields as follows:

| StockSpec | RenderSpec |
| :--- | :--- |
| `page.width` / `page.height` | `page.width` / `page.height` |
| `label.width` / `label.height` | `stock.width` / `stock.height` |
| `grid.rows` / `grid.columns` | `stock.rows` / `stock.columns` |
| `margins.left` / `margins.top` | `stock.margin_left` / `stock.margin_top` |
| `pitch.horizontal` / `pitch.vertical` | `stock.horizontal_pitch` / `stock.vertical_pitch` |

If a RenderSpec already includes inline `stock`, and a StockSpec is also supplied, the two MUST agree on mapped numeric fields within ±0.1 mm. Implementations MUST reject conflicting pairs rather than silently preferring one source.

Shape, `corner_radius`, `printable_area`, and metadata exist only on StockSpec. Renderers SHOULD still clip to StockSpec shape when a StockSpec is attached.

---

## 8. Examples

Validated example stocks are maintained in [examples/](examples/):

| Example | File | Demonstrates |
| :--- | :--- | :--- |
| Avery 5160 | [avery_5160.yaml](examples/avery_5160.yaml) | US Letter 30-up sheet, rounded-rectangle, margins, pitch, printable area |
| 2-inch round | [round_2inch.yaml](examples/round_2inch.yaml) | A4 grid of circular labels (`shape: round`) |
| 4×6 shipping | [shipping_4x6.yaml](examples/shipping_4x6.yaml) | Thermal roll, 1×1 grid, page equals label |

All examples MUST validate against [schema.json](schema.json). CI runs schema validation via [scripts/validate_schemas.py](../../scripts/validate_schemas.py). Mathematical rules in Section 6 are additional to JSON Schema and MUST be enforced by stock parsers.
