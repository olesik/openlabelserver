# Backend

FastAPI REST API service for OpenLabelServer.

## Responsibilities

- REST API defined in [specs/api/](../specs/api/)
- Asset storage and retrieval
- Render and print job queue management
- Authentication and configuration
- Logging and metrics

## Status

Wave 4 (Backend) has started: `backend/main.py` serves `GET /v1/health` and
`GET /v1/info` under the mandatory `/v1` prefix, stamps `X-API-Version: 1.0` on
every response and renders
errors as RFC 9457 `application/problem+json` problem documents
(`backend/problems.py`). These are the only implemented pieces so far: there is
no persistence, authentication, asset storage or job execution, and the info
resource reports no rendering or printing capability until there is one.

The conformance suite's first `CP-API` cases (`AP-102`, `AP-103`) drive the
application in-process; `CP-API` itself stays unclaimed until the rest of its
requirements are observable.

The container healthcheck probes `GET /v1/health` in the `app` stage, while the
stub stage keeps the unversioned `/health` its placeholder server answers.

## Running locally

```bash
python3 -m pip install -r backend/requirements.txt
python3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
curl -fsS http://127.0.0.1:8000/v1/health
curl -fsS http://127.0.0.1:8000/v1/info
```

The container image runs the same application through
`scripts/entrypoints/backend.sh` (`uvicorn backend.main:app`).

## Ownership

Owned by the **Backend** subsystem. See [AGENTS.md](../AGENTS.md).
