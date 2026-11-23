# RFC-0005: Typography and Placement for the Barcode Human-Readable Caption

- **Status:** Draft
- **Author(s):** OpenLabelServer maintainers
- **Created:** 2026-11-23
- **Updated:** 2026-11-23
- **Specification:** OpenLabelServer RenderSpec v1.0 and ConformanceSpec v1.0

## Summary

RenderSpec Section 8.2.10 defines `barcode.draw_text` but not what it prints.
This RFC defines the caption: three OPTIONAL properties for its family, size and
gap, the band it occupies below the bars, one centred line and its baseline, and
the string each symbology prints. An implementation can then draw the caption
without choosing a typeface, a size, a position or a string of its own, and a new
ConformanceSpec `RT-118` can measure it.

## Motivation

Section 8.2.10 declares `draw_text` OPTIONAL with a default of `true` and says
only:

```text
* `draw_text` (OPTIONAL, boolean, default `true`): Controls human-readable text display.
```

The schema's description adds "print human-readable text underneath barcode", and
nothing else in either document constrains the caption. ConformanceSpec `RT-116`
requires that `draw_text` "defaults to `true` and renders human-readable text",
but its verification measures module extents only, so no requirement pins the
caption's face, size, position or string. Four things are therefore left to each
implementation, and every one is visible on the printed label:

1. **Face.** A registered family, a standard family, a system font? Two renderers
   can disagree while each passes `DT-101`, which only requires two renders of
   one document to be byte-identical.
2. **Size.** The `text` object defaults to 10 pt (3.5278 mm); nothing says whether
   a caption shares that default, or uses points at all.
3. **Position.** `height` is "Total height of barcode bars in mm", so the caption
   is not inside it, but nothing says where it goes instead.
4. **String.** The raw `content`, the normalized payload, or the payload with or
   without check digits and guards? An EAN-13 payload of twelve digits prints as
   thirteen, a Code 39 symbol carries `*` guards that are structure and not data,
   and a UPC-E payload of six digits carries an implied number system and check
   digit.

The reference implementation reports the document rather than inventing an
answer:

```text
draw_text is true, and RenderSpec does not define the caption's face, size or
position; set draw_text to false
```

`specs/renderspec/examples/barcode_label.json` sets `draw_text: true` on its
`sku_barcode` object, so the caption is one of the reasons the reference
implementation cannot render the specification's own example. It is not the only
one: the example's SVG logo (`RO-103`) and its remote Roboto source are reported
first, and this RFC closes none of that. With those two set aside, `draw_text` is
the remaining refusal — the gap this RFC closes.

This RFC keeps the caption simple — one centred line of the normalized payload
below the bars — so implementing it needs no font shaping, no wrapping and no
per-symbology layout engine.

## Detailed design

### 1. New Section 8.2.10 properties

Three OPTIONAL properties are added to the `barcode` object. They take effect only
when `draw_text` is `true`; a document that sets `draw_text: false` keeps its
current behaviour and its current output bytes.

| Property | Type | Presence | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `caption_font_family` | `string` | OPTIONAL | `"Helvetica"` | Family of a face declared in the Section 7.1 `fonts` registry, or one of the standard families Helvetica, Times or Courier. Resolved exactly as `text.font_family` is resolved (`RS-113`). |
| `caption_font_size` | `number` | OPTIONAL | `6.0` | Caption size in points, MUST be greater than `0.0`. Converted to millimetres at `1 pt = 1/72 in` (`RT-113`). |
| `caption_gap` | `number` | OPTIONAL | `0.5` | Distance in mm between the bottom of the bars and the top of the caption's em box, MUST be greater than or equal to `0.0`. |

The caption is always set at weight `normal` and style `normal`; Section 8.2.10
gains no weight or style property in this revision.

The defaults need no asset and no document decision. Helvetica is one of the three
standard families `RS-113` requires to work without a registry entry, so a caption
never fails for a missing face, and 6.0 pt is the smallest size the published
examples set text at (`qr_caption` in `barcode_label.json`). The 0.5 mm gap keeps
the caption clear of the bars. The published example registers Roboto for its text
but sets no caption family, so it takes the Helvetica default; changing the example
is out of scope here.

### 2. Caption geometry

All lengths are object-local millimetres, in the coordinate system the bars are
drawn in, so the Transform Model (Section 9) applies to the caption exactly as it
applies to the bars: a rotated barcode prints a rotated caption, and `scale_x` /
`scale_y` scale both.

Let:

