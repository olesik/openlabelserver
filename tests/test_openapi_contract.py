"""The service checked against the published OpenAPI contract (API §13, B1 — API).

`specs/api/openapi.yaml` is the authoritative machine-readable contract, so the
service is held to it in three ways: an operation the service serves must be one the
contract publishes, an operation the contract publishes must be served or named as
deferred to the subsystem that will serve it, and every answer a served operation
gives must be one the operation documents — the status, the media type and a body
that validates against the published schema.

Response validation runs against the OpenAPI document itself (with the domain
schemas it references loaded from `specs/`), so the contract is the only description
of the expected bodies and this suite has none of its own to drift from.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.request import url2pathname

import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import main  # noqa: E402

# API §3.1 and §8: every path is served under the mandatory `/v1` prefix, while the
# OpenAPI document's operation paths are relative to its `/v1` server.
PREFIX = "/v1"
OPENAPI_PATH = ROOT / "specs" / "api" / "openapi.yaml"
OPENAPI_URI = OPENAPI_PATH.as_uri()
METHODS = ("get", "post", "put", "patch", "delete")
VERSION_HEADER = "X-API-Version"

# The operations the contract publishes that this service does not serve yet, each
# with the subsystem that will. A newly published operation fails the surface test
# until it is served or named here, so the gap cannot grow silently.
DEFERRED = {
    ("POST", "/auth/token"): "API §4.3 token issuance, outside the authentication item",
    ("GET", "/auth/me"): "API §4.2 principal route, with token issuance",
    ("GET", "/auth/api-keys"): "API §4.4 API-key management",
    ("POST", "/auth/api-keys"): "API §4.4 API-key management",
    ("DELETE", "/auth/api-keys/{key_id}"): "API §4.4 API-key management",
    ("DELETE", "/render-jobs/{job_id}"): "B4 — Jobs owns the job lifecycle",
    ("GET", "/render-jobs/{job_id}/output"): "B4 — Jobs owns rendering",
    ("GET", "/print-jobs"): "B4 — Jobs owns print job submission",
    ("POST", "/print-jobs"): "B4 — Jobs owns print job submission",
    ("GET", "/print-jobs/{job_id}"): "B4 — Jobs owns print job submission",
    ("DELETE", "/print-jobs/{job_id}"): "B4 — Jobs owns print job submission",
    ("GET", "/printers"): "Printing owns CUPS/IPP discovery",
    ("POST", "/printers/discover"): "Printing owns CUPS/IPP discovery",
    ("GET", "/printers/{printer_id}"): "Printing owns CUPS/IPP discovery",
    ("GET", "/printers/{printer_id}/capabilities"): "Printing owns CUPS/IPP discovery",
}

# API §8.6: a PNG signature and header, so the upload path moves bytes nothing has to
# interpret. The contract only says the content is binary.
PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 16

TEMPLATE_ID = "contract_template"
STOCK_ID = "contract_stock"
CALIBRATION_ID = "contract_calibration"


def _load(path: Path) -> Any:
    if path.suffix == ".yaml":
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    return json.loads(path.read_text(encoding="utf-8"))


SPEC = _load(OPENAPI_PATH)


def _retrieve(uri: str) -> Resource:
    """Load a schema reference from disk, e.g. `../renderspec/schema.json`."""

    path = Path(url2pathname(urlparse(uri).path))
    return Resource.from_contents(
        _load(path), default_specification=DRAFT202012
    )


REGISTRY = Registry(retrieve=_retrieve).with_resource(
    OPENAPI_URI, Resource.from_contents(SPEC, default_specification=DRAFT202012)
)


def _example(kind: str, name: str) -> dict[str, Any]:
    return _load(ROOT / "specs" / kind / "examples" / name)


def _published() -> set[tuple[str, str]]:
    """Every operation the contract publishes, as (method, path without the prefix)."""

    return {
        (method.upper(), path)
        for path, item in SPEC["paths"].items()
        for method in item
        if method in METHODS
    }


def _served() -> set[tuple[str, str]]:
    """Every operation the service routes, in the contract's own spelling."""

    return {
        (method.upper(), route.path[len(PREFIX) :])
        for route in main.router.routes
        if route.path.startswith(PREFIX)
        for method in route.methods
        if method.lower() in METHODS
    }


