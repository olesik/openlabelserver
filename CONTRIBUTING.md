# Contributing to OpenLabelServer

Thank you for your interest in OpenLabelServer.

This project is **specification-first**. Published specifications define public behavior. The reference implementation exists to demonstrate compliance with those specifications.

> **The specification is the product; the code is an implementation of the specification.**

If implementation and specification disagree, **the specification wins** until an accepted RFC changes the specification.

---

## Before You Start

Read these documents:

| Document | Purpose |
|----------|---------|
| [README.md](README.md) | Project overview and architecture |
| [PROJECT_CHARTER.md](PROJECT_CHARTER.md) | Mission, principles, and non-goals |
| [MILESTONES.md](MILESTONES.md) | Development waves and subsystem ownership |
| [CHECKLIST.md](CHECKLIST.md) | Project completion criteria |
| [AGENTS.md](AGENTS.md) | Guidance for contributors and AI agents |
| [specs/](specs/) | Published specifications |

A contributor should be able to implement a feature using only the documents above and the published specifications, without tribal knowledge.

---

## What to Contribute

Contributions are welcome in several areas:

- **Specifications** — RenderSpec, StockSpec, CalibrationSpec, API, and conformance documents
- **Reference implementation** — Backend, renderer, printing, and frontend subsystems
- **Infrastructure** — Docker, CI/CD, and release tooling
- **Tests** — Unit, conformance, regression, and performance tests
- **Documentation** — User guides, developer guides, and examples

Check [ROADMAP.md](ROADMAP.md) for current priorities.

---

## Subsystem Ownership

Work within your assigned subsystem. Do not modify another team's public contract without coordination.

| Area | Owns |
|------|------|
| **Governance** | Specifications process, RFCs, ADRs, repository governance |
| **Platform** | Docker, CI/CD |
| **Backend** | REST API, database, jobs |
| **Renderer** | Layout, PDF, PostScript |
| **Printing** | CUPS, IPP, calibration application |
| **Frontend** | UI, preview, editor |
| **QA** | Tests, conformance, regression |

If you discover a conflict between specifications, **report it** (open an issue) rather than silently changing another specification.

---

## Contribution Workflow

### 1. Open an issue

For significant work — new features, architectural changes, or specification updates — open an issue first and discuss the approach.

Small fixes (typos, clear bugs with obvious fixes) may proceed directly to a pull request.

### 2. Branch from `main`

Use a descriptive branch name:

```text
feature/pdf-renderer-text-objects
fix/stockspec-margin-validation
docs/contributing-guide
spec/renderspec-barcode-object
```

### 3. Make focused changes

- **One feature per pull request**
- **Small commits** with clear messages
- Keep public APIs **versioned**
- Avoid breaking changes without a version increment and migration notes

### 4. Follow project rules

1. Never invent public interfaces outside published specifications.
2. Never bypass RenderSpec for layout.
3. Never hardcode label layouts.
4. Never add printer-specific logic to the UI.
5. Never silently rasterize vector artwork.
6. Preserve deterministic rendering.
7. Write tests with every feature.
8. Update documentation with every architectural change.

### 5. Specification changes

Specification changes require:

1. An issue or RFC describing the change and motivation
2. Updates to the specification document
3. Updates to the JSON Schema or OpenAPI contract where applicable
4. Example documents demonstrating the change
5. Conformance test updates where behavior is observable

Major architectural principles may only change through accepted RFCs.

### 6. Pull request checklist

Before submitting, verify:

- [ ] Tests pass locally (or note why tests are not yet applicable)
- [ ] Documentation updated
- [ ] Schema updated if the public contract changed
- [ ] No architectural violations (see [AGENTS.md](AGENTS.md))
- [ ] Conformance maintained
- [ ] CHANGELOG.md updated for user-visible changes

### 7. Review

Maintainers review for:

- Alignment with project principles
- Specification compliance
- Test coverage
- Documentation completeness
- Scope — changes should be focused and reviewable

---

## Development Standards

### Determinism

Identical inputs must produce identical output. Avoid nondeterministic sources (unordered iteration affecting output, timestamps in rendered artifacts, environment-dependent floating-point behavior without documented tolerance).

### Vector first

Prefer vector output. Rasterize only when explicitly required or unavoidable.

### Platform independence

Do not introduce:

- Vendor SDKs
- Windows-only APIs
- Proprietary file formats
- Hidden configuration

### Container native

Components should run in containers. Prefer Docker Compose for local development once the platform subsystem is available.

---

## Code Style

Follow conventions established in each subsystem. When no convention exists:

- Use clear, descriptive names
- Keep functions and modules focused
- Prefer explicit behavior over implicit side effects
- Document non-obvious business logic

Linting and formatting rules will be enforced by CI as subsystems land.

---

## Testing

Every feature should include tests appropriate to its subsystem:

| Layer | Examples |
|-------|----------|
| Schema | JSON Schema validation of examples |
| Renderer | Golden PDF/PostScript, coordinate accuracy |
| API | OpenAPI conformance, request/response contracts |
| Integration | End-to-end render and print flows |
| Regression | Snapshot and hash validation |

Performance targets (from [CHECKLIST.md](CHECKLIST.md)) include render &lt; 500 ms, preview &lt; 250 ms, and documented concurrency goals.

---

## Documentation

Update documentation when you change:

- Public APIs or schemas
- Architecture or subsystem boundaries
- Installation or deployment procedures
- User-visible behavior

Specification documents live under `specs/`. User and developer guides will live under `docs/` as the project matures.

---

## Community

- Be respectful and constructive. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
- Report security issues privately. See [SECURITY.md](SECURITY.md).
- Ask questions in issues. Label enhancement proposals clearly.

---

## License

By contributing, you agree that your contributions will be licensed under the [Apache License 2.0](LICENSE), the same license that covers this project.
