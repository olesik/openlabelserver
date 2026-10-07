# OpenLabelServer Container Platform

Docker images and Compose stacks for local development, CI, and production
deployments of OpenLabelServer.

## Layout

```text
docker/
├── backend/          FastAPI REST API image
├── frontend/         Vue web UI image
├── renderer/         RenderSpec rendering engine image
├── printing/         CUPS / print service image
├── ci/               CI tooling image (schema validation, lint helpers)
├── docker-compose.yml
├── docker-compose.dev.yml
└── docker-compose.prod.yml
```

Application source lives outside this directory (`backend/`, `frontend/`,
`renderer/`, `printing/`). Each service Dockerfile exposes two build targets:

| Target | Purpose |
|--------|---------|
| `stub` | Runnable placeholder until application code lands (default) |
| `app` | Full service image; requires the corresponding application directory |

## Quick Start

From the repository root:

```bash
# Validate compose configuration
docker compose -f docker/docker-compose.yml config

# Build stub images (no application code required)
docker compose -f docker/docker-compose.yml build

# Start the development stack
docker compose -f docker/docker-compose.yml -f docker/docker-compose.dev.yml up

# Run CI validation inside the CI container
docker compose -f docker/docker-compose.yml --profile ci run --rm ci
```

## Compose Files

| File | Use |
|------|-----|
| `docker-compose.yml` | Base service definitions, networks, and volumes |
| `docker-compose.dev.yml` | Development overrides (bind mounts, debug ports) |
| `docker-compose.prod.yml` | Production overrides (restart policy, read-only root) |

### Production

```bash
docker compose \
  -f docker/docker-compose.yml \
  -f docker/docker-compose.prod.yml \
  up -d
```

When application subsystems are ready, build with the `app` target:

```bash
docker compose -f docker/docker-compose.yml build --build-arg BUILD_TARGET=app
```

Or set `BUILD_TARGET=app` in an environment file consumed by Compose.

## Services

| Service | Port (dev) | Description |
|---------|------------|-------------|
| `backend` | 8000 | FastAPI REST API |
| `frontend` | 5173 | Vue 3 web interface |
| `renderer` | 8001 | RenderSpec PDF/PostScript engine |
| `printing` | — | CUPS print integration |
| `ci` | — | Schema and specification validation (profile: `ci`) |

## Environment Variables

Common variables are documented inline in `docker-compose.yml`. Override them
with a local `.env` file at the repository root or via `docker-compose.override.yml`
(gitignored).

For smaller build contexts, copy or symlink `docker/.dockerignore` to the
repository root as `.dockerignore` once the Platform team adopts it project-wide.

## Subsystem Ownership

This directory is owned by the **Platform** subsystem. Application Dockerfiles
must not embed printer-specific logic or bypass RenderSpec. See
[AGENTS.md](../AGENTS.md) and [MILESTONES.md](../MILESTONES.md).
