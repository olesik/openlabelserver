# OpenLabelServer REST API Specification v1.0

## Status of this Document

This document defines version **1.0** of the **OpenLabelServer REST API**, the canonical HTTP interface for label design storage, rendering, asset management, printer discovery, and print job submission within the OpenLabelServer ecosystem.

The machine-readable contract is published as [openapi.yaml](./openapi.yaml).

---

## 1. Introduction

### 1.1 Purpose

The OpenLabelServer REST API exposes all platform functionality required for automation, integration, and UI clients. It is the single public boundary between clients and the OpenLabelServer backend.

All label layout semantics are expressed through published domain specifications. The API transports, validates, stores, and orchestrates those documents; it does **not** define layout rules.

### 1.2 Scope

This specification defines:

- Resource model and URI structure
- HTTP methods and status codes
- Request and response envelopes
- Authentication and authorization
- Error representation
- Pagination
- API versioning
- Asynchronous job lifecycle for rendering and printing

This specification does **not** define:

- RenderSpec layout rules ([RenderSpec](../renderspec/specification.md))
- Stock geometry rules ([StockSpec](../stockspec/specification.md))
- Printer calibration transforms ([CalibrationSpec](../calibrationspec/specification.md))
- Internal renderer or print subsystem implementation

### 1.3 Conformance

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT", "SHOULD", "SHOULD NOT", "RECOMMENDED", "MAY", and "OPTIONAL" in this document are to be interpreted as described in [RFC 2119](https://tools.ietf.org/html/rfc2119).

A conforming **API server** MUST implement every endpoint, schema, and behaviour defined in [openapi.yaml](./openapi.yaml) for the declared API version unless explicitly marked OPTIONAL.

A conforming **API client** MUST tolerate unknown JSON properties in response bodies and SHOULD ignore undocumented HTTP headers.

---

## 2. Design Principles

1. **Specification-first payloads** — Domain documents (`RenderSpec`, `StockSpec`, `CalibrationSpec`) are validated against their published JSON Schemas before persistence or job execution.
2. **Deterministic orchestration** — Given identical inputs, render jobs MUST produce byte-identical output (see RenderSpec determinism requirements).
3. **No layout in the API** — The API MUST NOT accept printer-vendor commands, proprietary template formats, or layout shortcuts that bypass RenderSpec.
4. **Automation-friendly** — Every UI capability MUST have a corresponding API operation.
5. **Open standards** — Errors follow [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) Problem Details. OpenAPI 3.1 describes the HTTP contract.

---

## 3. Versioning

### 3.1 API Version

The current API version is **`1.0`**.

Every resource URI MUST be prefixed with a major version segment:

```
/v1/{resource}
```

Example:

```
GET /v1/templates
POST /v1/render-jobs
```

### 3.2 Version Identification

Implementations MUST expose the active API version through:

| Mechanism | Location | Example |
| :--- | :--- | :--- |
| URI prefix | Path | `/v1/` |
| `info.version` | OpenAPI document | `1.0.0` |
| Response header | `X-API-Version` | `1.0` |
| Info resource | `GET /v1/info` body | `{ "api_version": "1.0", ... }` |

The URI major version (`v1`) is the **compatibility boundary**. Breaking changes REQUIRE a new major prefix (`v2`).

### 3.3 Domain Specification Versions

Domain documents carry their own version fields independent of the API:

| Document | Version field | Current value |
| :--- | :--- | :--- |
| RenderSpec | `renderspec` | `"1.0"` |
| StockSpec | `stockspec` | `"1.0"` |
| CalibrationSpec | `calibrationspec` | `"1.0"` |

API servers MUST reject domain documents whose version field is unrecognized.

### 3.4 Deprecation

When an endpoint or field is deprecated:

1. The `Deprecation` response header MUST be set (RFC 8594).
2. The `Sunset` header SHOULD indicate the planned removal date.
3. The replacement MUST be documented in the OpenAPI `description` and release notes.

Deprecated endpoints MUST continue to function for at least one minor release cycle after announcement.

### 3.5 Content Negotiation

Request and response bodies use `application/json` unless otherwise noted (for example, binary asset download or multipart upload).

Clients MAY send:

```
Accept: application/json
Accept: application/problem+json
```

Servers MUST return `application/problem+json` for error responses.

---

## 4. Authentication Model

### 4.1 Overview

OpenLabelServer is self-hosted. Authentication is **REQUIRED in production deployments** but MAY be disabled by server configuration for single-user development environments.

