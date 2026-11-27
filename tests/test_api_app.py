"""Tests for `backend/main.py`: the system endpoints, the templates resource, the `/v1`
prefix, the version header and problem documents.

Responses are checked against the published OpenAPI components and the tables of
the API specification, so the service and the contract cannot drift apart.
"""

from __future__ import annotations

import hashlib
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
from urllib.parse import urlsplit

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
STOCK_DOCUMENT = (
    ROOT / "tests" / "conformance" / "fixtures" / "stockspec" / "valid" / "generic_3x7.json"
)
CALIBRATION_DOCUMENT = (
    ROOT / "tests" / "conformance" / "fixtures" / "calibrationspec" / "valid" / "profile.json"
)

# API Spec §3.3: the domain document versions the specification publishes.
SPECIFICATIONS = {"renderspec": "1.0", "stockspec": "1.0", "calibrationspec": "1.0"}

# API §8.3 to §8.5: the patch schema each PATCH publishes, and the schema the document
# a patch merges into has to satisfy.
PATCH_SCHEMAS = {
    "templates": "TemplatePatch",
    "stocks": "StockPatch",
    "calibrations": "CalibrationPatch",
}
DOMAIN_SCHEMAS = {
    "templates": ROOT / "specs" / "renderspec" / "schema.json",
    "stocks": ROOT / "specs" / "stockspec" / "schema.json",
    "calibrations": ROOT / "specs" / "calibrationspec" / "schema.json",
}


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


def test_templates_are_listed_as_an_empty_paginated_collection(client: TestClient) -> None:
    response = client.get("/v1/templates")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["X-API-Version"] == "1.0"
    body = response.json()
    # API §8.3: no operation stores a template, so the catalog is genuinely empty.
    assert body["object"] == "list"
    assert body["data"] == []
    # API §6.2: the envelope, with the §6.1 defaults.
    assert body["pagination"] == {
        "page": 1,
        "page_size": 20,
        "total_items": 0,
        "total_pages": 0,
        "has_next": False,
        "has_previous": False,
    }
    _validator("TemplateList").validate(body)


def test_templates_honor_the_pagination_parameters(client: TestClient) -> None:
    response = client.get("/v1/templates?page=3&page_size=50")

    assert response.status_code == 200
    body = response.json()
    # The requested page is echoed even past the last one, and total_pages is
    # ceil(total_items / page_size) over the same empty catalog.
    assert body["pagination"] == {
        "page": 3,
        "page_size": 50,
        "total_items": 0,
        "total_pages": 0,
        "has_next": False,
        "has_previous": True,
    }
    _validator("TemplateList").validate(body)


def test_templates_reject_a_page_parameter_outside_the_specification(
    client: TestClient,
) -> None:
    # API §6.1 bounds both parameters; §5.2 makes an invalid query parameter a 400.
    for query in ("page=0", "page=-1", "page=two", "page_size=0", "page_size=101"):
        response = client.get(f"/v1/templates?{query}")

        assert response.status_code == 400, query
        assert response.headers["content-type"] == PROBLEM, query
        body = response.json()
        assert body["type"] == "https://openlabelserver.org/errors/bad-request", query
        assert body["status"] == 400, query
        assert body["instance"] == "/v1/templates", query
    # The documented boundaries themselves are valid.
    for query in ("page=1", "page_size=1", "page_size=100"):
        assert client.get(f"/v1/templates?{query}").status_code == 200, query


def _document(template_id: str = "minimal-valid", name: str | None = None) -> dict[str, Any]:
    """The published valid fixture under another identity, for the storing endpoints."""

    document = _render_document()
    document["id"] = template_id
    if name is not None:
        document["name"] = name
    return document


def _stock_document(stock_id: str = "generic-3x7", name: str | None = None) -> dict[str, Any]:
    """The published valid StockSpec fixture under another identity."""

    document = json.loads(STOCK_DOCUMENT.read_text(encoding="utf-8"))
    document["metadata"]["id"] = stock_id
    if name is not None:
        document["metadata"]["name"] = name
    return document


