"""Conformance checks that drive the REST API (`CP-API`).

The suite starts no server of its own: each check builds the FastAPI application
in-process and sends it ASGI requests, so the routes, middleware and error
handlers under test are the ones `backend/main.py` exposes.

`CP-API` is not claimed yet. `AP-101` to `AP-106` are the requirements that are
observable: the `/v1` prefix on the templates collection and the stateless validate
operation, the system endpoints, the validate operation's `422`, which gives
`AP-104` its second error case and `AP-106` the field-level entries it asks for,
and the `type` URI of each error the service emits, which is `AP-105` for the four
statuses reachable without an authentication layer. `AR-101`, `AR-102`, `AR-103`
and `AR-106` are observable now that the templates resource stores documents: every
template operation is exercised against the SQLite-backed catalog, a replace
through another path id is a `409`, a duplicate create is a `409`, and a document
that fails the schema is rejected with `422` and never stored. `AQ-101` is the
RFC-0001 case the stored resource made observable: validate answers the submitted
document without reading or writing the catalog, so a valid body creates nothing and
a mismatched id is a `409`. `AP-110` is the other requirement the store unlocked: with
127 templates stored, the collection's pagination arithmetic is observable at every
page boundary instead of only over an empty catalog.
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
COLLECTION_PATH = "/v1/templates"
VALID_RENDERSPEC = (
    ROOT / "tests" / "conformance" / "fixtures" / "renderspec" / "valid" / "minimal_valid.json"
)

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
    """The `rel` targets of an RFC 8288 `Link` header, split the way API §6.3 shows."""

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


CHECKS = {
    "resource_uris_are_versioned": resource_uris_are_versioned,
    "api_version_is_reported": api_version_is_reported,
    "health_reports_ok": health_reports_ok,
    "error_responses_are_problem_documents": error_responses_are_problem_documents,
    "validation_errors_carry_field_and_message": validation_errors_carry_field_and_message,
    "error_types_name_their_condition": error_types_name_their_condition,
    "template_resource_supports_every_operation": template_resource_supports_every_operation,
    "replace_rejects_a_document_naming_another_id": replace_rejects_a_document_naming_another_id,
    "create_rejects_a_duplicate_id": create_rejects_a_duplicate_id,
    "invalid_documents_are_not_stored": invalid_documents_are_not_stored,
    "stateless_validation_persists_nothing": stateless_validation_persists_nothing,
    "pagination_arithmetic_over_a_seeded_catalog": pagination_arithmetic_over_a_seeded_catalog,
    "pagination_links_name_the_first_and_next_pages": (
        pagination_links_name_the_first_and_next_pages
    ),
}