When authentication is enabled, every mutating request and every read of sensitive resources MUST be authenticated. When disabled, the server MUST behave as a single implicit administrator principal.

### 4.2 Supported Schemes

| Scheme | Mechanism | Use case |
| :--- | :--- | :--- |
| **Bearer token** | `Authorization: Bearer <token>` | Interactive sessions, short-lived access |
| **API key** | `X-API-Key: <key>` | Automation, CI/CD, integrations |

Both schemes MAY be enabled simultaneously. If both are present, the server MUST validate the Bearer token first.

OpenAPI security scheme definitions appear in [openapi.yaml](./openapi.yaml) under `components.securitySchemes`.

### 4.3 Token Issuance

```
POST /v1/auth/token
Content-Type: application/json

{
  "grant_type": "password",
  "username": "admin",
  "password": "secret"
}
```

Supported `grant_type` values:

| Value | Description |
| :--- | :--- |
| `password` | Username and password exchange |
| `api_key` | Exchange a long-lived API key for a short-lived Bearer token |
| `refresh_token` | Rotate an expired access token |

Successful response:

```json
{
  "access_token": "eyJ...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "refresh_token": "rt_..."
}
```

### 4.4 API Keys

API keys are opaque server-issued strings prefixed with `ols_`. They MUST be treated as secrets.

Key lifecycle operations (create, revoke, list) are exposed under `/v1/auth/api-keys` and require an authenticated administrator.

### 4.5 Principal Identity

```
GET /v1/auth/me
Authorization: Bearer <token>
```

Returns the authenticated principal:

```json
{
  "id": "usr_admin",
  "object": "user",
  "username": "admin",
  "roles": ["admin"],
  "created_at": "2026-01-15T10:00:00Z"
}
```

### 4.6 Authorization

Authorization is role-based. The v1.0 API defines these roles:

| Role | Capabilities |
| :--- | :--- |
| `admin` | Full read/write on all resources |
| `operator` | Create render and print jobs; read templates, stocks, printers |
| `viewer` | Read-only access to templates, stocks, jobs, printers |

Servers MUST return `403 Forbidden` when an authenticated principal lacks permission.

### 4.7 Unauthenticated Responses

Missing or invalid credentials MUST produce:

```
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Bearer realm="OpenLabelServer"
Content-Type: application/problem+json
```

---

## 5. Error Model

### 5.1 Problem Details

All error responses MUST use [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) Problem Details with media type `application/problem+json`.

Base schema:

| Field | Type | Presence | Description |
| :--- | :--- | :--- | :--- |
| `type` | `string` (URI) | **REQUIRED** | Stable error category identifier |
| `title` | `string` | **REQUIRED** | Short human-readable summary |
| `status` | `integer` | **REQUIRED** | HTTP status code |
| `detail` | `string` | OPTIONAL | Specific explanation |
| `instance` | `string` (URI) | OPTIONAL | Request URI or resource identifier |
| `errors` | `array` | OPTIONAL | Field-level validation errors |

### 5.2 Standard Error Types

| HTTP Status | `type` URI | When |
| :--- | :--- | :--- |
| 400 | `https://openlabelserver.org/errors/bad-request` | Malformed JSON, invalid query parameter |
| 401 | `https://openlabelserver.org/errors/unauthorized` | Missing or invalid credentials |
| 403 | `https://openlabelserver.org/errors/forbidden` | Authenticated but not permitted |
| 404 | `https://openlabelserver.org/errors/not-found` | Resource does not exist |
| 409 | `https://openlabelserver.org/errors/conflict` | Duplicate ID, state conflict |
| 422 | `https://openlabelserver.org/errors/validation-error` | Domain schema or business rule failure |
| 429 | `https://openlabelserver.org/errors/rate-limited` | Rate limit exceeded |
| 500 | `https://openlabelserver.org/errors/internal-error` | Unexpected server failure |
| 503 | `https://openlabelserver.org/errors/service-unavailable` | Dependency unavailable (renderer, CUPS) |

### 5.3 Validation Errors

When domain document validation fails, the server MUST return `422 Unprocessable Entity` with an `errors` array:

```json
{
  "type": "https://openlabelserver.org/errors/validation-error",
  "title": "Validation Error",
  "status": 422,
  "detail": "RenderSpec document failed schema validation.",
  "instance": "/v1/templates/shipping-label",
  "errors": [
    {
      "field": "layers[0].objects[1].width",
      "code": "minimum",
      "message": "must be greater than 0"
    }
  ]
}
```

Each validation error object:

