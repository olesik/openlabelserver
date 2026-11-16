# Printing

Print service for submitting rendered output to physical printers.

## Responsibilities

- Printer discovery (IPP)
- CUPS integration and queue management
- Calibration profile application ([CalibrationSpec](../specs/calibrationspec/))
- Print job history
- Raw PostScript submission
- Printer capability detection

## Status

Calibration is implemented in [calibration.py](calibration.py): the
CalibrationSpec Section 7 transform, Section 8 profile selection and the
Section 9.6 recommended-range warnings.

Selection follows the Section 8 precedence, where a `target` carrying only
informational fields (`media_type`) selects at the printer-only level exactly as
an absent `target` does ([ADR-0004](../docs/adr/ADR-0004-informational-target-selection.md)).
Profiles matching at one level are ordered by `metadata.updated_at`; when that
cannot order them the engine rejects with the `AJ-108` ambiguity error instead of
choosing, carrying the tied profile ids and the precedence level for the API's
`AJ-108` context ([RFC-0004](../rfcs/RFC-0004-ambiguous-profile-error-context.md));
that is why Section 6.1 recommends the timestamp for profiles that can only
match at the printer-only level.

The conformance suite verifies this module against ConformanceSpec `CP-CE`
(`CS-112`–`CS-119`) and `CS-122`, and uses it for `CS-106` (angle normalization)
and `CS-120` (YAML/JSON equivalence).

Printer discovery, CUPS/IPP, queue management and job history are not yet
implemented; they begin in Wave 6 per [MILESTONES.md](../MILESTONES.md).

## Ownership

Owned by the **Printing** subsystem. See [AGENTS.md](../AGENTS.md).
