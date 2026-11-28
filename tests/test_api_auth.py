"""Tests for `backend/auth.py` and the credential layer of `backend/main.py`.

API §4.1 lets a server run without authentication, §4.2 names the two schemes and
§4.6 the roles; these tests pin all three, the §4.7 challenge and the configuration
that enables them.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import auth, main  # noqa: E402

DOCUMENT = (
    ROOT / "tests" / "conformance" / "fixtures" / "renderspec" / "valid" / "minimal_valid.json"
)
PROBLEM = "application/problem+json"
CHALLENGE = 'Bearer realm="OpenLabelServer"'
UNAUTHORIZED = "https://openlabelserver.org/errors/unauthorized"
FORBIDDEN = "https://openlabelserver.org/errors/forbidden"

PRINCIPALS = {
    "principals": [
        {
            "id": "usr_admin",
            "username": "admin",
            "roles": ["admin"],
            "bearer_token": "admin-token",
            "api_key": "ols_admin_key",
        },
        {
            "id": "usr_operator",
            "username": "operator",
            "roles": ["operator"],
            "api_key": "ols_operator_key",
        },
        {
            "id": "usr_viewer",
            "username": "viewer",
            "roles": ["viewer"],
            "bearer_token": "viewer-token",
        },
    ]
}


def _render_document(template_id: str) -> dict:
    """The published valid RenderSpec under the identity a case stores."""

    document = json.loads(DOCUMENT.read_text(encoding="utf-8"))
    document["id"] = template_id
    return document


@pytest.fixture()
def authenticated(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A client whose application was configured with the three principals above."""

    monkeypatch.setenv(auth.AUTH_ENV, json.dumps(PRINCIPALS))
    with TestClient(main.create_app()) as client:
        yield client


def test_authentication_is_off_without_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(auth.AUTH_ENV, raising=False)
    client = TestClient(main.create_app())
    listing = client.get("/v1/templates")
    created = client.post("/v1/templates", json=_render_document("unauthenticated"))
    info = client.get("/v1/info").json()
    assert listing.status_code == 200
    assert created.status_code == 201
    assert info["capabilities"]["authentication"] is False


def test_missing_credentials_are_unauthorized(authenticated: TestClient) -> None:
    response = authenticated.get("/v1/templates")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == CHALLENGE
    assert response.headers["content-type"].startswith(PROBLEM)
    assert response.headers["x-api-version"] == main.API_VERSION
    body = response.json()
    assert body["type"] == UNAUTHORIZED
    assert body["status"] == 401


def test_invalid_credentials_are_unauthorized(authenticated: TestClient) -> None:
    bearer = authenticated.get("/v1/templates", headers={"Authorization": "Bearer wrong"})
    key = authenticated.get("/v1/templates", headers={"X-API-Key": "ols_wrong"})
    scheme = authenticated.get("/v1/templates", headers={"Authorization": "Basic abc"})
    empty = authenticated.get("/v1/templates", headers={"Authorization": "Bearer"})
    assert [response.status_code for response in (bearer, key, scheme, empty)] == [
        401,
        401,
        401,
        401,
    ]


def test_the_system_endpoints_answer_without_credentials(authenticated: TestClient) -> None:
    health = authenticated.get("/v1/health")
    info = authenticated.get("/v1/info")
    assert health.status_code == 200
    assert info.status_code == 200
    assert info.json()["capabilities"]["authentication"] is True


def test_a_bearer_token_authenticates_its_principal(authenticated: TestClient) -> None:
    response = authenticated.get(
        "/v1/templates", headers={"Authorization": "Bearer viewer-token"}
    )
    assert response.status_code == 200


def test_an_api_key_authenticates_its_principal(authenticated: TestClient) -> None:
    response = authenticated.get("/v1/templates", headers={"X-API-Key": "ols_operator_key"})
    assert response.status_code == 200


def test_the_bearer_token_is_evaluated_before_the_api_key(authenticated: TestClient) -> None:
    accepted = authenticated.get(
        "/v1/templates",
        headers={"Authorization": "Bearer viewer-token", "X-API-Key": "ols_absent"},
    )
    rejected = authenticated.get(
        "/v1/templates",
        headers={"Authorization": "Bearer absent", "X-API-Key": "ols_admin_key"},
    )
    assert accepted.status_code == 200
    assert rejected.status_code == 401


def test_a_viewer_may_read_but_not_create(authenticated: TestClient) -> None:
    headers = {"Authorization": "Bearer viewer-token"}
    created = authenticated.post(
        "/v1/templates", json=_render_document("viewer-template"), headers=headers
    )
    listing = authenticated.get("/v1/templates", headers=headers).json()
    assert created.status_code == 403
    assert created.headers["content-type"].startswith(PROBLEM)
    assert created.json()["type"] == FORBIDDEN
    assert listing["pagination"]["total_items"] == 0


def test_an_operator_may_read_but_not_write_templates(authenticated: TestClient) -> None:
    headers = {"X-API-Key": "ols_operator_key"}
    assert authenticated.get("/v1/stocks", headers=headers).status_code == 200
    created = authenticated.post(
        "/v1/templates", json=_render_document("operator-template"), headers=headers
    )
    assert created.status_code == 403
    assert created.json()["type"] == FORBIDDEN


def test_an_administrator_may_write(authenticated: TestClient) -> None:
    response = authenticated.post(
        "/v1/templates",
        json=_render_document("admin-template"),
        headers={"X-API-Key": "ols_admin_key"},
    )
    assert response.status_code == 201


def test_configuration_rejects_a_principal_without_credentials() -> None:
    config = {"principals": [{"id": "usr", "username": "usr", "roles": ["viewer"]}]}
    with pytest.raises(ValueError, match='needs a "bearer_token" or an "api_key"'):
        auth.Credentials.from_config(config)


def test_configuration_rejects_an_unknown_role() -> None:
    config = {
        "principals": [
            {"id": "usr", "username": "usr", "roles": ["owner"], "bearer_token": "token"}
        ]
    }
    with pytest.raises(ValueError, match="roles outside §4.6"):
        auth.Credentials.from_config(config)


def test_configuration_rejects_a_credential_two_principals_share() -> None:
    config = {
        "principals": [
            {"id": "one", "username": "one", "roles": ["viewer"], "bearer_token": "token"},
            {"id": "two", "username": "two", "roles": ["viewer"], "bearer_token": "token"},
        ]
    }
    with pytest.raises(ValueError, match="already configured"):
        auth.Credentials.from_config(config)


def test_configuration_rejects_an_api_key_without_the_published_prefix() -> None:
    config = {
        "principals": [
            {"id": "usr", "username": "usr", "roles": ["viewer"], "api_key": "key"}
        ]
    }
    with pytest.raises(ValueError, match='without the "ols_" prefix'):
        auth.Credentials.from_config(config)


def test_a_malformed_configuration_stops_the_application(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(auth.AUTH_ENV, "not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        main.create_app()
