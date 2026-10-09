# RenderSpec Specification v1.0

## Status of this Document

This document defines version 1.0 of the **RenderSpec** specification, the canonical declarative format for label design and printing within the OpenLabelServer ecosystem.

---

## 1. Introduction

### 1.1 Purpose
RenderSpec is a versioned, machine-readable JSON specification describing a document layout for printing or digital preview. It serves as the primary contract between front-end editors, database services, and output rendering engines (such as PDF, PostScript, and SVG rasterizers).

The goal of RenderSpec is to guarantee **deterministic rendering**: the same RenderSpec input MUST yield identical physical and visual output regardless of the execution environment, compiler, operating system, or printer vendor.

### 1.2 Scope
RenderSpec defines the *layout* of a page and its labels. It does NOT define printer-specific calibration (e.g., margins, alignment shifts, or print density profiles), which is governed separately by **CalibrationSpec**.

---

## 2. Conformance & Terminology

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT", "SHOULD", "SHOULD NOT", "RECOMMENDED", "MAY", and "OPTIONAL" in this document are to be interpreted as described in [RFC 2119](https://tools.ietf.org/html/rfc2119).

* **Renderer**: A software component that consumes a RenderSpec document and outputs a print-ready file (e.g., PDF, PostScript).
* **RenderSpec Document**: A JSON document adhering to the structural schema and validation rules defined in this specification.
* **Canvas**: The coordinate plane on which objects are drawn.
* **Active Boundary**: The physical boundary within which layout coordinates are valid. This is either the full Page (when no stock is defined) or an individual Label (when stock is defined).

---

## 3. Coordinate System & Units

### 3.1 Millimeter Canonical Coordinate System
1. All physical dimensions, coordinates, sizes, offsets, and pitches MUST be defined in **millimeters (mm)** as floating-point numbers.
2. The only exception is typography font sizes, which MUST be defined in **points (pt)** (where $1\text{ pt} = \frac{1}{72}\text{ inch} = 0.352777\dots\text{ mm}$).
3. The coordinate system uses a two-dimensional Cartesian plane:
   * The **X-axis** is horizontal, increasing from left to right.
   * The **Y-axis** is vertical, increasing from top to bottom.
4. The origin `(0.0, 0.0)` MUST represent the **top-left corner** of the active rendering canvas.

### 3.2 Target Resolution
Renderers MUST internalize coordinates as double-precision floating-point values to minimize rounding errors. When generating vector outputs (such as PDF or PostScript), renderers SHOULD avoid rasterizing vector coordinates, maintaining coordinate resolution up to the printer's physical limit.

---

## 4. Document Model

A RenderSpec document is a single JSON object. The root object MUST contain the following properties:

| Property | Type | Presence | Description |
| :--- | :--- | :--- | :--- |
| `renderspec` | `string` | **REQUIRED** | MUST be exactly `"1.0"`. |
| `id` | `string` | **REQUIRED** | A unique slug identifier matching the regex `^[a-zA-Z0-9_-]+$`. |
| `name` | `string` | **REQUIRED** | A descriptive name for the label layout. |
| `description` | `string` | OPTIONAL | Human-readable details. |
| `created_at` | `string` | OPTIONAL | ISO 8601 UTC timestamp of creation. |
| `updated_at` | `string` | OPTIONAL | ISO 8601 UTC timestamp of last update. |
| `page` | `object` | **REQUIRED** | Bounding dimensions of the output sheet/paper. |
| `stock` | `object` | OPTIONAL | Details for sheet grids. If omitted, rendering is page-absolute. |
| `assets` | `array` | OPTIONAL | Registry of external graphics (SVG, raster images). |
| `fonts` | `array` | OPTIONAL | Registry of custom web/sought OpenType/TrueType fonts. |
| `layers` | `array` | **REQUIRED** | Ordered lists of layers containing drawing primitives. |
| `data` | `array` | OPTIONAL | Row-level data records for variable interpolation. |
| `output` | `object` | OPTIONAL | Directives on output target formats and constraints. |

