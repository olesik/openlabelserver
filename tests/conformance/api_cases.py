"""Conformance checks that drive the REST API (`CP-API`).

The suite starts no server of its own: each check builds the FastAPI application
in-process and sends it ASGI requests, so the routes, middleware and error
handlers under test are the ones `backend/main.py` exposes.

`CP-API` is not claimed yet. `AP-102` is the first of its requirements to be
observable, because the service currently serves the system endpoint only.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import API_VERSION, create_app  # noqa: E402

MISSING_PATH = "/v1/no-such-resource"


def api_version_is_reported() -> tuple[bool, str]:
    """AP-102: responses carry `X-API-Version`, and `/v1/info` reports `api_version`."""

    client = TestClient(create_app())
    info = client.get("/v1/info")
    error = client.get(MISSING_PATH)
    body = info.json() if info.status_code == 200 else {}
    checks = {
        "GET /v1/info answers 200": info.status_code == 200,
        "the info resource reports api_version 1.0": body.get("api_version") == "1.0",
        "the reported version is the implemented one": body.get("api_version") == API_VERSION,
        "the success response carries X-API-Version": info.headers.get("x-api-version")
        == API_VERSION,
        "the error response carries X-API-Version": error.headers.get("x-api-version")
        == API_VERSION,
    }
    broken = [name for name, passed in checks.items() if not passed]
    if broken:
        return False, "failed: " + ", ".join(broken)
    return True, (
        f"/v1/info reports api_version {body['api_version']}, and X-API-Version is "
        f"{API_VERSION} on a 200 and on a {error.status_code} response"
    )


CHECKS = {"api_version_is_reported": api_version_is_reported}
