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

Implementation began in Wave 4 per [MILESTONES.md](MILESTONES.md) and is defined
by the [REST API specification](specs/api/specification.md). `backend/main.py`
serves `GET /v1/health`, `GET /v1/info` and the stateless
`POST /v1/templates/{template_id}/validate`, stamps `X-API-Version` on every
response and answers every error as an RFC 9457 `application/problem+json`
document. There is still no persistence, authentication or job execution. An item
is checked once all of it is implemented, so only the finished ones are checked.

## Service (B1 — API)

- [ ] FastAPI application and `/v1` routing for the endpoints in API Section 8
- [ ] Request and response validation against the published OpenAPI contract
- [x] RFC 9457 `application/problem+json` error model with the standard types (Section 5.2)
- [x] Stateless `POST /v1/templates/{template_id}/validate` with the RFC-0001 `409` and the Section 5.3 `422` body (`AP-104`)
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
- [x] `GET /v1/health` returning `200` with `status: "ok"` (`AP-103`)

## Verification

- [ ] `CP-API` conformance: protocol, resources, cross-specification behaviour and the RFC-0001 replay cases (`AP-*`, `AJ-*`, `AQ-*`)
- [ ] Ambiguous-profile rejection asserted against the published `context`, once a service can run it

---

# Renderer

`renderer/` implements text, shapes, raster images, SVG artwork, barcodes and QR
codes in PDF and PostScript. Raster images are carried as the stream the
document supplied — PNG and JPEG in PDF, and in PostScript a JPEG whole and a
PNG as its unfiltered rows, since a Level 2 image dictionary has no deflate
filter. SVG assets are drawn as vector subpaths through the RenderSpec
Section 7.2.1 profile, and a construct outside that profile is reported rather
than rasterized or approximated.

## Core

- [x] RenderSpec Parser
- [x] Layout Engine
- [x] Coordinate Engine
- [x] Font Engine

## Objects

- [x] Text
- [x] Shapes
- [x] Images
- [x] PNG images in PostScript
- [x] SVG (RenderSpec Section 7.2.1 profile; constructs outside it are reported)
- [x] Barcode (Code 128, Code 39, EAN-13, EAN-8, UPC-A, UPC-E, ITF and Codabar)
- [x] PDF417 (the stacked 2D symbology)
- [x] The human-readable barcode caption (`draw_text`; RenderSpec Section 8.2.10 defines its face, size, band and string)
- [x] QR Code (Model 2, byte mode, versions 1-40)
- [x] Barcode decode verification (`RO-107`; the suite rasterizes every symbology and reads it back with `tests/conformance/barcode_reader.py`)
- [x] QR decode verification (`RO-108`; the suite rasterizes the symbol and reads it back with `tests/conformance/qr_reader.py`)

## Outputs

- [x] PDF
- [x] PostScript

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
- [x] Example and snippet validation — `scripts/validate_examples.py` validates
      every published API example against its OpenAPI component schema, checks
      embedded JSON and YAML blocks in the specifications, README, docs and RFCs
      against their example files (full copies or snippets), and validates every
      other embedded block against its named schema

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

- [x] Golden PDFs
- [x] Golden PostScript
- [ ] Snapshot Tests
- [x] PDF Hash Validation

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
(`CP-API`) conformance is observable in-process for the requirements the service
implements — `AP-102` to `AP-104` pass — and renderer (`CP-RND`) conformance
remains open; both profiles stay open until the rest of their requirements, and
the jobs and replay cases, can be observed.

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