### 4.1 Metadata

The root-level metadata fields identify and describe a RenderSpec document:

| Field | Type | Presence | Description |
| :--- | :--- | :--- | :--- |
| `id` | `string` | **REQUIRED** | Stable slug identifier. MUST match `^[a-zA-Z0-9_-]+$`. |
| `name` | `string` | **REQUIRED** | Human-readable title for editors and job logs. |
| `description` | `string` | OPTIONAL | Longer human-readable summary of the layout purpose. |
| `created_at` | `string` | OPTIONAL | ISO 8601 UTC timestamp (`YYYY-MM-DDTHH:MM:SSZ`) of initial creation. |
| `updated_at` | `string` | OPTIONAL | ISO 8601 UTC timestamp of the last structural edit. |

Renderers MUST NOT embed metadata timestamps into rendered output artifacts. Timestamps exist for document management only and MUST NOT affect deterministic rendering output.

### 4.2 Output Options

The optional root `output` object directs the renderer's target format and fidelity constraints:

| Field | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `format` | `string` | — | Target format: `"pdf"` or `"postscript"`. |
| `color_space` | `string` | `"rgb"` | Output color space: `"rgb"`, `"cmyk"`, or `"grayscale"`. |
| `resolution_dpi` | `integer` | `300` | Resolution for any required rasterization, in dots per inch. MUST be ≥ 72. |
| `pdf_version` | `string` | `"1.4"` | PDF compliance level when `format` is `"pdf"`. |
| `embed_fonts` | `boolean` | `true` | Embed registered fonts in vector output. MUST be `true` when custom fonts are used. |
| `compress` | `boolean` | `true` | Enable stream compression for PDF output. |

When `output` is omitted, renderers MUST use the defaults above and select a format according to renderer configuration or API request parameters.

---

## 5. Sub-Object Structure & Geometry

### 5.1 Page Object
Defines the overall canvas sheet target.
* `width` (REQUIRED, float): Physical page width in mm. MUST be greater than `0.0`.
* `height` (REQUIRED, float): Physical page height in mm. MUST be greater than `0.0`.
* `margin` (OPTIONAL, object): Safety margins. Contains `left`, `top`, `right`, and `bottom` keys (floats, in mm, default `0.0`).

### 5.2 Stock Object
Specifies grid repeating parameters for labels on a single sheet. If the `stock` object is present, it changes the rendering mode from **Page-Absolute Mode** to **Stock-Grid Mode**:
* **Page-Absolute Mode (Stock absent)**: The canvas origin `(0,0)` is the top-left of the page. Rendering is performed once.
* **Stock-Grid Mode (Stock present)**: The canvas origin `(0,0)` is the top-left of the individual label. The renderer replicates the layers across the rows and columns specified by the grid.

Properties of `stock`:
* `width` (REQUIRED, float): The physical width of a single label in mm.
* `height` (REQUIRED, float): The physical height of a single label in mm.
* `rows` (REQUIRED, integer): The number of rows on the sheet. MUST be $\ge 1$.
* `columns` (REQUIRED, integer): The number of columns on the sheet. MUST be $\ge 1$.
* `margin_left` (REQUIRED, float): Left edge of the page to the left edge of the first label column.
* `margin_top` (REQUIRED, float): Top edge of the page to the top edge of the first label row.
* `horizontal_pitch` (REQUIRED, float): Distance from the left edge of one label to the left edge of the next column.
* `vertical_pitch` (REQUIRED, float): Distance from the top edge of one label to the top edge of the next row.

#### Stock-Grid Layout Calculation
The top-left coordinate $(X_{col}, Y_{row})$ on the page for a label at index $(c, r)$ (0-indexed) is calculated as:
$$X_{col} = \text{margin\_left} + c \times \text{horizontal\_pitch}$$
$$Y_{row} = \text{margin\_top} + r \times \text{vertical\_pitch}$$

