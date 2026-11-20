# Changelog

All notable changes to OpenLabelServer are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
once tagged releases begin.

## [Unreleased]

### Added

- Golden artifacts (`RO-111`, `tests/regression/`): a representative stock-grid document — two records, two layers, a rounded panel, a stroked circle, a dashed rule, bold text and rotated text — is published as a PDF and a PostScript artifact with its exact byte count and SHA-256 digest; `tests/regression/publish.py` republishes them, and the conformance suite verifies the committed bytes against the manifest and re-renders the document for a byte comparison, so a placement, resource-name, operator-order or page-transform regression fails with the artifact that moved, and ConformanceSpec `RO-111` now passes (95 requirement entries: 91 pass, 4 not-tested)
- PDF and PostScript output (`renderer/output.py`, `renderer/plan.py`, `renderer/geometry.py`, `renderer/pdf.py`, `renderer/postscript.py`): `output.artifact` validates a RenderSpec document, expands it into pages (one per grid of `data` records), composes and resolves each label body through the Section 8.2 primitives into a backend-neutral plan of fill, stroke and text operations in page millimetres, and writes a compressed PDF 1.4 or a DSC-conformant PostScript Level 2 program — page size from the declared `page` (`RO-109`), vector operators only (`RO-102`), the documented Section 4.2 colour-space conversions honoured, no creation timestamp or time-derived identifier (`RO-110`, IN-3) and identical bytes for identical input (`RS-119`, `DT-101`); images, barcodes, QR codes, custom font embedding and text alignment or wrapping are reported rather than approximated, so ConformanceSpec `RS-119`, `RO-101`, `RO-102`, `RO-106`, `RO-109`, `RO-110` and `DT-101` now pass, and the new modules have unit tests run by `scripts/test.sh`
- Per-object renderers (`renderer/objects.py`): one backend-neutral primitive per RenderSpec Section 8.2 object type with its defaults applied — a `text` run with `font_size` converted from points to its 3.5278 mm em size, shapes with `"none"` colours resolved to absent paint, and the declared image, barcode and QR code extents with `draw_text` defaulting to `true`; the renderer parser now rejects `align` or `wrap` without `width` and `valign` without `height`, so ConformanceSpec `RT-103` and `RT-113`-`RT-116` now pass, and the module has unit tests run by `scripts/test.sh`
- Layer and object composition (`renderer/composition.py`): the ordered draw list a renderer paints, with `visible: false` on a layer, group or object suppressing it entirely, the effective alpha as the product of layer, ancestor group and object opacity, and the Section 9 matrix (`T(x, y) x R(rotation) x S(scale_x, scale_y) x M_custom` over the parent) for every drawn object, so ConformanceSpec `RT-107`-`RT-112` now pass, and the module has unit tests run by `scripts/test.sh`
- Data binding (`renderer/binding.py`): deterministic `{{variable}}` resolution from a `data` record for `text.content`, `barcode.content` and `qrcode.content` only, with unresolved names resolving to the empty string and numeric/boolean values serialized to their JSON spelling; `page_slots` maps records to stock-grid frames row-major, repeats the grid on further pages, leaves frames without a record empty and renders one blank sheet when `data` is omitted or empty, so ConformanceSpec `RB-101`-`RB-104`, `RT-105` and `RT-106` now pass, and the module has unit tests run by `scripts/test.sh`
- Page placement (`renderer/layout.py`): `document_frames` returns the bodies a RenderSpec renders — one page-sized body at `(0, 0)` for a page-absolute document and one body per inline-stock frame in row-major order for stock-grid documents; ConformanceSpec `RT-101` and `RT-102` now pass
- Label-shape clipping (`renderer/clip.py`): the StockSpec Section 5.3 clip for `rectangle`, `rounded-rectangle`, `round` and `oval` labels, placed on every frame in row-major order, plus the RenderSpec Section 5.2 per-frame rectangle that keeps content from bleeding into neighbouring labels; ConformanceSpec `SS-112` and `RT-104` are now verified against four full-bleed shape fixtures, and the module has unit tests run by `scripts/test.sh`
- Layout engine (`renderer/layout.py`): StockSpec Section 6.2 frame origins in Section 5.4 row-major order, the RenderSpec Section 3/5.2 active boundary (page or individual label), and `RS-118` boundary-overflow warnings that name the offending object without rejecting the document; ConformanceSpec `SS-104`, `SS-113`, `SS-115`, `SS-118` and `RS-118` now pass instead of being deferred, and the module has unit tests run by `scripts/test.sh`
- RenderSpec parser and coordinate engine (`renderer/renderspec.py`, `renderer/coordinates.py`): schema-driven parsing in strict and forward-compatibility modes with dotted-path diagnostics, and the Section 3 millimetres/top-left/Y-down coordinates with the Section 9 transform composition; ConformanceSpec `CN-102` and `CN-105` now pass instead of being deferred, and both modules have unit tests run by `scripts/test.sh`
- Executable conformance suite (`tests/conformance/`) with fixture-driven checks for the common rules and the RenderSpec, StockSpec and CalibrationSpec requirements, run by `scripts/test.sh` and the Specification Tests workflow
- Calibration engine (`printing/calibration.py`): CalibrationSpec §7 transform application, §8 profile selection with the `AJ-108` ambiguous-profile rejection, and §9.6 recommended-range warnings, verified by the conformance suite through `CP-CE`
- RFC-0002 accepted: CalibrationSpec Section 8 rule 3 selects a `target` carrying only informational fields at the printer-only precedence level, and ConformanceSpec `CS-114` states the same clause
- ADR-0004 summarizing the decision that informational target fields never decide calibration selection
- RFC-0003 accepted: CalibrationSpec Section 6.1 recommends `metadata.updated_at` on profiles that can only match at the printer-only precedence level, as a SHOULD rather than a MUST
- RFC-0004 accepted: `errors[]` entries carry a `context` object, defined for `ambiguous-calibration-profile` as the tied profile ids in ascending order and the precedence level they share, and the engine's `AmbiguousProfileError` exposes both
- Example and snippet validation (`scripts/validate_examples.py`): every published API example is validated against its OpenAPI component schema, embedded JSON and YAML blocks in the specifications, README, docs and RFCs are checked against their example files (full copies or snippets), and every other embedded block is validated against its named schema, run by `scripts/test.sh`
- ConformanceSpec v1.0 report schema (`specs/conformance/schema.json`): the §16 example block validates against it, and `tests/conformance/runner.py --json` rejects reports that fail it, so the example validator carries no exemptions
- Conformance suite `--json` report output in the ConformanceSpec v1.0 report format, validated against the published report schema and report rules `CR-1`–`CR-7` before it is printed
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
