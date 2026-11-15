# Conformance

Defines how implementations prove compliance with OpenLabelServer specifications.

The published document is [specification.md](specification.md) — **ConformanceSpec v1.0**.

## Purpose

A conforming implementation must:

- Accept documents that validate against published schemas
- Produce observable behavior defined by the specifications
- Pass the conformance test suite

Third-party renderers, APIs, and print services should be verifiable using only the published specifications and conformance documents.

## Coverage

| Area | Specification | Requirements | Status |
|------|---------------|--------------|--------|
| RenderSpec | [renderspec/](../renderspec/) | `CN-*`, `RS-*`, `RT-*`, `RB-*` | Published |
| StockSpec | [stockspec/](../stockspec/) | `SS-*` | Published |
| CalibrationSpec | [calibrationspec/](../calibrationspec/) | `CS-*` | Published |
| REST API | [api/](../api/) | `AP-*`, `AR-*`, `AJ-*`, `AQ-*` | Published |
| Renderer output | Golden PDF/PostScript | `RO-*`, `DT-*`, `PL-*` | Published |
| Physical printing | Registration, scaling, rotation, feed | `PH-*` | Published |
| Performance (optional) | Render, preview, memory, concurrency | `PF-*` | Published |

## Status

ConformanceSpec v1.0 is published as a draft v1.0 contract. It defines conformance profiles, requirement identifiers, verification procedures, the reporting format and the claim format; the executable test suite under `tests/conformance/` is not yet implemented. See [CHECKLIST.md](../../CHECKLIST.md).

## Ownership

Owned by the **QA** and **Governance** subsystems. See [AGENTS.md](../../AGENTS.md).