Renderers MUST apply a clipping path to $(X_{col}, Y_{row}, \text{width}, \text{height})$ during rendering to ensure that objects within a label do not bleed into neighboring labels.

> **Note:** The inline `stock` object provides a simplified grid definition for common sheet layouts. For reusable stock definitions with richer geometry (non-rectangular labels, printable areas, bleed), use a standalone [StockSpec](../stockspec/specification.md) document. Renderers MAY accept StockSpec input and map it to the inline `stock` and `page` fields before rendering.

---

## 6. Layers and Composition

1. Layers provide separation of concerns (e.g., background artwork, barcodes, human-readable text).
2. The `layers` array is ordered. Renderers MUST draw layers in the order they appear in the array (index 0 is rendered first, acting as the background; the last index is rendered last, acting as the foreground).
3. Properties:
   * `id` (REQUIRED, string): Unique identifier.
   * `name` (REQUIRED, string): Human-readable name.
   * `visible` (OPTIONAL, boolean, default `true`): If `false`, the renderer MUST NOT draw any objects in this layer.
   * `opacity` (OPTIONAL, float, default `1.0`): Opacity multiplier $[0.0, 1.0]$. The renderer MUST apply this opacity recursively to all elements in the layer.

---

## 7. Font and Asset Registries

### 7.1 Font Registry (`fonts`)
The `fonts` list registers custom typefaces to embed.
* `family` (REQUIRED, string): The identifier name used by `text` objects.
* `variants` (REQUIRED, array): List of variant definitions. Each variant contains:
  * `style` (REQUIRED, string): `"normal"`, `"italic"`, or `"oblique"`.
  * `weight` (REQUIRED, string): e.g., `"normal"`, `"bold"`, or numerical weight strings (`"100"` to `"900"`).
  * `source` (REQUIRED, string): Absolute HTTPS URL, local path, or base64 encoded data-URI of the TTF/OTF font file.

Renderers MUST embed fonts in vector formats (e.g., PDF subset embedding) to guarantee text looks identical across platforms. Renderers SHOULD fallback to standard system families (Helvetica, Times, Courier) if font loading fails.

### 7.2 Asset Registry (`assets`)
The `assets` list registers external graphics.
* `id` (REQUIRED, string): Unique reference identifier.
* `type` (REQUIRED, string): `"svg"`, `"png"`, or `"jpeg"`.
* `source` (REQUIRED, string): Absolute HTTPS URL, local file path, or base64 encoded data-URI.

Renderers MUST preserve SVG as vector operations without rasterization unless explicitly dictated by output limits.

### 7.3 Color Model

Color values throughout RenderSpec are encoded as strings on object properties such as `color`, `fill_color`, `stroke_color`, `background_color`, and related fields.

#### 7.3.1 Supported Formats

Renderers MUST accept the following color string formats:

| Format | Example | Notes |
| :--- | :--- | :--- |
| Hex (6-digit) | `"#RRGGBB"` | `"#0066cc"` |
| Hex (3-digit) | `"#RGB"` | Shorthand; `"#06c"` expands to `"#0066cc"`. |
| Hex (8-digit) | `"#RRGGBBAA"` | Includes alpha channel. |
| CSS `rgb()` | `"rgb(0, 102, 204)"` | Integer channels 0–255. |
| CSS `rgba()` | `"rgba(0, 102, 204, 0.5)"` | Alpha 0.0–1.0. |
| Transparent | `"none"` | No fill or stroke; valid for `fill_color` and `stroke_color`. |

Renderers SHOULD reject malformed color strings during validation.

#### 7.3.2 Output Color Space

The root `output.color_space` field controls how colors are converted at render time:

* `"rgb"` — Preserve sRGB values in PDF/PostScript output.
* `"cmyk"` — Convert colors to CMYK for print workflows. Renderers MUST document the conversion algorithm used.
* `"grayscale"` — Convert colors to luminance values for monochrome output.

