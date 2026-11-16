# RFC-0004: Machine-Readable Detail for Ambiguous Calibration Profiles

- **Status:** Draft
- **Author(s):** OpenLabelServer maintainers
- **Created:** 2026-11-16
- **Updated:** 2026-11-16
- **Specification:** OpenLabelServer REST API v1.0 and ConformanceSpec v1.0

## Summary

Adds an optional `context` object to `errors[]` entries and defines it for the
`ambiguous-calibration-profile` code (`AJ-108`): `context.profiles` lists the
CalibrationSpec `metadata.id` values that tied, sorted lexicographically, and
`context.precedence` records the level at which they tied. Today the profile
names exist only in the human-readable `message`, so a client cannot tell which
profiles to disambiguate without parsing prose.

## Motivation

When profile selection is ambiguous, the server returns `422` with an
`errors[]` entry whose `code` is `ambiguous-calibration-profile` and whose
`field` is `calibration_id`. The published example names the profiles inside
`message`:

```json
"message": "Profiles laser-sheet-full and thermal-roll-offset both match; specify calibration_id explicitly"
```

That is adequate for a person and useless for a program. A UI that wants to show
"choose one of these two profiles" has to parse an English sentence with
document identifiers in it — brittle across servers, untranslatable, and
ambiguous when an id contains a word like "and". The information exists in the
server at the moment of rejection; only the response shape prevents it from being
usable.

ConformanceSpec `AJ-108` currently requires only that the `field` identify the
selection input and the `code` be `ambiguous-calibration-profile`; nothing
verifies the profile names at all, so implementations can omit them and still
conform.

RFC-0003 left this question open: "Should the ambiguous-profile error name the
profiles that tied? That is an API error-detail change under the REST API
specification and belongs in a separate proposal." This is that proposal.

## Detailed design

### 1. `context` on field errors

Add an OPTIONAL `context` member to the validation-error entry defined in
REST API Section 5.3:

| Field | Type | Presence | Description |
| :--- | :--- | :--- | :--- |
| `context` | `object` | OPTIONAL | Code-specific machine-readable detail. Keys are defined per `code`; clients MUST ignore keys they do not understand (ConformanceSpec `AP-113`). |

`context` is deliberately generic: every business-rule code has parameters a
client may want (`printer-not-found` has the printer id, `stock-not-found` has
the stock id), and adding a code-specific top-level member (`profiles`) to a
shared error entry would make the schema grow one member per code. This RFC
defines the member and one set of keys; later codes define their own.

### 2. Keys for `ambiguous-calibration-profile`

| Key | Type | Presence | Description |
| :--- | :--- | :--- | :--- |
| `context.profiles` | `array` of `string` | **REQUIRED** for this code | `metadata.id` of every enabled CalibrationSpec profile that matched at the winning precedence level. MUST contain at least two entries, MUST NOT contain duplicates, and MUST be sorted in ascending Unicode code-point order. |
| `context.precedence` | `integer` | OPTIONAL | The CalibrationSpec Section 8 precedence level (1–3) at which the profiles tied. |

Sorted order is normative rather than incidental: two servers holding the same
profiles must produce the same array for the same job, in the same way
ConformanceSpec `CS-119` requires identical coordinates (determinism, `DT-109`
covers declared output ordering).

Updated example, replacing
[ambiguous_calibration_error.json](../specs/api/examples/ambiguous_calibration_error.json):

```json
{
  "type": "https://openlabelserver.org/errors/validation-error",
  "title": "Validation Error",
  "status": 422,
  "detail": "Multiple calibration profiles match printer warehouse-zebra and stock shipping-4x6.",
  "instance": "/v1/print-jobs",
  "errors": [
    {
      "field": "calibration_id",
      "code": "ambiguous-calibration-profile",
      "message": "Profiles laser-sheet-full and thermal-roll-offset both match; specify calibration_id explicitly",
      "context": {
        "precedence": 3,
        "profiles": ["laser-sheet-full", "thermal-roll-offset"]
      }
    }
  ]
}
```