- $W$ = `width`, $H$ = `height` (the declared pattern box, unchanged: the bars
  still span exactly $W \times H$, so `RT-116`'s measurements are unaffected);
- $em = \text{caption\_font\_size} \times 25.4 / 72$ in mm;
- $g$ = `caption_gap`.

Then the caption occupies one em box:

| Quantity | Value |
| :--- | :--- |
| Em-box top | $y + H + g$ |
| Em-box bottom | $y + H + g + em$ |
| Em-box height | $em$ |
| Baseline | $y + H + g + 0.80 \times em$ |
| Centre line | $x + W / 2$ |
| Align | centred on the centre line: the run's measured advance $A$ places its left edge at $x + (W - A)/2$ |

The `0.80` baseline fraction is the single-line convention the reference renderer
already uses for a `text` object whose `valign` is `top` (`ASCENT = 0.8`,
`DESCENT = 0.2` of the em box). Pinning it here means two implementations place
the same glyphs at the same height without agreeing on a font's declared ascender,
which registered fonts disagree about.

Further rules:

1. The caption is **one line**. It is never wrapped, truncated, shrunk or
   auto-fitted, and `caption_font_size` is used as given even when the run is
   wider than $W$.
2. A caption wider than the symbol overflows **symmetrically** about the centre
   line: it is not clipped to $W$. In stock-grid mode it is still clipped by the
   Section 5.2 label frame (`RT-104`), and it counts toward the object's bounding
   box for the `RS-118` boundary-overflow diagnostic, so a caption that leaves the
   label or page is reported rather than passing unnoticed.
3. The caption paints in the object's `color`, with the alpha product of layer,
   ancestor group and object opacity (`RT-108`). `color: "none"` paints no caption.
4. `background_color` covers the bars only. The caption is not given a background
   of its own, so a caption over printed artwork shows that artwork between its
   glyphs.
5. `draw_text: false` paints no caption.

Worked example — the `sku_barcode` object of the published
`specs/renderspec/examples/barcode_label.json`, with the defaults:

```text
x = 6.0, y = 34.0, width = 55.0, height = 28.0
caption_font_size = 6.0 pt  ->  em = 2.1167 mm
caption_gap = 0.5 mm

em-box top     = 34.0 + 28.0 + 0.5          = 62.5000 mm
baseline       = 62.5000 + 0.80 x 2.1167    = 64.1933 mm
em-box bottom  = 62.5000 + 2.1167           = 64.6167 mm
centre line    = 6.0 + 55.0 / 2             = 33.5000 mm
```

The caption bottom sits at 64.6167 mm: 10.3833 mm above the page's bottom edge,
and 6.3833 mm above the 71.0 mm line its 4 mm bottom margin marks. Margins do not
clip (`RT-114`), so the caption fits the page without relying on them.

### 3. Caption string per symbology

The caption is the **normalized payload** — the string the encoder printed, after
check digits were computed and after data binding — with symbol structure removed,
so no caption ever prints a guard character:

| Symbology | Caption | Example content → caption |
| :--- | :--- | :--- |
| `code128` | the encoded payload, unchanged | `ABC-123` → `ABC-123` |
| `code39` | the payload, without its `*` start and stop characters | `ABC-123` → `ABC-123` |
| `ean13` | all thirteen digits, including the check digit | `400638133393` → `4006381333931` |
| `ean8` | all eight digits, including the check digit | `9638507` → `96385074` |
| `upca` | all twelve digits, including the check digit | `03600029145` → `036000291452` |
| `upce` | number system, six payload digits and check digit | `123456` → `01234565` |
| `itf` | the digits | `12345678` → `12345678` |
| `codabar` | the data characters between the `A`–`D` guards | `A1234B` → `1234` |
| `pdf417` | undefined in this revision | — |

The ISO/IEC 15420 human-readable arrangement used on retail packaging — the
EAN-13 lead digit left of the bars, the right-hand digits grouped under the end
guard — is not adopted: it needs the symbol's left quiet zone, which RenderSpec
does not model. One centred run of the normalized payload is representable by
every renderer and is what `RT-118` measures.

`pdf417` is named only to close the table. Its caption stays undefined in this
revision, so a `pdf417` object with `draw_text: true` is still reported rather
than given an invented caption; the question below tracks it.

### 4. Conformance

A new requirement joins ConformanceSpec Section 7.2, next to `RT-116`:

| ID | Requirement | Verification |
| :--- | :--- | :--- |
| `RT-118` | With `draw_text` true, a `barcode` MUST paint exactly one single-line caption carrying the string of Section 8.2.10's caption table — em size `caption_font_size × 25.4/72` mm, em-box top at `y + height + caption_gap`, baseline `0.80` em below that top, centred on `x + width / 2`, never wrapped or shrunk. With `draw_text` false it MUST paint no caption. | Render a 40 × 12 mm `code128` at `(x, y)` with defaults; the plan carries one text run whose content equals the payload, whose em size is 2.1167 mm ± 0.02 mm, whose em-box top sits at `y + 12.5` mm ± 0.1 mm, and whose centre line is within 0.1 mm of `x + 20`. Repeat with an `ean8` given seven digits: the caption carries the computed check digit. Render with `draw_text: false`: no text run. |

`RT-116` keeps its meaning for the bars; its verification note gains a sentence
pointing the caption at `RT-118`, so a caption band is never mistaken for part of
the pattern box.

### 5. Reference implementation

- `renderer/objects.py`: the `Barcode` primitive gains `caption_font_family`,
  `caption_font_size` (converted from points to mm as `text` is) and `caption_gap`,
  read from the document with the defaults above.
- `renderer/output.py`: `_barcode_ops` appends one `Text` operation after the bars,
  built from the encoded payload and the caption face, placed by Section 2.
- The linear-symbology tests that assert `draw_text` is reported become caption
  tests; the `pdf417` test keeps asserting the report until that caption is
  defined. No golden artifact changes: no golden document contains a `barcode`.

## Specification impact

| Location | Change |
| :--- | :--- |
| [RenderSpec Section 8.2.10](../specs/renderspec/specification.md#8210-barcode) | Three new OPTIONAL properties, the caption geometry, the baseline fraction, the single-line and overflow rules, and the per-symbology caption table |
| [renderspec/schema.json](../specs/renderspec/schema.json) | `caption_font_family` (`type: string`), `caption_font_size` (`number`, `exclusiveMinimum: 0`, default 6.0) and `caption_gap` (`number`, `minimum: 0`, default 0.5) join the `barcode` branch's `properties`. The schema does not set `additionalProperties: false` on objects, and the reference parser accepts an unknown object property today, so the fields need to be declared for their types and defaults to be registered rather than merely tolerated |
| [ConformanceSpec Section 7.2](../specs/conformance/specification.md#72-transforms) | New `RT-118` row; `RT-116` verification note points the caption at `RT-118` |
| [renderer/objects.py](../renderer/objects.py), [renderer/output.py](../renderer/output.py) | Caption fields on the primitive and the caption `Text` operation |
| [tests/test_renderer_barcode.py](../tests/test_renderer_barcode.py), [tests/conformance/renderer_cases.py](../tests/conformance/renderer_cases.py) | Caption unit tests and the `RT-118` case |

No new object type, no new HTTP surface, no new conformance profile. The `barcode`
object keeps its required properties and its meaning for `width` and `height`.
`renderer/barcode.py` does not change: `Symbol.content` already carries check
digits, the UPC-E number system and uppercase Codabar guards, so the caption reads
it and drops Codabar's guards in the output step, not in the encoder.

## Backward compatibility

Additive for documents: the three properties are OPTIONAL with defaults, so every
valid RenderSpec document stays valid and renders the same bytes unless it sets
`draw_text: true`. RenderSpec v1.0 is still a draft, so this lands in the draft
rather than as a version increment; if v1.0 were frozen first, this would be a
minor revision (OPTIONAL properties, no removals, no changed defaults).

The visible change is limited to `draw_text: true` documents:

- The reference renderer rejected them; it will render them. Tests and documents
  that rely on the rejection migrate by setting `draw_text: false`.
- Layouts must reserve `caption_gap + em` below `height` — 2.6167 mm at the
  defaults — and `RS-118` reports a caption that leaves the label or page.
- The published `barcode_label.json` example stops being refused for its caption,
  but still cannot render until its SVG logo (`RO-103`) and remote Roboto source
  are addressed; that is separate work.
- No stored document, asset or `output` setting changes, and no golden artifact
  moves.

## Alternatives considered

- **Leave `draw_text` reported and require a separate `text` object.** Rejected:
  `RT-116` would then require text from a flag that produces none, and every
  document would repeat the same boilerplate text object with hand-computed
  coordinates — the hardcoded layout the project's rules exist to avoid.
- **Put the caption inside `height` and shrink the bars to make room.** Rejected:
  it silently changes the bar geometry and the scannable width of every
  `draw_text: true` document, and `RT-116` would have to change from "the pattern
  spans `height`" to "the pattern and caption span `height`".
- **A fixed base-14 caption with no properties.** Rejected: a document that
  registers a family for its text would have no way to set the caption in it, so
  labels would mix a registered face with a hardcoded one.

## Unresolved questions

- Are 6 pt and 0.5 mm the right defaults, or should the caption default larger?
- When `pdf417`'s caption is defined, does it print the payload or an indicator,
  and does that fit the band above? Until then `draw_text: true` on a `pdf417`
  object stays reported.