def _calibration_document(
    calibration_id: str = "laser-sheet", name: str | None = None
) -> dict[str, Any]:
    """The published valid CalibrationSpec fixture under another identity."""

    document = json.loads(CALIBRATION_DOCUMENT.read_text(encoding="utf-8"))
    document["metadata"]["id"] = calibration_id
    if name is not None:
        document["metadata"]["name"] = name
    return document


def test_create_stores_the_template_and_returns_the_resource(client: TestClient) -> None:
    document = _document()
    response = client.post("/v1/templates", json=document)

    assert response.status_code == 201
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    # API §7.1 and §9.3: the resource id is the document's own id.
    assert (body["id"], body["object"]) == (document["id"], "template")
    assert body["document"] == document
    assert body["created_at"].endswith("Z")
    # `updated_at` is OPTIONAL (§7.1), and nothing has updated the document yet.
    assert "updated_at" not in body
    _validator("Template").validate(body)
    # The collection that was empty lists it, with the §6.2 arithmetic.
    listing = client.get("/v1/templates").json()
    assert listing["pagination"]["total_items"] == 1
    assert [item["id"] for item in listing["data"]] == [document["id"]]


def test_create_rejects_a_duplicate_id(client: TestClient) -> None:
    assert client.post("/v1/templates", json=_document()).status_code == 201
    duplicate = _document(name="Second Name")
    response = client.post("/v1/templates", json=duplicate)

    assert response.status_code == 409
    assert response.headers["content-type"] == PROBLEM
    body = response.json()
    assert body["type"] == "https://openlabelserver.org/errors/conflict"
    assert body["status"] == 409
    # AR-103 rejects the create; the stored document keeps its own content.
    stored = client.get("/v1/templates/minimal-valid").json()
    assert stored["document"]["name"] != "Second Name"


def test_create_rejects_an_invalid_document_and_stores_nothing(client: TestClient) -> None:
    document = _document()
    del document["page"]
    response = client.post("/v1/templates", json=document)

    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM
    entry = response.json()["errors"][0]
    assert (entry["field"], entry["code"]) == ("page", "required")
    # AR-106: a document that fails the schema is never persisted.
    assert client.get("/v1/templates/minimal-valid").status_code == 404


def test_retrieving_an_unknown_template_is_a_not_found(client: TestClient) -> None:
    response = client.get("/v1/templates/absent-template")

    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM
    body = response.json()
    assert body["type"] == "https://openlabelserver.org/errors/not-found"
    assert body["instance"] == "/v1/templates/absent-template"


def test_replace_updates_the_stored_document(client: TestClient) -> None:
    created = client.post("/v1/templates", json=_document()).json()
    replacement = _document(name="Replaced Name")
    replacement["page"]["width"] = 60.0
    response = client.put("/v1/templates/minimal-valid", json=replacement)

    assert response.status_code == 200
    body = response.json()
    assert body["document"] == replacement
    # §7.1: the creation time is the resource's, and the replace stamps the change.
    assert body["created_at"] == created["created_at"]
    assert body["updated_at"].endswith("Z")
    assert client.get("/v1/templates/minimal-valid").json() == body
    _validator("Template").validate(body)


def test_replace_rejects_a_document_naming_another_id(client: TestClient) -> None:
    created = client.post("/v1/templates", json=_document()).json()
    response = client.put("/v1/templates/other-template", json=_document())

    assert response.status_code == 409
    assert response.headers["content-type"] == PROBLEM
    assert response.json()["type"] == "https://openlabelserver.org/errors/conflict"
    # AR-102: the stored document is untouched.
    assert client.get("/v1/templates/minimal-valid").json() == created


def test_replace_of_an_unknown_template_is_a_not_found(client: TestClient) -> None:
    # The document names the path id, so the identity rule passes and existence decides.
    response = client.put("/v1/templates/absent-template", json=_document("absent-template"))

    assert response.status_code == 404
    assert response.json()["type"] == "https://openlabelserver.org/errors/not-found"


