# RFC-0002: CalibrationSpec Selection with Informational Target Fields

- **Status:** Draft
- **Author(s):** OpenLabelServer maintainers
- **Created:** 2026-11-15
- **Updated:** 2026-11-15
- **Specification:** OpenLabelServer CalibrationSpec v1.0

## Summary

Corrects the third precedence rule in [CalibrationSpec Section 8](../specs/calibrationspec/specification.md#8-printer-profile-selection).
It currently requires "`target` is absent", which excludes a profile whose
`target` carries only informational fields — today `target.media_type`, which
Section 6.3 marks informational and ConformanceSpec `CS-122` forbids using for
selection. The rule becomes: `target` is absent **or carries only informational
fields**.

## Motivation

Three statements in CalibrationSpec v1.0 cannot all hold for a document like:

```yaml
printer: { identifier: zebra-zd421 }
target: { media_type: thermal-direct }
```

1. Section 6.3 defines `target.media_type` as "Informational; MUST NOT be used
   for profile selection in v1.0."
2. Section 8 rule 3 selects an enabled profile whose `printer.identifier` matches
   and whose `target` is **absent**.
3. Section 8 rule 2 selects a printer-and-`page_format` profile only when
   `target.stock_id` is absent and `target.page_format` matches.

The document above matches none of the three numbered rules: it has a `target`,
so rule 3 does not apply, and it has no `page_format`, so rule 2 does not apply.
The profile is therefore unreachable — a field that is defined as never
influencing selection silently switches a profile off. Implementations cannot
tell whether that is the intended reading or an oversight, and the two readings
produce different printing behaviour for the same profile and job.

The reference engine in [printing/calibration.py](../printing/calibration.py)
takes the reading that informational fields impose no condition, and the
conformance suite pins it (`CS-114`, `CS-122`). The specification text should say
so rather than leave a conforming implementation to guess.

## Detailed design

Replace Section 8 rule 3:

> 3. Enabled profile where `printer.identifier` matches AND `target` is absent.

with:

> 3. Enabled profile where `printer.identifier` matches AND `target` is either
>    absent or carries only informational fields.

and add one clarifying sentence after the numbered list:

> The selection-bearing fields of `target` are `stock_id` and `page_format`. A
> `target` that carries neither MUST be treated exactly as an absent `target`,
> regardless of any informational fields it also carries (Section 6.3).

The precedence itself does not change, and neither do rules 1, 2 or 4:

- A profile with `target.stock_id` still matches only the stock it names, and
  never a different stock that shares a `page_format` (`CS-116`).
- A profile with `target.page_format` and no `stock_id` still matches only when
  the job supplies that page format, and still outranks a printer-only profile.
- A `target` carrying `page_format` does not fall through to rule 3 when the job
  has no page format: rule 2 is the only rule for it, and it does not match.

No schema change: `target` already permits both fields to be omitted.

## Specification impact

| Location | Change |
| :--- | :--- |
| [CalibrationSpec Section 8](../specs/calibrationspec/specification.md#8-printer-profile-selection) | Rule 3 wording plus one clarifying sentence |

No JSON Schema change, no example change, and no change to ConformanceSpec:
`CS-114` (precedence) and `CS-122` (`media_type` never selects) already imply
this behaviour, and the suite's `calibration_informational_target_fallback` case
verifies it against the reference engine.

## Backward compatibility

Not a breaking change for documents: every profile that selected before still
selects, and every profile that was skipped only because of an informational
field now selects at the printer-only level.

- An implementation that read "absent" literally excluded such profiles. After
  the erratum it becomes non-conforming, but the observable difference appears
  only for profiles the erratum was written to rescue — none can select at a
  higher precedence, so no job picks a *different* calibration than before.
- CalibrationSpec v1.0 is still a draft and unreleased; there is no published
  behaviour to migrate.

## Alternatives considered

- **Require `target` to be omitted when it carries no selection fields.** Rejected:
  it invalidates documents that are useful and readable, and a schema cannot
  express "omit this object if its only member is informational" without
  forbidding `media_type` outright.
- **Treat `target.media_type`-only profiles as non-conformant documents.** Rejected:
  Section 6.3 calls the field informational, not invalid, and `CS-122` expects
  two profiles differing only in `media_type` to behave identically — which
  should include both being selectable.
- **Leave the specification and document the reading in implementation notes.**
  Rejected: the selection precedence is normative and public; third-party
  implementations must be able to derive it from the specification alone.
- **Handle it as a Specification Change issue.** Rejected: the RFCS README reserves
  the issue template for clarifications with no behavioural effect, and this
  changes which profiles can be selected.

## Unresolved questions

- Should the clarifying sentence enumerate informational fields, or state the
  general rule (anything that is not `stock_id` or `page_format`)? The proposal
  states the general rule and cites Section 6.3, so a future informational field
  does not reopen this text.
- If a future CalibrationSpec version adds a selection-bearing target field, the
  sentence must be updated in the same change that introduces it. No action for
  v1.0.
