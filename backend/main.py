"""FastAPI application serving the `/v1` REST API (API Spec Sections 3, 5, 6, 7 and 8).

The service exposes the two system endpoints, `GET /v1/health` and `GET /v1/info`,
the templates resource — the paginated collection, create, retrieve, replace,
metadata patch and delete — the same six operations for stocks and calibration
profiles, the asset upload, metadata and content operations, and the stateless
`POST /v1/templates/{template_id}/validate`. The three catalogs and the assets are
SQLite tables (`backend/storage.py`); there is no authentication or job execution
yet, so the routes that need those are not registered and the info resource claims
no capability.
"""

from __future__ import annotations

import copy
import json
import os
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend import problems, storage, validation

# API Spec §3.1: the URI major version is the compatibility boundary.
API_VERSION = "1.0"

router = APIRouter(prefix="/v1")


@router.get("/health")
def read_health() -> dict[str, str]:
    """API §8.1: liveness probe. It needs no credentials and checks no dependency."""

    return {"status": "ok"}


@router.get("/info")
def read_info() -> dict[str, Any]:
    """API §8.1: server identity, API version, supported specification versions and capabilities."""

    return {
        "api_version": API_VERSION,
        "server_version": "0.1.0",
        # API Spec §3.3: the domain document versions this server accepts.
        "specifications": {"renderspec": "1.0", "stockspec": "1.0", "calibrationspec": "1.0"},
        # API Spec §8.1: no render pipeline, printing or authentication exists yet,
        # so the server claims none of them.
        "capabilities": {"rendering": [], "printing": False, "authentication": False},
    }


# API §6.1: the page defaults and the page_size ceiling every collection shares.
DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# API §6.1: `sort` names a field with an optional `-` for descending. The default is
# resource-specific, and a catalog's own order is newest first, ties broken by id.
DEFAULT_SORT = "-created_at"


# API §6.1: what a collection can sort on, keyed by the name `sort` accepts.
SortFields = dict[str, Callable[[storage.StoredDocument], Any]]


def _at(document: dict[str, Any], location: str) -> Any:
    """The value a dotted `location` names, so a field is found where its schema keeps it."""

    for part in location.split("."):
        document = document[part]
    return document


def _sort_fields(name_location: str) -> SortFields:
    """The §6.1 sort fields the catalogs share: the identity, the timestamps, the name."""

    return {
        "id": lambda stored: stored.id,
        "created_at": lambda stored: stored.created_at,
        "updated_at": lambda stored: stored.updated_at or "",
        "name": lambda stored: _at(stored.document, name_location),
    }


# API §6.1: `sort=name` reaches the field each domain schema uses for a document's name.
SORT_FIELDS = {
    "templates": _sort_fields("name"),
    "stocks": _sort_fields("metadata.name"),
    "calibrations": _sort_fields("metadata.name"),
}

# API §8.3 to §8.5 and the `TemplatePatch`, `StockPatch` and `CalibrationPatch` schemas:
# the fields a patch body may carry, and where each domain schema keeps them.
PATCH_FIELDS = {
    "templates": {"name": "name", "description": "description"},
    "stocks": {
        "name": "metadata.name",
        "description": "metadata.description",
        "tags": "metadata.tags",
    },
    "calibrations": {
        "name": "metadata.name",
        "description": "metadata.description",
        "enabled": "enabled",
    },
}


def _page_parameter(request: Request, name: str, default: int, ceiling: int | None = None) -> int:
    """Read one API §6.1 query parameter, answering §5.2's `400` outside its range."""

    raw = request.query_params.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value < 1 or (ceiling is not None and value > ceiling):
        bound = f" between 1 and {ceiling}" if ceiling is not None else " of at least 1"
        raise HTTPException(
            status_code=400,
            detail=f'The "{name}" query parameter must be an integer{bound}.',
        )
    return value


def _store(request: Request, table: str) -> storage.DocumentStore:
    """The catalog this application was built with: its table name names it."""

    return request.app.state.catalogs[table]


async def _body_object(request: Request) -> dict[str, Any] | JSONResponse:
    """The request body as a JSON object, or the §5.2 `400` it earns."""

    try:
        body = json.loads(await request.body())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return problems.problem_response(request, 400, "The request body is not valid JSON.")
    if not isinstance(body, dict):
        return problems.problem_response(request, 400, "The request body must be a JSON object.")
    return body


