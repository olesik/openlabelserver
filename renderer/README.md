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

The layout engine, object renderers and the PDF/PostScript backends remain open
per [MILESTONES.md](../MILESTONES.md).

## Ownership

Owned by the **Renderer** subsystem. See [AGENTS.md](../AGENTS.md).
