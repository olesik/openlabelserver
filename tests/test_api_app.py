"""Tests for `backend/main.py`: `/v1` routing, the version header and RFC 9457 errors.

The responses are validated against the published OpenAPI component schemas, so a
change to the contract and a change to the service cannot drift apart.
"""

from __future__ import annotations

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

from backend import main  # noqa: E402
from scripts import validate_examples  # noqa: E402

OPENAPI = ROOT / "specs" / "api" / "openapi.yaml"


@pytest.fixture()
def client() -> Iterator[TestClient]:
    with TestClient(main.create_app()) as test_client:
        yield test_client


def _validator(schema_name: str) -> Any:
    """An OpenAPI component validator, resolved the way the example validator resolves it."""

    spec = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))
    return validate_examples.validator_for(schema_name, validate_examples.openapi_registry(spec))


def test_info_reports_versions_and_capabilities(client: TestClient) -> None:
    response = client.get("/v1/info")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["api_version"] == "1.0"
    assert body["server_version"] == main.SERVER_VERSION
    assert body["specifications"] == main.SPECIFICATIONS
    assert set(body["capabilities"]) == {"rendering", "printing", "authentication"}
    _validator("InfoResponse").validate(body)


def test_no_unversioned_route_answers(client: TestClient) -> None:
    for path in ("/info", "/templates"):
        assert client.get(path).status_code == 404, path
        assert client.post(path).status_code == 404, path


def test_every_response_carries_the_api_version(client: TestClient) -> None:
    for method, path, expected in (
        ("GET", "/v1/info", 200),
        ("GET", "/v1/missing", 404),
        ("PUT", "/v1/info", 405),
    ):
        response = client.request(method, path)
        assert response.status_code == expected, f"{method} {path}"
        assert response.headers["X-API-Version"] == "1.0", f"{method} {path}"


def test_unknown_path_is_a_problem_document(client: TestClient) -> None:
    response = client.get("/v1/missing")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["type"] == "https://openlabelserver.org/errors/not-found"
    assert body["title"] == "Not Found"
    assert body["status"] == 404
    assert body["instance"] == "/v1/missing"
    assert "detail" not in body, "the title already states the condition"
    _validator("ProblemDetails").validate(body)


def test_error_media_type_ignores_accept_json(client: TestClient) -> None:
    response = client.get("/v1/missing", headers={"Accept": "application/json"})

    assert response.headers["content-type"] == "application/problem+json"


def test_unsupported_method_is_a_problem_document(client: TestClient) -> None:
    response = client.put("/v1/info")

    assert response.status_code == 405
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    # API Spec §5.2 names no type for 405, so RFC 9457's `about:blank` applies.
    assert body["type"] == "about:blank"
    assert body["status"] == 405


def test_unexpected_failure_is_a_problem_document() -> None:
    app = main.create_app()

    @app.get("/v1/_failure")
    def fail() -> None:
        raise RuntimeError("boom")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/v1/_failure")

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["X-API-Version"] == "1.0"
    body = response.json()
    assert body["type"] == "https://openlabelserver.org/errors/internal-error"
    assert body["status"] == 500