When `output` is omitted, renderers MUST treat colors as sRGB (`"rgb"`).

---

## 8. Graphical Objects (RenderObject)

Every object inside the `objects` list of a layer MUST contain `id` and `type` fields. Position coordinates `x` and `y` represent translation offsets relative to the parent context (the label, page, or containing group).

### 8.1 Common Properties
All RenderObjects inherit the following properties:
* `id` (REQUIRED, string): Unique name.
* `type` (REQUIRED, string): One of the types listed below.
* `x` (OPTIONAL, float, default `0.0`): Horizontal translation offset in mm.
* `y` (OPTIONAL, float, default `0.0`): Vertical translation offset in mm.
* `visible` (OPTIONAL, boolean, default `true`): Hides object if `false`.
* `opacity` (OPTIONAL, float, default `1.0`): Alpha transparency $[0.0, 1.0]$.
* `rotation` (OPTIONAL, float, default `0.0`): Rotation angle in degrees clockwise, applied around the anchor `(x, y)`.
* `scale_x` (OPTIONAL, float, default `1.0`): Horizontal scaling factor.
* `scale_y` (OPTIONAL, float, default `1.0`): Vertical scaling factor.
* `transforms` (OPTIONAL, array): Ordered list of transform operations (see Section 9).

---

### 8.2 Object Primitives

#### 8.2.1 `text`
Renders single-line or wrapped typography text.
* `content` (REQUIRED, string): The string to render. Supports dynamic data variables (`{{variable}}`).
* `width` (OPTIONAL, float): Wrapping and boundary width in mm.
* `height` (OPTIONAL, float): Bounding box height in mm.
* `font_family` (OPTIONAL, string): Name of a font declared in `fonts` or standard systems.
* `font_size` (OPTIONAL, float, default `10.0`): Height in points (pt).
* `font_weight` (OPTIONAL, string, default `"normal"`): Weight classification.
* `font_style` (OPTIONAL, string, default `"normal"`): Style classification.
* `color` (OPTIONAL, string, default `"#000000"`): Fill color.
* `align` (OPTIONAL, string, default `"left"`): Horizontal alignment (`"left"`, `"center"`, `"right"`, `"justify"`). Requires `width` to be defined.
* `valign` (OPTIONAL, string, default `"top"`): Vertical alignment (`"top"`, `"middle"`, `"bottom"`). Requires `height` to be defined.
* `line_spacing` (OPTIONAL, float, default `1.0`): Line gap scale multiplier.
* `wrap` (OPTIONAL, boolean, default `false`): Wraps text if true. Requires `width` to be defined.

#### 8.2.2 `rect`
Renders a rectangle.
* `width` (REQUIRED, float): Horizontal dimension in mm.
* `height` (REQUIRED, float): Vertical dimension in mm.
* `fill_color` (OPTIONAL, string, default `"none"`): Inside color.
* `stroke_color` (OPTIONAL, string, default `"none"`): Border color.
* `stroke_width` (OPTIONAL, float, default `1.0`): Line weight in mm.
* `rx` (OPTIONAL, float, default `0.0`): Horizontal corner radius in mm.
* `ry` (OPTIONAL, float, default `0.0`): Vertical corner radius in mm.

#### 8.2.3 `circle`
Renders a circle.
* `r` (REQUIRED, float): Radius in mm.
* `fill_color` (OPTIONAL, string, default `"none"`).
* `stroke_color` (OPTIONAL, string, default `"none"`).
* `stroke_width` (OPTIONAL, float, default `1.0`).

#### 8.2.4 `ellipse`
Renders an ellipse.
* `rx` (REQUIRED, float): Horizontal radius in mm.
* `ry` (REQUIRED, float): Vertical radius in mm.
* `fill_color` (OPTIONAL, string, default `"none"`).
* `stroke_color` (OPTIONAL, string, default `"none"`).
* `stroke_width` (OPTIONAL, float, default `1.0`).

