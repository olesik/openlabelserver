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

`POST /v1/templates/{template_id}/validate` validates a RenderSpec body against
the published [schema](../specs/renderspec/schema.json) without loading or
persisting anything (API §8.3, RFC-0001): `200` with `{"valid": true}` for a valid
document, `422` with one `errors` entry per failing field (§5.3), `409` when
`document.id` differs from the path id, and `400` for a body that is not JSON
(§5.2). The rules are the schema file itself, read through `jsonschema`, so the
API has no second definition of a RenderSpec to drift from — and the `app` image
copies that file next to `backend/`.

The conformance suite's `CP-API` cases (`AP-102`, `AP-103`, `AP-104`) drive the
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
curl -fsS -X POST http://127.0.0.1:8000/v1/templates/simple_address_label/validate \
  -H 'Content-Type: application/json' \
  --data @specs/renderspec/examples/simple_label.json
```

The container image runs the same application through
`scripts/entrypoints/backend.sh` (`uvicorn backend.main:app`).

## Ownership

Owned by the **Backend** subsystem. See [AGENTS.md](../AGENTS.md).
