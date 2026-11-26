"""Conformance checks that drive the REST API (`CP-API`).

The suite starts no server of its own: each check builds the FastAPI application
in-process and sends it ASGI requests, so the routes, middleware and error
handlers under test are the ones `backend/main.py` exposes.

`CP-API` is not claimed yet. `AP-101` to `AP-106` are the requirements that are
observable: the `/v1` prefix on the one resource the service serves, the system
endpoints, the stateless validate operation, whose `422` gives `AP-104` its second
error case and `AP-106` the field-level entries it asks for, and the `type` URI of
each error the service emits, which is `AP-105` for the four statuses reachable
without an authentication layer.
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

# API Spec §5.2, restated rather than imported from `backend/problems.py`: importing
# the table the service builds its answers from would only prove it agrees with itself.
ERROR_TYPE_PREFIX = "https://openlabelserver.org/errors/"


def resource_uris_are_versioned() -> tuple[bool, str]:
    """AP-101: every resource URI is under `/v1`.

    The templates collection is not implemented, so the positive half of the
    requirement is observed on the resource the service does serve: the stateless
    validate operation answers under `/v1`. The same operation without the prefix,
    and the unversioned collection path the requirement names, must not answer a
    success status. Without those two the case would pass on a service that routed
    nothing at all, and a router mounted without its prefix would go unnoticed.
    """

    valid = json.loads(VALID_RENDERSPEC.read_text(encoding="utf-8"))
    client = TestClient(create_app())
    versioned = client.post(VALIDATE_PATH, json=valid)
    unversioned_collection = client.get("/templates")
    unversioned_operation = client.post("/templates/minimal-valid/validate", json=valid)
    checks = {
        "the validate operation answers 200 under /v1": versioned.status_code == 200,
        "an unversioned GET /templates is not a success response": not (
            200 <= unversioned_collection.status_code < 300
        ),
        "the validate path without /v1 is not a success response": not (
            200 <= unversioned_operation.status_code < 300
        ),
    }
    broken = [name for name, passed in checks.items() if not passed]
    if broken:
        return False, "failed: " + ", ".join(broken)
    return True, (
        f"/v1/templates/minimal-valid/validate answered {versioned.status_code}, "
        f"/templates answered {unversioned_collection.status_code} and the "
        f"unversioned validate path {unversioned_operation.status_code}"
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


def error_types_name_their_condition() -> tuple[bool, str]:
    """AP-105: each error's `type` is the §5.2 URI for the status it answers.

    The service reaches `400`, `404`, `409` and `422` today. `401`, `403`, `429`,
    `500` and `503` need the authentication, rate-limiting or rendering layers
    `GET /v1/info` still reports as absent, so this case asserts the four it can
    reach instead of claiming the rest.
    """

    valid = json.loads(VALID_RENDERSPEC.read_text(encoding="utf-8"))
    invalid = json.loads(VALID_RENDERSPEC.read_text(encoding="utf-8"))
    del invalid["page"]

    client = TestClient(create_app())
    # API §5.2: one fixture per status the service can answer, with the type slug
    # §5.2 publishes for it.
    fixtures = {
        400: (client.post(VALIDATE_PATH, content=b"{"), "bad-request"),
        404: (client.get(MISSING_PATH), "not-found"),
        409: (client.post("/v1/templates/another-template/validate", json=valid), "conflict"),
        422: (client.post(VALIDATE_PATH, json=invalid), "validation-error"),
    }
    checks: dict[str, bool] = {}
    for status, (response, slug) in fixtures.items():
        content_type = response.headers.get("content-type", "")
        body = response.json() if content_type.startswith("application/problem+json") else {}
        checks[f"the {status} fixture answers the §5.2 {slug} type"] = (
            response.status_code == status and body.get("type") == ERROR_TYPE_PREFIX + slug
        )
    broken = [name for name, passed in checks.items() if not passed]
    if broken:
        return False, "failed: " + ", ".join(broken)
    return True, "400, 404, 409 and 422 each carried the §5.2 type URI for its status"


CHECKS = {
    "resource_uris_are_versioned": resource_uris_are_versioned,
    "api_version_is_reported": api_version_is_reported,
    "health_reports_ok": health_reports_ok,
    "error_responses_are_problem_documents": error_responses_are_problem_documents,
    "validation_errors_carry_field_and_message": validation_errors_carry_field_and_message,
    "error_types_name_their_condition": error_types_name_their_condition,
}