def _invalid_document(request: Request, document: Any, schema: str) -> JSONResponse | None:
    """The §5.3 `422` for a document that fails the published schema, or `None` (AR-106)."""

    errors = validation.errors_for(document, schema)
    if not errors:
        return None
    return problems.problem_response(
        request,
        422,
        f"{validation.document_name(schema)} document failed schema validation.",
        title="Validation Error",
        errors=errors,
    )


def _missing_resource(request: Request, kind: str, resource_id: str) -> JSONResponse:
    """The §5.2 `404` for an id the catalog does not hold."""

    return problems.problem_response(
        request, 404, f'The {kind} "{resource_id}" does not exist.'
    )


def _pagination_links(request: Request, page: int, page_size: int, total_pages: int) -> str:
    """The API §6.3 `Link` header, naming only pages other than the one requested.

    The query keeps the caller's page size and any `sort` / `filter`, so following a
    link stays in the collection the request described.
    """

    def target(number: int) -> str:
        query = {"page": str(number), "page_size": str(page_size)}
        for name in ("sort", "filter"):
            value = request.query_params.get(name)
            if value:
                query[name] = value
        return f"{request.url.path}?{urlencode(query)}"

    relations = []
    if page < total_pages:
        relations.append(f'<{target(page + 1)}>; rel="next"')
    if page > 1:
        relations.append(f'<{target(1)}>; rel="first"')
    return ", ".join(relations)


def _identity_conflict(
    request: Request, document_id: str, parameter: str, path_id: str
) -> JSONResponse:
    """The §9.3 `409` for a document whose identity the request path contradicts."""

    return problems.problem_response(
        request,
        409,
        f'The document id "{document_id}" does not match the {parameter} "{path_id}".',
    )


def _duplicate(request: Request, kind: str) -> JSONResponse:
    """The §9.3 `409` for a create whose identity is already in the catalog."""

    return problems.problem_response(
        request, 409, f"A {kind} with this identifier already exists."
    )


def _patched(
    document: dict[str, Any], body: dict[str, Any], fields: dict[str, str]
) -> dict[str, Any]:
    """A deep copy of `document` with the patch body's fields written into it.

    Each field is written where its domain schema keeps it, so a RenderSpec's `name` is a
    root property while a StockSpec's is `metadata.name`, and a field the body omits is
    left alone. The copy is deep so the result compares by content with the stored
    document instead of sharing the nested objects it would otherwise change in place.
    """

    patched: dict[str, Any] = copy.deepcopy(document)
    for field, location in fields.items():
        if field not in body:
            continue
        *parents, leaf = location.split(".")
        target = _at(patched, ".".join(parents)) if parents else patched
        target[leaf] = body[field]
    return patched


async def _patch(
    request: Request, table: str, kind: str, schema: str, resource_id: str
) -> Any:
    """API §8.3 to §8.5: merge the published patch body into a stored document.

    The patched document is validated as a whole (`422`) and stored only then, and a
    patch that changes nothing keeps the resource's `updated_at` (§7.1), because that
    field records a modification.
    """

    body = await _body_object(request)
    if isinstance(body, JSONResponse):
        return body
    store = _store(request, table)
    stored = store.get(resource_id)
    if stored is None:
        return _missing_resource(request, kind, resource_id)
    document = _patched(stored.document, body, PATCH_FIELDS[table])
    if document == stored.document:
        return stored.resource()
    invalid = _invalid_document(request, document, schema)
    if invalid is not None:
        return invalid
    replaced = store.replace(resource_id, document)
    if replaced is None:  # the row was removed between the read and the write
        return _missing_resource(request, kind, resource_id)
    return replaced.resource()


