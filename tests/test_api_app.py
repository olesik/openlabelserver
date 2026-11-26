"""Tests for `backend/main.py`: `/v1` routing, the version header and problem documents.

Responses are checked against the published OpenAPI components and the tables of
the API specification, so the service and the contract cannot drift apart.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import main, problems  # noqa: E402
from scripts import validate_examples  # noqa: E402

OPENAPI = ROOT / "specs" / "api" / "openapi.yaml"
SPECIFICATION = ROOT / "specs" / "api" / "specification.md"
PROBLEM = "application/problem+json"

# API Spec §3.3: the domain document versions the specification publishes.
SPECIFICATIONS = {"renderspec": "1.0", "stockspec": "1.0", "calibrationspec": "1.0"}


@pytest.fixture()
def client() -> Iterator[TestClient]:
    with TestClient(main.create_app()) as test_client:
        yield test_client


def _validator(schema_name: str) -> Any:
    """An OpenAPI component validator, resolved the way the example validator resolves it."""

    spec = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))
    return validate_examples.validator_for(schema_name, validate_examples.openapi_registry(spec))


def test_info_reports_the_published_versions(client: TestClient) -> None:
    response = client.get("/v1/info")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["api_version"] == "1.0"
    assert body["specifications"] == SPECIFICATIONS
    assert isinstance(body["server_version"], str) and body["server_version"]
    # The service offers no rendering, printing or authentication, so it must not
    # report a capability it cannot honour.
    assert body["capabilities"] == {"rendering": [], "printing": False, "authentication": False}
    _validator("InfoResponse").validate(body)


def test_an_unversioned_path_never_succeeds(client: TestClient) -> None:
    # AP-101: the version prefix is mandatory, so no unversioned path may answer.
    for method in ("get", "post"):
        for path in ("/info", "/templates"):
            response = getattr(client, method)(path)
            assert response.status_code >= 400, f"{method.upper()} {path}"


def test_every_response_carries_the_api_version(client: TestClient) -> None:
    for method, path, expected in (
        ("GET", "/v1/info", 200),
        ("GET", "/v1/missing", 404),
        ("PUT", "/v1/info", 405),
    ):
        response = client.request(method, path)
        assert response.status_code == expected, f"{method} {path}"
        assert response.headers["X-API-Version"] == "1.0", f"{method} {path}"


def test_an_unknown_path_is_a_problem_document(client: TestClient) -> None:
    response = client.get("/v1/missing")

    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM
    body = response.json()
    # API §5.2 fixes the type for 404; §5.1 requires the status to repeat the HTTP status.
    assert body["type"] == "https://openlabelserver.org/errors/not-found"
    assert body["status"] == 404
    assert isinstance(body["title"], str) and body["title"]
    assert body["instance"] == "/v1/missing"
    _validator("ProblemDetails").validate(body)


def test_an_error_ignores_accept_json(client: TestClient) -> None:
    # AP-115: errors are `problem+json` even when the client accepts `application/json`.
    response = client.get("/v1/missing", headers={"Accept": "application/json"})

    assert response.headers["content-type"] == PROBLEM


def test_an_unsupported_method_keeps_its_status(client: TestClient) -> None:
    response = client.put("/v1/info")

    assert response.status_code == 405
    assert response.headers["content-type"] == PROBLEM
    body = response.json()
    # API §5.2 names no type for 405, so RFC 9457's `about:blank` applies.
    assert body["type"] == "about:blank"
    assert body["status"] == 405


def test_an_unexpected_failure_is_a_problem_document() -> None:
    app = main.create_app()

    @app.get("/v1/_failure")
    def fail() -> None:
        raise RuntimeError("boom")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/v1/_failure")

    assert response.status_code == 500
    assert response.headers["content-type"] == PROBLEM
    assert response.headers["X-API-Version"] == "1.0"
    body = response.json()
    assert body["type"] == "https://openlabelserver.org/errors/internal-error"
    assert body["status"] == 500


def test_problem_types_are_the_published_ones() -> None:
    """API §5.2: the type the service returns is the one the specification names."""

    section = SPECIFICATION.read_text(encoding="utf-8").split("### 5.2 Standard Error Types")[1]
    published = {
        int(status): uri
        for status, uri in re.findall(r"^\| (\d{3}) \| `([^`]+)` \|", section, re.MULTILINE)
    }

    assert published, "the §5.2 table did not parse"
    assert problems.TYPE_URIS == published
