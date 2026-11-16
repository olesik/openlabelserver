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

- [ ] FastAPI
- [ ] SQLAlchemy
- [ ] SQLite
- [ ] Asset Storage
- [ ] Job Queue
- [ ] Configuration
- [ ] Authentication
- [ ] Logging
- [ ] Metrics

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
- [ ] API example validation — validate every published API example against the
      OpenAPI schemas, and check that JSON blocks embedded in the specifications
      match their example files, so a published fixture and the contract cannot
      drift apart

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
