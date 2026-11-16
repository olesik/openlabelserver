# ADR-0004: Informational Target Fields Do Not Decide Profile Selection

- **Status:** Accepted
- **Date:** 2026-11-15
- **Deciders:** Project Lead

## Context

CalibrationSpec Section 6.3 marks `target.media_type` as informational and states
it MUST NOT be used for profile selection. Section 8, however, granted the
printer-only precedence level to a profile whose `target` is *absent*, so a
profile carrying only `media_type` matched none of the selecting rules and the
job fell through to identity. A field defined as never influencing selection
therefore switched a profile off, and it was not possible to tell from the text
whether that was intended.

The reference engine already treated informational fields as imposing no
condition, and ConformanceSpec `CS-114` and `CS-122` pinned that behaviour, which
left the specification as the part that needed correcting. [RFC-0002](../../rfcs/RFC-0002-calibration-informational-target-selection.md)
proposed the correction and was accepted on 2026-11-15.

## Decision

Define the printer-only precedence level by the *absence of selection-bearing
fields*, not by the absence of the `target` object.

1. **Rule 3 covers informational-only targets.** Section 8 rule 3 selects an
   enabled profile where `printer.identifier` matches and `target` is either
   absent or carries only informational fields.
2. **Name the selection fields.** The selection-bearing fields of `target` are
   `stock_id` and `page_format`; a `target` that carries neither MUST be treated
   exactly as an absent `target`, whatever informational fields it also carries.
   `target.media_type` remains informational and still never selects.
3. **No sub-precedence.** An absent target and an informational-only target are
   peers at rule 3, so Section 8's existing tie-break decides between them:
   implementations SHOULD prefer the most recent `updated_at` and MUST reject
   with an ambiguous-profile error when timestamps are equal or absent.
4. **The conformance requirement follows.** ConformanceSpec `CS-114` restates the
   clause and was amended with the specification.

## Consequences

### Positive

- An informational field can no longer disable a profile by its presence.
- Selection precedence is derivable from Section 8 alone, without inferring it
  from Section 6.3.
- No schema or example change: `target` had no required members, and the
  reference engine and conformance suite already behaved this way.

### Negative

- A profile that was previously invisible is now a candidate, which can turn a
  silent selection into an `AJ-108` ambiguity rejection, or select the
  informational-only profile where a bare one used to win.
- Deployments with more than one printer-level profile must disambiguate them
  with `metadata.updated_at` or a `stock_id` / `page_format` constraint.
  [RFC-0003](../../rfcs/RFC-0003-updated-at-for-printer-level-profiles.md)
  settles that guidance as a SHOULD rather than a MUST, since the tie is already a
  deterministic error.

## References

- [RFC-0002: CalibrationSpec Selection with Informational Target Fields](../../rfcs/RFC-0002-calibration-informational-target-selection.md)
- [CalibrationSpec v1.0 Section 6.3](../../specs/calibrationspec/specification.md#63-target-object-target)
- [CalibrationSpec v1.0 Section 8](../../specs/calibrationspec/specification.md#8-printer-profile-selection)
- [ConformanceSpec v1.0 `CS-114`, `CS-115`, `CS-122`](../../specs/conformance/specification.md#92-application-cp-ce)
- [Reference calibration engine](../../printing/calibration.py)
