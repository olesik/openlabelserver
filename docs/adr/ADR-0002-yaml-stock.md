# ADR-0002: YAML StockSpec for Physical Label Geometry

- **Status:** Accepted
- **Date:** 2026-06-26
- **Deciders:** Project Lead

## Context

Label stock geometry (page size, die-cut shape, grid, margins, pitch) must be reusable across designs and independent of RenderSpec artwork. Contributors need a format that is easy to author by hand and still machine-validatable.

## Decision

Define **StockSpec** as a versioned YAML document (JSON accepted) with a published JSON Schema.

1. **YAML as the preferred serialization** — Readable for catalogs of commercial stocks (Avery, thermal rolls, round stickers).
2. **JSON Schema Draft-07 as the machine schema** — YAML is parsed, then validated; no separate YAML Schema dialect.
3. **Millimeter coordinates, top-left origin** — Identical to RenderSpec so stocks can be mapped into inline `stock` fields.
4. **Mathematical validation beyond schema** — Pitch ≥ label size, grid enclosure, optional outer-margin consistency (±0.1 mm).
5. **Shape clipping on the die-cut** — Rectangle, rounded-rectangle, round, and oval; renderers clip artwork to the active boundary.

## Consequences

### Positive

- Stock catalogs are independent of designs and printer calibration.
- The same stock can back many RenderSpec documents.
- Schema validation in CI plus geometric rules catch physically impossible layouts.

### Negative

- JSON Schema cannot express all geometric constraints (for example, `width == height` for round labels); parsers must implement Section 6 of the specification.
- Inline RenderSpec `stock` is a subset; attaching both sources requires conflict detection.

## References

- [StockSpec v1.0 specification](../../specs/stockspec/specification.md)
- [StockSpec JSON Schema](../../specs/stockspec/schema.json)
- [RenderSpec v1.0 specification](../../specs/renderspec/specification.md)
