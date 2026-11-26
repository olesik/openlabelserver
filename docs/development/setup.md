# Local Setup

How to get a working checkout and run the checks CI runs.

Commands below run from the repository root. The gates are POSIX shell, so work
in bash: Linux, macOS, WSL, or Git Bash on Windows.

```bash
git clone https://github.com/olesik/openlabelserver.git
cd openlabelserver
```

## 1. Python environment

Use Python 3.12: both workflows do, and `RO-111` compares the published goldens
byte for byte.

```bash
python3 -m venv .venv
source .venv/bin/activate        # Git Bash on Windows: source .venv/Scripts/activate
python -m pip install -r docker/ci/requirements.txt
```

[docker/ci/requirements.txt](../../docker/ci/requirements.txt) is what the Test
workflow installs ([test.yml](../../.github/workflows/test.yml)), so the schema,
OpenAPI, example, unit and conformance steps run at the versions CI uses,
`fastapi` and `uvicorn` pins included.

The scripts invoke `python3`, not `python`. Windows installers normally provide
only `python.exe` inside the virtual environment, so on Git Bash copy the
interpreter in once:

```bash
cp .venv/Scripts/python.exe .venv/Scripts/python3.exe
```

## 2. Ghostscript

The suite renders the published PostScript goldens with Ghostscript and requires
the result to paint where the PDF of the same document paints (`RO-111`). It
looks for `OPENLABEL_GS`, then `gs`, `gswin64c` and `gswin32c` on `PATH`, and
a missing interpreter fails the case instead of skipping it.

```bash
# Ubuntu/Debian
sudo apt-get update && sudo apt-get install -y --no-install-recommends ghostscript

# macOS
brew install ghostscript

# Windows: choco install ghostscript, or use the official installer, then
# point OPENLABEL_GS at the executable in Git Bash:
export OPENLABEL_GS="$(find 'C:/Program Files/gs' -name gswin64c.exe -print -quit)"
```

Selecting the executable through `OPENLABEL_GS` is what the Determinism
(Windows) job does, so the same export reproduces its run locally.

## 3. Lint and test scripts

```bash
bash scripts/lint.sh    # shell, Python, YAML, Dockerfile and workflow lint
bash scripts/test.sh    # Compose, schemas, OpenAPI, examples, unit tests, conformance
```

Neither script reports success unless every gate ran. A gate whose tool is
missing prints `SKIPPED gate: <tool> is not installed; … not checked.` and exits
`77`; the entrypoint collects those gates, names them and exits `1` instead of
printing its success line.

- `scripts/lint.sh` needs `shellcheck`, `ruff`, `yamllint`, `hadolint` and
  `actionlint` on `PATH`. [CONTRIBUTING.md](../../CONTRIBUTING.md#local-checks)
  carries the install commands and the versions the Lint workflow fetches.
- `scripts/test.sh` needs the `docker` CLI with the Compose v2 plugin, because
  the first gate resolves the Compose files. Without that CLI the rest still
  runs, and the script then exits `1` naming `compose validation`.

The Specification Tests workflow has the suite write a report while it runs and
puts that report into the job summary. Locally, the same two steps print the
summary:

```bash
CONFORMANCE_REPORT=conformance-report.json bash scripts/test.sh
python3 scripts/conformance_summary.py conformance-report.json
```

## 4. Conformance runner

The suite on its own, without the schema, example and unit steps:

```bash
python3 tests/conformance/runner.py                # every case, one line each
python3 tests/conformance/runner.py --filter RO    # only RO-* requirements
python3 tests/conformance/runner.py -q             # failures only
python3 tests/conformance/runner.py --json > conformance-report.json
```

`--json` refuses to run with `--filter`, because a ConformanceSpec report must
cover every requirement of its claimed profiles (`CR-2`); a filtered run is a
progress check, not a report.

Two more entrypoints keep the suite honest and its fixtures current:

```bash
python3 tests/conformance/mutations.py    # five breakages the cases must catch
python3 tests/regression/publish.py       # republish the goldens after an intentional change
```

[conformance/README.md](../../tests/conformance/README.md) describes what the
suite covers and how each reported profile is claimed;
[tests/README.md](../../tests/README.md) covers the test layers.

## Not covered here

Container images and the Compose stack: [docker/README.md](../../docker/README.md).
Branch naming, commit style and the pull request checklist:
[CONTRIBUTING.md](../../CONTRIBUTING.md).
