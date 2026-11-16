# RFCs (Requests for Comments)

RFCs propose significant changes to OpenLabelServer — especially changes to core principles, public specifications, or subsystem boundaries.

## When to write an RFC

- Breaking changes to a published specification
- New public APIs or specification versions
- Architectural decisions that affect multiple subsystems
- Changes to core principles listed in [PROJECT_CHARTER.md](../PROJECT_CHARTER.md)

Minor specification clarifications and bug fixes do not require an RFC. Use a [Specification Change](../.github/ISSUE_TEMPLATE/specification_change.yml) issue instead.

## Process

1. Copy [RFC-0000-template.md](RFC-0000-template.md) to `RFC-NNNN-short-title.md`.
2. Fill in the template and open a pull request for discussion.
3. Address review feedback.
4. Once accepted, implement the change across specifications, schemas, examples, and tests.

Accepted RFCs may be summarized as ADRs under [docs/adr/](../docs/adr/).

## Status

| RFC | Title | Status |
|-----|-------|--------|
| [RFC-0001](RFC-0001-api-validation-and-idempotency-corrections.md) | API Validation and Idempotency Corrections | Accepted |
| [RFC-0002](RFC-0002-calibration-informational-target-selection.md) | CalibrationSpec Selection with Informational Target Fields | Accepted |
| [RFC-0003](RFC-0003-updated-at-for-printer-level-profiles.md) | `updated_at` on Printer-Level Calibration Profiles | Accepted |
| [RFC-0004](RFC-0004-ambiguous-profile-error-context.md) | Machine-Readable Detail for Ambiguous Calibration Profiles | Draft |