def _collection(
    request: Request,
    response: Response,
    catalog: list[storage.StoredDocument],
    sort_fields: SortFields,
) -> dict[str, Any]:
    """API §6: a catalog as the §6.2 pagination envelope.

    `sort` names a field with an optional `-` for descending, and the id breaks every
    tie, so a page boundary can neither repeat nor skip a row. An unknown sort field
    is the §5.2 `400`, not a silent default.
    """

    page = _page_parameter(request, "page", DEFAULT_PAGE)
    page_size = _page_parameter(request, "page_size", DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE)
    sort = request.query_params.get("sort") or DEFAULT_SORT
    descending = sort.startswith("-")
    field = sort[1:] if descending else sort
    if field not in sort_fields:
        raise HTTPException(
            status_code=400,
            detail=f'The "sort" query parameter must name one of: {", ".join(sort_fields)}.',
        )
    catalog.sort(
        key=lambda stored: (sort_fields[field](stored), stored.id), reverse=descending
    )

    total_items = len(catalog)
    total_pages = (total_items + page_size - 1) // page_size
    start = (page - 1) * page_size
    links = _pagination_links(request, page, page_size, total_pages)
    if links:
        response.headers["Link"] = links
    return {
        "object": "list",
        "data": [stored.resource() for stored in catalog[start : start + page_size]],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_items": total_items,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_previous": page > 1,
        },
    }


@router.get("/templates")
def list_templates(request: Request, response: Response) -> dict[str, Any]:
    """API §8.3 and §6: the stored templates in the §6.2 pagination envelope.

    `filter` matches a case-insensitive substring of `document.name`; a RenderSpec
    carries no tag, so no template has one for the OpenAPI parameter's tag half to
    match.
    """

    catalog = _store(request, "templates").all()
    needle = request.query_params.get("filter")
    if needle:
        folded = needle.casefold()
        catalog = [
            stored for stored in catalog if folded in stored.document["name"].casefold()
        ]
    return _collection(request, response, catalog, SORT_FIELDS["templates"])


@router.post("/templates")
async def create_template(request: Request) -> Any:
    """API §8.3: create a template from a RenderSpec body, validated first (AR-106).

    The resource id is `document.id` (§9.3), so an id already in the catalog is a
    `409 Conflict` (AR-103) and an invalid document is a `422` that stores nothing.
    """

    body = await _body_object(request)
    if isinstance(body, JSONResponse):
        return body
    invalid = _invalid_document(request, body, "renderspec")
    if invalid is not None:
        return invalid
    stored = _store(request, "templates").insert(body["id"], body)
    if stored is None:
        return _duplicate(request, "template")
    return JSONResponse(stored.resource(), status_code=201)


@router.get("/templates/{template_id}")
def read_template(template_id: str, request: Request) -> Any:
    """API §8.3: retrieve a stored template, or the §5.2 `404`."""

    stored = _store(request, "templates").get(template_id)
    if stored is None:
        return _missing_resource(request, "template", template_id)
    return stored.resource()


@router.put("/templates/{template_id}")
async def replace_template(template_id: str, request: Request) -> Any:
    """API §8.3 and §9.3: replace the stored document, keeping its identity.

    The document is validated first (`422`), then its id is checked against the path
    (`409`, AR-102) and only then is the catalog asked for the row (`404`). Identity
    comes before existence so a document stored under one id cannot be written
    through another path, which is the pair AR-102 publishes.
    """

    body = await _body_object(request)
    if isinstance(body, JSONResponse):
        return body
    invalid = _invalid_document(request, body, "renderspec")
    if invalid is not None:
        return invalid
    document_id = body["id"]
    if document_id != template_id:
        return _identity_conflict(request, document_id, "template_id", template_id)
    stored = _store(request, "templates").replace(template_id, body)
    if stored is None:
        return _missing_resource(request, "template", template_id)
    return stored.resource()


@router.patch("/templates/{template_id}")
async def patch_template(template_id: str, request: Request) -> Any:
    """API §8.3: update the RenderSpec fields OpenAPI's `TemplatePatch` publishes."""

    return await _patch(request, "templates", "template", "renderspec", template_id)


@router.delete("/templates/{template_id}")
def delete_template(template_id: str, request: Request) -> Any:
    """API §8.3: delete a stored template, answering `204` or the §5.2 `404`."""

    if not _store(request, "templates").delete(template_id):
        return _missing_resource(request, "template", template_id)
    return Response(status_code=204)


