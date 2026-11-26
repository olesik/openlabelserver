"""FastAPI application serving the `/v1` REST API (API Spec Sections 3, 5 and 8).

The service exposes the two system endpoints today, `GET /v1/health` and
`GET /v1/info`, plus the stateless `POST /v1/templates/{template_id}/validate`.
There is no persistence, authentication or job execution yet, so the routes that
need them are not registered and the info resource claims no capability.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, FastAPI, Request
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
