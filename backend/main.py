"""FastAPI application serving the `/v1` REST API (API Spec Sections 3, 5, 6 and 8).

The service exposes the two system endpoints today, `GET /v1/health` and
`GET /v1/info`, the paginated `GET /v1/templates` collection and the stateless
`POST /v1/templates/{template_id}/validate`. There is no persistence,
authentication or job execution yet: nothing stores a template, so the collection
lists an empty catalog, the routes that need storage are not registered, and the
info resource claims no capability.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend import problems, validation

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


@router.get("/templates")
def list_templates(request: Request) -> dict[str, Any]:
    """API §8.3 and §6: list the stored templates in the §6.2 pagination envelope.

    Nothing stores a template yet — `POST /v1/templates` is not implemented — so the
    catalog is empty and `data` is empty with it. The envelope, its arithmetic and the
    query bounds are the contract the persistence layer fills in; only the source of
    `data` and `total_items` changes when there is a store to read.
    """

    page = _page_parameter(request, "page", DEFAULT_PAGE)
    page_size = _page_parameter(request, "page_size", DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE)
    # §8.3 stores RenderSpec documents. No operation creates one, so there are none.
    catalog: list[dict[str, Any]] = []
    total_items = len(catalog)
    total_pages = (total_items + page_size - 1) // page_size
    start = (page - 1) * page_size
    return {
        "object": "list",
        "data": catalog[start : start + page_size],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_items": total_items,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_previous": page > 1,
        },
    }


@router.post("/templates/{template_id}/validate")
async def validate_template(template_id: str, request: Request) -> JSONResponse:
    """API §8.3 and RFC-0001: validate a submitted RenderSpec without storing anything.

    The path id is the identity the document is validated against, so a document
    that fails the schema is a `422` and one that names a different id is a `409`.
    Neither branch loads a template, which is why the operation never answers `404`.
    """

    try:
        document = json.loads(await request.body())
    except json.JSONDecodeError:
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


def create_app() -> FastAPI:
    """Build the application; a fresh instance keeps tests and conformance cases apart."""

    # The published contract is specs/api/openapi.yaml, so FastAPI's own schema and
    # documentation routes stay off: they would serve unversioned paths (API §3.1).
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
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
