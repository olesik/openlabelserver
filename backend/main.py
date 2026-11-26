"""FastAPI application serving the `/v1` REST API (API Spec Sections 3, 5 and 8).

The service exposes the two system endpoints today, `GET /v1/health` and
`GET /v1/info`. There is no persistence, authentication or job execution yet, so
the routes that need them are not registered and the capabilities the info
resource reports are empty.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend import problems

# API Spec §3.1: the URI major version is the compatibility boundary.
API_VERSION = "1.0"
# API Spec §3.2: the OpenAPI document carries the patch-level contract version.
CONTRACT_VERSION = "1.0.0"
SERVER_VERSION = "0.1.0"

# API Spec §3.3: the domain document versions the server accepts.
SPECIFICATIONS = {"renderspec": "1.0", "stockspec": "1.0", "calibrationspec": "1.0"}

# API Spec §8.1: capabilities the server offers. No render pipeline, printing or
# authentication exists yet, so the info resource claims none of them.
CAPABILITIES: dict[str, Any] = {"rendering": [], "printing": False, "authentication": False}

router = APIRouter(prefix="/v1")


@router.get("/health")
def read_health() -> dict[str, str]:
    """API §8.1: liveness probe. It needs no credentials and checks no dependency."""

    return {"status": "ok"}


@router.get("/info")
def read_info() -> dict[str, Any]:
    """Return API version, server version, specification versions and capabilities."""

    return {
        "api_version": API_VERSION,
        "server_version": SERVER_VERSION,
        "specifications": dict(SPECIFICATIONS),
        "capabilities": dict(CAPABILITIES),
    }


def _versioned(response: JSONResponse) -> JSONResponse:
    """Stamp the active API version (AP-102) on a response the middleware never sees."""

    response.headers["X-API-Version"] = API_VERSION
    return response


def create_app() -> FastAPI:
    """Build the application; a fresh instance keeps tests and conformance cases apart."""

    app = FastAPI(
        title="OpenLabelServer REST API",
        version=CONTRACT_VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
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
