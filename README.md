# OpenLabelServer

> **Open-source, self-hosted platform for deterministic label rendering and printing.**
>
> **Render once. Print anywhere.**

OpenLabelServer is a vendor-independent label generation platform designed for professional print workflows. It generates deterministic, vector-based output for pre-cut label sheets and prints directly through CUPS using standards-based PDF and PostScript.

Unlike traditional label software, OpenLabelServer does **not** rely on proprietary templates, Windows printer drivers, or manufacturer SDKs. Every label layout is defined declaratively and rendered with repeatable, pixel-accurate results.

---

## Project Goals

* Deterministic rendering
* Self-hosted deployment
* Vector-first rendering pipeline
* API-first architecture
* Docker-native deployment
* Vendor-independent printing
* Extensible and modular design
* Reproducible output
* Open standards

---

## Features (Planned)

* FastAPI REST API
* Vue 3 web interface
* YAML-defined label stock
* Versioned RenderSpec specification
* PDF generation
* PostScript generation
* SVG artwork support
* Barcode generation
* QR Code generation
* Variable data rendering
* CUPS integration
* IPP printer discovery
* Printer calibration
* Print queue management
* Snapshot-based regression testing

---

## Architecture

```text
Browser
    │
    ▼
Web UI (Vue)
    │
REST API (FastAPI)
    │
RenderSpec
    │
Renderer
    │
PDF / PostScript
    │
Print Service
    │
CUPS
    │
Printer
```

---

## Core Principles

OpenLabelServer is built around a few simple principles.

### Declarative

Everything is described as data.

Layouts are defined in a versioned RenderSpec rather than hardcoded rendering logic.

### Deterministic

Identical inputs should always produce identical output.

Rendering should be reproducible across operating systems, deployments, and printers.

### Vendor Independent

No proprietary label formats.

No Windows-only dependencies.

No manufacturer SDKs.

### Open Standards

The project is built on widely adopted technologies including:

* PDF
* PostScript
* SVG
* IPP
* OpenType
* Docker
* OpenAPI

---

## RenderSpec

The heart of OpenLabelServer is **RenderSpec**.

RenderSpec is a versioned JSON document describing everything required to render a label:

* page geometry
* stock definition
* objects
* assets
* fonts
* variable data
* output options

The renderer consumes only RenderSpec.

This allows multiple renderers (PDF, PostScript, SVG, ZPL, EPL, etc.) to share a common specification.

---

## Label Stock

Label stock is defined using simple YAML files.

Example:

```yaml
page:
  width: 215.9
  height: 279.4

label:
  width: 66.675
  height: 25.4

rows: 10
columns: 3

margin_left: 4.76
margin_top: 12.7

horizontal_pitch: 69.85
vertical_pitch: 25.4
```

Adding new label stock should never require code changes.

---

## Planned Repository Structure

```text
openlabelserver/

├── backend/
├── frontend/
├── renderer/
├── printing/
├── schemas/
├── examples/
├── docs/
├── docker/
├── scripts/
├── tests/
└── .github/
```

---

## Roadmap

### v0.1

* Repository scaffold
* Docker Compose
* FastAPI skeleton
* Vue skeleton
* Architecture documentation
* RenderSpec v1 draft
* JSON Schemas
* CI pipeline

### v0.2

* RenderSpec validation
* PDF renderer
* SVG support
* YAML stock definitions

### v0.3

* Barcode support
* QR code support
* Variable data
* Snapshot testing

### v0.4

* CUPS integration
* Printer discovery
* Calibration
* Print queue

### v0.5

* Web UI
* Live preview
* Job management

### v1.0

* Stable API
* Stable RenderSpec
* Production-ready renderer
* Complete documentation

---

## Project Status

🚧 **Early Development**

OpenLabelServer is currently in the architecture and specification phase.

The initial focus is establishing stable specifications before implementation begins.

---

## Contributing

Contributions are welcome.

Before implementing new functionality, please open an issue to discuss significant architectural or specification changes.

The project follows one guiding principle:

> **The specification is the product; the code is an implementation of the specification.**

---

## License

Licensed under the Apache License 2.0.

See the `LICENSE` file for details.

---

## Vision

OpenLabelServer aims to become the open platform for professional label generation.

By separating layout, rendering, and printing through a stable, versioned specification, the project enables deterministic output, long-term maintainability, and support for multiple rendering and printing backends without changing application logic.