#### 8.2.5 `line`
Renders a line segment.
* `x2` (REQUIRED, float): Endpoint X coordinate in mm (relative to `x`).
* `y2` (REQUIRED, float): Endpoint Y coordinate in mm (relative to `y`).
* `stroke_color` (OPTIONAL, string, default `"#000000"`).
* `stroke_width` (OPTIONAL, float, default `1.0`).
* `stroke_dasharray` (OPTIONAL, array of floats): Dash and space sizes in mm.

#### 8.2.6 `polyline`
Renders connected line segments.
* `points` (REQUIRED, array of coordinate pairs `[x, y]`): Vertices in mm relative to the anchor `(x, y)`.
* `stroke_color` (OPTIONAL, string, default `"#000000"`).
* `stroke_width` (OPTIONAL, float, default `1.0`).

#### 8.2.7 `polygon`
Renders a closed shape from connected line segments.
* `points` (REQUIRED, array of coordinate pairs `[x, y]`): Vertices in mm.
* `fill_color` (OPTIONAL, string, default `"none"`).
* `stroke_color` (OPTIONAL, string, default `"none"`).
* `stroke_width` (OPTIONAL, float, default `1.0`).

#### 8.2.8 `path`
Renders a complex shape from SVG path commands.
* `d` (REQUIRED, string): Standard SVG command string (e.g. `"M 10 10 L 20 20 Z"`). Units are interpreted in mm.
* `fill_color` (OPTIONAL, string, default `"none"`).
* `stroke_color` (OPTIONAL, string, default `"none"`).
* `stroke_width` (OPTIONAL, float, default `1.0`).

#### 8.2.9 `image`
Renders an image from the asset registry.
* `asset_id` (REQUIRED, string): Reference matching an `id` in the `assets` list.
* `width` (REQUIRED, float): Width to scale the image in mm.
* `height` (REQUIRED, float): Height to scale the image in mm.
* `preserve_aspect_ratio` (OPTIONAL, boolean, default `true`): Maintains source proportions.

#### 8.2.10 `barcode`
Renders a 1D linear barcode.
* `content` (REQUIRED, string): Character payload. Supports templates.
* `symbology` (REQUIRED, string): Supported types: `"code128"`, `"code39"`, `"ean13"`, `"ean8"`, `"upca"`, `"upce"`, `"itf"`, `"codabar"`, `"pdf417"`.
* `width` (REQUIRED, float): Total rendering width of barcode pattern in mm.
* `height` (REQUIRED, float): Total height of barcode bars in mm.
* `draw_text` (OPTIONAL, boolean, default `true`): Controls human-readable text display.
* `color` (OPTIONAL, string, default `"#000000"`): Bar color.
* `background_color` (OPTIONAL, string, default `"#ffffff"`): Background fill.

#### 8.2.11 `qrcode`
Renders a 2D QR Code.
* `content` (REQUIRED, string): Payload string. Supports templates.
* `size` (REQUIRED, float): Width and height of the code grid in mm.
* `error_correction` (OPTIONAL, string, default `"M"`): `"L"` (7%), `"M"` (15%), `"Q"` (25%), `"H"` (30%).
* `color` (OPTIONAL, string, default `"#000000"`).
* `background_color` (OPTIONAL, string, default `"#ffffff"`).

#### 8.2.12 `group`
A container to group children. Useful for applying transforms, visibility, or opacities to multiple items.
* `objects` (REQUIRED, array of RenderObjects): Child items.

---

## 9. Transform Model

The renderer MUST apply transformations hierarchically. The coordinate transformation matrix $M$ applied to an object's points is:
$$M = M_{parent} \times T(x, y) \times R(\theta) \times S(s_x, s_y) \times M_{custom}$$

Where:
* $T(x, y)$ is the translation vector defined by the object's `x` and `y` offsets.
* $R(\theta)$ is rotation by `rotation` degrees clockwise.
* $S(s_x, s_y)$ is scaling by `scale_x` and `scale_y`.
* $M_{custom}$ is the cumulative product of the operations specified in the `transforms` array.

