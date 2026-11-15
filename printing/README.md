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
CalibrationSpec Section 7 transform, Section 8 profile selection (including the
`AJ-108` ambiguous-profile rejection) and the Section 9.6 recommended-range
warnings. The conformance suite verifies it against ConformanceSpec `CP-CE`
(`CS-113`–`CS-117`, `CS-119`) and `CS-122`.

Printer discovery, CUPS/IPP, queue management and job history are not yet
implemented; they begin in Wave 6 per [MILESTONES.md](../MILESTONES.md).

## Ownership

Owned by the **Printing** subsystem. See [AGENTS.md](../AGENTS.md).
