# OpenLabelServer Roadmap

This document tracks planned work and current status. It complements [MILESTONES.md](MILESTONES.md), which defines development waves and agent ownership.

> **Rule #1:** If implementation conflicts with a published specification, **the specification wins.**

---

## Current Status

**Phase:** Waves 0–2 complete — specifications, platform scaffolding and CI are in place. Wave 3 (Renderer) in progress.

OpenLabelServer is in early development. The public specifications are published and stable enough for conformance-driven implementation, and the renderer implements them for text, shapes, images, barcodes, QR codes and SVG artwork; the backend, printing and frontend have not started.

| Area | Status |
|------|--------|
| Governance & repository | Complete |
| RenderSpec v1.0 | Published (v1.0 draft) |
| StockSpec v1.0 | Published (v1.0 draft) |
| CalibrationSpec v1.0 | Published (v1.0 draft) |
| REST API v1.0 | Published (v1.0 draft) |
| Conformance specification | Published (v1.0 draft) |
| Conformance suite | Executable for `CP-RS`, `CP-ST` and `CP-CAL`; `CP-RND` and `CP-API` pending — see [Tech Debt and Follow-Up Work](#tech-debt-and-follow-up-work) |
| Reference implementation | Renderer implemented for text, shapes, images, barcodes, QR codes and SVG artwork (`renderer/`); backend, printing and frontend not started |
| Docker / CI | Platform scaffolding complete; release pipeline pending |

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
- [x] Docker Compose skeleton
- [ ] FastAPI and Vue application skeletons
- [x] CI pipeline (lint, schema validation)

### v0.2 — Render Pipeline

**Goal:** Validated RenderSpec in, vector PDF out.

- [x] RenderSpec JSON Schema validation in CI (all three schemas and the OpenAPI contract)
- [x] RenderSpec parser and layout engine
- [x] PDF renderer for text and shapes
- [x] Image objects in the PDF and PostScript output (PNG and JPEG in both formats)
- [x] SVG artwork support (the RenderSpec Section 7.2.1 vector profile)
- [x] StockSpec grid layout
- [ ] StockSpec YAML loading
- [x] Golden PDF regression tests

### v0.3 — Rich Content & Data

**Goal:** Production-like label content and variable data.

- [x] Barcode generation (Code 128, Code 39, EAN-13, EAN-8, UPC-A, UPC-E, ITF and Codabar)
- [x] PDF417 barcode generation
- [x] Barcode human-readable caption (`draw_text`)
- [x] QR code generation (Model 2, byte mode, versions 1-40)
- [x] Barcode decode verification (`RO-107`; the suite reads every rasterized symbology back)
- [x] QR code decode verification (`RO-108`; the suite reads a rasterized symbol back)
- [x] Variable data binding and iteration
- [x] Font embedding and typography conformance
- [ ] Snapshot-based regression testing
- [x] PostScript output backend (initial)

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
- [ ] Conformance specification and compliance test suite (document profiles
  `CP-RS`, `CP-ST`, `CP-CAL` covered; `CP-RND` and `CP-API` pending)
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
| Conformance | `specs/conformance/` | Requirement IDs, conformance profiles, verification procedures, claim format |

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

## Tech Debt and Follow-Up Work

Items below are not on the critical path of the normal use case — validating a
RenderSpec document and rendering it to a deterministic PDF or PostScript. They
are recorded here so they are not lost, and each names what would schedule it.

| Item | Why it is deferred | Trigger |
|------|--------------------|---------|
| `DT-102` — identical bytes on two operating systems or architectures | Needs a CI matrix (Windows, macOS, arm64) and a job that compares digests across them; CI renders on one `ubuntu-latest` runner today | Release, or the `CP-RND` claim |
| Harness patches private renderer attributes | `mutations.py` replaces `composition.object_matrix`, `composition._opacity`, `composition._hidden`, `pdf.write` and `fonts.Sfnt.subset`; a rename breaks the harness loudly instead of skipping it, but the file needs the same edit | Whenever those modules are refactored |
| Compression-enabled golden artifact | Both published goldens set `output.compress: false` because deflate output can differ between zlib builds, so the default compressed path is byte-unpinned | After `DT-102` fixes the zlib builds |
| Requirement-to-case audit | Nothing fails when a claimed-profile requirement has neither a case nor a recorded reason, or when `cases.json` names a check that no longer exists | The next ConformanceSpec revision |
| Cross-format raster equivalence | Ghostscript compares PDF and PostScript only for the three golden documents; barcodes, QR codes, images and SVG artwork are never compared between the two backends | The next backend change |
| Artifact-level pagination | Page expansion is covered at the plan level; the artifact's page count and page order are not asserted | The first multi-page stock document |
| `DT-109` operator-order case | Byte-identical output for identical input (`DT-101`, `DT-107`) already implies a stable operator order within one environment; the requirement adds cross-environment ordering | Alongside `DT-102` |
| `DT-108` calibration determinism | Its verification is `CS-119`, already exercised through `CP-CE`; a renderer-side case would restate it | Only if `CS-119` is revised |
| Parallel case runner | 600 dpi rasterization across the suite dominates CI time; running cases concurrently would help, but risks flakiness in a suite whose value is determinism | When CI runtime starts blocking review |
| `CP-RND` claim | Requires every `RO-*` and `DT-*` requirement to pass or carry a justified reason, which needs `DT-102` and `DT-109` first | v1.0 |
| Stale requirement counts | Two older changelog entries state "96 requirement entries: 92 pass, 4 not-tested", which the suite has since outgrown | Historical text; left alone until the next release |

## How This Document Changes

- **ROADMAP.md** — High-level direction and milestone status (this file)
- **MILESTONES.md** — Wave definitions and subsystem ownership
- **CHECKLIST.md** — Granular completion tracking
- **CHANGELOG.md** — What shipped in each release

Update the roadmap when milestones shift. Record delivered work in the changelog at release time.

---

## Contributing to the Roadmap

Open an issue to propose roadmap changes. Significant architectural shifts require an RFC. Implementation PRs should reference the milestone or checklist items they address.
