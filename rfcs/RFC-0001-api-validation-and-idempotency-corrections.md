# RFC-0001: API Validation and Idempotency Corrections

- **Status:** Accepted
- **Author(s):** OpenLabelServer maintainers
- **Created:** 2026-11-14
- **Updated:** 2026-11-14
- **Specification:** OpenLabelServer REST API v1.0

## Summary

Corrects two normative statements in the REST API v1.0 specification that
contradicted the rest of the contract.

1. `POST /v1/templates/{template_id}/validate` validates a document supplied in
   the request body. It must never return `404 Not Found`; an identity mismatch
   between the path and the document is a `409 Conflict`.
2. Idempotent replay must return the stored response of the original request —
   `201 Created` for assets and `202 Accepted` for jobs — instead of a synthetic
   `200 OK`.

## Motivation

### Validation is stateless

Section 8.3 introduced `POST /v1/templates/{template_id}/validate` to validate a
RenderSpec document "without persisting" it, and the OpenAPI contract advertised
`404` on that operation. Nothing in the operation loads a stored resource, so
`404` has no referent: a conforming server has no object whose absence could be
reported. The status code also conflicted with the identity rule in Section 9.3,
which requires `409 Conflict` when the URL path ID and the nested document ID
disagree.

Implementers could not tell from the specification whether validation required
a stored template to exist first, which would have turned a pure validation
operation into a read-modify-write operation.

### Idempotent replay misreported the original outcome

Section 10 required a duplicate `Idempotency-Key` with an identical body to
return "the original response with `200 OK`". No successful submission returns
`200`: asset upload returns `201 Created` and render/print submissions return
`202 Accepted`. Returning `200` would tell a client that no resource was
created, while the original request did create one — exactly the ambiguity
idempotency keys exist to remove — and it desynchronised the prose from the
response schemas generated out of [openapi.yaml](../specs/api/openapi.yaml).

## Detailed design

### 1. Stateless RenderSpec validation

`POST /v1/templates/{template_id}/validate`:

- MUST NOT load or persist a stored template.
- MUST NOT return `404 Not Found`.
- MUST treat `template_id` as the identity the submitted document is validated
  against. If `document.id` differs from `template_id`, the server MUST return
  `409 Conflict`, consistent with the identity normalization rule in Section 9.3.

In [openapi.yaml](../specs/api/openapi.yaml) the `validateTemplate` operation
replaces its `404` response with `409` and documents the stateless behaviour.

### 2. Idempotent replay returns the stored response

For `POST /v1/assets`, `POST /v1/render-jobs`, and `POST /v1/print-jobs`:

- A duplicate key with the same body within 24 hours MUST replay the stored
  response for the original request: the same status code and the same body
  (`201 Created` for assets, `202 Accepted` for jobs).
- Replay MUST NOT create a second resource.
- A key reused with a different body MUST return `409 Conflict` (unchanged).

This section introduces no new status codes; the corrected sentence matches the
responses the contract already defines.

## Specification impact

| Location | Change |
| :--- | :--- |
| [specification.md Section 8.3](../specs/api/specification.md#83-templates) | Adds the no-`404` / `409` identity rule for the validate operation |
| [specification.md Section 10](../specs/api/specification.md#10-idempotency) | Replay returns the stored status code and body, not `200 OK` |
| [specification.md Section 5.1](../specs/api/specification.md#51-problem-details) | Editorial: `instance` is a URI reference and MAY be relative |
| [openapi.yaml](../specs/api/openapi.yaml) | `validateTemplate` `409` in place of `404`, plus description; shared `Conflict` description broadened to cover identity conflicts; `ProblemDetails.instance` and `RenderJob.output_url` use `format: uri-reference`; `servers` description corrected |

The URI formats and the `servers` description are editorial clarifications: the
published examples already used relative `instance` and `output_url` values, and
operation paths were already relative to the `/v1` prefix.

No example document changes. When the API conformance suite described in
[specs/conformance](../specs/conformance/README.md) is published, it must cover:

- validation with a `document.id` differing from `template_id` returning `409`;
- replay of an asset upload returning the original `201` and body without a
  second asset;
- replay of a job submission returning the original `202` without a second job.

## Backward compatibility

Not a breaking change: no URI, media type, or payload shape changes. The only
schema change relaxes two `format` keywords, which cannot invalidate a document
that already validated.

- A server that returned `404` from the validate operation, or `200` on replay,
  becomes non-conforming. Migration is a response-code change confined to those
  two behaviours.
- Clients that already follow Section 10 treat replay as "the resource from the
  first request exists" and are unaffected by receiving the original `201` or
  `202`.
- Generated clients see `404` removed and `409` added on a single operation,
  plus documentation text; no model changes.

## Alternatives considered

- **Keep `404` on validation.** Rejected: it implies a fetch that never happens
  and contradicts Section 9.3's `409` identity rule.
- **Move validation to `POST /v1/templates/validate`.** Rejected: it changes a
  published URI for no behavioural gain, and AGENTS.md forbids inventing or
  silently changing public interfaces.
- **Keep `200 OK` for replay while allowing `201`/`202` initially.** Rejected:
  it makes the same request produce two different success codes depending on how
  often it was sent, and misreports resource creation.

## Unresolved questions

None. Both corrections are settled and require no follow-up change for v1.0.
