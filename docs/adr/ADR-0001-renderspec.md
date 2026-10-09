# ADR-0001: RenderSpec as the Canonical Layout Contract

- **Status:** Accepted
- **Date:** 2026-06-26
- **Deciders:** Project Lead

## Context

OpenLabelServer needs a vendor-independent, deterministic format for describing label layouts. Multiple subsystems (editors, APIs, renderers, print services) must share a single contract without embedding layout logic in application code.

## Decision

Adopt **RenderSpec** as the canonical, versioned JSON specification for label layout.

Key properties of the decision:

1. **JSON document model** — Machine-readable, schema-validated, suitable for API transport and storage.
2. **Millimeter coordinates** — All layout dimensions use millimeters; font sizes use points. Origin is top-left.
3. **Layer-based composition** — Ordered layers with z-index determined by array order.
4. **Inline stock grid** — Common sheet layouts embed a simplified `stock` object; richer geometry defers to StockSpec.
5. **Variable data** — Template interpolation via `{{variable}}` syntax against a root `data` array.
6. **Vector-first output** — Renderers produce PDF or PostScript; SVG assets remain vector unless rasterization is explicitly required.

## Consequences

### Positive

- Any compliant renderer can produce output from the same input.
- Front-end editors, APIs, and print pipelines share one contract.
- JSON Schema enables automated validation and conformance testing.

### Negative

- JSON is verbose compared to domain-specific binary formats.
- Inline stock is less expressive than StockSpec for complex label shapes.

## References

- [RenderSpec v1.0 specification](../../specs/renderspec/specification.md)
- [RenderSpec JSON Schema](../../specs/renderspec/schema.json)
- [StockSpec v1.0 specification](../../specs/stockspec/specification.md)
