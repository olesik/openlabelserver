"""Tests for `backend/main.py`: `/v1` routing, the version header and problem documents.

Responses are checked against the published OpenAPI components and the tables of
the API specification, so the service and the contract cannot drift apart.
"""

from __future__ import annotations

import json
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
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

# API §8.3: the validate operation takes any path id and stores nothing to look up.
VALIDATE = "/v1/templates/minimal-valid/validate"
RENDER_DOCUMENT = (
    ROOT / "tests" / "conformance" / "fixtures" / "renderspec" / "valid" / "minimal_valid.json"
)

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


def _render_document() -> dict[str, Any]:
    return json.loads(RENDER_DOCUMENT.read_text(encoding="utf-8"))


def _free_port() -> int:
    """A port the kernel just released, for the server under test to claim."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _get_when_ready(
    process: subprocess.Popen[str], url: str, timeout: float = 30.0
) -> tuple[int, Any, Any]:
    """Poll `url` until the server answers, or fail with what the process said."""

    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            pytest.fail(f"the server exited with {process.returncode}: {process.stderr.read()}")
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return response.status, response.headers, json.loads(response.read())
        except urllib.error.URLError as exc:  # not listening yet
            last_error = exc
            time.sleep(0.2)
    pytest.fail(f"{url} did not answer within {timeout:.0f}s: {last_error}")


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


def test_health_reports_ok(client: TestClient) -> None:
    response = client.get("/v1/health")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"status": "ok"}
    assert response.headers["X-API-Version"] == "1.0"
    _validator("HealthResponse").validate(response.json())


def test_validate_accepts_a_document_that_matches_the_path_id(client: TestClient) -> None:
    # Nothing stores `minimal-valid`, so a 200 also shows the operation loads no template.
    response = client.post(VALIDATE, json=_render_document())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"valid": True}
    assert response.headers["X-API-Version"] == "1.0"
    _validator("ValidationSuccess").validate(response.json())


def test_validate_reports_schema_failures_as_validation_errors(client: TestClient) -> None:
    missing_page = _render_document()
    del missing_page["page"]
    zero_width = _render_document()
    zero_width["page"]["width"] = 0

    for document, (field, code) in (
        (missing_page, ("page", "required")),
        (zero_width, ("page.width", "exclusiveMinimum")),
    ):
        response = client.post(VALIDATE, json=document)

        assert response.status_code == 422
        assert response.headers["content-type"] == PROBLEM
        body = response.json()
        assert body["type"] == "https://openlabelserver.org/errors/validation-error"
        # API §5.3 publishes this title and a dotted path per failing field.
        assert body["title"] == "Validation Error"
        assert body["status"] == 422
        assert body["instance"] == VALIDATE
        entry = body["errors"][0]
        assert (entry["field"], entry["code"]) == (field, code)
        # API §5.3 makes `message` required; its type is the FieldError schema's business.
        assert entry["message"]
        _validator("ProblemDetails").validate(body)


def test_validate_rejects_a_document_whose_id_differs_from_the_path(client: TestClient) -> None:
    # RFC-0001: the path id is the identity the document is validated against.
    document = _render_document()
    document["id"] = "other-template"
    response = client.post(VALIDATE, json=document)

    assert response.status_code == 409
    assert response.headers["content-type"] == PROBLEM
    body = response.json()
    assert body["type"] == "https://openlabelserver.org/errors/conflict"
    assert body["status"] == 409
    assert "other-template" in body["detail"] and "minimal-valid" in body["detail"]
    assert "errors" not in body
    _validator("ProblemDetails").validate(body)


def test_validate_reports_malformed_json_as_a_bad_request(client: TestClient) -> None:
    # API §5.2: malformed JSON is a `400`, distinct from a well-formed invalid document.
    response = client.post(
        VALIDATE, content=b"{not json", headers={"content-type": "application/json"}
    )

    assert response.status_code == 400
    assert response.headers["content-type"] == PROBLEM
    body = response.json()
    assert body["type"] == "https://openlabelserver.org/errors/bad-request"
    assert body["status"] == 400


def test_an_unversioned_path_never_succeeds(client: TestClient) -> None:
    # AP-101: the version prefix is mandatory, so no unversioned path may answer.
    # `/health` is among them: the application serves the versioned route only, which
    # is why the app image's healthcheck probes `/v1/health`.
    for method in ("get", "post"):
        for path in ("/health", "/info", "/templates"):
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


def test_uvicorn_serves_the_entrypoint_route() -> None:
    """Smoke: `uvicorn backend.main:app`, the command the container runs, answers /v1/info.

    The in-process client never imports the application as a module path or runs it
    under an ASGI server, so this starts the real entrypoint on a loopback port.
    """

    port = _free_port()
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        status, headers, body = _get_when_ready(process, f"http://127.0.0.1:{port}/v1/info")
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=15)

    assert status == 200
    assert headers["Content-Type"].startswith("application/json")
    assert headers["X-API-Version"] == "1.0"
    assert body["api_version"] == "1.0"


def test_problem_types_are_the_published_ones() -> None:
    """API §5.2: the type the service returns is the one the specification names."""

    section = SPECIFICATION.read_text(encoding="utf-8").split("### 5.2 Standard Error Types")[1]
    published = {
        int(status): uri
        for status, uri in re.findall(r"^\| (\d{3}) \| `([^`]+)` \|", section, re.MULTILINE)
    }

    assert published, "the §5.2 table did not parse"
    assert problems.TYPE_URIS == published