@router.post("/templates/{template_id}/validate")
async def validate_template(template_id: str, request: Request) -> JSONResponse:
    """API §8.3 and RFC-0001: validate a submitted RenderSpec without storing anything.

    The path id is the identity the document is validated against, so a document
    that fails the schema is a `422` and one that names a different id is a `409`.
    Neither branch loads a template, which is why the operation never answers `404`.
    """

    try:
        document = json.loads(await request.body())
    except (json.JSONDecodeError, UnicodeDecodeError):
        # API §5.2: malformed JSON is a `400`, distinct from a well-formed invalid document.
        return problems.problem_response(request, 400, "The request body is not valid JSON.")

    # API §5.3 publishes the title, the detail and one entry per failing field.
    invalid = _invalid_document(request, document, "renderspec")
    if invalid is not None:
        return invalid
    # The schema requires `id`, so a document that reached here carries one.
    document_id = document["id"]
    if document_id != template_id:
        return _identity_conflict(request, document_id, "template_id", template_id)
    return JSONResponse({"valid": True})


@router.get("/stocks")
def list_stocks(request: Request, response: Response) -> dict[str, Any]:
    """API §8.4 and §6: the stored StockSpec documents in the §6.2 envelope.

    `filter` matches a case-insensitive substring of `document.metadata.name`, the
    StockSpec field that names a stock.
    """

    catalog = _store(request, "stocks").all()
    needle = request.query_params.get("filter")
    if needle:
        folded = needle.casefold()
        catalog = [
            stored
            for stored in catalog
            if folded in stored.document["metadata"]["name"].casefold()
        ]
    return _collection(request, response, catalog, SORT_FIELDS["stocks"])


@router.post("/stocks")
async def create_stock(request: Request) -> Any:
    """API §8.4, §9.3 and §7.1: create a stock from a StockSpec body.

    The resource id is `document.metadata.id`, so an id already in the catalog is a
    `409 Conflict` (AR-104) and an invalid document is a `422` that stores nothing.
    """

    body = await _body_object(request)
    if isinstance(body, JSONResponse):
        return body
    invalid = _invalid_document(request, body, "stockspec")
    if invalid is not None:
        return invalid
    stored = _store(request, "stocks").insert(body["metadata"]["id"], body)
    if stored is None:
        return _duplicate(request, "stock")
    return JSONResponse(stored.resource(), status_code=201)


@router.get("/stocks/{stock_id}")
def read_stock(stock_id: str, request: Request) -> Any:
    """API §8.4: retrieve a stored stock, or the §5.2 `404`."""

    stored = _store(request, "stocks").get(stock_id)
    if stored is None:
        return _missing_resource(request, "stock", stock_id)
    return stored.resource()


@router.put("/stocks/{stock_id}")
async def replace_stock(stock_id: str, request: Request) -> Any:
    """API §8.4 and §9.3: replace the stored StockSpec, keeping its identity.

    The document is validated first (`422`), then its metadata id is checked against
    the path (`409`, AR-104) and only then is the catalog asked for the row (`404`).
    """

    body = await _body_object(request)
    if isinstance(body, JSONResponse):
        return body
    invalid = _invalid_document(request, body, "stockspec")
    if invalid is not None:
        return invalid
    document_id = body["metadata"]["id"]
    if document_id != stock_id:
        return _identity_conflict(request, document_id, "stock_id", stock_id)
    stored = _store(request, "stocks").replace(stock_id, body)
    if stored is None:
        return _missing_resource(request, "stock", stock_id)
    return stored.resource()


@router.patch("/stocks/{stock_id}")
async def patch_stock(stock_id: str, request: Request) -> Any:
    """API §8.4: update the StockSpec metadata OpenAPI's `StockPatch` publishes."""

    return await _patch(request, "stocks", "stock", "stockspec", stock_id)


@router.delete("/stocks/{stock_id}")
def delete_stock(stock_id: str, request: Request) -> Any:
    """API §8.4: delete a stored stock, answering `204` or the §5.2 `404`."""

    if not _store(request, "stocks").delete(stock_id):
        return _missing_resource(request, "stock", stock_id)
    return Response(status_code=204)


