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

The erratum creates no sub-precedence between an absent `target` and one carrying
only informational fields: both are rule 3 candidates. Section 8's existing
tie-break therefore applies unchanged - the most recent `metadata.updated_at`
wins, and when that cannot order the candidates the job is rejected with an
ambiguous-profile error. A deployment that relied on a bare profile silently
winning over an informational-only one must disambiguate the documents; it must
not rely on `media_type` being ignored to decide the match.

## Specification impact

| Location | Change |
| :--- | :--- |
| [CalibrationSpec Section 8](../specs/calibrationspec/specification.md#8-printer-profile-selection) | Rule 3 wording plus one clarifying sentence |

No JSON Schema change, no example change, and no change to ConformanceSpec:
`CS-114` (precedence) and `CS-122` (`media_type` never selects) already imply
this behaviour, and the suite's `calibration_informational_target_fallback` case
verifies it against the reference engine.

## Backward compatibility

Not a breaking change for documents, but a behavioural change for selection:
profiles that a literal reading made invisible now compete for jobs. There are
three outcomes, and the third can reject work that previously succeeded.

1. **The informational-only profile is alone.** The printer printed uncalibrated
   before and prints calibrated now. This is the change the erratum exists for.
2. **It competes with a bare profile and the timestamps order the candidates.**
   A profile with no `target` and one carrying only `media_type` are peers at
   rule 3, so the newest `metadata.updated_at` wins. That may be the
   informational profile, in which case the job's calibration differs from what
   a literal implementation produced.
3. **It competes with a bare profile and the timestamps cannot order it.** A
   literal implementation selected the bare profile and ignored the other
   because it matched nothing. Under the erratum both match at rule 3, so the
   job MUST be rejected with an ambiguous-profile error (`AJ-108`): a job that
   printed before now fails.

Outcome 3 is a real regression for a deployment, and it is deliberate: the
alternative is to let an informational field decide which profile is used,
which is what Section 6.3 forbids and what this erratum is written to remove.
Section 8 already states that implementations MUST reject rather than choose
arbitrarily.

Migration for a deployment that hits outcome 3: give the profiles distinct
`metadata.updated_at` values, or disambiguate them with `target.stock_id` or
`target.page_format` so they no longer tie at rule 3. No document rewrite is
required by the schema, and outcome 3 cannot arise for a printer with a single
printer-level profile.

CalibrationSpec v1.0 is still a draft and unreleased, so there is no published
behaviour to migrate and no released implementation to coordinate with.

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
- **Rank the absent-target profile above an informational-only one.** Rejected:
  it invents a precedence the numbered list does not contain, and it makes
  `media_type` influence selection again - this time by demoting the profile
  instead of hiding it. Section 8's existing tie-break already resolves the
  cases where an ordering exists.
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
