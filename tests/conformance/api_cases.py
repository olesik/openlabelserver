"""Conformance checks that drive the REST API (`CP-API`).

The suite starts no server of its own: each check builds the FastAPI application
in-process and sends it ASGI requests, so the routes, middleware and error
handlers under test are the ones `backend/main.py` exposes.

`CP-API` is not claimed yet. `AP-101` to `AP-106` are the requirements that are
observable: the `/v1` prefix on the templates collection and the stateless validate
operation, the system endpoints, the validate operation's `422`, which gives
`AP-104` its second error case and `AP-106` the field-level entries it asks for,
and the `type` URI of each error the service emits, which is `AP-105` for the four
statuses the default configuration reaches. `AR-101`, `AR-102`, `AR-103`
and `AR-106` are observable now that the templates resource stores documents: every
template operation is exercised against the SQLite-backed catalog, a replace
through another path id is a `409`, a duplicate create is a `409`, and a document
that fails the schema is rejected with `422` and never stored. `AQ-101` is the
RFC-0001 case the stored resource made observable: validate answers the submitted
document without reading or writing the catalog, so a valid body creates nothing and
a mismatched id is a `409`. `AP-110` is the other requirement the store unlocked: with
127 templates stored, the collection's pagination arithmetic is observable at every
page boundary instead of only over an empty catalog. `AR-104` follows from the same
store holding stocks and calibration profiles: their id is `document.metadata.id`, so
the mismatch and duplicate fixtures the requirement names can answer `409`. `AR-105`
follows from stored assets: an upload answers a server-generated `ast_` id and the
content operation returns the bytes that were sent, so the round trip and the
content-type rejection the requirement names are both observable. `AQ-102` follows
the same store once uploads honour `Idempotency-Key`: a repeated key replays the stored
`201` and a changed body under it is a `409`. `AJ-107` follows from the same store once
templates keep their asset references: an upload named on another host is stored as the
API asset URI the upload published, and that URI serves the bytes, while the external
URL and base64 forms are stored as sent. `AP-108` and `AP-109` follow once `OPENLABEL_AUTH` configures
principals: the former requires the anonymous `401` with its challenge, the viewer's
read and the `403` its create earns, and the latter the Bearer-first rule.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import create_app  # noqa: E402

MISSING_PATH = "/v1/no-such-resource"
VALIDATE_PATH = "/v1/templates/minimal-valid/validate"
COLLECTION_PATH = "/v1/templates"
VALID_RENDERSPEC = (
    ROOT / "tests" / "conformance" / "fixtures" / "renderspec" / "valid" / "minimal_valid.json"
)
STOCK_COLLECTION = "/v1/stocks"
CALIBRATION_COLLECTION = "/v1/calibrations"
ASSET_COLLECTION = "/v1/assets"
VALID_STOCKSPEC = (
    ROOT / "tests" / "conformance" / "fixtures" / "stockspec" / "valid" / "generic_3x7.json"
)
VALID_CALIBRATIONSPEC = (
    ROOT / "tests" / "conformance" / "fixtures" / "calibrationspec" / "valid" / "profile.json"
)

# API §4.1 leaves the credential configuration to the server; this is the shape
# `backend/auth.py` documents, so the authentication cases set it as an operator would.
AUTH_ENV = "OPENLABEL_AUTH"
AUTH_PRINCIPALS = {
    "principals": [
        {
            "id": "usr_admin",
            "username": "admin",
            "roles": ["admin"],
            "api_key": "ols_admin_key",
        },
        {
            "id": "usr_viewer",
            "username": "viewer",
            "roles": ["viewer"],
            "bearer_token": "viewer-token",
        },
    ]
}
VIEWER = {"Authorization": "Bearer viewer-token"}
ADMIN = {"X-API-Key": "ols_admin_key"}

# API Spec §5.2, restated rather than imported from `backend/problems.py`: importing
# the table the service builds its answers from would only prove it agrees with itself.
ERROR_TYPE_PREFIX = "https://openlabelserver.org/errors/"


def _template_document(template_id: str = "conformance-template", name: str | None = None) -> dict:
    """The published valid fixture under the identity the resource cases store."""

    document = json.loads(VALID_RENDERSPEC.read_text(encoding="utf-8"))
    document["id"] = template_id
    if name is not None:
        document["name"] = name
    return document


def _stock_document(stock_id: str = "conformance-stock") -> dict:
    """The published valid StockSpec fixture under the identity the resource cases store."""

    document = json.loads(VALID_STOCKSPEC.read_text(encoding="utf-8"))
    document["metadata"]["id"] = stock_id
    return document


def _calibration_document(calibration_id: str = "conformance-profile") -> dict:
    """The published valid CalibrationSpec fixture under the identity the cases store."""

    document = json.loads(VALID_CALIBRATIONSPEC.read_text(encoding="utf-8"))
    document["metadata"]["id"] = calibration_id
    return document


def _json_body(response) -> dict:
    """The parsed body of a JSON response, success or problem document, or `{}`."""

    content_type = response.headers.get("content-type", "")
    if not content_type.startswith(("application/json", "application/problem+json")):
        return {}
    return response.json()


def resource_uris_are_versioned() -> tuple[bool, str]:
    """AP-101: every resource URI is under `/v1`.

    The requirement's published verification is this pair of requests: the templates
    collection answers under the prefix, and the same collection without it does not.
    The catalog is empty because nothing stores a template yet, so the case also
    requires the §6.2 list envelope — a `200` from a handler that answered nothing
    would not be the resource the specification names.
    """

    client = TestClient(create_app())
    versioned = client.get("/v1/templates")
    unversioned = client.get("/templates")
    content_type = versioned.headers.get("content-type", "")
    body = versioned.json() if content_type.startswith("application/json") else {}
    checks = {
        "GET /v1/templates answers 200": versioned.status_code == 200,
        "GET /v1/templates answers the list envelope": (
            body.get("object") == "list" and isinstance(body.get("data"), list)
        ),
        "an unversioned GET /templates is not a success response": not (
            200 <= unversioned.status_code < 300
        ),
    }
    broken = [name for name, passed in checks.items() if not passed]
    if broken:
        return False, "failed: " + ", ".join(broken)
    return True, (
        f"/v1/templates answered {versioned.status_code} with a list envelope, and "
        f"/templates answered {unversioned.status_code}"
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


def template_resource_supports_every_operation() -> tuple[bool, str]:
    """AR-101: list, create, retrieve, replace, patch, delete and validate are exposed."""

    client = TestClient(create_app())
    document = _template_document()
    path = f"{COLLECTION_PATH}/conformance-template"

    created = client.post(COLLECTION_PATH, json=document)
    retrieved = client.get(path)
    replaced = client.put(path, json=_template_document(name="Conformance Template v2"))
    patched = client.patch(path, json={"name": "Conformance Template v3"})
    listed = client.get(COLLECTION_PATH)
    deleted = client.delete(path)
    gone = client.get(path)
    validated = client.post(f"{path}/validate", json=document)

    listed_ids = [item.get("id") for item in _json_body(listed).get("data", [])]
    checks = {
        "POST /v1/templates answers 201": created.status_code == 201,
        "GET /v1/templates/{id} returns the created document": (
            retrieved.status_code == 200
            and _json_body(retrieved).get("document") == document
        ),
        "PUT /v1/templates/{id} returns the replaced document": (
            replaced.status_code == 200
            and _json_body(replaced).get("document", {}).get("name")
            == "Conformance Template v2"
        ),
        "PATCH /v1/templates/{id} returns the patched metadata": (
            patched.status_code == 200
            and _json_body(patched).get("document", {}).get("name")
            == "Conformance Template v3"
        ),
        "GET /v1/templates lists the stored template": listed_ids == ["conformance-template"],
        "DELETE /v1/templates/{id} answers 204": deleted.status_code == 204,
        "GET /v1/templates/{id} after the delete answers 404": gone.status_code == 404,
        "POST /v1/templates/{id}/validate answers 200": validated.status_code == 200,
    }
    broken = [name for name, passed in checks.items() if not passed]
    if broken:
        return False, "failed: " + ", ".join(broken)
    return True, (
        "create, retrieve, replace, patch, list, delete and validate each answered the "
        "status and body the templates resource publishes"
    )


def replace_rejects_a_document_naming_another_id() -> tuple[bool, str]:
    """AR-102: a stored document cannot be written through another path id."""

    client = TestClient(create_app())
    stored = client.post(COLLECTION_PATH, json=_template_document("stored-template"))
    response = client.put(
        f"{COLLECTION_PATH}/other-template", json=_template_document("stored-template", "Renamed")
    )
    content_type = response.headers.get("content-type", "")
    body = response.json() if content_type.startswith("application/problem+json") else {}
    after = _json_body(client.get(f"{COLLECTION_PATH}/stored-template"))
    checks = {
        "the stored document is created": stored.status_code == 201,
        "the replace answers 409": response.status_code == 409,
        "the body is a problem document": content_type == "application/problem+json",
        "the type names the conflict": body.get("type") == ERROR_TYPE_PREFIX + "conflict",
        "the stored document keeps its own content": (
            after.get("document", {}).get("name") == stored.json()["document"]["name"]
        ),
    }
    broken = [name for name, passed in checks.items() if not passed]
    if broken:
        return False, "failed: " + ", ".join(broken)
    return True, (
        "a document stored as stored-template answered 409 conflict when replaced through "
        "/v1/templates/other-template, and its stored content did not change"
    )


def create_rejects_a_duplicate_id() -> tuple[bool, str]:
    """AR-103: creating a template whose id already exists answers `409 Conflict`."""

    client = TestClient(create_app())
    first = client.post(COLLECTION_PATH, json=_template_document())
    duplicate = client.post(COLLECTION_PATH, json=_template_document(name="Second Name"))
    content_type = duplicate.headers.get("content-type", "")
    body = duplicate.json() if content_type.startswith("application/problem+json") else {}
    checks = {
        "the first create answers 201": first.status_code == 201,
        "the duplicate create answers 409": duplicate.status_code == 409,
        "the body is a problem document": content_type == "application/problem+json",
        "the type names the conflict": body.get("type") == ERROR_TYPE_PREFIX + "conflict",
        "the stored document is the first one": (
            _json_body(client.get(f"{COLLECTION_PATH}/conformance-template"))
            .get("document", {})
            .get("name")
            == first.json()["document"]["name"]
        ),
    }
    broken = [name for name, passed in checks.items() if not passed]
    if broken:
        return False, "failed: " + ", ".join(broken)
    return True, "a second create of conformance-template answered 409 conflict and changed nothing"


def invalid_documents_are_not_stored() -> tuple[bool, str]:
    """AR-106: a document that fails the schema answers `422` and is never persisted."""

    client = TestClient(create_app())
    invalid = _template_document()
    del invalid["page"]
    rejected = client.post(COLLECTION_PATH, json=invalid)
    missing = client.get(f"{COLLECTION_PATH}/conformance-template")
    stored = client.post(COLLECTION_PATH, json=_template_document())
    still_invalid = _template_document(name="Not Stored")
    del still_invalid["page"]
    rejected_replace = client.put(
        f"{COLLECTION_PATH}/conformance-template", json=still_invalid
    )
    after = _json_body(client.get(f"{COLLECTION_PATH}/conformance-template"))
    checks = {
        "the invalid create answers 422": rejected.status_code == 422,
        "the invalid document was not stored": missing.status_code == 404,
        "a valid document is stored afterwards": stored.status_code == 201,
        "the invalid replace answers 422": rejected_replace.status_code == 422,
        "the stored document keeps its content": (
            after.get("document", {}).get("name") == stored.json()["document"]["name"]
        ),
    }
    broken = [name for name, passed in checks.items() if not passed]
    if broken:
        return False, "failed: " + ", ".join(broken)
    return True, (
        "a schema-invalid create answered 422 and left no template, and a schema-invalid "
        "replace answered 422 without changing the stored document"
    )


def stateless_validation_persists_nothing() -> tuple[bool, str]:
    """AQ-101: validate checks the submitted document, creates nothing and never 404s."""

    client = TestClient(create_app())
    document = _template_document()
    path = f"{COLLECTION_PATH}/{document['id']}/validate"

    validated = client.post(path, json=document)
    after = client.get(f"{COLLECTION_PATH}/{document['id']}")
    mismatch = client.post(f"{COLLECTION_PATH}/another-template/validate", json=document)
    mismatch_type = mismatch.headers.get("content-type", "")

    # A stored template at the path id must be neither read nor written: an invalid body
    # still fails, and a valid body leaves the stored document as it was.
    stored = client.post(COLLECTION_PATH, json=document)
    invalid = _template_document()
    del invalid["page"]
    rejected = client.post(path, json=invalid)
    client.post(path, json=_template_document(name="Not Stored Either"))
    after_revalidate = _json_body(client.get(f"{COLLECTION_PATH}/{document['id']}"))

    checks = {
        "a valid document answers 200": validated.status_code == 200,
        "the body is the published ValidationSuccess": _json_body(validated) == {"valid": True},
        "the validation created no template": after.status_code == 404,
        "a mismatched id answers 409": mismatch.status_code == 409,
        "the mismatch is a problem document": mismatch_type == "application/problem+json",
        "the mismatch names the conflict": (
            _json_body(mismatch).get("type") == ERROR_TYPE_PREFIX + "conflict"
        ),
        "the stored template is created": stored.status_code == 201,
        "an invalid body still fails against a stored id": rejected.status_code == 422,
        "the stored document is not overwritten": (
            after_revalidate.get("document", {}).get("name")
            == stored.json()["document"]["name"]
        ),
    }
    broken = [name for name, passed in checks.items() if not passed]
    if broken:
        return False, "failed: " + ", ".join(broken)
    return True, (
        "validate answered 200 for the document's own id and 409 conflict for another, "
        "created no template, and neither read nor overwrote one stored at the path id"
    )


def pagination_arithmetic_over_a_seeded_catalog() -> tuple[bool, str]:
    """AP-110: 127 stored templates page as the §6.2 envelope's arithmetic says.

    The requirement's published verification is the `page=3&page_size=50` request. The
    defaults and every page boundary are checked too, because `total_pages`, `has_next`
    and `has_previous` only say anything at the edges between pages.
    """

    client = TestClient(create_app())
    seeded = [
        client.post(COLLECTION_PATH, json=_template_document(f"seed-template-{number:03d}"))
        for number in range(1, 128)
    ]
    third = _json_body(client.get(f"{COLLECTION_PATH}?page=3&page_size=50"))
    default = _json_body(client.get(COLLECTION_PATH))
    last = _json_body(client.get(f"{COLLECTION_PATH}?page=7&page_size=20"))
    pages = [
        _json_body(client.get(f"{COLLECTION_PATH}?page={page}&page_size=20"))
        for page in range(1, 8)
    ]
    ids = [item["id"] for page in pages for item in page.get("data", [])]
    third_pagination = third.get("pagination", {})
    default_pagination = default.get("pagination", {})
    checks = {
        "seeding 127 templates answers 201 each time": all(
            response.status_code == 201 for response in seeded
        ),
        "page=3&page_size=50 answers the last 27 items": len(third.get("data", [])) == 27,
        "page=3&page_size=50 reports total_items 127": third_pagination.get("total_items") == 127,
        "page=3&page_size=50 reports total_pages 3": third_pagination.get("total_pages") == 3,
        "page=3&page_size=50 has no next page": third_pagination.get("has_next") is False,
        "page=3&page_size=50 has a previous page": third_pagination.get("has_previous") is True,
        "the defaults are page 1 and page_size 20": (
            default_pagination.get("page") == 1 and default_pagination.get("page_size") == 20
        ),
        "the default page holds 20 of 127 items over 7 pages": (
            default_pagination.get("total_items") == 127
            and default_pagination.get("total_pages") == 7
            and len(default.get("data", [])) == 20
        ),
        "the first page has no previous page": (
            default_pagination.get("has_previous") is False
            and default_pagination.get("has_next") is True
        ),
        "the last page holds the remaining 7 items": (
            len(last.get("data", [])) == 7
            and last.get("pagination", {}).get("has_next") is False
            and last.get("pagination", {}).get("has_previous") is True
        ),
        "every page reports its own neighbours": all(
            page["pagination"]["has_next"] == (number < 7)
            and page["pagination"]["has_previous"] == (number > 1)
            for number, page in enumerate(pages, start=1)
        ),
        "walking the pages yields every template exactly once": (
            len(ids) == 127 and len(set(ids)) == 127
        ),
        "a page and a page_size outside the bounds are rejected": (
            client.get(f"{COLLECTION_PATH}?page=0").status_code == 400
            and client.get(f"{COLLECTION_PATH}?page_size=101").status_code == 400
        ),
    }
    broken = [name for name, passed in checks.items() if not passed]
    if broken:
        return False, "failed: " + ", ".join(broken)
    return True, (
        "127 templates paged as 27 items on page 3 of 3 at page_size 50 and as 20, 20, ..., "
        "7 over seven default pages, every page reporting its neighbours and no id repeated"
    )


def _link_relations(header: str) -> dict[str, str]:
    """The `rel` targets of an RFC 8288 `Link` header, split the way API Â§6.3 shows."""

    relations: dict[str, str] = {}
    for link in header.split(","):
        target, _, parameters = link.partition(";")
        target = target.strip()
        if not (target.startswith("<") and target.endswith(">")):
            continue
        for parameter in parameters.split(";"):
            name, _, value = parameter.partition("=")
            if name.strip().lower() == "rel":
                relations[value.strip().strip('"')] = target[1:-1]
    return relations


def pagination_links_name_the_first_and_next_pages() -> tuple[bool, str]:
    """AP-111: a paginated response carries RFC 8288 links for `next` and `first`."""

    client = TestClient(create_app())
    seeded = [
        client.post(COLLECTION_PATH, json=_template_document(f"linked-template-{number}"))
        for number in range(1, 6)
    ]
    middle = client.get(f"{COLLECTION_PATH}?page=2&page_size=2")
    links = _link_relations(middle.headers.get("link", ""))
    # A relation the header should carry but does not resolves to a page past the end, so
    # the target checks fail on the page number instead of raising a KeyError here.
    absent = f"{COLLECTION_PATH}?page=999"
    next_page = _json_body(client.get(links.get("next", absent)))
    first_page = _json_body(client.get(links.get("first", absent)))
    next_pagination = next_page.get("pagination", {})
    first_pagination = first_page.get("pagination", {})
    checks = {
        "seeding five templates answers 201 each time": all(
            response.status_code == 201 for response in seeded
        ),
        "the middle page answers 200": middle.status_code == 200,
        "the response carries a next relation": "next" in links,
        "the response carries a first relation": "first" in links,
        "the next relation resolves to page 3": next_pagination.get("page") == 3,
        "the next relation keeps the page size": next_pagination.get("page_size") == 2,
        "the next relation holds the remaining item": len(next_page.get("data", [])) == 1,
        "the first relation resolves to page 1": first_pagination.get("page") == 1,
        "the first relation holds a whole page": len(first_page.get("data", [])) == 2,
    }
    broken = [name for name, passed in checks.items() if not passed]
    if broken:
        return False, "failed: " + ", ".join(broken)
    return True, (
        "page 2 of 3 linked <page=3>; rel=next and <page=1>; rel=first, and each target "
        "answered the page it named at the same page size"
    )


def stocks_and_calibrations_normalize_their_identity() -> tuple[bool, str]:
    """AR-104: the resource id is `document.metadata.id`, and a disagreement is a `409`.

    The requirement's published verification is the mismatch and duplicate pair, so the
    case runs both against both resources: a second create of a stored identity, and a
    replace whose path names another one.
    """

    client = TestClient(create_app())
    stock = _stock_document()
    profile = _calibration_document()
    created_stock = client.post(STOCK_COLLECTION, json=stock)
    created_profile = client.post(CALIBRATION_COLLECTION, json=profile)
    duplicate_stock = client.post(STOCK_COLLECTION, json=stock)
    duplicate_profile = client.post(CALIBRATION_COLLECTION, json=profile)
    # The path id names an identity the document does not carry.
    stock_mismatch = client.put(f"{STOCK_COLLECTION}/other-stock", json=stock)
    profile_mismatch = client.put(f"{CALIBRATION_COLLECTION}/other-profile", json=profile)
    stored_stock = _json_body(client.get(f"{STOCK_COLLECTION}/conformance-stock"))
    stored_profile = _json_body(client.get(f"{CALIBRATION_COLLECTION}/conformance-profile"))
    checks = {
        "creating a stock answers 201": created_stock.status_code == 201,
        "the stock id is its metadata id": (
            _json_body(created_stock).get("id") == "conformance-stock"
        ),
        "creating a calibration answers 201": created_profile.status_code == 201,
        "the calibration id is its metadata id": (
            _json_body(created_profile).get("id") == "conformance-profile"
        ),
        "a second stock of a stored identity is a 409": duplicate_stock.status_code == 409,
        "a second profile of a stored identity is a 409": (
            duplicate_profile.status_code == 409
        ),
        "a stock document naming another id is a 409": stock_mismatch.status_code == 409,
        "a profile document naming another id is a 409": profile_mismatch.status_code == 409,
        "the conflicts carry the Â§5.2 conflict type": (
            _json_body(duplicate_stock).get("type") == ERROR_TYPE_PREFIX + "conflict"
            and _json_body(stock_mismatch).get("type") == ERROR_TYPE_PREFIX + "conflict"
        ),
        "the stored stock is the one its metadata names": (
            stored_stock.get("document", {}).get("metadata", {}).get("id")
            == "conformance-stock"
        ),
        "the stored profile is the one its metadata names": (
            stored_profile.get("document", {}).get("metadata", {}).get("id")
            == "conformance-profile"
        ),
        "the refused requests left both documents unmodified": (
            stored_stock.get("document") == stock
            and stored_profile.get("document") == profile
        ),
        "an id neither catalog holds is a 404": (
            client.get(f"{STOCK_COLLECTION}/absent-stock").status_code == 404
            and client.get(f"{CALIBRATION_COLLECTION}/absent-profile").status_code == 404
        ),
    }
    broken = [name for name, passed in checks.items() if not passed]
    if broken:
        return False, "failed: " + ", ".join(broken)
    return True, (
        "both resources took their id from document.metadata.id, answered 409 for a "
        "duplicate create and for a replace naming another id, and left the stored "
        "documents unmodified"
    )


def assets_are_uploaded_and_served_byte_identically() -> tuple[bool, str]:
    """AR-105: a `multipart/form-data` upload with an opaque id and the same bytes back."""

    client = TestClient(create_app())
    png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 16
    created = client.post(
        ASSET_COLLECTION, files={"file": ("conformance.png", png, "image/png")}
    )
    body = _json_body(created)
    # An id the upload did not produce resolves to a path nothing holds, so the byte
    # check fails on the download instead of raising here.
    asset_id = str(body.get("id", "ast_absent"))
    download = client.get(f"{ASSET_COLLECTION}/{asset_id}/content")
    rejected = client.post(
        ASSET_COLLECTION, files={"file": ("notes.gif", b"GIF89a", "image/gif")}
    )
    checks = {
        "uploading a PNG answers 201": created.status_code == 201,
        "the asset id is opaque and prefixed with ast_": re.fullmatch(
            r"ast_[a-zA-Z0-9_-]+", asset_id
        )
        is not None,
        "the asset reports the uploaded content type": (
            body.get("content_type") == "image/png"
        ),
        "the download answers 200": download.status_code == 200,
        "the download is the uploaded file byte for byte": download.content == png,
        "an unsupported content type is rejected": rejected.status_code == 422,
        "the rejection is a problem document": rejected.headers.get(
            "content-type", ""
        ).startswith("application/problem+json"),
    }
    broken = [name for name, passed in checks.items() if not passed]
    if broken:
        return False, "failed: " + ", ".join(broken)
    return True, (
        "a PNG upload answered 201 with a server-generated ast_ id and downloaded byte "
        "for byte, and an image/gif upload was rejected as a problem document"
    )


def idempotency_key_replays_the_original_upload() -> tuple[bool, str]:
    """AQ-102: a repeated key replays the stored `201`; a new body under it is a `409`."""

    client = TestClient(create_app())
    png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 16
    headers = {"Idempotency-Key": "conformance-replay"}
    first = client.post(
        ASSET_COLLECTION, files={"file": ("conformance.png", png, "image/png")}, headers=headers
    )
    repeated = client.post(
        ASSET_COLLECTION, files={"file": ("conformance.png", png, "image/png")}, headers=headers
    )
    changed = client.post(
        ASSET_COLLECTION,
        files={"file": ("conformance.png", png + b"\x00", "image/png")},
        headers=headers,
    )
    listing = _json_body(client.get(ASSET_COLLECTION))
    original, replay = _json_body(first), _json_body(repeated)
    checks = {
        "the first upload answers 201": first.status_code == 201,
        "the repeated key answers 201": repeated.status_code == 201,
        # RFC-0001: the replay is the stored response, not a synthetic one.
        "the replay is the original body": replay == original,
        "the replay names the original asset": replay.get("id") == original.get("id"),
        "the replay carries the original download url": (
            replay.get("url") == original.get("url")
        ),
        "the key stored one asset": listing.get("pagination", {}).get("total_items") == 1,
        "another body under the key is a 409": changed.status_code == 409,
        "the conflict is a problem document": changed.headers.get(
            "content-type", ""
        ).startswith("application/problem+json"),
        "the conflict carries the §5.2 conflict type": (
            _json_body(changed).get("type") == ERROR_TYPE_PREFIX + "conflict"
        ),
    }
    broken = [name for name, passed in checks.items() if not passed]
    if broken:
        return False, "failed: " + ", ".join(broken)
    return True, (
        "a repeated Idempotency-Key replayed the original 201 with the same ast_ id and "
        "url and left one asset, and other bytes under that key answered 409 conflict"
    )


def asset_references_in_stored_templates_use_the_published_forms() -> tuple[bool, str]:
    """AJ-107: a stored template names an uploaded asset by the API asset URI it serves."""

    client = TestClient(create_app())
    png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 16
    upload = _json_body(
        client.post(ASSET_COLLECTION, files={"file": ("logo.png", png, "image/png")})
    )
    asset_id = str(upload.get("id", "ast_absent"))
    published = str(upload.get("url", ""))
    document = _template_document("conformance-assets")
    document["assets"] = [
        {
            "id": "uploaded",
            "type": "png",
            "source": f"https://uploads.example/v1/assets/{asset_id}/content",
        },
        {"id": "remote", "type": "svg", "source": "https://cdn.example.com/mark.svg"},
        {"id": "inline", "type": "png", "source": "data:image/png;base64,iVBORw0KGgo="},
    ]
    created = client.post(COLLECTION_PATH, json=document)
    stored = _json_body(client.get(f"{COLLECTION_PATH}/conformance-assets"))
    sources = {
        str(asset.get("id")): asset.get("source")
        for asset in (stored.get("document") or {}).get("assets") or []
    }
    served = client.get(f"{ASSET_COLLECTION}/{asset_id}/content")
    checks = {
        "storing the template answers 201": created.status_code == 201,
        # The published URI is this asset's content route on the serving host.
        "the upload published a content URI": published.endswith(
            f"/v1/assets/{asset_id}/content"
        ),
        # §9.5's first form, with the host the client used replaced by the serving one.
        "the uploaded asset is stored as its API asset URI": (
            sources.get("uploaded") == published
        ),
        "the stored URI serves the uploaded bytes": (
            served.status_code == 200 and served.content == png
        ),
        "an external HTTPS URL is stored as sent": (
            sources.get("remote") == "https://cdn.example.com/mark.svg"
        ),
        "a base64 data URI is stored as sent": (
            sources.get("inline") == "data:image/png;base64,iVBORw0KGgo="
        ),
    }
    broken = [name for name, passed in checks.items() if not passed]
    if broken:
        return False, "failed: " + ", ".join(broken)
    return True, (
        "a template stored with an upload named on another host kept the API asset URI "
        "the upload published and that URI served the uploaded bytes, while an external "
        "URL and a data URI were stored as sent; AJ-107's render half awaits the job "
        "pipeline"
    )


def _authenticated_app():
    """An application configured with the §4.2 credentials above.

    The environment is left as it was found, so a check does not change the
    configuration another case builds its application under.
    """

    previous = os.environ.get(AUTH_ENV)
    os.environ[AUTH_ENV] = json.dumps(AUTH_PRINCIPALS)
    try:
        return create_app()
    finally:
        if previous is None:
            os.environ.pop(AUTH_ENV, None)
        else:
            os.environ[AUTH_ENV] = previous


def credentials_are_required_and_roles_are_enforced() -> tuple[bool, str]:
    """AP-108: missing credentials answer `401` with the §4.7 challenge, a viewer's write `403`."""

    client = TestClient(_authenticated_app())
    anonymous = client.get(COLLECTION_PATH)
    viewer_read = client.get(COLLECTION_PATH, headers=VIEWER)
    viewer_create = client.post(
        COLLECTION_PATH, json=_template_document("viewer-denied"), headers=VIEWER
    )
    stored = _json_body(client.get(COLLECTION_PATH, headers=ADMIN))
    admin_create = client.post(
        COLLECTION_PATH, json=_template_document("admin-allowed"), headers=ADMIN
    )
    anonymous_body = _json_body(anonymous)
    denied_body = _json_body(viewer_create)
    checks = {
        "an anonymous read answers 401": anonymous.status_code == 401,
        "the 401 is a problem document": anonymous.headers.get(
            "content-type", ""
        ).startswith("application/problem+json"),
        # API §4.7 publishes the challenge verbatim.
        "the 401 carries the §4.7 challenge": (
            anonymous.headers.get("www-authenticate") == 'Bearer realm="OpenLabelServer"'
        ),
        "the 401 carries the §5.2 unauthorized type": (
            anonymous_body.get("type") == ERROR_TYPE_PREFIX + "unauthorized"
        ),
        "a viewer may read": viewer_read.status_code == 200,
        "a viewer may not create": viewer_create.status_code == 403,
        "the 403 is a problem document": viewer_create.headers.get(
            "content-type", ""
        ).startswith("application/problem+json"),
        "the 403 carries the §5.2 forbidden type": (
            denied_body.get("type") == ERROR_TYPE_PREFIX + "forbidden"
        ),
        "the denied create stored nothing": (
            stored.get("pagination", {}).get("total_items") == 0
        ),
        "an administrator may create": admin_create.status_code == 201,
    }
    broken = [name for name, passed in checks.items() if not passed]
    if broken:
        return False, "failed: " + ", ".join(broken)
    return True, (
        "an anonymous read answered 401 with the §4.7 challenge and the §5.2 unauthorized "
        "type, a viewer read the collection but its create answered 403 with the forbidden "
        "type and stored nothing, and the administrator's create answered 201"
    )


