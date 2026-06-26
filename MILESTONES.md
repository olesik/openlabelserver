# OpenLabelServer Development Milestones

> **Rule #1**
>
> If implementation conflicts with a published specification,
> **the specification wins.**

---

# Wave 0 — Foundation

**Owner:** Project Lead

Goal:
Prepare the repository for collaborative open-source development.

Deliverables

- Repository structure
- Governance documents
- Branching strategy
- AI agent documentation
- Initial roadmap
- GitHub configuration

Dependencies

None

---

# Wave 1 — Specifications (Highest Priority)

No implementation should begin until these contracts are stable.

## Agent G1 — RenderSpec

Owns

- RenderSpec
- Object Model
- Layers
- Coordinates
- Assets
- Fonts
- Output Options

Produces

- RenderSpec v1
- JSON Schema
- Example Documents

Consumes

Nothing

---

## Agent G2 — StockSpec

Owns

- YAML Stock Format
- Grid Model
- Page Geometry
- Margins
- Pitch

Produces

- StockSpec v1
- JSON Schema
- Example Stocks

Consumes

RenderSpec Coordinate System

---

## Agent G3 — CalibrationSpec

Owns

- Calibration Profiles
- Offsets
- Scaling
- Rotation

Produces

- CalibrationSpec v1
- JSON Schema

Consumes

Nothing

---

## Agent G4 — API Specification

Owns

- REST API
- Resources
- Authentication
- Errors
- Versioning

Produces

- OpenAPI Specification

Consumes

RenderSpec

---

## Agent G5 — Conformance

Owns

- Validation Rules
- Required Behaviour
- Compliance Tests

Produces

- Conformance Specification

Consumes

All Specifications

---

# Wave 2 — Platform

## Agent P1 — Infrastructure

Owns

- Docker
- Docker Compose
- Development Environment
- Production Environment

Produces

- Container Platform

Depends On

Wave 1
# OpenLabelServer Development Milestones

> **Rule #1**
>
> If implementation conflicts with a published specification,
> **the specification wins.**

---

# Wave 0 — Foundation

**Owner:** Project Lead

Goal:
Prepare the repository for collaborative open-source development.

Deliverables

- Repository structure
- Governance documents
- Branching strategy
- AI agent documentation
- Initial roadmap
- GitHub configuration

Dependencies

None

---

# Wave 1 — Specifications (Highest Priority)

No implementation should begin until these contracts are stable.

## Agent G1 — RenderSpec

Owns

- RenderSpec
- Object Model
- Layers
- Coordinates
- Assets
- Fonts
- Output Options

Produces

- RenderSpec v1
- JSON Schema
- Example Documents

Consumes

Nothing

---

## Agent G2 — StockSpec

Owns

- YAML Stock Format
- Grid Model
- Page Geometry
- Margins
- Pitch

Produces

- StockSpec v1
- JSON Schema
- Example Stocks

Consumes

RenderSpec Coordinate System

---

## Agent G3 — CalibrationSpec

Owns

- Calibration Profiles
- Offsets
- Scaling
- Rotation

Produces

- CalibrationSpec v1
- JSON Schema

Consumes

Nothing

---

## Agent G4 — API Specification

Owns

- REST API
- Resources
- Authentication
- Errors
- Versioning

Produces

- OpenAPI Specification

Consumes

RenderSpec

---

## Agent G5 — Conformance

Owns

- Validation Rules
- Required Behaviour
- Compliance Tests

Produces

- Conformance Specification

Consumes

All Specifications

---

# Wave 2 — Platform

## Agent P1 — Infrastructure

Owns

- Docker
- Docker Compose
- Development Environment
- Production Environment

Produces

- Container Platform

Depends On

Wave 1

---

## Agent P2 — CI/CD

Owns

- GitHub Actions
- Linting
- Testing
- Releases

Produces

- Automated Build Pipeline

Depends On

Wave 1

---

# Wave 3 — Renderer

## Agent R1 — Rendering Core

Owns

- RenderSpec Parser
- Coordinate Engine
- Layout Engine

Produces

- Internal Render Engine

Depends On

RenderSpec

---

## Agent R2 — Object Plugins

Owns

- Text
- Shapes
- Images
- SVG

Produces

- Rendering Objects

Depends On

Rendering Core

---

## Agent R3 — Codes

Owns

- Barcode
- QR Code

Produces

- Barcode Plugins

Depends On

Rendering Core

---

## Agent R4 — Output Backends

Owns

- PDF
- PostScript

Produces

- Output Generators

Depends On

Object Plugins

---

# Wave 4 — Backend

## Agent B1 — API

Owns

- FastAPI
- Routing
- Validation

Produces

- REST Service

Depends On

API Specification

---

## Agent B2 — Storage

Owns

- SQLAlchemy
- SQLite
- Configuration

Produces

- Persistence Layer

Depends On

API

---

## Agent B3 — Assets

Owns

- Uploads
- Storage
- Metadata

Produces

- Asset Service

Depends On

Storage

---

## Agent B4 — Jobs

Owns

- Queue
- History
- Scheduling

Produces

- Job Service

Depends On

Storage

---

# Wave 5 — Printing

## Agent PR1 — CUPS

Owns

- Printer Discovery
- Queues

Produces

- Print Service

Depends On

Renderer

---

## Agent PR2 — IPP

Owns

- IPP Communication
- Capability Detection

Produces

- Printer Transport

Depends On

CUPS

---

## Agent PR3 — Calibration

Owns

- Calibration Profiles
- Transform Application

Produces

- Calibration Engine

Depends On

CalibrationSpec

---

# Wave 6 — Frontend

## Agent F1 — Framework

Owns

- Vue
- Layout
- Routing

Produces

- Web UI

Depends On

Backend API

---

## Agent F2 — Editor

Owns

- Label Editor
- Property Panels

Produces

- Editing Interface

Depends On

RenderSpec

---

## Agent F3 — Preview

Owns

- PDF Preview
- Zoom
- Pan

Produces

- Preview Interface

Depends On

Renderer

---

## Agent F4 — Administration

Owns

- Printers
- Stocks
- Assets
- Jobs

Produces

- Management Interface

Depends On

Backend

---

# Wave 7 — Quality Assurance

## Agent Q1 — Unit Testing

- Backend
- Renderer
- Frontend

---

## Agent Q2 — Conformance

- Schema Validation
- Specification Compliance

---

## Agent Q3 — Regression

- Golden PDFs
- Golden PostScript
- Snapshot Tests
- Hash Validation

---

## Agent Q4 — Performance

- Benchmarks
- Memory
- Throughput

---

# Wave 8 — Documentation

## Agent D1 — User Documentation

- Installation
- Configuration
- Usage

---

## Agent D2 — Developer Documentation

- Architecture
- Specifications
- Plugin Development

---

## Agent D3 — API Documentation

- REST Reference
- Examples
- OpenAPI Publishing

---

# Dependency Flow

Foundation
↓

Specifications
↓

Infrastructure
↓

Renderer
↓

Backend
↓

Printing
↓

Frontend
↓

Testing
↓

Documentation
↓

Release

---

# Agent Rules

Every agent must:

- Work only within its assigned ownership.
- Follow published specifications.
- Never modify another subsystem's contract.
- Submit documentation alongside code.
- Add tests for all new functionality.
- Preserve deterministic behaviour.
- Keep public interfaces versioned.

No implementation should bypass RenderSpec or violate the architectural principles established in the project specifications.
