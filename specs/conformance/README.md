# Conformance

Defines how implementations prove compliance with OpenLabelServer specifications.

## Purpose

A conforming implementation must:

- Accept documents that validate against published schemas
- Produce observable behavior defined by the specifications
- Pass the conformance test suite

Third-party renderers, APIs, and print services should be verifiable using only the published specifications and conformance documents.

## Planned coverage

| Area | Specification | Status |
|------|---------------|--------|
| RenderSpec | [renderspec/](../renderspec/) | Planned |
| StockSpec | [stockspec/](../stockspec/) | Planned |
| CalibrationSpec | [calibrationspec/](../calibrationspec/) | Planned |
| REST API | [api/](../api/) | Planned |
| Renderer output | Golden PDF/PostScript | Planned |

## Status

The conformance specification is not yet published. See [CHECKLIST.md](../../CHECKLIST.md).

## Ownership

Owned by the **QA** and **Governance** subsystems. See [AGENTS.md](../../AGENTS.md).
