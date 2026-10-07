# OpenLabelServer Roadmap

This document tracks planned work and current status. It complements [MILESTONES.md](MILESTONES.md), which defines development waves and agent ownership.

> **Rule #1:** If implementation conflicts with a published specification, **the specification wins.**

---

## Current Status

**Phase:** Wave 0 (Foundation) and Wave 1 (Specifications)

OpenLabelServer is in early development. The primary focus is stabilizing public specifications before reference implementation work begins at scale.

| Area | Status |
|------|--------|
| Governance & repository | Complete |
| RenderSpec v1.0 | Draft published |
| StockSpec v1.0 | Draft published |
| CalibrationSpec v1.0 | Draft published |
| REST API v1.0 | Draft published |
| Conformance specification | Not started |
| Reference implementation | Not started |
| Docker / CI | Not started |

See [CHECKLIST.md](CHECKLIST.md) for the full completion criteria.

---

## Guiding Priorities

1. **Stabilize specifications** — Schemas, examples, and observable behavior before large implementation efforts
2. **Conformance** — Define how implementations prove compliance
3. **Platform** — Reproducible development and CI environments
4. **Renderer** — Deterministic PDF and PostScript output from RenderSpec
5. **Backend & printing** — API service, job orchestration, CUPS integration
6. **Frontend** — Editor, preview, and administration UI
7. **Quality & release** — Regression suite, performance benchmarks, v1.0

---

## Version Milestones

### v0.1 — Foundation

**Goal:** Repository ready for collaborative development.

- [x] Project charter and architecture documentation
- [x] AI agent and contributor guidance (AGENTS.md)
- [x] Development milestones and checklist
- [x] Governance documents complete (CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, CHANGELOG, ROADMAP)
- [x] Repository structure (`backend/`, `frontend/`, `renderer/`, etc.)
- [x] GitHub configuration (issue templates, PR template, CODEOWNERS)
- [ ] Docker Compose skeleton
- [ ] FastAPI and Vue application skeletons
- [ ] CI pipeline (lint, schema validation)

### v0.2 — Render Pipeline

**Goal:** Validated RenderSpec in, vector PDF out.

- [ ] RenderSpec JSON Schema validation in CI
- [ ] RenderSpec parser and layout engine
- [ ] PDF renderer (core objects: text, shapes, images)
- [ ] SVG artwork support
- [ ] StockSpec YAML loading and grid layout
- [ ] Golden PDF regression tests

### v0.3 — Rich Content & Data

**Goal:** Production-like label content and variable data.

- [ ] Barcode generation
- [ ] QR code generation
- [ ] Variable data binding and iteration
- [ ] Font embedding and typography conformance
- [ ] Snapshot-based regression testing
- [ ] PostScript output backend (initial)

### v0.4 — Printing

**Goal:** Print from the platform through standards-based paths.

- [ ] REST API reference implementation (render jobs)
- [ ] CUPS integration
- [ ] IPP printer discovery
- [ ] Calibration profile application (CalibrationSpec)
- [ ] Print queue and job history
- [ ] Physical print conformance tests (registration, scaling)

### v0.5 — Web Interface

**Goal:** Operate the platform through a browser.

- [ ] Vue 3 application shell
- [ ] Label editor (RenderSpec authoring)
- [ ] Live PDF preview
- [ ] Stock and asset management
- [ ] Printer and calibration administration
- [ ] Job management UI

### v1.0 — Stable Platform

**Goal:** Production-ready reference implementation and stable public contracts.

- [ ] All specifications versioned with published schemas and examples
- [ ] Conformance specification and compliance test suite
- [ ] Deterministic rendering verified across environments
- [ ] Stable REST API with documented versioning and migration policy
- [ ] Complete user and developer documentation
- [ ] Performance targets met (see CHECKLIST.md)
- [ ] Third-party implementations feasible using only published specs

---

## Development Waves

Wave dependencies from [MILESTONES.md](MILESTONES.md):

```text
Wave 0 — Foundation
    ↓
Wave 1 — Specifications (RenderSpec, StockSpec, CalibrationSpec, API, Conformance)
    ↓
Wave 2 — Platform (Docker, CI/CD)
    ↓
Wave 3 — Renderer
    ↓
Wave 4 — Backend
    ↓
Wave 5 — Printing
    ↓
Wave 6 — Frontend
    ↓
Wave 7 — Quality Assurance
    ↓
Wave 8 — Documentation
    ↓
Release
```

No large-scale implementation should bypass RenderSpec or violate the architectural principles in [PROJECT_CHARTER.md](PROJECT_CHARTER.md).

---

## Specification Maturity

Specifications evolve independently. Target maturity for v1.0:

| Specification | Location | v1.0 Target |
|---------------|----------|-------------|
| RenderSpec | `specs/renderspec/` | Stable schema, full object model, validation rules, examples |
| StockSpec | `specs/stockspec/` | Stable YAML schema, grid model, example stocks |
| CalibrationSpec | `specs/calibrationspec/` | Stable profile schema, transform rules, examples |
| REST API | `specs/api/` | Stable OpenAPI, auth, errors, job lifecycle |
| Conformance | `specs/conformance/` (planned) | Observable behavior and compliance tests |

Specification changes follow the RFC process described in [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Non-Goals

This roadmap does not include:

- Vendor SDK integrations
- Windows-only printing paths
- Proprietary label template formats
- Desktop publishing or general graphics editing
- Non-deterministic rendering shortcuts

See [PROJECT_CHARTER.md](PROJECT_CHARTER.md) for the full non-goals list.

---

## How This Document Changes

- **ROADMAP.md** — High-level direction and milestone status (this file)
- **MILESTONES.md** — Wave definitions and subsystem ownership
- **CHECKLIST.md** — Granular completion tracking
- **CHANGELOG.md** — What shipped in each release

Update the roadmap when milestones shift. Record delivered work in the changelog at release time.

---

## Contributing to the Roadmap

Open an issue to propose roadmap changes. Significant architectural shifts require an RFC. Implementation PRs should reference the milestone or checklist items they address.
