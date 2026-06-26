# OpenLabelServer Agent Guide

## Purpose

This document defines how contributors and AI coding agents should work on
OpenLabelServer.

The project is specification-first.

The specifications are authoritative.

If implementation conflicts with a specification, the specification wins.

---

# Project Philosophy

OpenLabelServer is not just an application.

It is an open label rendering platform.

The reference implementation demonstrates the published specifications.

---

# Rules

1. Never invent public interfaces.
2. Never bypass RenderSpec.
3. Never hardcode label layouts.
4. Never add printer-specific logic to the UI.
5. Never silently rasterize vector artwork.
6. Preserve deterministic rendering.
7. Write tests with every feature.
8. Update documentation with every architectural change.

---

# Before Writing Code

Verify:

- Which specification owns this feature?
- Which subsystem owns this feature?
- Does an RFC already exist?
- Does the change require a schema update?

---

# Ownership

Governance
- Specifications
- RFCs
- ADRs

Platform
- Docker
- CI/CD

Backend
- REST API
- Database
- Jobs

Renderer
- Layout
- PDF
- PostScript

Printing
- CUPS
- IPP
- Calibration

Frontend
- UI
- Preview
- Editor

QA
- Tests
- Conformance
- Regression

---

# Coding Standards

- Small commits
- One feature per PR
- Keep public APIs versioned
- Avoid breaking changes
- Document assumptions

---

# Pull Request Checklist

- Tests pass
- Documentation updated
- Schema updated if required
- No architectural violations
- Conformance maintained

---

# Out of Scope

Do not introduce:

- Vendor SDKs
- Windows-only APIs
- Proprietary file formats
- Hidden configuration
- Non-deterministic rendering

---

# Success Criteria

A contributor should be able to implement a feature using only:

- README.md
- CHECKLIST.md
- MILESTONES.md
- Published specifications

without requiring tribal knowledge.
