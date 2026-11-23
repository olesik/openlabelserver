# RFC-0006: SVG Artwork Profile for Vector Rendering

- **Status:** Accepted
- **Author(s):** OpenLabelServer maintainers
- **Created:** 2026-11-23
- **Updated:** 2026-11-23
- **Accepted:** 2026-11-23
- **Specification:** OpenLabelServer RenderSpec v1.0 and ConformanceSpec v1.0

## Summary

RenderSpec Section 7.2 declares `"svg"` as an asset type and requires renderers to
preserve SVG artwork as vector operations, but it defines no subset: it does not
say which elements, attributes, paints or transforms an `image` backed by an SVG
must cover, how the artwork's `viewBox` maps into the `image` object's declared
box, or what a renderer does with artwork it cannot express. This RFC adds
Section 7.2.1, a closed profile of SVG 1.1 that a vector renderer must draw, and
ConformanceSpec `RO-113`, which requires a construct outside that profile to be
reported rather than rasterized, approximated or dropped.

## Motivation

`RO-103` is the only published statement about SVG assets, and it cannot be
implemented as written without inventing behaviour:

* It does not define the supported vocabulary, so two renderers reading the same
  asset can legitimately draw different things.
* It does not define how user units reach millimetres, so an SVG with a
  `viewBox` has no specified size or origin inside its `image` box.
* It does not say what happens to artwork outside the profile. The reference
  renderer currently reports every SVG asset, which is honest (`RO-102` forbids
  rasterizing shapes) but leaves `RO-103` unimplemented and the renderer's SVG
  item open in [CHECKLIST.md](../CHECKLIST.md).

Without a profile, "SVG support" would be whatever library happened to be
linked in, and determinism (`RS-119`, `DT-101`) would depend on that library's
version. A drawing subset small enough to keep in the renderer, with a defined
mapping into the page, keeps the artifact a function of the document alone.

Accepted on 2026-11-23; the RenderSpec Section 7.2.1 text, `RO-113`, the
renderer profile and its tests landed in the same change.

## Detailed design

The proposal is a new RenderSpec Section 7.2.1, "SVG asset profile". It applies
to a Section 7.2 asset whose `type` is `"svg"` when a Section 8.2.9 `image`
draws it.

### 1. Document shape

1. The source MUST be a well-formed XML document whose root element is `svg`
   (in the SVG namespace or with no namespace).
2. A document type declaration (`<!DOCTYPE`) MUST be rejected: no entity
   expansion and no external reference is part of the profile.
3. The root's `width` and `height` attributes are not used for placement: the
   Section 8.2.9 `width` and `height` of the `image` object define the
   **viewport**, in millimetres.

### 2. Supported vocabulary

The profile draws these elements: `svg` (root), `g`, `rect`, `circle`,
`ellipse`, `line`, `polyline`, `polygon` and `path`.

`title`, `desc` and `metadata` are non-rendering and MUST be ignored.

Every other element is outside the profile and MUST be reported by name
(`RO-113`): `text`, `tspan`, `textPath`, `image`, `use`, `symbol`, `defs`'s
paint servers (`linearGradient`, `radialGradient`, `pattern`), `clipPath`,
`mask`, `filter`, `style` and `script` are all reported, not dropped.

Presentation properties are read from attributes, and from a `style` attribute
whose declarations name the same properties (a declaration for any other
property is ignored, as CSS forward-compatibility requires). Supported:

| Property | Default | Meaning |
| :--- | :--- | :--- |
| `fill` | `black` | Paint of the interior; `none` paints none. |
| `stroke` | `none` | Paint of the outline; `none` paints none. |
| `stroke-width` | `1` | Outline width in user units. |
| `stroke-dasharray` | none | Dash and gap lengths in user units. |
| `fill-opacity` | `1` | Alpha of the fill, inherited. |
| `stroke-opacity` | `1` | Alpha of the stroke, inherited. |
| `opacity` | `1` | Alpha multiplier of the element and its children. |
| `fill-rule` | `nonzero` | `nonzero` or `evenodd`. |

`fill` and `stroke` accept the Section 7.3 colour formats, the keyword `none`,
and the sixteen CSS basic colour keywords (`aqua`, `black`, `blue`, `fuchsia`,
`gray`, `green`, `lime`, `maroon`, `navy`, `olive`, `purple`, `red`, `silver`,
`teal`, `white`, `yellow`). A paint server reference (`url(...)`), `inherit`,
`currentColor` and any other value are reported.

`stroke-width` below `0` and opacity outside `[0, 1]` are reported; a
`stroke-width` of `0` paints no outline.

### 3. Units

Attribute lengths are SVG user units. A unitless number and the `px` suffix are
accepted and are equal; a percentage and every other unit (`mm`, `pt`, `em`,
...) are reported. The `viewBox` mapping below is what turns user units into
millimetres, so a document that omits the `viewBox` draws one user unit per
millimetre.

### 4. The viewBox mapping

1. With a `viewBox`, user space is the rectangle it declares. Its width and
   height MUST both be greater than `0`, and the four numbers MUST be present.
