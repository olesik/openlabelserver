# Changelog

All notable changes to OpenLabelServer are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
once tagged releases begin.

## [Unreleased]

### Added

- Executable conformance suite (`tests/conformance/`) with fixture-driven checks for the common rules and the RenderSpec, StockSpec and CalibrationSpec requirements, run by `scripts/test.sh` and the Specification Tests workflow
- Conformance suite `--json` report output in the ConformanceSpec v1.0 report format, validated against report rules `CR-1`–`CR-7` before it is printed
- CI publishes that report as the `conformance-report` artifact of the Specification Tests workflow, through `CONFORMANCE_REPORT`, and renders its per-profile statuses into the run's job summary
- ConformanceSpec v1.0 specification: conformance profiles, stable requirement identifiers for RenderSpec, StockSpec, CalibrationSpec, the REST API and renderer output, verification procedures, determinism requirements, physical print limits, an optional performance profile, and a conformance report and claim format
- RFC-0001 mandated conformance cases defined as normative checks: stateless validation returning `409` and never `404`, asset replay returning the original `201`, and job replay returning the original `202`
- REST API v1.0 specification completed: resource model, authentication schemes and roles, RFC 9457 error model, URI/header versioning, idempotency, and a validated OpenAPI 3.1 contract with request/response examples
- RFC-0001 recording the normative API corrections for stateless template validation (`409` instead of `404`) and idempotent replay (original `201`/`202`)
- CalibrationSpec v1.0 specification completed: printer profiles, offset, scale, page-clockwise rotation, JSON Schema, and examples
- ADR-0003 documenting printer calibration as a separate transform from layout and stock
- StockSpec v1.0 specification completed: page, grid, margins, pitch, label geometry, YAML/JSON schema, examples, and RenderSpec mapping
- ADR-0002 documenting YAML StockSpec for physical label geometry
- RenderSpec v1.0 specification completed: metadata, color model, output options, validation rules, and validated examples
- ADR-0001 documenting RenderSpec as the canonical layout contract
- Repository structure finalized with subsystem README files (`backend/`, `frontend/`, `renderer/`, `printing/`, `tests/`, `examples/`, `specs/`, `rfcs/`, `plugins/`, `reference/`)
- GitHub configuration: CODEOWNERS, issue templates (bug, feature, specification change), pull request template
- RFC template (`rfcs/RFC-0000-template.md`)
- Repository foundation: README, PROJECT_CHARTER, MILESTONES, CHECKLIST, AGENTS guide
- Governance documents: CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, CHANGELOG, ROADMAP
- Apache License 2.0
- Initial published specifications (draft v1.0):
  - RenderSpec — declarative label layout and rendering contract
  - StockSpec — YAML label stock and grid definitions
  - CalibrationSpec — printer calibration profiles
  - REST API — OpenAPI contract for platform operations
- JSON Schemas and example documents for each specification
- Specification-first development model and subsystem ownership model

### Changed

- CHECKLIST.md and ROADMAP.md corrected to reflect completed platform work (Docker, Compose, development and production containers, GitHub Actions, linting, automated tests); the release pipeline remains open

### Deprecated

- Nothing yet.

### Removed

- Nothing yet.

### Fixed

- OpenAPI validation now resolves the external RenderSpec, StockSpec, and CalibrationSpec schema references, so the published contract is validated in CI instead of failing on version detection
- Corrected the OpenAPI server description, the shared `Conflict` response description, and the `instance`/`output_url` URI formats to permit the relative URIs used by the published examples

### Security

- Nothing yet.

---

## Release History

No tagged releases yet. The project is in the architecture and specification phase.

Planned first implementation milestones are tracked in [ROADMAP.md](ROADMAP.md).
