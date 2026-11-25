# Conformance Suite

Executable checks for the requirements in [ConformanceSpec v1.0](../../specs/conformance/specification.md).

Each case names a requirement ID, a document, and the expected outcome. The suite
enforces the published JSON Schemas plus the semantic rules a schema cannot
express, so a specification change that weakens a rule breaks the suite.

## Current coverage

| Area | Requirement IDs | Status |
|------|-----------------|--------|
| Common rules | `CN-101`–`CN-106` | Covered |
| RenderSpec parser and coordinates | `CN-102`, `CN-105`, against `renderer/` | Covered |
| RenderSpec | `RS-101`–`RS-117` (structural and semantic) | Covered |
| StockSpec | `SS-101`–`SS-103`, `SS-105`–`SS-111`, `SS-114`, `SS-119` | Covered |
| Layout engine | `SS-104`, `SS-113`, `SS-115`, `SS-118`, `RS-118`, against `renderer/layout.py` | Covered |
| Label clipping | `SS-112`, `RT-104`, against `renderer/clip.py` | Covered |
| Page placement | `RT-101`, `RT-102`, against `renderer/layout.py` | Covered |
| Data binding | `RB-101`–`RB-104`, `RT-105`, `RT-106`, against `renderer/binding.py` | Covered |
| Composition | `RT-107`–`RT-112`, `RT-117`, against `renderer/composition.py` | Covered |
| Object primitives | `RT-103`, `RT-113`–`RT-116`, `RT-118`, against `renderer/objects.py`, `renderer/renderspec.py` and `renderer/layout.py` | Covered |
| Renderer output | `RS-119`, `RO-101`–`RO-104`, `RO-106`–`RO-111`, `RO-113`, `DT-101`, `DT-104`, `DT-105`, `DT-107`, against `renderer/output.py`, `renderer/fonts.py`, `renderer/svg.py`, `renderer/pdf.py`, `renderer/postscript.py`, [qr_reader.py](qr_reader.py), [barcode_reader.py](barcode_reader.py) and the [golden artifacts](../regression/) | Covered |
| CalibrationSpec | `CS-101`–`CS-112`, `CS-118`, `CS-120`, `CS-121` | Covered |
| Calibration engine (`CP-CE`) | `CS-113`–`CS-117`, `CS-119`, `CS-122`, against `printing/calibration.py` | Covered |
| Report format | `CR-1`–`CR-7` | Covered |
| Remaining renderer output (`RO`, `DT`) and the remaining `RT` requirements | `RO-105`, `RO-112`, `DT-102`, `DT-106`, `DT-108`, `DT-109` | Not started; needs raster inspection and multi-environment CI |
| REST API (`AP`, `AR`, `AJ`, `AQ`) | — | Not started; needs a server |
| Pipeline and physical (`PL`, `PH`) | — | Not started |

`RO-111` compares the published goldens under
[tests/regression/](../regression/) byte for byte: a base-14 stock label, a
document that sets text in a registered face, and a raster document carrying a
JPEG whole and a paletted PNG. The check verifies the committed files against
their manifest, re-renders each document and reports the observed byte count and
SHA-256 against the published one. It then renders every artifact with
Ghostscript and requires the PostScript one to paint where the PDF of the same
document paints, because byte-identical output can still be a page no
interpreter draws; `OPENLABEL_GS` selects the executable when it is not on
`PATH`, and CI installs it.

A second `RO-111` case reads the raster golden's paletted picture down to the
pixel. Its samples are table indices, so a wrong `Decode` paints every index as
entry 0 while still producing stable bytes and a stable digest. The case
rasterizes both published artifacts and reads the colour painted in each
quadrant of the picture's 2 x 2 grid, requiring the palette entry the source
declares, so neither the regression nor a republished golden with the wrong
`Decode` can pass.

