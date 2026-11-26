"""RFC 9457 Problem Details for the `/v1` API (API Spec §5.1 to §5.3).

Every error the service returns is built here, so the media type, the type URI
table and the requirement that `status` repeats the HTTP status have one home.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

# API Spec §5.1: every error response uses this media type, whatever the client accepts.
MEDIA_TYPE = "application/problem+json"

# RFC 9457 §4.2.1: a problem with no more specific type is `about:blank`.
DEFAULT_TYPE = "about:blank"

# API Spec §5.2: the stable type URI for each status the specification names.
TYPE_URIS = {
    400: "https://openlabelserver.org/errors/bad-request",
    401: "https://openlabelserver.org/errors/unauthorized",
    403: "https://openlabelserver.org/errors/forbidden",
    404: "https://openlabelserver.org/errors/not-found",
    409: "https://openlabelserver.org/errors/conflict",
    422: "https://openlabelserver.org/errors/validation-error",
    429: "https://openlabelserver.org/errors/rate-limited",
    500: "https://openlabelserver.org/errors/internal-error",
    503: "https://openlabelserver.org/errors/service-unavailable",
}


def title_for(status: int) -> str:
    """Return the HTTP reason phrase, or a neutral title for an unknown status."""

    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "Error"


def problem(
    status: int,
    detail: str | None = None,
    *,
    instance: str | None = None,
    errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a Problem Details body whose `status` equals the HTTP status (AP-104)."""

    body: dict[str, Any] = {
        "type": TYPE_URIS.get(status, DEFAULT_TYPE),
        "title": title_for(status),
        "status": status,
    }
    if detail:
        body["detail"] = detail
    if instance:
        body["instance"] = instance
    if errors:
        body["errors"] = errors
    return body


def problem_response(
    request: Request,
    status: int,
    detail: str | None = None,
    *,
    errors: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    """Return a problem document for `request`; `instance` names the request path."""

    return JSONResponse(
        problem(status, detail, instance=request.url.path, errors=errors),
        status_code=status,
        media_type=MEDIA_TYPE,
    )
