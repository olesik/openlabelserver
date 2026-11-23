# Renderer

RenderSpec parsing and deterministic vector output generation.

## Responsibilities

- Parse and validate RenderSpec documents
- Layout engine and coordinate system
- Font handling and embedding
- PDF and PostScript output
- Support for text, shapes, images, SVG, barcodes, and QR codes

The renderer consumes only RenderSpec. It must not hardcode label layouts or bypass the specification.

## Status

Wave 3 (R1) is in progress. Implemented:

- `renderspec.py` — schema-driven RenderSpec parser: strict by default, an
  OPTIONAL forward-compatibility mode, `CN-101` finite-number rejection and
  dotted-path diagnostics (`CN-106`).
- `coordinates.py` — Section 3 units and the Section 9 transform composition:
  millimetres, top-left origin, Y increasing downwards, clockwise rotation and
  points converted to millimetres.
- `layout.py` — stock-grid frame placement (StockSpec Section 6.2 origins in
  Section 5.4 row-major order), the bodies a document renders (one page-sized
  body at the origin for page-absolute mode, one per frame for stock-grid mode:
  `RT-101`, `RT-102`), the active boundary of Section 3/5.2 (page or individual
  label), and `RS-118` boundary-overflow warnings, which are reported without
  rejecting the document.
- `clip.py` — the label clip of StockSpec Section 5.3 for `rectangle`,
  `rounded-rectangle`, `round` and `oval` labels (`SS-112`) and the RenderSpec
  Section 5.2 per-frame rectangle that stops content bleeding between labels
  (`RT-104`).
- `binding.py` — Section 10 data binding: `{{variable}}` substitution in
  `text.content`, `barcode.content` and `qrcode.content` only (IN-7), an
  unresolved name resolving to the empty string, numbers and booleans serialized
  to their JSON spelling (`RB-101`–`RB-104`), and the Section 10.2 record-to-frame
  map with page overflow, empty trailing slots and a single blank sheet when the
  document carries no records (`RT-105`, `RT-106`).
- `composition.py` — Section 6 layer order and visibility, the Section 8.1 and
  8.2.12 visibility/opacity inheritance that makes the effective alpha the
  product of the layer, ancestor group and object opacity, and the Section 9
  matrix per drawn object (`RT-107`–`RT-112`).
- `objects.py` — the Section 8.2 per-object renderers: one backend-neutral
  primitive per object type with its Section 8.2 defaults applied, `font_size`
  converted from points to its millimetres em size (`RT-113`), the declared
  image, barcode and QR code extents (`RT-116`), and `"none"` colours resolved
  to absent paint.


- `geometry.py` — Section 8.2 shape geometry as subpaths of line and cubic
  segments in millimetres, including the rounded-rectangle corners, the
  quarter-circle constant, and the SVG `d` commands of `path` (`M`, `L`, `H`,
  `V`, `C`, `S`, `Q`, `T`, `Z`, absolute and relative); an elliptical arc is
  reported rather than approximated.
- `plan.py` and `output.py` — the page plan and `output.artifact`: the document
  is validated, expanded into pages (`RT-105`, `RT-106`), bound per label body,
  composed and resolved into `Fill`/`Stroke`/`Text`/`Image` operations in page
  millimetres, with the Section 4.2 colour-space conversions documented in the
  module and a single-line text convention for the em box.
- `assets.py` — the Section 7.2 asset registry: a picture loaded from a base64
  data-URI or a local path (a remote URL is reported, for the same reason a
  remote font is), with only its header read — dimensions, sample depth and
  colour layout — so its compressed data reaches the writers unchanged, and
  `samples` unpacks a PNG only where a backend has no filter for it. Neither
  format is re-encoded or resampled: a PNG rides the PDF predictor image, a JPEG
  is a `DCTDecode` stream in both formats, and PostScript paints a PNG's rows
  with their scanline filters undone. SVG artwork, a transparency channel, an
  interlaced PNG and a 16-bit PNG rendered to PostScript (a Level 2 image
  dictionary carries at most 12 bits per component) are reported rather than
  approximated.
