"""FastAPI application serving the `/v1` REST API (API Spec Sections 3 to 8).

The service exposes the two system endpoints, `GET /v1/health` and `GET /v1/info`,
the templates resource — the paginated collection, create, retrieve, replace,
metadata patch and delete — the same six operations for stocks and calibration
profiles, the assets resource — the paginated collection, upload, metadata, delete

The service exposes the two system endpoints, `GET /v1/health` and `GET /v1/info`,
the templates resource — the paginated collection, create, retrieve, replace,
metadata patch and delete — the same six operations for stocks and calibration
profiles, the assets resource — the paginated collection, upload, metadata, delete
and content operations — the stateless
`POST /v1/templates/{template_id}/validate`, and the render job resource — the
paginated collection, submission and status (API §8.7). A stored template names the
uploaded assets it references by the API asset URIs this host serves (API §9.5). The
three catalogs, the assets, the idempotency records and the render jobs are SQLite
tables (`backend/storage.py`); there is no job execution yet, so the routes that
need one are not registered. Authentication is off unless `OPENLABEL_AUTH`
configures principals (`backend/auth.py`), and then every operation but the system
endpoints needs a credential whose §4.6 role admits it.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend import auth, problems, storage, validation

# API Spec §3.1: the URI major version is the compatibility boundary.
API_VERSION = "1.0"

router = APIRouter(prefix="/v1")


@router.get("/health")
def read_health() -> dict[str, str]:
    """API §8.1: liveness probe. It needs no credentials and checks no dependency."""

    return {"status": "ok"}


@router.get("/info")
def read_info(request: Request) -> dict[str, Any]:
    """API §8.1: server identity, API version, supported specification versions and capabilities."""

    return {
        "api_version": API_VERSION,
        "server_version": "0.1.0",
        # API Spec §3.3: the domain document versions this server accepts.
        "specifications": {"renderspec": "1.0", "stockspec": "1.0", "calibrationspec": "1.0"},
        # API Spec §8.1: no render pipeline or printing exists yet, and the §4.2
        # credential layer runs only when it is configured; each is claimed when it is
        # there.
        "capabilities": {
            "rendering": [],
            "printing": False,
            "authentication": request.app.state.credentials is not None,
        },
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

    The query keeps the caller's page size, `sort` and the collection's filter parameter
    (`filter`, or `content_type` for the assets), so following a link stays in the
    collection the request described.
    """

    def target(number: int) -> str:
        query = {"page": str(number), "page_size": str(page_size)}
        for name in ("sort", "filter", "content_type"):
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


