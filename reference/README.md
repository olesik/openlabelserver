# Reference Implementation

The reference implementation demonstrates compliance with the published specifications in [specs/](../specs/).

Third-party implementations should be written using only the published specifications — no tribal knowledge from this codebase is required.

## Subsystems

Application code is organized as top-level subsystems:

| Directory | Responsibility |
|-----------|----------------|
| [backend/](../backend/) | REST API, database, job orchestration |
| [frontend/](../frontend/) | Web UI, label editor, live preview |
| [renderer/](../renderer/) | RenderSpec parsing, layout, PDF and PostScript output |
| [printing/](../printing/) | CUPS integration, IPP discovery, calibration application |

Each subsystem is independently testable and containerized. See [docker/](../docker/) for Compose stacks and Dockerfiles.

## Status

The reference implementation is in early development. Subsystem directories contain scaffolding; implementation work begins after Wave 1 specifications stabilize.

See [ROADMAP.md](../ROADMAP.md) and [MILESTONES.md](../MILESTONES.md) for milestone tracking.