def _published_path(path: str) -> str:
    """The published path a concrete one names, e.g. /templates/abc → /templates/{template_id}."""

    segments = path.split("?")[0].split("/")
    for candidate in SPEC["paths"]:
        parts = candidate.split("/")
        if len(parts) != len(segments):
            continue
        if all(part.startswith("{") or part == segment for part, segment in zip(parts, segments)):
            return candidate
    raise AssertionError(f"{path} is not a path the contract publishes")


def _operation(method: str, path: str) -> dict[str, Any]:
    return SPEC["paths"][_published_path(path)][method.lower()]


def _response_document(operation: dict[str, Any], status: int) -> dict[str, Any]:
    """The response object the operation documents for `status`."""

    documented = operation["responses"]
    key = str(status)
    assert key in documented or "default" in documented, (
        f"the operation documents {sorted(documented)} but answered {key}"
    )
    document = documented.get(key, documented.get("default"))
    if "$ref" in document:
        resolved = REGISTRY.resolver(base_uri=OPENAPI_URI).lookup(document["$ref"])
        return resolved.contents
    return document


def _validator(schema: dict[str, Any]) -> Draft202012Validator:
    """A validator for a schema taken from the published document.

    A `$ref` is made absolute against the OpenAPI document first, so both a reference
    to one of its components and one to a domain schema beside it resolve through the
    registry rather than against the fragment's own empty base.
    """

    if "$ref" in schema:
        return Draft202012Validator(
            {"$ref": urljoin(OPENAPI_URI, schema["$ref"])}, registry=REGISTRY
        )
    return Draft202012Validator(schema, registry=REGISTRY)


def _check(client: TestClient, method: str, path: str, **kwargs: Any) -> Any:
    """Call one operation and hold its answer to the contract; return the response."""

    response = client.request(method, path, **kwargs)
    operation = _operation(method, path[len(PREFIX) :])
    where = f"{method} {path} answered {response.status_code}"

    # API §3.2: the version header is on every response.
    assert response.headers.get(VERSION_HEADER) == main.API_VERSION, (
        f"{where} without {VERSION_HEADER}: {main.API_VERSION}"
    )

    document = _response_document(operation, response.status_code)
    media = response.headers.get("content-type", "").split(";")[0]
    if not response.content:
        assert not document.get("content"), (
            f"{where} with no body, but the contract documents "
            f"{sorted(document.get('content', {}))}"
        )
        return response

    documented = document.get("content", {})
    assert media in documented, (
        f"{where} as {media!r}, but the contract documents {sorted(documented)}"
    )
    schema = documented[media].get("schema")
    if schema is None or not media.endswith("json"):
        return response

    errors = sorted(_validator(schema).iter_errors(response.json()), key=str)
    assert not errors, (
        f"{where} with a body the published {media} schema rejects: "
        f"{errors[0].message} at {list(errors[0].path)}"
    )
    return response


def test_every_operation_the_service_serves_is_published() -> None:
    unpublished = _served() - _published()

    assert not unpublished, (
        "the service routes operations the contract does not publish: "
        f"{sorted(unpublished)}"
    )


def test_every_published_operation_is_served_or_declared_deferred() -> None:
    unaccounted = _published() - (_served() | set(DEFERRED))

    assert not unaccounted, (
        "the contract publishes operations the service neither serves nor defers: "
        f"{sorted(unaccounted)}"
    )


def test_no_operation_is_both_served_and_declared_deferred() -> None:
    stale = _served() & set(DEFERRED)

    assert not stale, f"the service serves operations it still declares deferred: {sorted(stale)}"


def _parameters(operation: dict[str, Any], path: str) -> list[dict[str, Any]]:
    """The operation's parameters, with the path item's own and every `$ref` resolved."""

    declared = list(SPEC["paths"][path].get("parameters", [])) + list(
        operation.get("parameters", [])
    )
    resolved = []
    for parameter in declared:
        if "$ref" in parameter:
            reference = urljoin(OPENAPI_URI, parameter["$ref"])
            parameter = REGISTRY.resolver().lookup(reference).contents
        resolved.append(parameter)
    return resolved