def _page(
    request: Request, response: Response, catalog: list[Any]
) -> tuple[list[Any], dict[str, Any]]:
    """API §6.1 to §6.3: the page this request names, its counts and its `Link` header."""

    page = _page_parameter(request, "page", DEFAULT_PAGE)
    page_size = _page_parameter(request, "page_size", DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE)
    total_pages = (len(catalog) + page_size - 1) // page_size
    links = _pagination_links(request, page, page_size, total_pages)
    if links:
        response.headers["Link"] = links
    start = (page - 1) * page_size
    return catalog[start : start + page_size], {
        "page": page,
        "page_size": page_size,
        "total_items": len(catalog),
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_previous": page > 1,
    }


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
    rows, pagination = _page(request, response, catalog)
    return {
        "object": "list",
        "data": [stored.resource() for stored in rows],
        "pagination": pagination,
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
    A valid document is stored with its uploaded assets named by API §9.5's URIs.
    """

    body = await _body_object(request)
    if isinstance(body, JSONResponse):
        return body
    invalid = _invalid_document(request, body, "renderspec")
    if invalid is not None:
        return invalid
    stored = _store(request, "templates").insert(body["id"], _portable(request, body))
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
    through another path, which is the pair AR-102 publishes. The replacement is
    stored with the asset references rewritten the way a create rewrites them.
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
    stored = _store(request, "templates").replace(template_id, _portable(request, body))
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


def _idempotency(request: Request) -> storage.IdempotencyStore:
    """The record of the responses `Idempotency-Key` headers already answered (§10)."""

    return request.app.state.idempotency


def _asset_url(request: Request, asset_id: str) -> str:
    """The API asset URI API §9.5 publishes, resolved from the route that serves it."""

    return str(request.url_for("download_asset", asset_id=asset_id))


# API §9.5: an uploaded asset as a client can hand it back — the opaque id the upload
# answered, the content path, or that path on whatever host the client uploaded through.
_ASSET_ID = re.compile(r"^ast_[A-Za-z0-9_-]+$")
_ASSET_URI = re.compile(r"^(?:https?://[^/]+)?/v1/assets/(ast_[A-Za-z0-9_-]+)/content$")


def _portable_source(request: Request, source: str) -> str:
    """An uploaded asset's reference as the URI this host serves (API §9.5)."""

    if _ASSET_ID.match(source):
        asset_id = source
    else:
        matched = _ASSET_URI.match(source)
        if matched is None:
            return source
        asset_id = matched.group(1)
    if _assets(request).get(asset_id) is None:
        return source
    return _asset_url(request, asset_id)


def _portable(request: Request, document: dict[str, Any]) -> dict[str, Any]:
    """API §9.5: name a RenderSpec's uploaded assets the way this API serves them.

    `assets[].source` and `fonts[].variants[].source` carry the reference the client
    sent unless it names a stored asset — by the opaque upload id, or by the content
    path on any host — because then the stored document can name that asset by the URI
    this deployment serves instead of the spelling the client happened to use. The
    other two §9.5 forms, an external HTTPS URL and a base64 data URI, are the
    document's own content, and a reference to an asset nothing stored is left alone
    rather than turned into a URI that would answer `404`.
    """

    for asset in document.get("assets") or []:
        asset["source"] = _portable_source(request, asset["source"])
    for font in document.get("fonts") or []:
        for variant in font.get("variants") or []:
            variant["source"] = _portable_source(request, variant["source"])
    return document

def _media_type(value: str) -> str:
    """A media type as §8.6 compares it: case-folded, with any parameters dropped."""

    return value.split(";", 1)[0].strip().lower()


def _asset_content_type(upload: UploadFile, hint: str | None) -> str:
    """The type an upload declares: the `content_type` hint, else the file part's own.

    A part that names no type is the generic binary type §8.6 allows.
    """

    return _media_type(hint or upload.content_type or "application/octet-stream")


def _upload_fingerprint(
    content: bytes, upload: UploadFile, name: str | None, hint: str | None
) -> str:
    """What API §10 compares two uploads by: the file and the fields that carry it.

    A retry sends the same parts, so the digest is the same even though the multipart
    boundary and the part headers around them differ between the two requests.
    """

    fields = json.dumps(
        [hashlib.sha256(content).hexdigest(), upload.filename, upload.content_type, name, hint]
    )
    return hashlib.sha256(fields.encode()).hexdigest()


def _replay(
    request: Request, recorded: storage.IdempotentRequest, fingerprint: str
) -> JSONResponse | None:
    """API §10: the `201` a repeated key already answered, or the `409` for a new body.

    `None` means the resource that key names is gone — it was deleted since — so the
    key is released and the caller uploads again rather than replay a dead asset.
    """

    if recorded.fingerprint != fingerprint:
        return problems.problem_response(
            request,
            409,
            "The Idempotency-Key header was already used with a different request body.",
        )
    stored = _assets(request).get(recorded.resource_id)
    if stored is None:
        _idempotency(request).forget(recorded.key)
        return None
    return JSONResponse(stored.resource(_asset_url(request, stored.id)), status_code=201)


@router.get("/assets")
def list_assets(request: Request, response: Response) -> dict[str, Any]:
    """API §8.6 and §6: the stored assets in the §6.2 envelope, newest first.

    `content_type` keeps the assets of one media type, the filter this collection
    publishes in place of §6.1's generic `filter`. Media types are case-insensitive,
    so the parameter is compared folded.
    """

    content_type = request.query_params.get("content_type")
    # A media type contains no space, and `+` in a query string decodes as one, so
    # `image/svg+xml` written without percent-encoding still names the SVG type.
    filtered = _media_type(content_type.replace(" ", "+")) if content_type else None
    catalog = _assets(request).all(filtered)
    rows, pagination = _page(request, response, catalog)
    return {
        "object": "list",
        "data": [asset.resource(_asset_url(request, asset.id)) for asset in rows],
        "pagination": pagination,
    }


@router.post("/assets")
async def upload_asset(
    request: Request,
    file: UploadFile = File(...),
    name: str | None = Form(None),
    content_type: str | None = Form(None),
) -> Any:
    """API §8.6 and §10: store an uploaded file and answer the `Asset` that describes it.

    `file` is the REQUIRED field, and the bytes are stored as sent, so the content
    operation hands back the file the client uploaded rather than a re-encoding. A
    repeated `Idempotency-Key` answers the upload it already stored instead of a second
    one, or the §5.2 `409` when the body under that key has changed.
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
    fingerprint = _upload_fingerprint(content, file, name, content_type)
    key = (request.headers.get("Idempotency-Key") or "").strip()
    if key:
        recorded = _idempotency(request).find(key)
        if recorded is not None:
            replayed = _replay(request, recorded, fingerprint)
            if replayed is not None:
                return replayed
    asset_id = ASSET_ID_PREFIX + secrets.token_urlsafe(16)
    stored = _assets(request).insert(
        asset_id, name or file.filename or asset_id, declared, content
    )
    if key:
        # A request that claimed the key while this one was uploading is the original, so
        # this upload is the duplicate of it: its row is dropped and the request answers
        # what the key already answered.
        claimed = _idempotency(request).record(key, fingerprint, asset_id)
        if claimed is not None:
            replayed = _replay(request, claimed, fingerprint)
            if replayed is not None:
                _assets(request).delete(asset_id)
                return replayed
    return JSONResponse(stored.resource(_asset_url(request, asset_id)), status_code=201)


@router.get("/assets/{asset_id}")
def read_asset(asset_id: str, request: Request) -> Any:
    """API §8.6: retrieve an asset's metadata, or the §5.2 `404`."""

    stored = _assets(request).get(asset_id)
    if stored is None:
        return _missing_resource(request, "asset", asset_id)
    return stored.resource(_asset_url(request, asset_id))


@router.delete("/assets/{asset_id}")
def delete_asset(asset_id: str, request: Request) -> Any:
    """API §8.6: delete a stored asset, answering `204` or the §5.2 `404`."""

    if not _assets(request).delete(asset_id):
        return _missing_resource(request, "asset", asset_id)
    return Response(status_code=204)


@router.get("/assets/{asset_id}/content")
def download_asset(asset_id: str, request: Request) -> Any:
    """API §8.6: serve the stored bytes, unchanged and under their own media type."""

    stored = _assets(request).get(asset_id)
    if stored is None:
        return _missing_resource(request, "asset", asset_id)
    return Response(content=stored.content, media_type=stored.content_type)


# API §8.7: render job ids are server-generated opaque strings. `token_urlsafe` yields
# the `[A-Za-z0-9_-]` alphabet OpenAPI's `RenderJobId` pattern accepts.
JOB_ID_PREFIX = "rnd_"

# API §8.7: the statuses a render job may hold. A print job's list also has `rendering`
# and `printing`, which a render job cannot reach, so neither is accepted here.
JOB_STATUSES = ("queued", "processing", "completed", "failed", "cancelled")

# OpenAPI's `OutputOptions`: the formats a submission may ask for, the dpi bounds the
# schema publishes, and the defaults it gives when a submission omits them.
OUTPUT_FORMATS = ("pdf", "postscript")
MIN_OUTPUT_DPI = 72
MAX_OUTPUT_DPI = 2400
DEFAULT_OUTPUT_FORMAT = "pdf"
DEFAULT_OUTPUT_DPI = 300

# OpenAPI's `RenderJobCreateRequest`: both reference fields are published with this
# pattern, so a value outside it is the request's own `422`.
_JOB_REFERENCE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _jobs(request: Request) -> storage.JobStore:
    """The render job store this application was built with (API §8.7)."""

    return request.app.state.jobs


def _field_error(
    request: Request, field: str, message: str, code: str | None = None
) -> JSONResponse:
    """The §5.3 `422` for one rejected field of a request body."""

    entry: dict[str, str] = {"field": field, "message": message}
    if code is not None:
        entry["code"] = code
    return problems.problem_response(
        request,
        422,
        f'The "{field}" field is not acceptable.',
        title="Validation Error",
        errors=[entry],
    )


def _job_output(request: Request, output: Any) -> JSONResponse | dict[str, Any]:
    """The `OutputOptions` a submission asks for, or the §5.3 `422` (AR-108).

    The defaults are the ones OpenAPI publishes, so a job that asks for neither still
    says what it will be rendered with.
    """

    if output is None:
        return {"format": DEFAULT_OUTPUT_FORMAT, "dpi": DEFAULT_OUTPUT_DPI}
    if not isinstance(output, dict):
        return _field_error(request, "output", "must be an object")
    format = output.get("format", DEFAULT_OUTPUT_FORMAT)
    dpi = output.get("dpi", DEFAULT_OUTPUT_DPI)
    if format not in OUTPUT_FORMATS:
        return _field_error(
            request, "output.format", "must be one of: " + ", ".join(OUTPUT_FORMATS)
        )
    whole = isinstance(dpi, int) and not isinstance(dpi, bool)
    if not whole or not MIN_OUTPUT_DPI <= dpi <= MAX_OUTPUT_DPI:
        return _field_error(
            request,
            "output.dpi",
            f"must be an integer between {MIN_OUTPUT_DPI} and {MAX_OUTPUT_DPI}",
        )
    return {"format": format, "dpi": dpi}


def _job_submission(request: Request, body: dict[str, Any]) -> JSONResponse | dict[str, Any]:
    """The submission API §8.7 accepts, or the problem document it earns.

    AR-107 is the rule §8.7 states first: exactly one of `template_id` and `document`
    names what to render, and neither or both is the §5.4 `missing-template-or-document`
    code, reported on `template_id` because that is the field the rule constrains and
    the code is what tells the cases apart. §5.4's `stock-not-found` is a stock the
    submission names that no catalog holds, and AR-108 is the `output` options.

    The submitted document is stored as sent, not validated here: an effective
    RenderSpec only exists once §9.2.2 has translated the stock into it, so §9.1's
    validation belongs to the execution that builds it — and nothing executes a job
    yet, so no submitted document bypasses it.
    """

    named = [name for name in ("template_id", "document") if body.get(name) is not None]
    if len(named) != 1:
        return _field_error(
            request,
            "template_id",
            'exactly one of "template_id" or "document" must be provided',
            code="missing-template-or-document",
        )
    for name in ("template_id", "stock_id"):
        value = body.get(name)
        if value is None:
            continue
        if not isinstance(value, str) or _JOB_REFERENCE.match(value) is None:
            return _field_error(request, name, "must match ^[a-zA-Z0-9_-]+$")
    document = body.get("document")
    if document is not None and not isinstance(document, dict):
        return _field_error(request, "document", "must be a RenderSpec object")
    data = body.get("data")
    if data is not None and not isinstance(data, list):
        return _field_error(request, "data", "must be an array of objects")
    stock_id = body.get("stock_id")
    if stock_id is not None and _store(request, "stocks").get(stock_id) is None:
        return _field_error(
            request, "stock_id", f'no stock "{stock_id}" is stored', code="stock-not-found"
        )
    output = _job_output(request, body.get("output"))
    if isinstance(output, JSONResponse):
        return output
    submission = {
        name: body[name] for name in ("template_id", "document", "data") if name in body
    }
    if stock_id is not None:
        submission["stock_id"] = stock_id
    submission["output"] = output
    return submission


@router.get("/render-jobs")
def list_render_jobs(request: Request, response: Response) -> dict[str, Any]:
    """API §8.7 and §6: the accepted jobs in the §6.2 envelope, newest submission first.

    `status` keeps the jobs holding one of §8.7's five statuses; any other value is the
    §5.2 `400` an invalid query parameter earns, the way an unknown `sort` is.
    """

    jobs = _jobs(request).all()
    status = request.query_params.get("status")
    if status:
        if status not in JOB_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=(
                    'The "status" query parameter must name one of: '
                    + ", ".join(JOB_STATUSES)
                    + "."
                ),
            )
        jobs = [job for job in jobs if job.status == status]
    jobs.sort(key=lambda job: (job.created_at, job.id), reverse=True)
    rows, pagination = _page(request, response, jobs)
    return {
        "object": "list",
        "data": [job.resource() for job in rows],
        "pagination": pagination,
    }