- `fonts.py` — the Section 7.1 font registry: a program loaded from a base64
  data-URI or a local path (a remote URL is reported, because fetching it would
  make the artifact depend on the network), TrueType `glyf` tables read without
  external dependencies, and a deterministic glyph subset that keeps `.notdef`
  and composite components (`RO-104`). CFF/OTF outlines and collections are
  reported rather than converted.
- `barcode.py` — Code 128 subset B (start, data, modulo-103 check character,
  stop), Code 39 between its `*` start and stop characters over the 43-character
  alphabet, EAN-13, EAN-8, UPC-A and UPC-E (a payload with its check digit
  computed, or the full one verified; UPC-E also derives the UPC-A expansion and
  the parity pattern its check digit selects), ITF with its digits interleaved
  two at a time, and Codabar between the `A`-`D` start and stop characters its
  content names, all as module sequences. `code39`, `itf` and `codabar` print
  wide elements three modules wide, and content a symbology cannot carry (a
  lowercase Code 39 letter, an odd ITF count, a Codabar payload without guards, a
  UPC-E number system other than 0) is reported. PDF417 is not a module sequence
  of this module; `pdf417.py` draws it. The `draw_text` caption is drawn by
  `renderer/output.py` from the normalized payload, so the encoder stays free of
  the caption's typography.
- `pdf417.py` and `pdf417_tables.py` — PDF417 (ISO/IEC 15438) as rows of module
  runs: UTF-8 byte compaction only (the 924 latch when the byte count is a
  multiple of six, 901 otherwise, six bytes to five codewords by base 900, and
  trailing bytes one codeword each), error correction level 2 (eight codewords)
  over GF(929) from the generator polynomial computed instead of tabulated, the
  row indicator codewords that carry the row, the row and column counts and the
  level, and the standard's 3 x 929 seventeen-module pattern table. The column
  count is not a RenderSpec property, so it is the count in 1-30 whose rows at
  the standard's three-module height shape the symbol closest to the declared
  box. Empty content and content beyond the 928 codewords a symbol holds are
  reported, as is the `draw_text` caption.
- `qrcode.py` — QR Code Model 2 in byte mode, versions 1-40 at every
  `error_correction` level: `content` is encoded as UTF-8, the smallest version
  whose capacity holds it is chosen, the payload is split into the blocks of
  ISO/IEC 18004 Table 9 with their Reed-Solomon codewords and interleaved, and
  the mask with the lowest penalty score is applied, so one document always
  produces one matrix. Micro QR, structured-append and ECI symbols and content
  longer than a version 40-L symbol are reported rather than approximated.
- `pdf.py` and `postscript.py` — deterministic writers for that plan: a
  `MediaBox` of the declared page (`RO-109`), vector operators for shapes and
  text, the picture's own stream — or a PNG's unfiltered rows — for an `image`
  (`RO-102`),
  no creation timestamp or time-derived identifier (`RO-110`, IN-3, `DT-105`),
  and the same bytes for the same document (`RS-119`, `DT-101`). A registered
  family is embedded, never substituted: the PDF carries the subset as an
  `Identity-H` Type0 font with `/ToUnicode`, and PostScript carries the whole
  program as a Type 42 font (`RO-104`). That Type 42 dictionary follows
  TN #5012 — identity `FontMatrix`, `loca` indices in `CharStrings` with the
  required `/.notdef`, `sfnts` strings with the pad byte — and the base-14
  copies name WinAnsi's glyphs in their own `/Encoding` array, because
  PostScript has no `WinAnsiEncoding` resource. The published golden PDF and
  PostScript artifacts pin those bytes, including the embedded subset, the `/W`
  widths, the `/ToUnicode` CMap and the Type 42 prolog of a registered face
  (`RO-111`, see [tests/regression/](../tests/regression/)).

The conformance suite reads a rendered QR symbol back with
[tests/conformance/qr_reader.py](../tests/conformance/qr_reader.py) (`RO-108`).

Still open: SVG artwork (`RO-103`), the `pdf417` caption (RenderSpec leaves it
undefined), decoding a rendered barcode for `RO-107`, general text alignment and
wrapping, PostScript transparency, and CFF/OTF font embedding. See
[MILESTONES.md](../MILESTONES.md).

## Ownership

Owned by the **Renderer** subsystem. See [AGENTS.md](../AGENTS.md).