### 9.1 Custom Transformation Array (`transforms`)
Each transform operation in the list is evaluated sequentially:
1. **`translate`**: `{"type": "translate", "x": <float>, "y": <float>}`. Translates origin by $x$, $y$ mm.
2. **`scale`**: `{"type": "scale", "sx": <float>, "sy": <float>}`. Scales relative to current origin.
3. **`rotate`**: `{"type": "rotate", "angle": <float>, "cx": <float>, "cy": <float>}`. Rotates by `angle` degrees clockwise around the point `(cx, cy)`. If `cx` and `cy` are omitted, rotation occurs around the current origin `(0.0, 0.0)`.
4. **`matrix`**: `{"type": "matrix", "matrix": [a, b, c, d, e, f]}`. 2D affine transform matrix:
   $$\begin{bmatrix} a & c & e \\ b & d & f \\ 0 & 0 & 1 \end{bmatrix}$$

---

## 10. Data Binding and Interpolation

RenderSpec supports variable substitution using the double curly brace syntax `{{variable_name}}` in `text.content`, `barcode.content`, and `qrcode.content` strings.

### 10.1 Variable Substitution Rules
1. The renderer MUST evaluate dynamic values against the record arrays provided in the root `data` list.
2. If `data` is omitted or empty, template interpolation expressions SHOULD resolve to empty strings `""` or trigger a validation alert depending on renderer configuration.
3. If a record object contains numeric or boolean values, they MUST be serialized to their string equivalents.

### 10.2 Stock-Grid Iteration Model
When in **Stock-Grid Mode**, the page-grid contains $N$ label frames ($N = \text{rows} \times \text{columns}$).
* If `data` contains $M$ records, the renderer MUST populate each label frame index $i$ ($0 \le i < M$) with data from `data[i]`.
* Labels MUST be filled in row-major order: Row 0 Col 0, Row 0 Col 1, ...
* If $M > N$ (more records than single sheet slots), the renderer MUST generate multiple output pages, repeating the stock grid layout on subsequent pages until all records are rendered.
* If $M < N$ (fewer records than slots), the remaining label slots on the grid MUST remain empty and MUST NOT render any layer objects.

---

## 11. Validation Rules

Renderers MUST perform structural validation before rendering:

1. **Schema Check**: The document MUST pass structural validation against the canonical `schema.json`.
2. **Asset reference integrity**: Any `image` object MUST reference a valid `asset_id` present in the root `assets` list.
3. **Font family resolution**: Any `text` object's `font_family` SHOULD resolve to either a font in the root `fonts` family array or a known standard typography stack (Helvetica, Times, Courier).
4. **Active boundary overflow (Coordinate Check)**:
   * Renderers SHOULD trigger warnings if an object's computed bounding box extends outside the boundary of the active canvas (Label stock boundary or Page boundary).
   * Rect, Circle, Ellipse, Line, and Polyline objects MUST NOT contain infinite or NaN coordinates.
5. **Color validation**: Color properties MUST use a supported format from Section 7.3. The value `"none"` is valid only for fill and stroke properties.
6. **Unique identifiers**: `id` values MUST be unique within their scope (layer objects within a layer; layer `id` values within the document).

---

## 12. Examples

Validated example documents are maintained in [examples/](examples/):

| Example | File | Demonstrates |
| :--- | :--- | :--- |
| Simple Label | [simple_label.json](examples/simple_label.json) | Page-absolute mode, text, shapes, output options |
| Sheet Grid Labels | [sheet_labels.json](examples/sheet_labels.json) | Stock-grid mode, variable data binding |
| Barcode / QR Label | [barcode_label.json](examples/barcode_label.json) | Assets, fonts, barcodes, QR codes, layers |

All examples MUST validate against [schema.json](schema.json). CI runs schema validation via [scripts/validate_schemas.py](../../scripts/validate_schemas.py).