def the_bearer_token_is_evaluated_before_the_api_key() -> tuple[bool, str]:
    """AP-109: a Bearer token decides the request, whatever `X-API-Key` carries."""

    client = TestClient(_authenticated_app())
    accepted = client.get(
        COLLECTION_PATH,
        headers={"Authorization": "Bearer viewer-token", "X-API-Key": "ols_absent"},
    )
    rejected = client.get(
        COLLECTION_PATH,
        headers={"Authorization": "Bearer absent-token", "X-API-Key": "ols_admin_key"},
    )
    checks = {
        "a valid Bearer token with an invalid API key succeeds": accepted.status_code == 200,
        "an invalid Bearer token with a valid API key answers 401": (
            rejected.status_code == 401
        ),
    }
    broken = [name for name, passed in checks.items() if not passed]
    if broken:
        return False, "failed: " + ", ".join(broken)
    return True, (
        "a valid Bearer token was accepted beside an invalid API key, and an invalid Bearer "
        "token answered 401 beside the administrator's API key"
    )


CHECKS = {
    "resource_uris_are_versioned": resource_uris_are_versioned,
    "api_version_is_reported": api_version_is_reported,
    "health_reports_ok": health_reports_ok,
    "error_responses_are_problem_documents": error_responses_are_problem_documents,
    "validation_errors_carry_field_and_message": validation_errors_carry_field_and_message,
    "error_types_name_their_condition": error_types_name_their_condition,
    "credentials_are_required_and_roles_are_enforced": (
        credentials_are_required_and_roles_are_enforced
    ),
    "the_bearer_token_is_evaluated_before_the_api_key": (
        the_bearer_token_is_evaluated_before_the_api_key
    ),
    "template_resource_supports_every_operation": template_resource_supports_every_operation,
    "replace_rejects_a_document_naming_another_id": replace_rejects_a_document_naming_another_id,
    "create_rejects_a_duplicate_id": create_rejects_a_duplicate_id,
    "invalid_documents_are_not_stored": invalid_documents_are_not_stored,
    "stateless_validation_persists_nothing": stateless_validation_persists_nothing,
    "pagination_arithmetic_over_a_seeded_catalog": pagination_arithmetic_over_a_seeded_catalog,
    "pagination_links_name_the_first_and_next_pages": (
        pagination_links_name_the_first_and_next_pages
    ),
    "stocks_and_calibrations_normalize_their_identity": (
        stocks_and_calibrations_normalize_their_identity
    ),
    "assets_are_uploaded_and_served_byte_identically": (
        assets_are_uploaded_and_served_byte_identically
    ),
    "idempotency_key_replays_the_original_upload": (
        idempotency_key_replays_the_original_upload
    ),
    "asset_references_in_stored_templates_use_the_published_forms": (
        asset_references_in_stored_templates_use_the_published_forms
    ),
}
