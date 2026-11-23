"""Publish the RO-111 golden artifacts and their SHA-256 digests.

ConformanceSpec Section 4.2 puts golden artifacts and hash comparison under
`tests/regression/`. This script renders each published document to PDF and
PostScript, writes every artifact, and records the exact byte length and digest
in `artifacts.json`. The conformance suite re-renders the documents and compares
both the bytes and the published digest, so a placement, resource or ordering
change fails with the artifact that moved.

Three documents are published: `golden_label.json` pins placement and resource
order with base-14 text, `golden_font.json` pins the bytes a registered face adds
— the embedded subset, the `/W` widths, the `/ToUnicode` CMap and the Type 42
prolog — and `golden_image.json` pins raster assets carried unchanged: the image
XObject and `/DCTDecode` stream of a JPEG, the box `preserve_aspect_ratio` fits it
into, and an indexed PNG's colour space, depth-wide Decode and unfiltered rows,
whose painted quadrants the conformance suite also reads.
The fixture pictures under `tests/conformance/fixtures/renderspec/assets/` are
inputs, not artifacts: `mark.jpg` was encoded once from a tiny PostScript program
and `mark.png` written with `struct` and `zlib`, and both are committed so the
goldens do not depend on an encoder being installed.

Both documents set `compress: false`: deflate output can differ between zlib
builds, and a golden that depended on one would not be reproducible across the
environments Section 12 requires. Compression itself is covered by `RO-106`.

Regenerate after an intentional change, and read the diff before committing:

    python3 tests/regression/publish.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from renderer import output, renderspec  # noqa: E402

GOLDENS = ("golden_label", "golden_font", "golden_image")
FORMATS = {"pdf": "pdf", "postscript": "ps"}
FIXTURES = Path("tests/conformance/fixtures/renderspec/valid")
ARTIFACTS = Path("tests/regression")
MANIFEST = ARTIFACTS / "artifacts.json"


def digest(data: bytes) -> str:
    """The SHA-256 digest RO-111 publishes for an artifact."""

    return hashlib.sha256(data).hexdigest()


def publish() -> dict:
    """Render every golden document, write its artifacts, and return the manifest."""

    entries = []
    for stem in GOLDENS:
        fixture = FIXTURES / f"{stem}.json"
        document = renderspec.load(ROOT / fixture)
        for target, extension in FORMATS.items():
            artifact = output.artifact(document, format=target)
            path = ARTIFACTS / target / f"{stem}.{extension}"
            destination = ROOT / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(artifact)
            entries.append(
                {
                    "format": target,
                    "document": fixture.as_posix(),
                    "path": path.as_posix(),
                    "bytes": len(artifact),
                    "sha256": digest(artifact),
                }
            )
            print(f"wrote {path} ({len(artifact)} bytes, sha256 {digest(artifact)})")
    return {"requirement": "RO-111", "artifacts": entries}


def main() -> None:
    manifest = publish()
    (ROOT / MANIFEST).write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"wrote {MANIFEST}")


if __name__ == "__main__":
    main()