| Field | Type | Presence | Description |
| :--- | :--- | :--- | :--- |
| `field` | `string` | **REQUIRED** | JSON Pointer or dotted path to the invalid value |
| `code` | `string` | OPTIONAL | Machine-readable rule identifier |
| `message` | `string` | **REQUIRED** | Human-readable explanation |

### 5.4 Business Rule Error Codes

In addition to JSON Schema validation, servers MUST use these stable `code` values in `errors[].code` for cross-specification integration failures:

| Code | HTTP Status | When |
| :--- | :--- | :--- |
| `ambiguous-calibration-profile` | 422 | Multiple enabled CalibrationSpec profiles match the same printer and stock; see Section 9.4 |
| `stock-translation-failed` | 422 | StockSpec document could not be translated to RenderSpec stock geometry |
| `missing-template-or-document` | 422 | Render or print job omitted both `template_id` and `document` |
| `printer-not-found` | 422 | Print job `printer_id` does not match a discovered printer |
| `stock-not-found` | 422 | Job `stock_id` does not match a stored Stock resource |

Example — ambiguous calibration profile:

```json
{
  "type": "https://openlabelserver.org/errors/validation-error",
  "title": "Validation Error",
  "status": 422,
  "detail": "Multiple calibration profiles match printer warehouse-zebra and stock shipping-4x6.",
  "instance": "/v1/print-jobs",
  "errors": [
    {
      "field": "calibration_id",
      "code": "ambiguous-calibration-profile",
      "message": "Profiles laser-sheet-full and thermal-roll-offset both match; specify calibration_id explicitly"
    }
  ]
}
```

### 5.5 Job Failure Errors

Failed asynchronous jobs expose error details on the job resource itself (`status: "failed"`, `error` object) in addition to any synchronous rejection at submission time.

---

## 6. Pagination

### 6.1 Query Parameters

Collection endpoints support offset pagination:

| Parameter | Type | Default | Constraints | Description |
| :--- | :--- | :--- | :--- | :--- |
| `page` | integer | `1` | ≥ 1 | 1-based page index |
| `page_size` | integer | `20` | 1–100 | Items per page |
| `sort` | string | resource-specific | — | Sort field; prefix `-` for descending |
| `filter` | string | — | — | Resource-specific filter expression |

Example:

```
GET /v1/templates?page=2&page_size=50&sort=-updated_at
```

### 6.2 Paginated Response Envelope

Collection responses wrap items in a pagination envelope:

```json
{
  "object": "list",
  "data": [ ... ],
  "pagination": {
    "page": 2,
    "page_size": 50,
    "total_items": 127,
    "total_pages": 3,
    "has_next": true,
    "has_previous": true
  }
}
```

| Field | Type | Description |
| :--- | :--- | :--- |
| `object` | `string` | Always `"list"` |
| `data` | `array` | Page of resource objects |
| `pagination.page` | integer | Current page (1-based) |
| `pagination.page_size` | integer | Requested page size |
| `pagination.total_items` | integer | Total matching items |
| `pagination.total_pages` | integer | `ceil(total_items / page_size)` |
| `pagination.has_next` | boolean | Whether a next page exists |
| `pagination.has_previous` | boolean | Whether a previous page exists |

### 6.3 Link Headers

