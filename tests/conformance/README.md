# Conformance Suite

Executable checks for the requirements in [ConformanceSpec v1.0](../../specs/conformance/specification.md).

Each case names a requirement ID, a document, and the expected outcome. The suite
enforces the published JSON Schemas plus the semantic rules a schema cannot
express, so a specification change that weakens a rule breaks the suite.

## Current coverage

| Area | Requirement IDs | Status |
|------|-----------------|--------|
| Common rules | `CN-101`, `CN-103`, `CN-104`, `CN-106` | Covered |
| RenderSpec | `RS-101`–`RS-117` (structural and semantic) | Covered |
| StockSpec | `SS-101`–`SS-103`, `SS-105`–`SS-111`, `SS-114`, `SS-119` | Covered |
| CalibrationSpec | `CS-101`–`CS-112`, `CS-118`, `CS-120`, `CS-121` | Covered |
| Report format | `CR-1`–`CR-7` | Covered |
| Renderer output (`RT`, `RB`, `RO`, `DT`) | — | Not started; needs a renderer |
| REST API (`AP`, `AR`, `AJ`, `AQ`) | — | Not started; needs a server |
| Pipeline and physical (`PL`, `PH`) | — | Not started |

`CN-102`, `CN-105`, `RS-118`, `RS-119`, `SS-104`, `SS-112`, `SS-113`, `SS-115`,
`SS-116`–`SS-118`, `SS-120` and `CS-113`–`CS-117`, `CS-119`, `CS-122` need a
renderer, a layout implementation, a calibration engine, the API or a
configurable parser mode, and are deferred with the profiles that own them.

## Layout

```text
tests/conformance/
├── cases.json       Declared cases: requirement, document, expected outcome
├── runner.py        Case runner and the computational checks
├── rules.py         Schema plus semantic checks, one rule per requirement ID
└── fixtures/
    ├── renderspec/{valid,invalid}/
    ├── stockspec/{valid,invalid}/
    └── calibrationspec/{valid,invalid}/
```

Cases point at the published examples under `specs/*/examples/` where one exists,
so the examples are checked by CI in the same pass.

## Running

```bash
python3 tests/conformance/runner.py               # all cases, one line each
python3 tests/conformance/runner.py --filter SS   # only SS-* requirements
python3 tests/conformance/runner.py --json        # ConformanceSpec report
```

The runner exits non-zero if any case fails and prints the requirement, the
fixture and the observed result. It runs from `scripts/test.sh`, so the
**Specification Tests** workflow covers it on every push and pull request.

`CONFORMANCE_REPORT` makes `scripts/test.sh` write the `--json` report as it
runs, and CI publishes that file as the **`conformance-report`** artifact of the
Specification Tests workflow, including when cases fail. `scripts/conformance_summary.py`
turns the same file into the run's job summary: one row per claimed profile with
its pass, fail and not-tested counts, so the profile status is on the run page.

```bash
CONFORMANCE_REPORT=conformance-report.json bash scripts/test.sh
```

### Report output

`--json` prints a report in the Section 16 format of ConformanceSpec v1.0 and
suppresses the per-case lines:

```json
{
  "conformance": "1.0",
  "profiles": ["CP-RS", "CP-ST", "CP-CAL"],
  "implementation": {"name": "OpenLabelServer published specifications", "version": "1.0"},
  "specifications": {"renderspec": "1.0", "stockspec": "1.0", "calibrationspec": "1.0"},
  "suite": {"name": "openlabelserver-conformance", "version": "1.0.0"},
  "environment": {"os": "linux", "arch": "x86_64", "runtime": "python 3.12.3"},
  "results": [
    {"requirement": "RS-101", "status": "pass", "details": "2 case(s) passed"},
    {"requirement": "CN-102", "status": "not-tested", "reason": "coordinate convention needs a renderer or parser implementation"}
  ],
  "summary": {"total": 62, "passed": 48, "failed": 0, "not_applicable": 0, "not_tested": 14},
  "generated_at": "2026-11-15T00:00:00Z"
}
```

The suite claims the document-level profiles `CP-RS`, `CP-ST` and `CP-CAL`. Only
those three are claimed: the renderer, API and physical profiles need an
implementation to observe. `results` holds one entry per requirement of every
claimed profile — a failing case yields `fail` with the observed details, an
executed requirement `pass`, and a requirement in a claimed profile that the
suite does not execute `not-tested` with the reason it is deferred.

A report must cover a whole profile, so `--json` cannot be combined with
`--filter`; the runner rejects that combination instead of emitting a partial
report. Before printing, the report is validated against `CR-1`–`CR-7`
(version, profile completeness, status values, reasons, failure details,
summary consistency, ISO 8601 timestamp) and the run exits non-zero if it does
not hold. The `CR-1` case exercises the same builder and validator.

## Fixture rules

- One invalid fixture per rule, so a failure names a single requirement.
- A case may assert the exact rule (`expect_rule`) and the reported location
  (`expect_path`). A `reject` case is judged on its errors and an `accept` case
  on its warnings, so a RECOMMENDED warning is asserted by accepting the
  document and naming its rule. A path must equal the diagnostic's path exactly,
  never appear in its message, so a location bug cannot hide behind the text.
- `fixtures/renderspec/invalid/nonfinite_coordinate.json` intentionally contains
  a bare `NaN` token. Strict JSON cannot express a non-finite number, and the
  fixture exists to exercise `CN-101`; Python's `json` module accepts it.
- Valid fixtures satisfy every rule the suite implements, so an accepted
  document also proves the rules do not over-reject.

## Adding a case

1. Add the fixture under the matching `valid/` or `invalid/` directory.
2. Add an entry to `cases.json` with the requirement ID, the `spec` kind
   (`renderspec`, `stockspec` or `calibrationspec`), and `expect`.
3. Run the suite; a new semantic rule belongs in `rules.py` with its requirement
   ID as the diagnostic's `requirement`.
