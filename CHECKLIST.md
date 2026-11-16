# OpenLabelServer Project Checklist

> **Project Philosophy**
>
> OpenLabelServer is an open, specification-first label rendering platform.
>
> The specifications are the product.
> The reference implementation exists to prove the specifications.
>
> If implementation and specification disagree, **the specification always wins**.

---

# Core Principles

These principles may only change through the RFC process.

- [ ] Specification First
- [ ] API First
- [ ] Renderer Agnostic
- [ ] Deterministic Rendering
- [ ] Reproducible Output
- [ ] Vector First
- [ ] Platform Independent
- [ ] Container Native
- [ ] Plugin Architecture
- [ ] Version Everything
- [ ] Test Before Optimize

---

# Repository

- [x] Repository structure finalized
- [x] README complete
- [x] CONTRIBUTING.md
- [x] CODE_OF_CONDUCT.md
- [x] SECURITY.md
- [x] CHANGELOG.md
- [x] ROADMAP.md
- [x] LICENSE
- [x] CODEOWNERS
- [x] GitHub Issue Templates
- [x] Pull Request Template

---

# Specifications

## RenderSpec

- [x] Object Model
- [x] Coordinate System
- [x] Layer Model
- [x] Asset Model
- [x] Font Model
- [x] Color Model
- [x] Output Options
- [x] Metadata
- [x] JSON Schema
- [x] Validation Rules
- [x] Example Documents

## StockSpec

- [x] YAML Schema
- [x] Page Definition
- [x] Grid Definition
- [x] Margins
- [x] Pitch
- [x] Label Geometry
- [x] Example Stocks
- [x] JSON Schema

## CalibrationSpec

- [x] Calibration Schema
- [x] Printer Profiles
- [x] Offset
- [x] Scaling
- [x] Rotation
- [x] JSON Schema

## API

- [x] REST Resources
- [x] OpenAPI
- [x] Error Model
- [x] Authentication
- [x] Versioning

---

# Infrastructure

- [x] Docker
- [x] Docker Compose
- [x] Development Container
- [x] Production Container
- [x] GitHub Actions
- [x] Linting
- [x] Automated Tests
- [ ] Release Pipeline

---

# Backend

Scaffolding only: `backend/pyproject.toml` is empty and `backend/README.md`
records the intent. Implementation begins in Wave 4 per
[MILESTONES.md](MILESTONES.md) and is defined by the
[REST API specification](specs/api/specification.md). Nothing below is
implemented, so no item is checked.

## Service (B1 — API)

- [ ] FastAPI application and `/v1` routing for the endpoints in API Section 8
- [ ] Request and response validation against the published OpenAPI contract
- [ ] RFC 9457 `application/problem+json` error model with the standard types (Section 5.2)
- [ ] Stable business-rule codes (Section 5.4), including `ambiguous-calibration-profile` with its RFC-0004 `context`
- [ ] Authentication: Bearer token, `X-API-Key`, and viewer/operator/admin roles (Section 6)
- [ ] Pagination envelope on every collection (Section 8)

## Persistence (B2 — Storage)

- [ ] SQLAlchemy models for templates, stocks, calibrations, assets and jobs
- [ ] SQLite database
- [ ] Configuration loading for the database path, storage root and server settings

## Assets (B3 — Assets)

- [ ] Upload, retrieval and metadata for binary assets
- [ ] All three asset reference forms: API asset URI, external HTTPS URL, base64 data URI (Section 9.5)

## Jobs (B4 — Jobs)

- [ ] Render job submission with `202 Accepted` and the documented status transitions (Section 8.7)
- [ ] Print job submission, applying calibration after layout and before print submission (Section 9.4)
- [ ] Calibration selection through the engine, including the `AJ-108` context and the `calibration_id` override
- [ ] Idempotent replay for asset and job submissions (Section 10, RFC-0001)
- [ ] Queue execution with job failure details exposed on the job resource (Section 5.5)

## Operations

- [ ] Structured logging
- [ ] Metrics
- [ ] `GET /v1/health` returning `200` with `status: "ok"` (`AP-103`)

## Verification

- [ ] `CP-API` conformance: protocol, resources, cross-specification behaviour and the RFC-0001 replay cases (`AP-*`, `AJ-*`, `AQ-*`)
- [ ] Ambiguous-profile rejection asserted against the published `context`, once a service can run it

---

# Renderer

## Core

- [ ] RenderSpec Parser
- [ ] Layout Engine
- [ ] Coordinate Engine
- [ ] Font Engine

## Objects

- [ ] Text
- [ ] Shapes
- [ ] Images
- [ ] SVG
- [ ] Barcode
- [ ] QR Code

## Outputs

- [ ] PDF
- [ ] PostScript

---

# Printing

- [ ] Printer Discovery
- [ ] IPP
- [ ] CUPS
- [ ] Queue Management
- [ ] Job History
- [ ] Calibration
- [ ] Raw PostScript
- [ ] Printer Capability Detection

---

# Frontend

- [ ] Vue Application
- [ ] Label Editor
- [ ] Live Preview
- [ ] Asset Manager
- [ ] Stock Manager
- [ ] Printer Manager
- [ ] Calibration Wizard
- [ ] Print Management

---

# Plugin System

- [ ] Plugin Interface
- [ ] Plugin Discovery
- [ ] Capability Registration
- [ ] Version Compatibility
- [ ] Lifecycle Management

---

# Validation

## Schema

- [x] RenderSpec Validation
- [x] StockSpec Validation
- [x] Calibration Validation
- [x] API example validation — `scripts/validate_api_examples.py` validates every
      published API example against its OpenAPI component schema, checks embedded
      JSON and YAML blocks against their example files (full copies or snippets),
      and validates every other embedded block against its named schema (or exempts
      it with a reason)

Schema validation runs in `scripts/test.sh` on every push and pull request, and
`tests/conformance/` adds the semantic rules a schema cannot express.

## Rendering

- [ ] Coordinate Accuracy
- [ ] Embedded Fonts
- [ ] SVG Fidelity
- [ ] Barcode Validation
- [ ] QR Validation

## Physical Printing

- [ ] Registration
- [ ] Scaling
- [ ] Rotation
- [ ] Feed Consistency
- [ ] Calibration Accuracy

## Regression

- [ ] Golden PDFs
- [ ] Golden PostScript
- [ ] Snapshot Tests
- [ ] PDF Hash Validation

## Performance

- [ ] Render < 500 ms
- [ ] Preview < 250 ms
- [ ] Memory < 512 MB
- [ ] 10+ Concurrent Users
- [ ] 100+ Concurrent Jobs

---

# Conformance

- [x] RenderSpec Conformance
- [x] StockSpec Conformance
- [x] Calibration Conformance
- [ ] API Conformance
- [ ] Renderer Conformance

Document-level conformance is executed by `tests/conformance/` against the
requirements of ConformanceSpec profiles `CP-RS`, `CP-ST` and `CP-CAL`. API
(`CP-API`) and renderer (`CP-RND`) conformance remain open: they need a running
service and a renderer to observe.

---

# Definition of Done

OpenLabelServer v1.0 is complete when:

- Every specification is versioned.
- Every specification has a published schema.
- Every specification includes examples.
- The reference implementation passes the complete conformance suite.
- Rendering is deterministic.
- Physical print accuracy meets specification.
- Every subsystem is independently testable.
- Third-party implementations can be written using only the published specifications.
- Continuous Integration validates schemas, regression tests, conformance tests and performance benchmarks.
