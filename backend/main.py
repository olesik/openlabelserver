"""FastAPI application serving the `/v1` REST API (API Spec Sections 3, 5 and 8).

The service exposes one system endpoint today, `GET /v1/info`. There is no
persistence, authentication or job execution yet, so the routes that need them
are not registered and the info resource claims no capability.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend import problems

# API Spec §3.1: the URI major version is the compatibility boundary.
API_VERSION = "1.0"

router = APIRouter(prefix="/v1")


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