def test_operations_that_take_input_document_a_bad_request() -> None:
    """API §5.2: a malformed body or query parameter is a documented `400`."""

    missing = []
    for method, path in sorted(_served()):
        operation = _operation(method, path)
        takes_query = any(
            parameter.get("in") == "query" for parameter in _parameters(operation, path)
        )
        takes_json = "application/json" in operation.get("requestBody", {}).get("content", {})
        if (takes_query or takes_json) and "400" not in operation["responses"]:
            missing.append(f"{method} {path}")

    assert not missing, (
        "these operations validate input but do not publish the §5.2 400: "
        f"{', '.join(missing)}"
    )


def test_every_served_operation_answers_as_published() -> None:
    """Walk each served operation once, validating every answer it gives."""

    client = TestClient(main.create_app())
    covered: set[tuple[str, str]] = set()

    def call(method: str, path: str, **kwargs: Any) -> Any:
        covered.add((method.upper(), _published_path(path[len(PREFIX) :])))
        return _check(client, method, path, **kwargs)

    template = _example("renderspec", "simple_label.json")
    template["id"] = TEMPLATE_ID
    stock = _example("stockspec", "shipping_4x6.yaml")
    stock["metadata"]["id"] = STOCK_ID
    calibration = _example("calibrationspec", "thermal_roll_offset.yaml")
    calibration["metadata"]["id"] = CALIBRATION_ID

    call("GET", "/v1/health")
    call("GET", "/v1/info")

    call("GET", "/v1/templates")
    call("POST", "/v1/templates", json=template)
    call("GET", f"/v1/templates/{TEMPLATE_ID}")
    call("PUT", f"/v1/templates/{TEMPLATE_ID}", json=template)
    call("PATCH", f"/v1/templates/{TEMPLATE_ID}", json={"name": "Contract label"})
    call("POST", f"/v1/templates/{TEMPLATE_ID}/validate", json=template)

    call("GET", "/v1/stocks")
    call("POST", "/v1/stocks", json=stock)
    call("GET", f"/v1/stocks/{STOCK_ID}")
    call("PUT", f"/v1/stocks/{STOCK_ID}", json=stock)
    call("PATCH", f"/v1/stocks/{STOCK_ID}", json={"name": "Contract stock"})

    call("GET", "/v1/calibrations")
    call("POST", "/v1/calibrations", json=calibration)
    call("GET", f"/v1/calibrations/{CALIBRATION_ID}")
    call("PUT", f"/v1/calibrations/{CALIBRATION_ID}", json=calibration)
    call("PATCH", f"/v1/calibrations/{CALIBRATION_ID}", json={"name": "Contract profile"})

    upload = call(
        "POST",
        "/v1/assets",
        files={"file": ("contract.png", PNG_BYTES, "image/png")},
    )
    asset_id = upload.json()["id"]
    call("GET", "/v1/assets")
    call("GET", f"/v1/assets/{asset_id}")
    call("GET", f"/v1/assets/{asset_id}/content")

    call("GET", "/v1/render-jobs")
    job = call(
        "POST",
        "/v1/render-jobs",
        json={"template_id": TEMPLATE_ID, "output": {"format": "pdf"}},
    )
    job_id = job.json()["id"]
    call("GET", f"/v1/render-jobs/{job_id}")

    # The documented failures answer with the problem document the contract publishes.
    call("GET", "/v1/templates/contract_missing")
    call("POST", "/v1/templates", json={})
    call("POST", "/v1/templates", json=template)
    call("GET", "/v1/templates?page=0")
    call("GET", "/v1/stocks?page=0")
    call("GET", "/v1/calibrations?page=0")
    call("GET", "/v1/assets?page=0")
    call("GET", "/v1/render-jobs?status=bogus")
    call("POST", "/v1/stocks", content=b"{", headers={"content-type": "application/json"})
    call("GET", "/v1/render-jobs/rnd_missing")
    call("POST", "/v1/render-jobs", json={})

    call("DELETE", f"/v1/assets/{asset_id}")
    call("DELETE", f"/v1/calibrations/{CALIBRATION_ID}")
    call("DELETE", f"/v1/stocks/{STOCK_ID}")
    call("DELETE", f"/v1/templates/{TEMPLATE_ID}")

    assert covered == _served(), (
        "the contract check did not exercise every served operation: "
        f"{sorted(_served() - covered)}"
    )