`RO-108` renders a 25 mm `qrcode` at each error-correction level to both
artifacts, rasterizes each at 600 dpi and decodes the symbol back from its
pixels with [qr_reader.py](qr_reader.py) — an ISO/IEC 18004 reader that finds the
finder and timing patterns, reads both format-information copies (level and
mask), unmasks the data area and parses the byte-mode segment. It shares no
table with `renderer/qrcode.py` and reads the single-block versions 1 and 2. The
content, the level, the 25 x 25 module grid and the painted extent within
`0.1` mm must all come back.

The reader also evaluates the block's Reed-Solomon syndromes at every generator
root and requires them zero, and the case checks the degree it evaluated for
each level. It then flips one module of the first error codeword in the `M`
symbol: the data codewords still decode, so only a syndrome can reject it, and
the case requires exactly that (`S0` nonzero) — a misplaced, missing or damaged
error block cannot pass unnoticed.

`RO-107` renders one `barcode` per symbology — `code128`, `code39`, `ean13`,
`ean8`, `upca`, `upce`, `itf`, `codabar` and the stacked `pdf417` — to both
artifacts, rasterizes each at 600 dpi and decodes it back from its pixels with
[barcode_reader.py](barcode_reader.py). The reader fits every element of a scan
line to one module grid, inverts the standard's published pattern tables and
computes its own check digits (modulo 10 and modulo 103), so a wrong bar or a
missing character cannot pass. For `pdf417` it reads every row's start and stop
pattern and codewords, recovers the column, row and error-correction level from
the row indicators, decompacts the byte mode and requires every Reed-Solomon
syndrome to be zero. Each symbol must decode to the payload its symbology prints
— the EAN/UPC check digits are expected back — and paint its declared box within
`0.1` mm.

`RO-103` draws an SVG asset from the RenderSpec Section 7.2.1 profile — a rect, a
circle and a stroked path in a `0 0 20 10` viewBox — and requires the plan to
carry a fill and a stroke and no picture, the artwork to cover its declared
box, and the PDF and PostScript artifacts to carry path operators with no image
XObject or `image` operator. `RO-113` draws two assets outside the profile, one
with a `text` element and one with a gradient reference, and requires each to be
reported by name with no artifact produced.

`RT-118` renders a 40 x 12 mm `code128` and an `ean8` with their caption defaults
and reads the plan's single text run: its content, 2.1167 mm em size, em-box top
at `y + 12.5` mm and centre line at `x + 20` mm must match the section, and
`draw_text: false` must paint no run.

`SS-116`, `SS-117`, `SS-120` and `CS-110` need an API server or a common rule, and
are deferred with the profiles that own them.

## Layout

```text
tests/conformance/
├── cases.json         Declared cases: requirement, document, expected outcome
├── runner.py          Case runner and the computational checks
├── mutations.py       Named renderer breakages that the cases must catch
├── rules.py           Schema plus semantic checks, one rule per requirement ID
├── qr_reader.py       ISO/IEC 18004 reader for the RO-108 raster check
├── barcode_reader.py  ISO/IEC 15417/16388/15420/16390/16389/15438 readers for RO-107
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

`mutations.py` keeps the cases honest. It applies four named renderer breakages —
a group's matrix, its opacity and its visibility ignored, and a creation
timestamp written into the PDF — and requires the case that owns each property
to pass unbroken, then fail with a detail that names the breakage.
`scripts/test.sh` runs it, so a case that stops being able to fail fails the
build instead of reporting the same `pass` whether the renderer honours the
requirement or not. A subset-cache mutation is deliberately absent: no case
renders two documents that reach different glyph sets, so a cache keyed wrongly
would be indistinguishable from a correct one and the mutation would prove
nothing.

```bash
python3 tests/conformance/mutations.py            # every mutation
python3 tests/conformance/mutations.py --filter alpha
```

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
    {"requirement": "SS-116", "status": "not-tested", "reason": "StockSpec to RenderSpec translation belongs to the API profile"}
  ],
  "summary": {"total": 96, "passed": 92, "failed": 0, "not_applicable": 0, "not_tested": 4},
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
