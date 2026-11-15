# Conformance

Defines how implementations prove compliance with OpenLabelServer specifications.

The published document is [specification.md](specification.md) — **ConformanceSpec v1.0**.
The executable suite lives in [tests/conformance/](../../tests/conformance/) and runs from `scripts/test.sh`.

## Purpose

A conforming implementation must:

- Accept documents that validate against published schemas
- Produce observable behavior defined by the specifications
- Pass the conformance test suite

Third-party renderers, APIs, and print services should be verifiable using only the published specifications and conformance documents.

## Coverage

| Area | Specification | Requirements | Status |
|------|---------------|--------------|--------|
| RenderSpec | [renderspec/](../renderspec/) | `CN-*`, `RS-*`, `RT-*`, `RB-*` | Published; `RS-*` executed |
| StockSpec | [stockspec/](../stockspec/) | `SS-*` | Published; executed |
| CalibrationSpec | [calibrationspec/](../calibrationspec/) | `CS-*` | Published; `CS-101`–`CS-121` executed |
| REST API | [api/](../api/) | `AP-*`, `AR-*`, `AJ-*`, `AQ-*` | Published; suite pending |
| Renderer output | Golden PDF/PostScript | `RO-*`, `DT-*`, `PL-*` | Published; suite pending |
| Physical printing | Registration, scaling, rotation, feed | `PH-*` | Published; needs hardware |
| Performance (optional) | Render, preview, memory, concurrency | `PF-*` | Published; suite pending |

## Status

ConformanceSpec v1.0 defines the profiles, requirement identifiers, verification procedures, reporting format and claim format. The executable suite is started: it covers the common rules and the document requirements for RenderSpec, StockSpec and CalibrationSpec. Renderer, API and physical checks follow with their profiles. See [CHECKLIST.md](../../CHECKLIST.md).

## Ownership

Owned by the **QA** and **Governance** subsystems. See [AGENTS.md](../../AGENTS.md).