def test_patch_updates_the_document_metadata(client: TestClient) -> None:
    created = client.post("/v1/templates", json=_document()).json()
    response = client.patch(
        "/v1/templates/minimal-valid", json={"name": "Patched Name", "description": "A note."}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["document"]["name"] == "Patched Name"
    assert body["document"]["description"] == "A note."
    # The patch edits metadata only: the identity and the layout are the document's.
    assert body["document"]["id"] == created["document"]["id"]
    assert body["document"]["layers"] == created["document"]["layers"]
    assert body["updated_at"].endswith("Z")
    assert client.get("/v1/templates/minimal-valid").json() == body


def test_patch_rejects_metadata_that_breaks_the_document(client: TestClient) -> None:
    created = client.post("/v1/templates", json=_document()).json()
    response = client.patch("/v1/templates/minimal-valid", json={"name": 12})

    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM
    assert response.json()["errors"][0]["field"] == "name"
    # The patched document is validated as a whole, and a failure stores nothing.
    assert client.get("/v1/templates/minimal-valid").json() == created


def test_patch_with_nothing_to_change_returns_the_template(client: TestClient) -> None:
    created = client.post("/v1/templates", json=_document()).json()
    response = client.patch(
        "/v1/templates/minimal-valid", json={"name": created["document"]["name"]}
    )

    assert response.status_code == 200
    # §7.1: `updated_at` records a modification, so an unchanged document keeps none.
    assert response.json() == created


def test_delete_removes_the_template(client: TestClient) -> None:
    client.post("/v1/templates", json=_document())

    response = client.delete("/v1/templates/minimal-valid")

    assert response.status_code == 204
    assert response.content == b""
    assert client.get("/v1/templates/minimal-valid").status_code == 404
    # A second delete has nothing left to remove.
    assert client.delete("/v1/templates/minimal-valid").status_code == 404


def test_the_collection_pages_over_stored_templates(client: TestClient) -> None:
    for number in (1, 2, 3):
        document = _document(f"template-{number}", f"Template {number}")
        assert client.post("/v1/templates", json=document).status_code == 201

    page = client.get("/v1/templates?page=2&page_size=2").json()

    assert page["pagination"] == {
        "page": 2,
        "page_size": 2,
        "total_items": 3,
        "total_pages": 2,
        "has_next": False,
        "has_previous": True,
    }
    assert len(page["data"]) == 1
    _validator("TemplateList").validate(page)


def test_the_collection_sorts_and_filters(client: TestClient) -> None:
    # API §6.1 makes sort and filter collection parameters, so a stored catalog has to
    # honour them instead of returning every row whatever the request asked for.
    for template_id, name in (("zebra", "Zebra"), ("apple", "apple"), ("pie", "Apple pie")):
        assert client.post("/v1/templates", json=_document(template_id, name)).status_code == 201

    def names(query: str) -> list[str]:
        body = client.get(f"/v1/templates?{query}").json()
        return [item["document"]["name"] for item in body["data"]]

    assert names("sort=name") == ["Apple pie", "Zebra", "apple"]
    assert names("sort=-name") == ["apple", "Zebra", "Apple pie"]
    # The filter is a case-insensitive substring of the document name.
    assert names("filter=apple") == ["Apple pie", "apple"]
    assert names("filter=APPLE") == ["Apple pie", "apple"]
    # An undocumented sort field is an invalid query parameter, not a silent default.
    assert client.get("/v1/templates?sort=document").status_code == 400


def test_templates_survive_a_new_application_instance(tmp_path: Path) -> None:
    database = tmp_path / "templates.db"
    with TestClient(main.create_app(database)) as first:
        assert first.post("/v1/templates", json=_document()).status_code == 201

    # A second application on the same database is what a restart leaves the API with.
    with TestClient(main.create_app(database)) as second:
        response = second.get("/v1/templates/minimal-valid")

    assert response.status_code == 200
    assert response.json()["document"] == _document()


def test_paginated_response_links_the_first_and_next_pages(client: TestClient) -> None:
    for number in range(1, 6):
        document = _document(f"template-{number}")
        assert client.post("/v1/templates", json=document).status_code == 201

    page = client.get("/v1/templates?page=2&page_size=2")

    # API §6.3 publishes the relations in this order and this form.
    assert page.headers["link"] == (
        '</v1/templates?page=3&page_size=2>; rel="next", '
        '</v1/templates?page=1&page_size=2>; rel="first"'
    )
    following = client.get("/v1/templates?page=3&page_size=2").json()
    assert following["pagination"]["page"] == 3
    assert len(following["data"]) == 1


def test_pagination_links_keep_the_collection_query(client: TestClient) -> None:
    for number in range(1, 4):
        document = _document(f"template-{number}", f"Template {number}")
        assert client.post("/v1/templates", json=document).status_code == 201

    page = client.get("/v1/templates?page=1&page_size=2&filter=template&sort=name")

    # A next link that dropped the filter or the sort would leave the collection.
    assert page.headers["link"] == (
        '</v1/templates?page=2&page_size=2&sort=name&filter=template>; rel="next"'
    )


def test_a_single_page_collection_carries_no_link_header(client: TestClient) -> None:
    assert client.post("/v1/templates", json=_document()).status_code == 201

    # §6.3's relations name other pages, and a collection with one page has none.
    assert "link" not in client.get("/v1/templates").headers


def test_create_stores_the_stock_and_returns_the_resource(client: TestClient) -> None:
    document = _stock_document()
    response = client.post("/v1/stocks", json=document)

    assert response.status_code == 201
    body = response.json()
    # API §9.3: a stock's identity is `document.metadata.id`.
    assert (body["id"], body["object"]) == (document["metadata"]["id"], "stock")
    assert body["document"] == document
    assert body["created_at"].endswith("Z")
    assert "updated_at" not in body
    _validator("Stock").validate(body)
    listing = client.get("/v1/stocks").json()

    assert listing["pagination"]["total_items"] == 1
    assert [item["id"] for item in listing["data"]] == [document["metadata"]["id"]]


def test_create_rejects_a_duplicate_stock(client: TestClient) -> None:
    assert client.post("/v1/stocks", json=_stock_document()).status_code == 201
    response = client.post("/v1/stocks", json=_stock_document(name="Second Name"))

    assert response.status_code == 409
    assert response.headers["content-type"] == PROBLEM
    assert response.json()["type"] == "https://openlabelserver.org/errors/conflict"
    # AR-104 enforces catalog uniqueness; the stored metadata is still the first one.
    stored = client.get("/v1/stocks/generic-3x7").json()
    assert stored["document"]["metadata"]["name"] != "Second Name"


def test_create_rejects_an_invalid_stock_and_stores_nothing(client: TestClient) -> None:
    document = _stock_document()
    del document["pitch"]
    response = client.post("/v1/stocks", json=document)

    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM
    # §5.3's detail names the domain document that failed, not always a RenderSpec.
    assert response.json()["detail"] == "StockSpec document failed schema validation."
    assert response.json()["errors"][0]["field"] == "pitch"
    assert client.get("/v1/stocks/generic-3x7").status_code == 404


def test_replace_requires_the_stock_metadata_id_to_match_the_path(client: TestClient) -> None:
    created = client.post("/v1/stocks", json=_stock_document()).json()
    response = client.put("/v1/stocks/other-stock", json=_stock_document())

    assert response.status_code == 409
    assert response.headers["content-type"] == PROBLEM
    assert response.json()["type"] == "https://openlabelserver.org/errors/conflict"
    # AR-104: the stored document is untouched.
    assert client.get("/v1/stocks/generic-3x7").json() == created


def test_replace_updates_the_stored_stock(client: TestClient) -> None:
    created = client.post("/v1/stocks", json=_stock_document()).json()
    replacement = _stock_document()
    replacement["grid"]["rows"] = 6
    response = client.put("/v1/stocks/generic-3x7", json=replacement)

    assert response.status_code == 200
    body = response.json()
    assert body["document"] == replacement
    assert body["created_at"] == created["created_at"]
    assert body["updated_at"].endswith("Z")
    _validator("Stock").validate(body)


def test_an_unknown_stock_is_a_not_found(client: TestClient) -> None:
    # The document names the path id, so the identity rule passes and existence decides.
    unknown = _stock_document("absent-stock")

    assert client.get("/v1/stocks/absent-stock").status_code == 404
    assert client.put("/v1/stocks/absent-stock", json=unknown).status_code == 404
    assert client.delete("/v1/stocks/absent-stock").status_code == 404


def test_patch_updates_the_stock_metadata(client: TestClient) -> None:
    created = client.post("/v1/stocks", json=_stock_document()).json()
    response = client.patch(
        "/v1/stocks/generic-3x7",
        json={"name": "Patched", "description": "A4 sheet.", "tags": ["a4"]},
    )

    assert response.status_code == 200
    body = response.json()
    # `name`, `description` and `tags` are the fields `StockPatch` publishes, and all
    # three live in StockSpec `metadata`.
    assert body["document"]["metadata"]["name"] == "Patched"
    assert body["document"]["metadata"]["description"] == "A4 sheet."
    assert body["document"]["metadata"]["tags"] == ["a4"]
    # The patch edits metadata only: the identity and the geometry are the document's.
    assert body["document"]["metadata"]["id"] == "generic-3x7"
    assert body["document"]["grid"] == created["document"]["grid"]
    _validator("Stock").validate(body)
    # The merge is stored, not only answered: a patch that shared the stored metadata
    # dictionary would report the change while writing nothing.
    assert client.get("/v1/stocks/generic-3x7").json() == body


def test_the_stock_collection_sorts_and_filters(client: TestClient) -> None:
    for stock_id, name in (("zebra-stock", "Zebra Stock"), ("apple-stock", "apple stock")):
        assert client.post("/v1/stocks", json=_stock_document(stock_id, name)).status_code == 201

    def names(query: str) -> list[str]:
        body = client.get(f"/v1/stocks?{query}").json()
        return [item["document"]["metadata"]["name"] for item in body["data"]]

    assert names("sort=name") == ["Zebra Stock", "apple stock"]
    assert names("sort=-name") == ["apple stock", "Zebra Stock"]
    # The filter is a case-insensitive substring of `metadata.name`.
    assert names("filter=STOCK&sort=name") == ["Zebra Stock", "apple stock"]
    assert client.get("/v1/stocks?sort=document").status_code == 400


def test_create_stores_the_calibration_profile(client: TestClient) -> None:
    document = _calibration_document()
    response = client.post("/v1/calibrations", json=document)

    assert response.status_code == 201
    body = response.json()
    # API §9.3: a calibration's identity is `document.metadata.id` too.
    assert (body["id"], body["object"]) == (document["metadata"]["id"], "calibration")
    assert body["document"] == document
    _validator("Calibration").validate(body)


def test_calibration_conflicts_and_not_found_follow_the_stock_rules(client: TestClient) -> None:
    assert client.post("/v1/calibrations", json=_calibration_document()).status_code == 201
    duplicate = client.post("/v1/calibrations", json=_calibration_document())
    mismatch = client.put("/v1/calibrations/other-profile", json=_calibration_document())
    unknown = _calibration_document("absent-profile")

    # AR-104: catalog uniqueness and the §9.3 identity rule, then existence.
    assert duplicate.status_code == 409
    assert mismatch.status_code == 409
    assert mismatch.json()["type"] == "https://openlabelserver.org/errors/conflict"
    assert client.get("/v1/calibrations/absent-profile").status_code == 404
    assert client.put("/v1/calibrations/absent-profile", json=unknown).status_code == 404
    assert client.delete("/v1/calibrations/absent-profile").status_code == 404


def test_patch_toggles_the_calibration_and_the_collection_filters_by_printer(
    client: TestClient,
) -> None:
    assert client.post("/v1/calibrations", json=_calibration_document()).status_code == 201
    other = _calibration_document("other-profile")
    other["printer"]["identifier"] = "printer-b"
    assert client.post("/v1/calibrations", json=other).status_code == 201

    patched = client.patch(
        "/v1/calibrations/laser-sheet",
        json={"name": "Patched Profile", "description": "Laser offset.", "enabled": False},
    )

    assert patched.status_code == 200
    # `enabled` is a CalibrationSpec root property, and the other two `CalibrationPatch`
    # fields are metadata.
    assert patched.json()["document"]["enabled"] is False
    assert patched.json()["document"]["metadata"]["name"] == "Patched Profile"
    assert patched.json()["document"]["metadata"]["description"] == "Laser offset."
    _validator("Calibration").validate(patched.json())
    assert client.get("/v1/calibrations/laser-sheet").json() == patched.json()
    # `printer_id` is the collection filter OpenAPI publishes for this resource.
    filtered = client.get("/v1/calibrations?printer_id=printer-b").json()
    assert [item["id"] for item in filtered["data"]] == ["other-profile"]


def test_stocks_survive_a_new_application_instance(tmp_path: Path) -> None:
    database = tmp_path / "catalogs.db"
    with TestClient(main.create_app(database)) as first:
        assert first.post("/v1/stocks", json=_stock_document()).status_code == 201
        assert first.post("/v1/calibrations", json=_calibration_document()).status_code == 201

    with TestClient(main.create_app(database)) as second:
        stock = second.get("/v1/stocks/generic-3x7")
        calibration = second.get("/v1/calibrations/laser-sheet")

    assert stock.status_code == 200
    assert calibration.status_code == 200
    assert stock.json()["document"] == _stock_document()


def test_a_duplicate_create_leaves_the_database_writable(tmp_path: Path) -> None:
    database = tmp_path / "templates.db"
    with TestClient(main.create_app(database)) as first:
        assert first.post("/v1/templates", json=_document()).status_code == 201
        assert first.post("/v1/templates", json=_document()).status_code == 409
        # The rejected insert must not keep a write transaction open: a second
        # connection writes at once instead of waiting on the lock it never released.
        with TestClient(main.create_app(database)) as second:
            response = second.post("/v1/templates", json=_document("other-template"))

    assert response.status_code == 201


def test_create_reports_a_body_that_is_not_utf8_as_a_bad_request(client: TestClient) -> None:
    # API §5.2: a body that is not JSON is a `400`, and undecodable bytes never reach
    # the schema validator as a server error.
    response = client.post(
        "/v1/templates", content=b'{"id": "\xff"}', headers={"content-type": "application/json"}
    )

    assert response.status_code == 400
    assert response.headers["content-type"] == PROBLEM
    assert response.json()["type"] == "https://openlabelserver.org/errors/bad-request"


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


# API §8.6: a PNG signature and header, so the upload path moves bytes nothing has to
# decode — the asset operations store and serve a file, they do not read it.
PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 16


def _upload(
    client: TestClient,
    content: bytes = PNG_BYTES,
    filename: str = "artwork.png",
    media_type: str = "image/png",
    **fields: str,
) -> Any:
    """POST one file part to the assets collection, with any optional form fields."""

    return client.post(
        "/v1/assets", files={"file": (filename, content, media_type)}, data=fields
    )


def test_upload_stores_the_file_and_answers_the_asset(client: TestClient) -> None:
    response = _upload(client, name="Label artwork")

    assert response.status_code == 201
    body = response.json()
    # API §8.6: the id is server-generated, opaque and prefixed with `ast_`.
    assert re.fullmatch(r"ast_[a-zA-Z0-9_-]+", body["id"])
    assert body["name"] == "Label artwork"
    assert body["content_type"] == "image/png"
    assert body["size_bytes"] == len(PNG_BYTES)
    assert body["sha256"] == hashlib.sha256(PNG_BYTES).hexdigest()
    # API §9.5's URI form, built from the route that serves the bytes and the host.
    assert body["url"] == f"http://testserver/v1/assets/{body['id']}/content"
    assert body["created_at"].endswith("Z")
    _validator("Asset").validate(body)


def test_download_serves_the_uploaded_bytes_unchanged(client: TestClient) -> None:
    created = _upload(client).json()

    content = client.get(f"/v1/assets/{created['id']}/content")

    # AR-105: the download is the file that was uploaded, byte for byte.
    assert content.status_code == 200
    assert content.content == PNG_BYTES
    assert content.headers["content-type"] == "image/png"
    # The display name defaults to the uploaded filename when the field is omitted.
    assert created["name"] == "artwork.png"
    assert client.get(f"/v1/assets/{created['id']}").json() == created


def test_the_content_type_field_overrides_the_file_part(client: TestClient) -> None:
    created = _upload(client, content_type="application/octet-stream").json()

    # API §8.6 publishes `content_type` as the hint, so it decides what is served.
    assert created["content_type"] == "application/octet-stream"
    content = client.get(f"/v1/assets/{created['id']}/content")
    assert content.headers["content-type"] == "application/octet-stream"
    assert content.content == PNG_BYTES


def test_upload_rejects_a_content_type_the_specification_does_not_allow(
    client: TestClient,
) -> None:
    # The file part's own media type is what the §8.6 allowlist refuses here.
    part = _upload(client, filename="notes.gif", media_type="image/gif")
    # An unallowed hint is not rescued by the part declaring an allowed type.
    hint = _upload(client, content_type="image/webp")

    assert (part.status_code, hint.status_code) == (422, 422)
    assert part.headers["content-type"] == PROBLEM
    assert part.json()["type"] == "https://openlabelserver.org/errors/validation-error"
    # §5.3's entry names the value that was refused, on the field that carried it.
    assert part.json()["errors"][0]["field"] == "file"
    assert '"image/gif"' in part.json()["detail"]
    assert hint.json()["errors"][0]["field"] == "content_type"
    assert '"image/webp"' in hint.json()["detail"]


def test_upload_requires_the_file_field(client: TestClient) -> None:
    response = client.post("/v1/assets", data={"name": "No file"})

    # API §8.6 makes `file` the REQUIRED request field, and §5.3 makes the answer one
    # problem document with a field-level entry rather than the parser's own body.
    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM
    assert response.headers["X-API-Version"] == "1.0"
    assert response.json()["errors"][0]["field"] == "file"


def test_an_unknown_asset_is_not_found(client: TestClient) -> None:
    metadata = client.get("/v1/assets/ast_absent")
    content = client.get("/v1/assets/ast_absent/content")

    assert (metadata.status_code, content.status_code) == (404, 404)
    assert metadata.headers["content-type"] == PROBLEM
    assert content.json()["type"] == "https://openlabelserver.org/errors/not-found"


def test_each_upload_gets_its_own_opaque_id(client: TestClient) -> None:
    first = _upload(client).json()
    second = _upload(client).json()

    # The id names the upload, not the bytes: identical files are separate assets, and
    # neither id says anything about what it holds.
    assert first["id"] != second["id"]
    assert first["sha256"] == second["sha256"]


def test_assets_survive_a_new_application_instance(tmp_path: Path) -> None:
    database = tmp_path / "assets.db"
    with TestClient(main.create_app(database)) as first:
        asset_id = _upload(first).json()["id"]

    with TestClient(main.create_app(database)) as second:
        content = second.get(f"/v1/assets/{asset_id}/content")

    assert content.status_code == 200
    assert content.content == PNG_BYTES


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


def test_a_stored_template_names_an_uploaded_asset_by_its_api_uri(
    client: TestClient,
) -> None:
    logo = _upload(client).json()
    document = _document("portable-logo")
    document["assets"] = [
        {
            "id": "logo",
            "type": "png",
            "source": f"http://elsewhere.example:9999/v1/assets/{logo['id']}/content",
        }
    ]

    created = client.post("/v1/templates", json=document)
    stored = client.get("/v1/templates/portable-logo").json()["document"]["assets"][0]
    served = client.get(urlsplit(stored["source"]).path)

    # API §9.5: the stored template names the asset by the URI this host serves, not the
    # host the client uploaded through, and that URI answers the bytes that were uploaded.
    assert created.status_code == 201
    assert stored["source"] == logo["url"]
    assert (served.status_code, served.content) == (200, PNG_BYTES)


def test_the_other_spellings_of_an_uploaded_asset_name_the_same_uri(
    client: TestClient,
) -> None:
    image = _upload(client).json()
    font = _upload(
        client, content=b"\x00\x01\x00\x00", filename="acme.ttf", media_type="font/ttf"
    ).json()
    document = _document("portable-spellings")
    document["assets"] = [
        {"id": "path", "type": "png", "source": f"/v1/assets/{image['id']}/content"},
        {"id": "opaque", "type": "png", "source": image["id"]},
    ]
    document["fonts"] = [
        {
            "family": "Acme",
            "variants": [{"style": "normal", "weight": "normal", "source": font["id"]}],
        }
    ]

    assert client.post("/v1/templates", json=document).status_code == 201
    stored = client.get("/v1/templates/portable-spellings").json()["document"]

    # §9.5 fixes the stored form, not the spelling a client used to hand an upload back;
    # a font variant's `source` is the same reference in the same registry.
    assert [asset["source"] for asset in stored["assets"]] == [image["url"]] * 2
    assert stored["fonts"][0]["variants"][0]["source"] == font["url"]


def test_sources_that_name_no_upload_are_stored_as_sent(client: TestClient) -> None:
    document = _document("portable-others")
    document["assets"] = [
        {"id": "remote", "type": "svg", "source": "https://cdn.example.com/logo.svg"},
        {"id": "inline", "type": "png", "source": "data:image/png;base64,iVBORw0KGgo="},
        {"id": "local", "type": "png", "source": "assets/logo.png"},
        {"id": "gone", "type": "png", "source": "ast_never-uploaded"},
    ]

    assert client.post("/v1/templates", json=document).status_code == 201
    stored = client.get("/v1/templates/portable-others").json()["document"]

    # The other two §9.5 forms, a local path and an id nothing stored are the document's
    # own content: rewriting them would either change a reference the server does not own
    # or point at a URI that answers `404`.
    assert [asset["source"] for asset in stored["assets"]] == [
        asset["source"] for asset in document["assets"]
    ]


def test_replace_rewrites_too_and_a_stored_document_round_trips(
    client: TestClient,
) -> None:
    logo = _upload(client).json()
    document = _document("portable-replace")
    document["assets"] = [{"id": "logo", "type": "png", "source": logo["id"]}]
    assert client.post("/v1/templates", json=document).status_code == 201
    stored = client.get("/v1/templates/portable-replace").json()["document"]

    replaced = client.put("/v1/templates/portable-replace", json=stored)

    # A replace stores what a create stores, and a document read back and written again
    # is already in the published form, so its source does not move between writes.
    assert replaced.status_code == 200
    assert replaced.json()["document"]["assets"][0]["source"] == logo["url"]


def _declares(schema: dict[str, Any], location: str) -> bool:
    """Whether a domain schema declares `location`, dotted through nested objects."""

    for part in location.split("."):
        properties = schema.get("properties", {})
        if part not in properties:
            return False
        schema = properties[part]
    return True


def test_patch_fields_are_the_published_ones() -> None:
    """API §8.3 to §8.5: a PATCH merges its schema's fields where its document keeps them."""

    components = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))["components"]["schemas"]
    for table, fields in main.PATCH_FIELDS.items():
        published = components[PATCH_SCHEMAS[table]]["properties"]

        assert set(fields) == set(published), table
        domain = json.loads(DOMAIN_SCHEMAS[table].read_text(encoding="utf-8"))
        for location in fields.values():
            assert _declares(domain, location), (table, location)


def test_problem_types_are_the_published_ones() -> None:
    """API §5.2: the type the service returns is the one the specification names."""

    section = SPECIFICATION.read_text(encoding="utf-8").split("### 5.2 Standard Error Types")[1]
    published = {
        int(status): uri
        for status, uri in re.findall(r"^\| (\d{3}) \| `([^`]+)` \|", section, re.MULTILINE)
    }

    assert published, "the §5.2 table did not parse"
    assert problems.TYPE_URIS == published