2. The root's `preserveAspectRatio` controls how that rectangle fills the
   viewport: the nine alignments (`xMin`, `xMid`, `xMax` crossed with `YMin`,
   `YMid`, `YMax`) each with `meet` (fit inside) or `slice` (fill and overflow);
   the default is `xMidYMid meet`; `none` stretches each axis independently.
   An unrecognised value is reported.
3. Section 8.2.9 `preserve_aspect_ratio: false` overrides the root's attribute
   and stretches the `viewBox` to the box, exactly as it stretches a raster
   picture. `preserve_aspect_ratio: true` leaves the root's attribute in
   charge, which is why an SVG without a `viewBox` still stretches to the box.
4. Without a `viewBox`, user units are millimetres and no scaling applies.

### 5. Geometry

* `rect`: `x`, `y` (default `0`), `width`, `height`, `rx` and `ry`; a missing
  radius takes the other one, as SVG defines.
* `circle`: `cx`, `cy` (default `0`) and `r`.
* `ellipse`: `cx`, `cy` (default `0`), `rx` and `ry`.
* `line`: `x1`, `y1`, `x2`, `y2`.
* `polyline` and `polygon`: `points`, an even list of user-unit coordinates.
* `path`: `d`, parsed exactly as RenderSpec Section 8.2.8 parses it. The
  elliptical arc commands are therefore reported, as they are for a `path`
  object.
* An element whose geometry is empty or degenerate paints nothing.

`transform` on a supported element or group is a list of `matrix(a b c d e f)`,
`translate(tx [ty])`, `scale(sx [sy])`, `rotate(a [cx cy])`, `skewX(a)` and
`skewY(a)`, composed in the order written, with SVG's units (degrees for the
rotations, user units for the translations).

### 6. Clipping

The artwork is clipped to the viewport — the `image` object's declared box — as
SVG's default `overflow: hidden` clips it. The active label boundary still
clips the whole object (`RT-104`).

### 7. Determinism and rejection

The profile contains no clock, randomness or environment dependence: one asset
and one box always produce one set of vector operations (`RS-119`, `DT-101`).
A construct outside the profile MUST be reported with the element or property
named, and no artifact MUST be produced for it (`RO-113`). Rasterizing the
artwork is never an option: `RO-102` and AGENTS.md rule 5 forbid it.

## Specification impact

* `specs/renderspec/specification.md`: new Section 7.2.1 with the rules above;
  Section 8.2.9 gains one sentence tying an SVG asset to that profile and to
  `preserve_aspect_ratio`.
* `specs/renderspec/schema.json`: no change. The profile constrains the asset's
  *content*, not the document, and `assets[].type` already accepts `"svg"`.
* `specs/conformance/specification.md`: new `RO-113`; `RO-103`'s verification
  gains the profile fixture and the raster-free assertion.
* `specs/renderspec/examples/`: no change. `barcode_label.json`'s inline SVG
  logo carries a `text` element, which the profile reports; the example is
  already unrenderable because of its remote Roboto source.
* Reference implementation: `renderer/svg.py` (new), `renderer/assets.py`,
  `renderer/output.py`, `renderer/plan.py`, `renderer/pdf.py`,
  `renderer/postscript.py`.

## Backward compatibility

The change is additive for documents: every document that renders today renders
the same bytes, because no existing golden artifact carries an SVG asset. An SVG
asset that is currently reported stays reported when it uses a construct outside
the profile, and now renders when it stays inside it. No RenderSpec property,
default or version changes.

## Alternatives considered

* **Full SVG 1.1 support**, including text, gradients, masks, filters, patterns,
  `use` and CSS selectors. Rejected: it is a document-rendering engine of its own,
  it would pull in a font stack and a raster compositor for filters, and the
  result would no longer be a deterministic function of the renderer's own code.
* **Delegate to a third-party SVG rasterizer or vectorizer.** Rejected:
  rasterizing violates `RO-102`/`RO-103` and AGENTS.md rule 5, a new dependency
  pins determinism to a library release, and the platform forbids vendor SDKs.
* **Serve SVG assets through the existing `path` object.** Rejected: `path`
  has no position, box, paint inheritance or viewBox, so every asset would need
  hand-transcription into the document, which is exactly what the asset registry
  exists to avoid.
* **Leave the asset reported and keep `RO-103` unimplemented.** Rejected: the
  requirement is published, and the renderer can meet it with a small,
  deterministic subset.

## Unresolved questions

1. SVG `text` and `tspan` are outside the profile. Rendering them needs font
   selection inside the asset, which Section 7.1's registry does not describe for
   artwork. A later RFC can add them as a separate profile version.
2. Gradients and patterns (`url(#...)`) are outside the profile for the same
   reason filters are: both need shading and clipping machinery the backends do
   not carry. A future profile version can define linear and radial gradients as
   PDF/PostScript shadings.
3. The profile has no version marker. RenderSpec `renderspec: "1.0"` is the only
   version, so a future profile widening would be a spec change under the normal
   RFC process rather than a per-asset negotiation.
