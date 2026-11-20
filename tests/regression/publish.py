"""Publish the RO-111 golden artifacts and their SHA-256 digests.

ConformanceSpec Section 4.2 puts golden artifacts and hash comparison under
`tests/regression/`. This script renders the representative document in
`tests/conformance/fixtures/renderspec/valid/golden_label.json` to PDF and
PostScript, writes each artifact, and records the exact byte length and digest
in `artifacts.json`. The conformance suite re-renders the document and compares
both the bytes and the published digest, so a placement, resource or ordering
change fails with the artifact that moved.

The document sets `compress: false`: deflate output can differ between zlib
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

DOCUMENT = Path("tests/conformance/fixtures/renderspec/valid/golden_label.json")
ARTIFACTS = (
    ("pdf", Path("tests/regression/pdf/golden_label.pdf")),
    ("postscript", Path("tests/regression/postscript/golden_label.ps")),
)
MANIFEST = Path("tests/regression/artifacts.json")


def digest(data: bytes) -> str:
    """The SHA-256 digest RO-111 publishes for an artifact."""

    return hashlib.sha256(data).hexdigest()


def publish() -> dict:
    """Render every golden artifact, write it, and return the manifest."""

    document = renderspec.load(ROOT / DOCUMENT)
    entries = []
    for target, path in ARTIFACTS:
        artifact = output.artifact(document, format=target)
        destination = ROOT / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(artifact)
        entries.append(
            {
                "format": target,
                "document": DOCUMENT.as_posix(),
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
