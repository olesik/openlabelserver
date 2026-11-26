"""RFC 9457 Problem Details for the `/v1` API (API Spec §5.1 to §5.3).

Every error response is built here, so the media type, the §5.2 type table and the
rule that `status` repeats the HTTP status have one home.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

# API Spec §5.1: every error response uses this media type, whatever the client accepts.
MEDIA_TYPE = "application/problem+json"

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
    """Return the HTTP reason phrase for `status`."""

    return HTTPStatus(status).phrase


def problem_response(request: Request, status: int, detail: str | None = None) -> JSONResponse:
    """Return a problem document for `request`, with `instance` naming its path."""

    body: dict[str, Any] = {
        # RFC 9457 §4.2.1: a status API §5.2 names no type for uses `about:blank`.
        "type": TYPE_URIS.get(status, "about:blank"),
        "title": title_for(status),
        "status": status,
        "instance": request.url.path,
    }
    if detail:
        body["detail"] = detail
    return JSONResponse(body, status_code=status, media_type=MEDIA_TYPE)
