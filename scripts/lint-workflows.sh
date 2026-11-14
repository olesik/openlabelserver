#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if ! command -v actionlint >/dev/null 2>&1; then
  echo "actionlint not installed; validating workflow YAML syntax with Python."
  python3 - <<'PY'
import sys
from pathlib import Path

import yaml

root = Path("scripts").resolve().parents[0]
workflows = sorted((root / ".github" / "workflows").glob("*.yml"))
errors = 0
for workflow in workflows:
    try:
        yaml.safe_load(workflow.read_text(encoding="utf-8"))
        print(f"OK  {workflow.relative_to(root)}")
    except yaml.YAMLError as exc:
        print(f"FAIL {workflow.relative_to(root)}: {exc}", file=sys.stderr)
        errors += 1
raise SystemExit(1 if errors else 0)
PY
  exit $?
fi

actionlint