Servers SHOULD include [RFC 8288](https://www.rfc-editor.org/rfc/rfc8288) `Link` headers on paginated responses:

```
Link: </v1/templates?page=3&page_size=50>; rel="next",
      </v1/templates?page=1&page_size=50>; rel="first"
```

---

## 7. Resource Model

### 7.1 Common Resource Envelope

Every resource object includes:

| Field | Type | Presence | Description |
| :--- | :--- | :--- | :--- |
| `id` | `string` | **REQUIRED** | Stable resource identifier |
| `object` | `string` | **REQUIRED** | Resource type discriminator |
| `created_at` | `string` | **REQUIRED** | ISO 8601 UTC creation timestamp |
| `updated_at` | `string` | OPTIONAL | ISO 8601 UTC last modification timestamp |

Resource IDs MUST match `^[a-zA-Z0-9_-]+$` unless the resource type explicitly uses opaque IDs (jobs, assets).

### 7.2 Resource Catalog

| Resource | `object` value | Description |
| :--- | :--- | :--- |
| Template | `template` | Stored RenderSpec document |
| Stock | `stock` | Stored StockSpec document |
| Calibration | `calibration` | Stored CalibrationSpec profile |
| Asset | `asset` | Uploaded binary (image, font, SVG) |
| RenderJob | `render_job` | Asynchronous render task |
| PrintJob | `print_job` | Asynchronous print task |
| Printer | `printer` | Discovered printer queue |
| User | `user` | Authenticated principal |

---

## 8. Endpoints

All paths are relative to the server root. The `/v1` prefix is mandatory.

### 8.1 System

| Method | Path | Description |
| :--- | :--- | :--- |
| `GET` | `/v1/health` | Liveness probe; returns `{ "status": "ok" }` |
| `GET` | `/v1/info` | Server identity, API version, supported spec versions, capabilities |

### 8.2 Authentication

| Method | Path | Description |
| :--- | :--- | :--- |
| `POST` | `/v1/auth/token` | Obtain access token |
| `GET` | `/v1/auth/me` | Current authenticated principal |
| `GET` | `/v1/auth/api-keys` | List API keys (admin) |
| `POST` | `/v1/auth/api-keys` | Create API key (admin) |
| `DELETE` | `/v1/auth/api-keys/{key_id}` | Revoke API key (admin) |

### 8.3 Templates

Templates store [RenderSpec](../renderspec/specification.md) documents.

| Method | Path | Description |
| :--- | :--- | :--- |
| `GET` | `/v1/templates` | List templates (paginated) |
| `POST` | `/v1/templates` | Create template from RenderSpec body |
| `GET` | `/v1/templates/{template_id}` | Retrieve template |
| `PUT` | `/v1/templates/{template_id}` | Replace template document |
| `PATCH` | `/v1/templates/{template_id}` | Partial update (metadata only) |
| `DELETE` | `/v1/templates/{template_id}` | Delete template |
| `POST` | `/v1/templates/{template_id}/validate` | Validate without persisting |

The `document` property on a Template resource contains the full RenderSpec object. The template `id` MUST equal `document.id`.

### 8.4 Stocks

Stocks store [StockSpec](../stockspec/specification.md) documents.

| Method | Path | Description |
| :--- | :--- | :--- |
| `GET` | `/v1/stocks` | List stocks (paginated) |
| `POST` | `/v1/stocks` | Create stock from StockSpec body |
| `GET` | `/v1/stocks/{stock_id}` | Retrieve stock |
| `PUT` | `/v1/stocks/{stock_id}` | Replace stock document |
| `PATCH` | `/v1/stocks/{stock_id}` | Partial update (metadata only) |
| `DELETE` | `/v1/stocks/{stock_id}` | Delete stock |

The stock `id` MUST equal `document.metadata.id`.

### 8.5 Calibrations

Calibrations store [CalibrationSpec](../calibrationspec/specification.md) profiles.

| Method | Path | Description |
| :--- | :--- | :--- |
| `GET` | `/v1/calibrations` | List calibration profiles (paginated) |
| `POST` | `/v1/calibrations` | Create calibration profile |
| `GET` | `/v1/calibrations/{calibration_id}` | Retrieve profile |
| `PUT` | `/v1/calibrations/{calibration_id}` | Replace profile |
| `PATCH` | `/v1/calibrations/{calibration_id}` | Partial update (metadata, `enabled`) |
| `DELETE` | `/v1/calibrations/{calibration_id}` | Delete profile |

The calibration `id` MUST equal `document.metadata.id`.

### 8.6 Assets

Assets are binary files referenced by RenderSpec `assets` and `fonts` registries.

| Method | Path | Description |
| :--- | :--- | :--- |
| `GET` | `/v1/assets` | List assets (paginated) |
| `POST` | `/v1/assets` | Upload asset (`multipart/form-data`) |
| `GET` | `/v1/assets/{asset_id}` | Retrieve asset metadata |
| `GET` | `/v1/assets/{asset_id}/content` | Download binary content |
| `DELETE` | `/v1/assets/{asset_id}` | Delete asset |

Upload request fields:

| Field | Type | Presence | Description |
| :--- | :--- | :--- | :--- |
| `file` | binary | **REQUIRED** | File content |
| `name` | string | OPTIONAL | Display name |
| `content_type` | string | OPTIONAL | MIME type hint |

Allowed content types: `image/png`, `image/jpeg`, `image/svg+xml`, `font/ttf`, `font/otf`, `application/octet-stream`.

Asset `id` values are server-generated opaque strings prefixed with `ast_`.

### 8.7 Render Jobs

Render jobs produce deterministic output from a RenderSpec input.

| Method | Path | Description |
| :--- | :--- | :--- |
| `GET` | `/v1/render-jobs` | List render jobs (paginated) |
| `POST` | `/v1/render-jobs` | Submit render job |
| `GET` | `/v1/render-jobs/{job_id}` | Retrieve job status |
| `DELETE` | `/v1/render-jobs/{job_id}` | Cancel pending job |
| `GET` | `/v1/render-jobs/{job_id}/output` | Download rendered output |

Submission body:

```json
{
  "template_id": "shipping-label",
  "stock_id": "avery-5160",
  "data": [{ "sku": "ABC-123", "name": "Widget" }],
  "output": {
    "format": "pdf",
    "dpi": 300
  }
}
```

Alternatively, inline RenderSpec:

```json
{
  "document": { "renderspec": "1.0", "...": "..." },
  "output": { "format": "pdf" }
}
```

Rules:

1. Exactly one of `template_id` or `document` MUST be provided.
2. When `stock_id` is provided, the server MUST build an effective RenderSpec using Section 9.2.2 (StockSpec translation and merge).
3. Supported output formats: `pdf`, `postscript`.
4. Job `id` values are opaque strings prefixed with `rnd_`.

Job status values: `queued`, `processing`, `completed`, `failed`, `cancelled`.

### 8.8 Print Jobs

Print jobs render and submit output to a physical printer.

| Method | Path | Description |
| :--- | :--- | :--- |
| `GET` | `/v1/print-jobs` | List print jobs (paginated) |
| `POST` | `/v1/print-jobs` | Submit print job |
| `GET` | `/v1/print-jobs/{job_id}` | Retrieve job status |
| `DELETE` | `/v1/print-jobs/{job_id}` | Cancel pending job |

Submission body:

```json
{
  "template_id": "shipping-label",
  "stock_id": "shipping-4x6",
  "printer_id": "warehouse-zebra",
  "calibration_id": "warehouse-zebra-shipping",
  "copies": 1,
  "data": [{ "tracking": "1Z999AA10123456784" }]
}
```

Rules:

1. `printer_id` MUST reference a discovered Printer resource.
2. When `calibration_id` is omitted, the server MUST select a calibration profile using CalibrationSpec profile selection rules.
3. When profile selection yields more than one enabled profile at the same precedence level, the server MUST reject the request with `422` and error code `ambiguous-calibration-profile` (Section 5.4). Clients MUST supply `calibration_id` to disambiguate.
4. Job `id` values are opaque strings prefixed with `prt_`.

Job status values: `queued`, `rendering`, `printing`, `completed`, `failed`, `cancelled`.

### 8.9 Printers

Printers represent discovered CUPS/IPP queues.

| Method | Path | Description |
| :--- | :--- | :--- |
| `GET` | `/v1/printers` | List discovered printers |
| `POST` | `/v1/printers/discover` | Refresh printer discovery |
| `GET` | `/v1/printers/{printer_id}` | Retrieve printer details |
| `GET` | `/v1/printers/{printer_id}/capabilities` | Retrieve printer capabilities |

Printer `id` MUST equal the CalibrationSpec `printer.identifier` when both exist.

---

## 9. Cross-Specification Integration

### 9.1 RenderSpec Consumption

The API MUST NOT accept rendering requests that bypass RenderSpec validation. All render and print pipelines MUST validate the effective RenderSpec document against [renderspec/schema.json](../renderspec/schema.json) before execution.

### 9.2 Stock Resolution

RenderSpec documents MAY embed a `stock` object directly. When a render or print job specifies `stock_id`, the server MUST:

1. Load the StockSpec document from the Stock resource.
2. Translate StockSpec geometry into RenderSpec form using the normative mapping in Section 9.2.1.
3. Merge the translated geometry into the **effective RenderSpec** used for the job.
4. Prefer explicit `stock_id` over any inline RenderSpec `stock` when both are present. Inline `stock` MUST be discarded after merge.

When `stock_id` is provided, the effective RenderSpec `page` object MUST be derived from StockSpec `page` even if the template document defines different page dimensions.

#### 9.2.1 StockSpec → RenderSpec Translation

This API defines the canonical translation from a [StockSpec](../stockspec/specification.md) document to the RenderSpec `page` and `stock` objects defined in [RenderSpec Section 5](../renderspec/specification.md). Implementations MUST NOT invent alternate field mappings.

**Page mapping** (effective RenderSpec root):

| RenderSpec field | StockSpec source |
| :--- | :--- |
| `page.width` | `page.width` |
| `page.height` | `page.height` |

**Stock mapping** (effective RenderSpec root):

| RenderSpec `stock` field | StockSpec source |
| :--- | :--- |
| `width` | `label.width` |
| `height` | `label.height` |
| `rows` | `grid.rows` |
| `columns` | `grid.columns` |
| `margin_left` | `margins.left` |
| `margin_top` | `margins.top` |
| `horizontal_pitch` | `pitch.horizontal` |
| `vertical_pitch` | `pitch.vertical` |

StockSpec fields without RenderSpec equivalents (`label.shape`, `label.corner_radius`, `printable_area`, `margins.right`, `margins.bottom`, `metadata`, `page.format`) MUST NOT appear in the translated RenderSpec. Renderers apply clipping using `stock.width` and `stock.height` only.

Translation MUST occur before RenderSpec schema validation of the effective document. If the StockSpec document is valid but translation produces values that fail RenderSpec validation, the server MUST return `422` with code `stock-translation-failed`.

#### 9.2.2 Effective Document Construction

Given a job with `template_id` or inline `document`, and optional `stock_id`:

1. Start from the template document or inline `document`.
2. If `stock_id` is present, load StockSpec and apply Section 9.2.1, replacing `page` and `stock`.
3. If `data` is provided on the job, set effective `data` to the job payload (overriding any template `data`).
4. Validate the effective document against [renderspec/schema.json](../renderspec/schema.json).
5. Pass the effective document to the renderer.

### 9.3 Resource Identity Mapping

Domain specifications use different identity field placements. API resources normalize identity as follows:

| Resource | API `id` source | Rule |
| :--- | :--- | :--- |
| Template | `document.id` | MUST equal RenderSpec root `id` on create and replace |
| Stock | `document.metadata.id` | MUST equal StockSpec `metadata.id` on create and replace |
| Calibration | `document.metadata.id` | MUST equal CalibrationSpec `metadata.id` on create and replace |
| Printer | `identifier` | MUST equal `printer.identifier` and CalibrationSpec `printer.identifier` |

On create, if the URL path ID (when used) or request body ID disagrees with the nested document ID, the server MUST return `409 Conflict`.

### 9.4 Calibration Application

Print jobs MUST apply CalibrationSpec transforms after layout resolution and before print submission, per [CalibrationSpec Section 7](../calibrationspec/specification.md#7-transform-application).

When `calibration_id` is omitted, profile selection MUST follow [CalibrationSpec Section 8](../calibrationspec/specification.md#8-printer-profile-selection). If selection fails due to ambiguity, the server MUST reject the job synchronously at submission time with error code `ambiguous-calibration-profile` (Section 5.4).

When `calibration_id` is provided, the server MUST use that profile exclusively and MUST NOT run automatic selection.

### 9.5 Asset References

RenderSpec `assets` and `fonts` entries MAY reference:

- API asset URIs: `https://{host}/v1/assets/{asset_id}/content`
- External HTTPS URLs
- Base64 data URIs

When storing templates, servers SHOULD rewrite uploaded assets to API asset URIs for portability.

---

## 10. Idempotency

Clients MAY supply an idempotency key on mutating requests:

```
Idempotency-Key: 7c9e6679-7425-40de-944b-e07fc1f90ae7
```

Supported on: `POST /v1/render-jobs`, `POST /v1/print-jobs`, `POST /v1/assets`.

When a duplicate key is received with the same request body within 24 hours, the server MUST return the original response with `200 OK` instead of creating a duplicate resource.

When the same key is reused with a different body, the server MUST return `409 Conflict`.

---

## 11. Rate Limiting

Servers MAY enforce rate limits. When limited, the response MUST be:

```
HTTP/1.1 429 Too Many Requests
Retry-After: 60
Content-Type: application/problem+json
```

Responses SHOULD include:

```
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1719408000
```

---

## 12. Examples

See the [examples/](./examples/) directory for request and response samples:

| File | Description |
| :--- | :--- |
| `create_render_job.json` | Render job submission with template and stock |
| `create_print_job.json` | Print job submission with calibration |
| `render_job_response.json` | Completed render job status |
| `template_list_response.json` | Paginated template list |
| `token_request.json` | Password grant token request |
| `validation_error.json` | Schema validation failure |
| `ambiguous_calibration_error.json` | Ambiguous calibration profile rejection |

---

## 13. OpenAPI Document

The authoritative machine-readable contract is [openapi.yaml](./openapi.yaml).

Schema identifier:

```
https://openlabelserver.org/schemas/openapi-v1.0.yaml
```

