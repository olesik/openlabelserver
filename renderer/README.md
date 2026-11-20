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

Object renderers and the PDF/PostScript backends remain open per
[MILESTONES.md](../MILESTONES.md).

## Ownership

Owned by the **Renderer** subsystem. See [AGENTS.md](../AGENTS.md).