`message` stays human-readable and MAY name the profiles; `context.profiles` is
the machine-readable source of truth, and a client MUST NOT derive the set from
`message`.

### 3. Reference engine

`printing.calibration.AmbiguousProfileError` gains `profiles` (a sorted tuple of
`metadata.id` values) and `precedence` (the integer level) so the API layer can
serialize the entry without re-running selection, which could disagree with the
rejection if a profile was edited in between. The message keeps its current
shape.

## Specification impact

| Location | Change |
| :--- | :--- |
| [REST API Section 5.3](../specs/api/specification.md#53-validation-errors) | `context` row in the error-entry table |
| [REST API Section 5.4](../specs/api/specification.md#54-business-rule-error-codes) | `context.profiles` / `context.precedence` defined for `ambiguous-calibration-profile`; example updated |
| [openapi.yaml](../specs/api/openapi.yaml) | `FieldError.context` (`type: object`, `additionalProperties: true`); example response updated |
| [ambiguous_calibration_error.json](../specs/api/examples/ambiguous_calibration_error.json) | Adds the `context` object |
| [ConformanceSpec `AJ-108`](../specs/conformance/specification.md#103-cross-specification-behavior) | Requires `context.profiles` to equal the tied ids in sorted order and `context.precedence` to match the fixture; verification asserts the published example byte-for-byte after resolution |
| [printing/calibration.py](../printing/calibration.py) | `AmbiguousProfileError` exposes `profiles` and `precedence` |

`AP-106` already requires `field` and `message` on `422` entries and is
unaffected. No new HTTP status, code, or `type` URI is introduced.

## Backward compatibility

Additive: a new OPTIONAL member on an existing response object. ConformanceSpec
`AP-113` already requires clients to tolerate unknown JSON properties, so clients
written before this change continue to work.

- Servers conforming to this RFC MUST include `context.profiles` on
  `ambiguous-calibration-profile` rejections. A server that omits it becomes
  non-conforming for `AJ-108`, which is why the conformance requirement changes
  in the same edit.
- Clients MAY use `context.profiles` to offer a profile picker; a client that
  receives no `context` MUST fall back to `calibration_id` guidance from
  `message`, as today.
- No stored document, URI, or media type changes.

## Alternatives considered

- **Name the profiles only in `message`.** Rejected: that is the current state,
  and it fails exactly the case this RFC exists to fix — machine consumption of
  an English sentence. It also cannot be localised without breaking parsers.
- **Add a top-level `profiles` array to the error entry.** Rejected: the error
  entry is shared by every validation and business-rule failure; adding a
  code-specific member to it invites one new member per code (`printer_id`,
  `stock_id`, ...), while `context` holds all of them.
- **Use the `type` URI to distinguish the conflict shape.** Rejected: `type`
  identifies the error category (`validation-error` for all `422`s), and `AP-105`
  requires `type` to correspond to the failing condition. Making it
  profile-specific would split a stable category and duplicate `code`.
- **Return each tied profile as a separate `errors[]` entry.** Rejected: one
  rejection is one problem; three entries would read as three failures and
  would not tell the client that the entries are alternatives.
- **Name the winner instead of the candidates.** Rejected: there is no winner —
  that is the condition being reported.

## Unresolved questions

- Should `context` be constrained to a closed value type (string, number,
  boolean, or array of strings) so generated clients can type it, or left as an
  open object per code? The proposal leaves it open, which keeps code-specific
  structures expressible but weakens generated types.
- Should `context.precedence` be normative? It is OPTIONAL here because acting on
  the conflict needs only `profiles`; if implementations find level useful for
  diagnostics, a later revision could require it.
- Should the other business-rule codes define `context` keys in the same change
  for consistency, or each in its own proposal? This RFC deliberately defines
  only `ambiguous-calibration-profile` to keep the change reviewable.
