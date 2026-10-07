# Tests

Automated tests for the reference implementation and specification conformance.

## Test layers

| Layer | Purpose |
|-------|---------|
| Schema | Validate example documents against JSON Schema and OpenAPI |
| Renderer | Golden PDF/PostScript, coordinate accuracy, font embedding |
| API | OpenAPI conformance, request/response contracts |
| Integration | End-to-end render and print flows |
| Conformance | Prove compliance with published specifications |
| Regression | Snapshot and hash validation |
| Performance | Render, preview, memory, and concurrency benchmarks |

## Layout

Tests will mirror subsystem boundaries as implementation lands:

```text
tests/
├── schema/
├── renderer/
├── api/
├── integration/
├── conformance/
├── regression/
└── performance/
```

## Status

Test infrastructure is defined in [scripts/](../scripts/) and CI workflows. Test suites will be added alongside each subsystem implementation.

## Ownership

Owned by the **QA** subsystem. See [AGENTS.md](../AGENTS.md).
