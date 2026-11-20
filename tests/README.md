# Tests

Automated tests for the reference implementation and specification conformance.

## Test layers

| Layer | Purpose |
|-------|---------|
| Schema | Validate example documents against JSON Schema and OpenAPI |
| Conformance | Prove compliance with published specifications |
| Renderer | Golden PDF/PostScript, coordinate accuracy, font embedding |
| API | OpenAPI conformance, request/response contracts |
| Integration | End-to-end render and print flows |
| Regression | Snapshot and hash validation |
| Performance | Render, preview, memory, and concurrency benchmarks |

## Layout

Tests mirror subsystem boundaries as implementation lands:

```text
tests/
├── conformance/     Fixture-driven requirement checks (implemented)
├── schema/
├── renderer/
├── api/
├── integration/
├── regression/
└── performance/
```

## Conformance suite

[tests/conformance/](conformance/) runs the requirement IDs defined in
[ConformanceSpec v1.0](../specs/conformance/specification.md):

```bash
python3 tests/conformance/runner.py
```

It currently covers the common rules and the RenderSpec, StockSpec and
CalibrationSpec document requirements; renderer, API and physical checks follow
with their profiles. See [tests/conformance/README.md](conformance/README.md).

## Status

`scripts/test.sh` runs schema validation, OpenAPI validation, example/snippet
validation, the RenderSpec parser, coordinate, layout, clipping, data-binding,
composition and object-renderer tests, and the conformance cases; the
**Specification Tests** workflow runs it on every push and pull request.
Remaining suites are added alongside each subsystem implementation.

## Ownership

Owned by the **QA** subsystem. See [AGENTS.md](../AGENTS.md).