@router.post("/render-jobs")
async def create_render_job(request: Request) -> Any:
    """API §8.7: accept a render job and answer `202` with the `rnd_` job.

    The job is stored as `queued` with the options it was accepted under, and the
    section's opaque id is generated here. Nothing executes it yet, so a status read
    reports the status the submission left.
    """

    body = await _body_object(request)
    if isinstance(body, JSONResponse):
        return body
    submission = _job_submission(request, body)
    if isinstance(submission, JSONResponse):
        return submission
    job_id = JOB_ID_PREFIX + secrets.token_urlsafe(16)
    stored = _jobs(request).insert(job_id, submission)
    return JSONResponse(stored.resource(), status_code=202)


@router.get("/render-jobs/{job_id}")
def read_render_job(job_id: str, request: Request) -> Any:
    """API §8.7: the job's status, and on a failed job the §5.5 `error` it carries."""

    stored = _jobs(request).get(job_id)
    if stored is None:
        return _missing_resource(request, "render job", job_id)
    return stored.resource()


def _versioned(response: JSONResponse) -> JSONResponse:
    """Stamp the active API version (AP-102) on a response the middleware never sees."""

    response.headers["X-API-Version"] = API_VERSION
    return response


def create_app(database: str | Path | None = None) -> FastAPI:
    """Build the application; a fresh instance keeps tests and conformance cases apart.

    `database` is the SQLite path the catalogs use; without it the path comes from
    `OPENLABEL_DATABASE`, and with neither the database is process-local, so stored
    documents outlive a request but not the process. `OPENLABEL_AUTH` configures the
    §4.2 credentials, and without it the service is the §4.1 implicit administrator.
    The published contract is `specs/api/openapi.yaml`, so FastAPI's own schema and
    documentation routes stay off: they would serve unversioned paths (API §3.1).
    """

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    configured = os.environ.get(auth.AUTH_ENV)
    app.state.credentials = auth.Credentials.from_json(configured) if configured else None
    catalogs = storage.Database(
        database or os.environ.get(storage.DATABASE_ENV, storage.DEFAULT_DATABASE)
    )
    app.state.catalogs = {
        "templates": catalogs.store("templates", "template"),
        "stocks": catalogs.store("stocks", "stock"),
        "calibrations": catalogs.store("calibrations", "calibration"),
    }
    app.state.assets = catalogs.assets()
    app.state.jobs = catalogs.jobs()
    app.state.idempotency = catalogs.idempotency()
    app.include_router(router)

    # API §4.1 and §4.7: configured credentials gate every operation but §8.1's system
    # endpoints, and the §4.6 roles decide whether the method is admitted. The version
    # header is stamped by the middleware declared after this one, so a `401` or a `403`
    # carries it too.
    @app.middleware("http")
    async def require_credentials(request: Request, call_next: Any) -> Any:
        credentials = app.state.credentials
        if credentials is None or request.url.path in auth.PUBLIC_PATHS:
            return await call_next(request)
        principal = credentials.principal(
            request.headers.get(auth.BEARER_HEADER),
            request.headers.get(auth.API_KEY_HEADER),
        )
        if principal is None:
            response = problems.problem_response(
                request, 401, "The request carries no credentials this server accepts."
            )
            response.headers["WWW-Authenticate"] = auth.CHALLENGE
            return response
        if not principal.permits(auth.roles_for(request.method)):
            return problems.problem_response(
                request,
                403,
                "The authenticated principal holds no role this operation accepts.",
            )
        return await call_next(request)

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
