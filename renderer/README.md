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

Not yet implemented. Work begins in Wave 5 (Renderer) per [MILESTONES.md](../MILESTONES.md).

## Ownership

Owned by the **Renderer** subsystem. See [AGENTS.md](../AGENTS.md).
