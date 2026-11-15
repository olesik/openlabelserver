# RFC-0002: CalibrationSpec Selection with Informational Target Fields

- **Status:** Accepted
- **Author(s):** OpenLabelServer maintainers
- **Created:** 2026-11-15
- **Updated:** 2026-11-15
- **Accepted:** 2026-11-15
- **Specification:** OpenLabelServer CalibrationSpec v1.0

## Summary

Corrects the third precedence rule in [CalibrationSpec Section 8](../specs/calibrationspec/specification.md#8-printer-profile-selection).
As published, it required "`target` is absent", which excluded a profile whose
`target` carries only informational fields — today `target.media_type`, which
Section 6.3 marks informational and ConformanceSpec `CS-122` forbids using for
selection. The rule becomes: `target` is absent **or carries only informational
fields**. Accepted on 2026-11-15; the Section 8 and `CS-114` wording landed in the
same change.

## Motivation

Three statements in CalibrationSpec v1.0 cannot all hold for a document like:

```yaml
printer: { identifier: zebra-zd421 }
target: { media_type: thermal-direct }
```

1. Section 6.3 marks `target.media_type` informational: "Informational; MUST NOT
   be used for profile selection in v1.0."
2. Section 8 rule 3 selects an enabled profile whose `printer.identifier` matches
   and whose `target` is **absent**.
3. Section 8 rule 2 selects a printer-and-`page_format` profile only when
   `target.stock_id` is absent and `target.page_format` matches.

The document above matches none of the first three rules: it has a `target`, so
rule 3 does not apply, and it has no `page_format`, so rule 2 does not apply. The
job falls through to rule 4 (identity) and the profile is unreachable — a field
that is defined as never influencing selection silently switches a profile off.
Implementations cannot tell whether that is the intended reading or an oversight,
and the two readings produce different printing behaviour for the same profile
and job.

The reference engine in [printing/calibration.py](../printing/calibration.py)
takes the reading that informational fields impose no condition, and the
conformance suite pins it (`CS-114`, `CS-115`, `CS-122`). The specification text
should say so rather than leave a conforming implementation to guess.

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

No schema change: `target` requires neither field and permits both to be
omitted.

The erratum creates no sub-precedence between an absent `target` and one carrying
only informational fields: both are rule 3 candidates. Section 8's tie-break
applies unchanged — implementations SHOULD prefer the profile with the most
recent `updated_at`, and when timestamps are equal or absent they MUST reject the
job with an ambiguous-profile error (`AJ-108`).

## Specification impact

| Location | Change |
| :--- | :--- |
| [CalibrationSpec Section 8](../specs/calibrationspec/specification.md#8-printer-profile-selection) | Rule 3 wording plus one clarifying sentence |
| [ConformanceSpec Section 9.2, `CS-114`](../specs/conformance/specification.md#92-application-cp-ce) | Its description repeats rule 3 as "matching `printer.identifier` with no `target`"; it must read "with no `target`, or one carrying only informational fields" |

No JSON Schema change and no example change. `CS-115` already requires rejection
when profiles match at the same precedence level, so the level-3 tie needs no new
requirement; the suite already covers this behaviour through
`calibration_informational_target_fallback` (`CS-114`) and the level-3 tie
scenario added to the `CS-115` case.

## Backward compatibility

The schema and every valid document are unchanged; selection behaviour is not.
Profiles that a literal reading made invisible now compete for jobs, in three
outcomes — the third rejects work that previously succeeded.

1. **The informational-only profile is alone.** The printer printed uncalibrated
   and prints calibrated now. This is the change the erratum exists for.
2. **It ties at rule 3 and the timestamps order the tie.** The other candidate is
   a bare profile, or another informational-only profile. Implementations SHOULD
   prefer the most recent `updated_at`, which may now be the informational
   profile, so the job's calibration differs from what a literal implementation
   produced — including two informational-only profiles, which previously both
   fell through to identity.
3. **It ties at rule 3 and the timestamps cannot order it.** A literal
   implementation selected the bare profile and ignored the informational one
   because it matched nothing; with two informational-only profiles it selected
   neither. Under the erratum every candidate matches at rule 3, so the job MUST
   be rejected with an ambiguous-profile error (`AJ-108`): a job that printed
   before now fails.

Outcome 3 is a real regression, and it is deliberate: the alternative is to let
an informational field decide which profile is used, which is what Section 6.3
forbids and what this erratum removes. Section 8 already states that
implementations MUST reject rather than choose arbitrarily.

Migration for a deployment that hits outcome 3: give the profiles distinct
`metadata.updated_at` values, or disambiguate them with `target.stock_id` or
`target.page_format` so they no longer tie at rule 3. No document rewrite is
required by the schema, and outcome 3 cannot arise for a printer with a single
printer-level profile.

CalibrationSpec v1.0 is a draft and unreleased, so there is no published
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
  `media_type` influence selection again — this time by demoting the profile
  instead of hiding it.
- **Handle it as a Specification Change issue.** Rejected: the RFCS README reserves
  the issue template for clarifications with no behavioural effect, and this
  changes which profiles can be selected.

## Unresolved questions

- Should a later revision require `metadata.updated_at` on a profile that can only
  match at rule 3, so outcome 3 fails at authoring time instead of at print time?
  Not proposed here: it adds a validation rule to fix a case that disambiguation
  already resolves, and it belongs in a version that may change validation.
