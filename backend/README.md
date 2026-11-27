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
(`backend/problems.py`). The templates, stocks and calibration-profile resources
store RenderSpec, StockSpec and CalibrationSpec documents in a SQLite database
(`backend/storage.py`), and uploaded files are stored in the same database; there is
still no authentication and no job execution, and the info resource reports no
rendering or printing capability until there is one.

`POST /v1/templates/{template_id}/validate` validates a RenderSpec body against
the published [schema](../specs/renderspec/schema.json) without loading or
persisting anything (API §8.3, RFC-0001): `200` with `{"valid": true}` for a valid
document, `422` with one `errors` entry per failing field (§5.3), `409` when
`document.id` differs from the path id, and `400` for a body that is not JSON
(§5.2). The rules are the schema file itself, read through `jsonschema`, so the
API has no second definition of a RenderSpec to drift from — and the `app` image
copies that file next to `backend/`.

Templates are a stored resource (API §8.3). `POST /v1/templates` takes a RenderSpec
body, validates it against the published schema before storing anything, answers
`201` with the `Template` resource, `422` (§5.3) for a document that fails the
schema and `409 Conflict` for an id already in the catalog; the resource id is
`document.id` (§9.3). `GET /v1/templates/{id}` answers `200` or `404`,
`PUT /v1/templates/{id}` revalidates and replaces the document — `409` when
`document.id` names another identity, `404` when the path id is not stored —
`PATCH /v1/templates/{id}` merges the `name` and `description` OpenAPI's
`TemplatePatch` publishes into the document and validates the result before
storing it, and `DELETE /v1/templates/{id}` answers `204` or `404`.

`GET /v1/templates` lists the stored templates in the API §6.2 pagination
envelope, honouring the §6.1 `page` and `page_size` bounds and answering `400`
(§5.2) for anything outside them. `sort` names `id`, `created_at`, `updated_at`
or `name` with an optional `-` for descending (the default is `-created_at`, ties
broken by id) and `filter` matches a case-insensitive substring of
`document.name` — a RenderSpec carries no tag, so no template has one for the
OpenAPI parameter's tag half to match. An unknown sort field is the §5.2 `400`,
not a silent default. A response with another page carries the §6.3 `Link` header —
`rel="next"` while a next page exists and `rel="first"` when the request is not on
the first page — and each target keeps the request's page size and any `sort` /
`filter`, so following it stays in the same collection.

Stocks and calibration profiles are stored resources too (API §8.4 and §8.5,
`AR-104`), with the same six operations and the same `201`, `404`, `409` and `422`
answers, and their bodies are read through the published
[StockSpec](../specs/stockspec/schema.json) and
[CalibrationSpec](../specs/calibrationspec/schema.json) schemas — the `422` detail
names the document that failed, so a bad profile is not reported as a RenderSpec.
Their identity is `document.metadata.id` (§9.3): a create whose `metadata.id` is
already in the catalog is a `409 Conflict`, and a replace whose document names
another id is the `409` before the `404` an unknown path id earns. `PATCH` edits what
OpenAPI publishes for each patch body — `name`, `description` and `tags` inside
StockSpec `metadata`, and `name`, `description` and the root `enabled` flag for a
CalibrationSpec profile. The stocks collection's `filter` matches a case-insensitive
substring of `metadata.name`, and the calibrations collection's `printer_id` keeps
the profiles whose `printer.identifier` is that printer.

Assets are files rather than documents (API §8.6, `AR-105`). `POST /v1/assets` reads
the required `multipart/form-data` `file` field and answers `201` with the `Asset`
resource: the id is a server-generated opaque `ast_` string, the name is the
optional field or the uploaded filename, the content type is the `content_type`
hint when given and the file part's own otherwise, and the size and SHA-256 describe
the bytes actually stored. The type must be one of the six §8.6 allows
(`image/png`, `image/jpeg`, `image/svg+xml`, `font/ttf`, `font/otf` and
`application/octet-stream`); anything else is the §5.3 `422` and stores nothing.
`GET /v1/assets/{id}` answers that metadata with `url` naming the §9.5 content URI,
and `GET /v1/assets/{id}/content` serves the bytes exactly as uploaded under their
stored media type, so a PNG survives the round trip unchanged. `python-multipart`
parses the upload; its own `422` for a body without a `file` field is rewritten as
the published problem document with a `file` entry, so a missing required field is
not the only error whose shape differs from §5.3.

The catalogs are a SQLite database. `OPENLABEL_DATABASE` names the file, which is
what keeps them across a restart; without it the service uses a process-local
(`:memory:`) database, so a stored document or asset outlives a request but not the
process. Only the identity, the document and the §7.1 timestamps are stored for a
catalog row — `object` is derived, because the catalog is the resource type — and an
asset row carries the metadata above with the file beside it.

The conformance suite drives the application in-process: `AP-101` to `AP-106`, and
`AR-101`, `AR-102`, `AR-103`, `AR-104`, `AR-105` and `AR-106` now that the catalogs
store documents and assets. `CP-API` itself stays unclaimed until the rest of its
requirements are observable.

The container healthcheck probes `GET /v1/health` in the `app` stage, while the
stub stage keeps the unversioned `/health` its placeholder server answers.

## Running locally

```bash
python3 -m pip install -r backend/requirements.txt
python3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
curl -fsS http://127.0.0.1:8000/v1/health
curl -fsS http://127.0.0.1:8000/v1/info
curl -fsS http://127.0.0.1:8000/v1/templates
curl -fsS -X POST http://127.0.0.1:8000/v1/templates \
  -H 'Content-Type: application/json' \
  --data @specs/renderspec/examples/simple_label.json
curl -fsS http://127.0.0.1:8000/v1/templates/simple_address_label
curl -fsS -X DELETE http://127.0.0.1:8000/v1/templates/simple_address_label
curl -fsS -X POST http://127.0.0.1:8000/v1/templates/simple_address_label/validate \
  -H 'Content-Type: application/json' \
  --data @specs/renderspec/examples/simple_label.json
curl -fsS -X POST http://127.0.0.1:8000/v1/assets \
  -F file=@tests/conformance/fixtures/renderspec/assets/mark.png
curl -fsS -o mark.png http://127.0.0.1:8000/v1/assets/ast_.../content
```

The container image runs the same application through
`scripts/entrypoints/backend.sh` (`uvicorn backend.main:app`).

## Ownership

Owned by the **Backend** subsystem. See [AGENTS.md](../AGENTS.md).
