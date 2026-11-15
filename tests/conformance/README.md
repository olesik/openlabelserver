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
| StockSpec | `SS-102`, `SS-105`–`SS-111`, `SS-114`, `SS-119` | Covered |
| CalibrationSpec | `CS-101`, `CS-103`, `CS-105`, `CS-107`–`CS-112`, `CS-118`, `CS-120`, `CS-121` | Covered |
| Renderer output (`RT`, `RB`, `RO`, `DT`) | — | Not started; needs a renderer |
| REST API (`AP`, `AR`, `AJ`, `AQ`) | — | Not started; needs a server |
| Pipeline and physical (`PL`, `PH`) | — | Not started |

`CN-102`, `CN-105`, `RS-113`, `RS-118`, `CS-114`–`CS-117`, `CS-122` need a
renderer, a calibration engine or a configurable parser mode, and are deferred
with the profiles that own them.

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
python3 tests/conformance/runner.py            # all cases
python3 tests/conformance/runner.py --filter SS # only SS-* requirements
```

The runner exits non-zero if any case fails and prints the requirement, the
fixture and the observed result. It runs from `scripts/test.sh`, so the
**Specification Tests** workflow covers it on every push and pull request.

## Fixture rules

- One invalid fixture per rule, so a failure names a single requirement.
- A case may assert the exact rule (`expect_rule`) and the reported location
  (`expect_path`); both are checked against the diagnostics. Where the message
  alone could satisfy the check, `expect_path_exact` requires a diagnostic whose
  path equals the value, so a location bug cannot hide behind the message text.
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