@router.get("/calibrations")
def list_calibrations(request: Request, response: Response) -> dict[str, Any]:
    """API §8.5 and §6: the stored CalibrationSpec profiles in the §6.2 envelope.

    `printer_id` keeps the profiles whose `document.printer.identifier` is that
    printer, the filter OpenAPI publishes for the collection.
    """

    catalog = _store(request, "calibrations").all()
    printer_id = request.query_params.get("printer_id")
    if printer_id:
        catalog = [
            stored
            for stored in catalog
            if stored.document["printer"]["identifier"] == printer_id
        ]
    return _collection(request, response, catalog, SORT_FIELDS["calibrations"])


@router.post("/calibrations")
async def create_calibration(request: Request) -> Any:
    """API §8.5, §9.3 and §7.1: create a profile from a CalibrationSpec body.

    The resource id is `document.metadata.id`, so an id already in the catalog is a
    `409 Conflict` (AR-104) and an invalid document is a `422` that stores nothing.
    """

    body = await _body_object(request)
    if isinstance(body, JSONResponse):
        return body
    invalid = _invalid_document(request, body, "calibrationspec")
    if invalid is not None:
        return invalid
    stored = _store(request, "calibrations").insert(body["metadata"]["id"], body)
    if stored is None:
        return _duplicate(request, "calibration")
    return JSONResponse(stored.resource(), status_code=201)


@router.get("/calibrations/{calibration_id}")
def read_calibration(calibration_id: str, request: Request) -> Any:
    """API §8.5: retrieve a stored profile, or the §5.2 `404`."""

    stored = _store(request, "calibrations").get(calibration_id)
    if stored is None:
        return _missing_resource(request, "calibration", calibration_id)
    return stored.resource()


@router.put("/calibrations/{calibration_id}")
async def replace_calibration(calibration_id: str, request: Request) -> Any:
    """API §8.5 and §9.3: replace the stored profile, keeping its identity.

    The document is validated first (`422`), then its metadata id is checked against
    the path (`409`, AR-104) and only then is the catalog asked for the row (`404`).
    """

    body = await _body_object(request)
    if isinstance(body, JSONResponse):
        return body
    invalid = _invalid_document(request, body, "calibrationspec")
    if invalid is not None:
        return invalid
    document_id = body["metadata"]["id"]
    if document_id != calibration_id:
        return _identity_conflict(request, document_id, "calibration_id", calibration_id)
    stored = _store(request, "calibrations").replace(calibration_id, body)
    if stored is None:
        return _missing_resource(request, "calibration", calibration_id)
    return stored.resource()


@router.patch("/calibrations/{calibration_id}")
async def patch_calibration(calibration_id: str, request: Request) -> Any:
    """API §8.5: update the fields OpenAPI's `CalibrationPatch` publishes."""

    return await _patch(
        request, "calibrations", "calibration", "calibrationspec", calibration_id
    )


@router.delete("/calibrations/{calibration_id}")
def delete_calibration(calibration_id: str, request: Request) -> Any:
    """API §8.5: delete a stored profile, answering `204` or the §5.2 `404`."""

    if not _store(request, "calibrations").delete(calibration_id):
        return _missing_resource(request, "calibration", calibration_id)
    return Response(status_code=204)


# API §8.6: asset ids are server-generated opaque strings. `token_urlsafe` yields the
# `[A-Za-z0-9_-]` alphabet OpenAPI's `AssetId` pattern accepts.
ASSET_ID_PREFIX = "ast_"

# API §8.6: the content types an upload may declare, and so the ones a download serves.
ASSET_CONTENT_TYPES = (
    "application/octet-stream",
    "font/otf",
    "font/ttf",
    "image/jpeg",
    "image/png",
    "image/svg+xml",
)


def _assets(request: Request) -> storage.AssetStore:
    """The asset catalog this application was built with (API §8.6)."""

    return request.app.state.assets


def _asset_url(request: Request, asset_id: str) -> str:
    """The API asset URI API §9.5 publishes, resolved from the route that serves it."""

    return str(request.url_for("download_asset", asset_id=asset_id))


def _asset_content_type(upload: UploadFile, hint: str | None) -> str:
    """The type an upload declares: the `content_type` hint, else the file part's own.

    A part that names no type is the generic binary type §8.6 allows. Media types are
    case-insensitive and a part may carry parameters, so both are normalized away.
    """

    declared = hint or upload.content_type or "application/octet-stream"
    return declared.split(";", 1)[0].strip().lower()


