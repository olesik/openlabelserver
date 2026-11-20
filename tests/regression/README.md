# Regression artifacts

Golden outputs and their SHA-256 digests (`RO-111`, ConformanceSpec Section 4.2).

The conformance suite re-renders each published document to both vector formats
and compares the bytes with what is committed here, so a change to placement,
resource names, layer order, operator order or the page transform fails with the
artifact that moved instead of passing unnoticed. It also renders every
artifact with Ghostscript and requires the PostScript one to paint where the
PDF paints, so a program no interpreter draws cannot pass.

| Artifact | Format | Document |
| :--- | :--- | :--- |
| `pdf/golden_label.pdf` | PDF 1.4 | `golden_label.json` |
| `postscript/golden_label.ps` | PostScript Level 2 | `golden_label.json` |
| `pdf/golden_font.pdf` | PDF 1.4 | `golden_font.json` |
| `postscript/golden_font.ps` | PostScript Level 2 | `golden_font.json` |
| `artifacts.json` | — | manifest: path, byte count and SHA-256 of each artifact |

`golden_label.json` is stock-grid with two records, so both frame origins and
the per-frame clip are covered, and it carries a rounded panel, a stroked
circle, a dashed rule, bold text and rotated text across two layers.

[golden_font.json](../conformance/fixtures/renderspec/valid/golden_font.json)
sets its text in the registered `Probe Sans` face — the five-glyph fixture under
[conformance/fixtures/renderspec/fonts/](../conformance/fixtures/renderspec/fonts/)
— whose `source` is a base64 data-URI of that program, so the document renders
the same wherever it is published. Its two records set an ASCII run and a
non-ASCII `ü` at two sizes, so the committed bytes pin what `RO-104` writes
around a face: the subset program in `/FontFile2`, the `/W` widths from `hmtx`,
the `/ToUnicode` CMap and the Type 42 prolog of the PostScript program. It
draws text only, because shapes and placement are already pinned by the
base-14 pair.

## Regenerating

After an intentional renderer change, republish and read the diff before
committing:

```bash
python3 tests/regression/publish.py
```

The script renders both formats of every published document, writes the
artifacts, and records their exact byte count and digest in `artifacts.json`.

Both documents set `output.compress: false`: deflate output can differ
between zlib builds, and a golden that depended on one would not be reproducible
across the environments `DT-102`/`DT-106` require. Stream compression is
verified separately by `RO-106`.
