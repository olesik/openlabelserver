# Regression artifacts

Golden outputs and their SHA-256 digests (`RO-111`, ConformanceSpec Section 4.2).

The conformance suite re-renders
[golden_label.json](../conformance/fixtures/renderspec/valid/golden_label.json)
to both vector formats and compares the bytes with what is committed here, so a
change to placement, resource names, layer order, operator order or the page
transform fails with the artifact that moved instead of passing unnoticed.

| Artifact | Format | Document |
| :--- | :--- | :--- |
| `pdf/golden_label.pdf` | PDF 1.4 | `golden_label.json` |
| `postscript/golden_label.ps` | PostScript Level 2 | `golden_label.json` |
| `artifacts.json` | — | manifest: path, byte count and SHA-256 of each artifact |

The document is stock-grid with two records, so both frame origins and the
per-frame clip are covered, and it carries a rounded panel, a stroked circle, a
dashed rule, bold text and rotated text across two layers.

## Regenerating

After an intentional renderer change, republish and read the diff before
committing:

```bash
python3 tests/regression/publish.py
```

The script renders both formats, writes the artifacts, and records their exact
byte count and digest in `artifacts.json`.

`golden_label.json` sets `output.compress: false`: deflate output can differ
between zlib builds, and a golden that depended on one would not be reproducible
across the environments `DT-102`/`DT-106` require. Stream compression is
verified separately by `RO-106`.
