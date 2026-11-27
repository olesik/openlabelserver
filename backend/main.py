"""FastAPI application serving the `/v1` REST API (API Spec Sections 3, 5, 6, 7 and 8).

The service exposes the two system endpoints, `GET /v1/health` and `GET /v1/info`,
the templates resource — the paginated collection, create, retrieve, replace,
metadata patch and delete — and the stateless
`POST /v1/templates/{template_id}/validate`. Templates are stored in SQLite
(`backend/storage.py`); there is no authentication, asset storage or job execution
yet, so the routes that need those are not registered and the info resource claims
no capability.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
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
SORT_FIELDS = {
    "id": lambda template: template.id,
    "created_at": lambda template: template.created_at,
    "updated_at": lambda template: template.updated_at or "",
    "name": lambda template: template.document["name"],
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


def _store(request: Request) -> storage.TemplateStore:
    """The template catalog this application was built with."""

    return request.app.state.templates


async def _body_object(request: Request) -> dict[str, Any] | JSONResponse:
    """The request body as a JSON object, or the §5.2 `400` it earns."""

    try:
        body = json.loads(await request.body())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return problems.problem_response(request, 400, "The request body is not valid JSON.")
    if not isinstance(body, dict):
        return problems.problem_response(request, 400, "The request body must be a JSON object.")
    return body


def _invalid_document(request: Request, document: Any) -> JSONResponse | None:
    """The §5.3 `422` for a document that fails the published schema, or `None` (AR-106)."""

    errors = validation.errors_for(document)
    if not errors:
        return None
    return problems.problem_response(
        request,
        422,
        "RenderSpec document failed schema validation.",
        title="Validation Error",
        errors=errors,
    )


def _missing_template(request: Request, template_id: str) -> JSONResponse:
    """The §5.2 `404` for an id the catalog does not hold."""

    return problems.problem_response(
        request, 404, f'The template "{template_id}" does not exist.'
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


@router.get("/templates")
def list_templates(request: Request, response: Response) -> dict[str, Any]:
    """API §8.3 and §6: the stored templates in the §6.2 pagination envelope.

    `filter` matches a case-insensitive substring of `document.name`; a RenderSpec
    carries no tag, so no template has one for the OpenAPI parameter's tag half to
    match. The id breaks every sort tie, so a page boundary can neither repeat nor
    skip a row.
    """

    page = _page_parameter(request, "page", DEFAULT_PAGE)
    page_size = _page_parameter(request, "page_size", DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE)
    catalog = _store(request).all()

    needle = request.query_params.get("filter")
    if needle:
        folded = needle.casefold()
        catalog = [
            template for template in catalog if folded in template.document["name"].casefold()
        ]

    sort = request.query_params.get("sort") or DEFAULT_SORT
    descending = sort.startswith("-")
    field = sort[1:] if descending else sort
    if field not in SORT_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=f'The "sort" query parameter must name one of: {", ".join(SORT_FIELDS)}.',
        )
    catalog.sort(
        key=lambda template: (SORT_FIELDS[field](template), template.id), reverse=descending
    )

    total_items = len(catalog)
    total_pages = (total_items + page_size - 1) // page_size
    start = (page - 1) * page_size
    links = _pagination_links(request, page, page_size, total_pages)
    if links:
        response.headers["Link"] = links
    return {
        "object": "list",
        "data": [template.resource() for template in catalog[start : start + page_size]],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_items": total_items,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_previous": page > 1,
        },
    }


@router.post("/templates")
async def create_template(request: Request) -> Any:
    """API §8.3: create a template from a RenderSpec body, validated first (AR-106).

    The resource id is `document.id` (§9.3), so an id already in the catalog is a
    `409 Conflict` (AR-103) and an invalid document is a `422` that stores nothing.
    """

    body = await _body_object(request)
    if isinstance(body, JSONResponse):
        return body
    invalid = _invalid_document(request, body)
    if invalid is not None:
        return invalid
    stored = _store(request).insert(body)
    if stored is None:
        return problems.problem_response(
            request, 409, "A template with this identifier already exists."
        )
    return JSONResponse(stored.resource(), status_code=201)


@router.get("/templates/{template_id}")
def read_template(template_id: str, request: Request) -> Any:
    """API §8.3: retrieve a stored template, or the §5.2 `404`."""

    stored = _store(request).get(template_id)
    if stored is None:
        return _missing_template(request, template_id)
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
    invalid = _invalid_document(request, body)
    if invalid is not None:
        return invalid
    document_id = body["id"]
    if document_id != template_id:
        return problems.problem_response(
            request,
            409,
            f'The document id "{document_id}" does not match the template_id "{template_id}".',
        )
    stored = _store(request).replace(template_id, body)
    if stored is None:
        return _missing_template(request, template_id)
    return stored.resource()


@router.patch("/templates/{template_id}")
async def patch_template(template_id: str, request: Request) -> Any:
    """API §8.3: update the document's metadata fields, `name` and `description`.

    OpenAPI's `TemplatePatch` names those two fields, and both are RenderSpec root
    properties, so a patch edits the stored document instead of a parallel record.
    The patched document is validated as a whole (`422`) and stored only then.
    """

    body = await _body_object(request)
    if isinstance(body, JSONResponse):
        return body
    store = _store(request)
    stored = store.get(template_id)
    if stored is None:
        return _missing_template(request, template_id)
    document = dict(stored.document)
    for field in ("name", "description"):
        if field in body:
            document[field] = body[field]
    if document == stored.document:
        return stored.resource()
    invalid = _invalid_document(request, document)
    if invalid is not None:
        return invalid
    replaced = store.replace(template_id, document)
    if replaced is None:  # the row was removed between the read and the write
        return _missing_template(request, template_id)
    return replaced.resource()


@router.delete("/templates/{template_id}")
def delete_template(template_id: str, request: Request) -> Any:
    """API §8.3: delete a stored template, answering `204` or the §5.2 `404`."""

    if not _store(request).delete(template_id):
        return _missing_template(request, template_id)
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

    errors = validation.errors_for(document)
    if errors:
        # API §5.3 publishes the title, the detail and one entry per failing field.
        return problems.problem_response(
            request,
            422,
            "RenderSpec document failed schema validation.",
            title="Validation Error",
            errors=errors,
        )
    # The schema requires `id`, so a document that reached here carries one.
    document_id = document["id"]
    if document_id != template_id:
        return problems.problem_response(
            request,
            409,
            f'The document id "{document_id}" does not match the template_id "{template_id}".',
        )
    return JSONResponse({"valid": True})


def _versioned(response: JSONResponse) -> JSONResponse:
    """Stamp the active API version (AP-102) on a response the middleware never sees."""

    response.headers["X-API-Version"] = API_VERSION
    return response


def create_app(database: str | Path | None = None) -> FastAPI:
    """Build the application; a fresh instance keeps tests and conformance cases apart.

    `database` is the SQLite path the template store uses; without it the path comes
    from `OPENLABEL_DATABASE`, and with neither the store is process-local, so
    templates outlive a request but not the process. The published contract is
    `specs/api/openapi.yaml`, so FastAPI's own schema and documentation routes stay
    off: they would serve unversioned paths (API §3.1).
    """

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.templates = storage.TemplateStore(
        database or os.environ.get(storage.DATABASE_ENV, storage.DEFAULT_DATABASE)
    )
    app.include_router(router)

    @app.middleware("http")
    async def stamp_api_version(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        response.headers["X-API-Version"] = API_VERSION
        return response

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
