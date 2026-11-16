# ADR-0003: Printer Calibration as a Separate Transform

- **Status:** Accepted
- **Date:** 2026-06-26
- **Deciders:** Project Lead

## Context

The same label design and stock must print on different devices. Mechanical error (shift, stretch, skew) is a property of a printer and media combination, not of the layout.

## Decision

Define **CalibrationSpec** as a versioned YAML document (JSON accepted) applied after RenderSpec layout and StockSpec placement.

1. **Separate from layout and stock** — RenderSpec draws content. StockSpec places label cells. CalibrationSpec corrects the printer.
2. **Affine correction only** — Offset in millimeters, positive scale factors, and clockwise rotation in the shared top-left, Y-down coordinate system.
3. **Profiles, not drivers** — A profile names a logical printer and may target a StockSpec `metadata.id` or a page format. It does not encode density, speed, or vendor commands.
4. **Deterministic selection** — Stock-specific profile, then page-format profile, then printer-only profile (one whose `target` carries no selection-bearing field, including a profile that carries only informational fields such as `media_type`), otherwise identity. Equal-level matches are ordered by the most recent `updated_at`; ties that cannot be ordered are errors, not silent picks.

## Consequences

### Positive

- Designs and stocks stay reusable across printers.
- Calibration can change without editing a RenderSpec.
- The transform order is specified, so two engines can produce the same coordinates.

### Negative

- v1.0 is a single affine transform per page or per label. It does not model per-cell variation across a sheet.
- JSON Schema cannot express recommended operating ranges; those remain warnings in the specification.

## References

- [CalibrationSpec v1.0 specification](../../specs/calibrationspec/specification.md)
- [CalibrationSpec JSON Schema](../../specs/calibrationspec/schema.json)
- [StockSpec v1.0 specification](../../specs/stockspec/specification.md)
- [ADR-0004: Informational Target Fields Do Not Decide Profile Selection](ADR-0004-informational-target-selection.md)