@router.post("/assets")
async def upload_asset(
    request: Request,
    file: UploadFile = File(...),
    name: str | None = Form(None),
    content_type: str | None = Form(None),
) -> Any:
    """API §8.6: store an uploaded file and answer the `Asset` that describes it.

    `file` is the REQUIRED field, and the bytes are stored as sent, so the content
    operation hands back the file the client uploaded rather than a re-encoding.
    """

    declared = _asset_content_type(file, content_type)
    if declared not in ASSET_CONTENT_TYPES:
        # §5.3 names the invalid value: the hint field when the client sent one, and
        # otherwise the uploaded part whose own media type was refused.
        return problems.problem_response(
            request,
            422,
            f'The content type "{declared}" is not one API §8.6 allows.',
            title="Validation Error",
            errors=[
                {
                    "field": "content_type" if content_type else "file",
                    "message": "must be one of: " + ", ".join(ASSET_CONTENT_TYPES),
                }
            ],
        )
    content = await file.read()
    asset_id = ASSET_ID_PREFIX + secrets.token_urlsafe(16)
    stored = _assets(request).insert(
        asset_id, name or file.filename or asset_id, declared, content
    )
    return JSONResponse(stored.resource(_asset_url(request, asset_id)), status_code=201)


@router.get("/assets/{asset_id}")
def read_asset(asset_id: str, request: Request) -> Any:
    """API §8.6: retrieve an asset's metadata, or the §5.2 `404`."""

    stored = _assets(request).get(asset_id)
    if stored is None:
        return _missing_resource(request, "asset", asset_id)
    return stored.resource(_asset_url(request, asset_id))


@router.get("/assets/{asset_id}/content")
def download_asset(asset_id: str, request: Request) -> Any:
    """API §8.6: serve the stored bytes, unchanged and under their own media type."""

    stored = _assets(request).get(asset_id)
    if stored is None:
        return _missing_resource(request, "asset", asset_id)
    return Response(content=stored.content, media_type=stored.content_type)


def _versioned(response: JSONResponse) -> JSONResponse:
    """Stamp the active API version (AP-102) on a response the middleware never sees."""

    response.headers["X-API-Version"] = API_VERSION
    return response


def create_app(database: str | Path | None = None) -> FastAPI:
    """Build the application; a fresh instance keeps tests and conformance cases apart.

    `database` is the SQLite path the catalogs use; without it the path comes from
    `OPENLABEL_DATABASE`, and with neither the database is process-local, so stored
    documents outlive a request but not the process. The published contract is
    `specs/api/openapi.yaml`, so FastAPI's own schema and documentation routes stay
    off: they would serve unversioned paths (API §3.1).
    """

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    catalogs = storage.Database(
        database or os.environ.get(storage.DATABASE_ENV, storage.DEFAULT_DATABASE)
    )
    app.state.catalogs = {
        "templates": catalogs.store("templates", "template"),
        "stocks": catalogs.store("stocks", "stock"),
        "calibrations": catalogs.store("calibrations", "calibration"),
    }
    app.state.assets = catalogs.assets()
    app.include_router(router)

    @app.middleware("http")
    async def stamp_api_version(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        response.headers["X-API-Version"] = API_VERSION
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        # A multipart upload with no `file` field is rejected by the request parser before
        # the handler runs, so §5.3's field-level detail comes from its own report.
        errors = [
            {
                "field": ".".join(str(part) for part in error["loc"] if part != "body"),
                "message": error["msg"],
            }
            for error in exc.errors()
        ]
        return _versioned(
            problems.problem_response(
                request,
                422,
                "The request does not match the operation's published parameters.",
                title="Validation Error",
                errors=errors,
            )
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Starlette repeats the status phrase as the detail; the title already says it.
        detail = exc.detail if isinstance(exc.detail, str) else None
        if detail == problems.title_for(exc.status_code):
            detail = None
        return _versioned(problems.problem_response(request, exc.status_code, detail))

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        return _versioned(
            problems.problem_response(request, 500, "The server failed to complete the request.")
        )

    return app


app = create_app()
