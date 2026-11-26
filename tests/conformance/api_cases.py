"""Conformance checks that drive the REST API (`CP-API`).

The suite starts no server of its own: each check builds the FastAPI application
in-process and sends it ASGI requests, so the routes, middleware and error
handlers under test are the ones `backend/main.py` exposes.

`CP-API` is not claimed yet. `AP-102`, `AP-103`, `AP-104` and `AP-106` are the
requirements that are observable: the system endpoints, and the stateless
validate operation, whose `422` gives `AP-104` its second error case and
`AP-106` the field-level entries it asks for.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import create_app  # noqa: E402

MISSING_PATH = "/v1/no-such-resource"
VALIDATE_PATH = "/v1/templates/minimal-valid/validate"
VALID_RENDERSPEC = (
    ROOT / "tests" / "conformance" / "fixtures" / "renderspec" / "valid" / "minimal_valid.json"
)


def api_version_is_reported() -> tuple[bool, str]:
    """AP-102: responses carry `X-API-Version`, and `/v1/info` reports `api_version`."""

    client = TestClient(create_app())
    info = client.get("/v1/info")
    error = client.get(MISSING_PATH)
    body = info.json() if info.status_code == 200 else {}
    # API §3.1 fixes the version string; comparing it against the module constant
    # would only prove the constant agrees with itself.
    checks = {
        "GET /v1/info answers 200": info.status_code == 200,
        "the info resource reports api_version 1.0": body.get("api_version") == "1.0",
        "the success response carries X-API-Version": info.headers.get("x-api-version") == "1.0",
        "the error response carries X-API-Version": error.headers.get("x-api-version") == "1.0",
    }
    broken = [name for name, passed in checks.items() if not passed]
    if broken:
        return False, "failed: " + ", ".join(broken)
    return True, (
        f"/v1/info reports api_version {body['api_version']}, and X-API-Version is "
        f"1.0 on a 200 and on a {error.status_code} response"
    )


def health_reports_ok() -> tuple[bool, str]:
    """AP-103: `GET /v1/health` answers 200 with a JSON body whose `status` is `ok`."""

    client = TestClient(create_app())
    response = client.get("/v1/health")
    content_type = response.headers.get("content-type", "")
    body = response.json() if content_type.startswith("application/json") else None
    checks = {
        "GET /v1/health answers 200": response.status_code == 200,
        "the body is JSON": isinstance(body, dict),
        "the body reports status ok": isinstance(body, dict) and body.get("status") == "ok",
    }
    broken = [name for name, passed in checks.items() if not passed]
    if broken:
        return False, "failed: " + ", ".join(broken)
    return True, f"/v1/health answered {response.status_code} {json.dumps(body, sort_keys=True)}"


def error_responses_are_problem_documents() -> tuple[bool, str]:
    """AP-104: `404` and `422` errors are `application/problem+json` naming their status."""

    invalid = json.loads(VALID_RENDERSPEC.read_text(encoding="utf-8"))
    # A schema-invalid RenderSpec is what makes the `422` half of AP-104 observable.
    del invalid["page"]

    client = TestClient(create_app())
    responses = {
        404: client.get(MISSING_PATH),
        422: client.post(VALIDATE_PATH, json=invalid),
    }
    checks: dict[str, bool] = {}
    for status, response in responses.items():
        content_type = response.headers.get("content-type", "")
        body = response.json() if content_type.startswith("application/problem+json") else {}
        checks[f"the {status} response answers {status}"] = response.status_code == status
        checks[f"the {status} response uses application/problem+json"] = (
            content_type == "application/problem+json"
        )
        checks[f"the {status} body carries a type"] = bool(body.get("type"))
        checks[f"the {status} body carries a title"] = bool(body.get("title"))
        checks[f"the {status} body repeats the HTTP status"] = body.get("status") == status
    broken = [name for name, passed in checks.items() if not passed]
    if broken:
        return False, "failed: " + ", ".join(broken)
    return True, (
        "a 404 and a 422 each answered application/problem+json with a type, a title "
        "and a status equal to the HTTP status"
    )


def validation_errors_carry_field_and_message() -> tuple[bool, str]:
    """AP-106: a `422` lists `errors`, and every entry carries `field` and `message`."""

    invalid = json.loads(VALID_RENDERSPEC.read_text(encoding="utf-8"))
    # A schema-invalid RenderSpec is what makes a `422` reachable in the first place.
    del invalid["page"]

    response = TestClient(create_app()).post(VALIDATE_PATH, json=invalid)
    content_type = response.headers.get("content-type", "")
    body = response.json() if content_type.startswith("application/problem+json") else {}
    entries = body.get("errors") if isinstance(body, dict) else None
    entries = entries if isinstance(entries, list) else []
    checks = {
        "the submission answers 422": response.status_code == 422,
        "the body carries a non-empty errors array": bool(entries),
        "every entry carries a field and a message": all(
            isinstance(entry, dict)
            and isinstance(entry.get("field"), str)
            and isinstance(entry.get("message"), str)
            for entry in entries
        ),
    }
    broken = [name for name, passed in checks.items() if not passed]
    if broken:
        return False, "failed: " + ", ".join(broken)
    described = ", ".join(f"{entry['field']} ({entry['message']})" for entry in entries)
    return True, f"the 422 carried {len(entries)} error entry: {described}"


CHECKS = {
    "api_version_is_reported": api_version_is_reported,
    "health_reports_ok": health_reports_ok,
    "error_responses_are_problem_documents": error_responses_are_problem_documents,
    "validation_errors_carry_field_and_message": validation_errors_carry_field_and_message,
}
