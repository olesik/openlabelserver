# RFC-0003: `updated_at` on Printer-Level Calibration Profiles

- **Status:** Draft
- **Author(s):** OpenLabelServer maintainers
- **Created:** 2026-11-15
- **Updated:** 2026-11-15
- **Specification:** OpenLabelServer CalibrationSpec v1.0

## Summary

Settles the question left open by [RFC-0002](RFC-0002-calibration-informational-target-selection.md):
whether a profile that can only match at the printer-only precedence level should
be *required* to carry `metadata.updated_at`. Recommendation: **no MUST**. Add a
SHOULD in CalibrationSpec Section 8 recommending the timestamp for those
profiles, and leave validation unchanged.

## Motivation

RFC-0002 made a profile whose `target` carries only informational fields a
candidate at Section 8 rule 3, alongside profiles with no `target` at all. Both
are now peers, so for a printer with two printer-level profiles that cannot be
ordered by `metadata.updated_at`, a job that previously printed now fails with
an ambiguous-profile error (`AJ-108`).

`updated_at` is OPTIONAL in Section 6.1 and in the JSON Schema (a `date-time`
string when present), so this state is reachable with individually valid
documents. Every shipped example carries the field, which suggests authors
already do this, but nothing states it.

The open question was therefore whether to make the timestamp a validation
requirement for profiles that can only match at rule 3 — that is, profiles whose
`target` is absent or carries neither `stock_id` nor `page_format`.

## Detailed design

Add one sentence to CalibrationSpec Section 8, after the clarifying sentence
RFC-0002 introduced:

> A profile whose `target` carries no selection-bearing field can only match at
> precedence level 3. Such a profile SHOULD carry `metadata.updated_at`, so that
> two printer-level profiles for the same printer can be ordered rather than
> rejected.

Nothing else changes: `updated_at` stays OPTIONAL, no schema conditional is
added, and no conformance requirement is introduced. The SHOULD describes
authoring practice; a document without the field remains valid and still selects
normally when it is the only candidate.

## Recommendation and rationale

Recommend the SHOULD, and explicitly not a MUST, for four reasons.

1. **Validity should not depend on other documents.** Whether a printer-level
   profile is ambiguous depends on which *other* profiles are loaded. A validation
   rule cannot see the set, so a MUST would enforce a timestamp on a
   single-profile deployment that has no ambiguity to resolve.
2. **A MUST would not remove the failure.** Profiles with equal timestamps still
   tie and still reject. The requirement would add a universal authoring burden
   without closing the case it targets.
3. **Determinism is already preserved.** Section 8 makes the tie an error rather
   than a silent pick (ADR-0003), so the remaining risk is an operational
   rejection, not nondeterministic output. That is a question of diagnostics and
   authoring guidance, which a SHOULD addresses in proportion.
4. **It matches existing practice.** Every example document in
   [specs/calibrationspec/examples](../specs/calibrationspec/examples) carries
   `updated_at`; the sentence records what authors already do instead of
   inventing a new obligation.

## Specification impact

| Location | Change |
| :--- | :--- |
| [CalibrationSpec Section 8](../specs/calibrationspec/specification.md#8-printer-profile-selection) | One SHOULD sentence on `metadata.updated_at` for rule-3-only profiles |

No JSON Schema change, no example change, and no ConformanceSpec change: the
suite does not enforce authoring SHOULDs, and no existing requirement is
affected. The reference engine already orders candidates by `updated_at` and
already rejects ties with `AJ-108`.

## Backward compatibility

Not a breaking change. The sentence adds guidance; it invalidates no document and
changes no selection outcome. Profiles without `updated_at` keep their current
behaviour in both directions: selected when unique, rejected with `AJ-108` when
tied with another printer-level profile.

## Alternatives considered

- **MUST for profiles that can only match at rule 3.** Rejected for the four
  reasons above — chief among them that it does not eliminate ties when
  timestamps are equal, while making an otherwise valid document invalid.
- **MUST for every profile.** Rejected: it burdens stock-specific and
  page-format profiles, which can only tie against peers that the same rule
  already orders by their narrower target, and it goes beyond the question
  RFC-0002 left open.
- **Express the requirement as a JSON Schema conditional.** Technically possible,
  since "target absent or without `stock_id`/`page_format`" is expressible with
  `if`/`then`. Rejected: it moves a selection-ordering concern into structural
  validation, where it cannot see the other profiles and still cannot prevent
  equal timestamps.
- **Do nothing and rely on the RFC-0002 compatibility note.** Rejected: the
  guidance currently lives only in a historical RFC, while implementers and
  calibration tools read the specification.

## Unresolved questions

- Should the ambiguous-profile error name the profiles that tied? That is an API
  error-detail change under the REST API specification and belongs in a separate
  proposal, not here.
- Should this SHOULD become a MUST in a later version, once profile tooling
  always writes `updated_at`? Revisit with deployment evidence rather than
  pre-emptively.
