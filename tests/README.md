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

## Regression artifacts

[tests/regression/](regression/) publishes the golden PDF and PostScript
artifacts for a representative document and for a document that sets text in a
registered face, with their exact byte count and SHA-256 digest (`RO-111`). The
conformance suite verifies the committed bytes against the manifest and
re-renders each document for a byte comparison. Republish with
`python3 tests/regression/publish.py` after an intentional change. See
[regression/README.md](regression/README.md).

## Status

`scripts/test.sh` runs schema validation, OpenAPI validation, example/snippet
validation, the RenderSpec parser, coordinate, layout, clipping, data-binding,
composition, object-renderer, geometry, font-loader and output-backend tests,
and the conformance cases; the
**Specification Tests** workflow runs it on every push and pull request.
Remaining suites are added alongside each subsystem implementation.

## Ownership

Owned by the **QA** subsystem. See [AGENTS.md](../AGENTS.md).
