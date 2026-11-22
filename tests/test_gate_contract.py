"""Regression tests for the skipped-gate contract of the check entrypoints.

A gate whose tool is missing exits `77` after printing
`SKIPPED gate: <tool> is not installed; <what> not checked.` No entrypoint may
then report success: `scripts/lint.sh` names the gates that never ran and fails,
and `scripts/test.sh` does the same for its steps. These tests run both
entrypoints with a `PATH` whose tools are stubs, so the contract is pinned without
needing the real linters, a Docker CLI or Ghostscript.

Each case has a passing counterpart, so a `PATH` that broke the entrypoint
outright could not satisfy the failure assertion for the wrong reason.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# The shell and Dockerfile gates feed file lists from `find` into `sort`; empty
# stubs keep those gates cheap and keep a platform `find` from changing the result.
QUIET_STUBS = ("find", "sort")

# Shell utilities the scripts invoke besides their gates. They are symlinked into
# the stub directory when the real directory holding them is dropped to hide a tool.
UTILITIES = ("bash", "dirname")


def _write_stub(directory: Path, name: str, body: str = "exit 0") -> None:
    path = directory / name
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _stub_path(tmp_path: Path, *, installed: tuple[str, ...], missing: str | None) -> dict[str, str]:
    """Build an environment whose `PATH` resolves `installed` to stubs."""

    stub_dir = tmp_path / "bin"
    stub_dir.mkdir(exist_ok=True)
    for name in (*QUIET_STUBS, *installed):
        _write_stub(stub_dir, name)
    # Announce the interpreter stub, so a test that stubs `python3` can prove the
    # stub ran the suite steps and the real interpreter did not re-enter the suite.
    if "python3" in installed:
        _write_stub(stub_dir, "python3", "echo stub-python3")

    directories = [entry for entry in os.environ.get("PATH", "").split(os.pathsep) if entry]
    if missing is not None:
        # Drop every directory that holds the tool, so no real copy can be found.
        directories = [entry for entry in directories if shutil.which(missing, path=entry) is None]

    for utility in UTILITIES:
        real = shutil.which(utility)
        if shutil.which(utility, path=os.pathsep.join(directories)) is None:
            if real is None:
                pytest.skip(f"cannot build an isolated PATH: {utility} is not installed")
            os.symlink(real, stub_dir / utility)

    return {**os.environ, "PATH": os.pathsep.join([str(stub_dir), *directories])}


def _run(scripts: str, env: dict[str, str]) -> tuple[int, str]:
    bash = shutil.which("bash")
    assert bash is not None
    result = subprocess.run(
        [bash, str(ROOT / "scripts" / scripts)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    return result.returncode, result.stdout + result.stderr


LINT_TOOLS = ("shellcheck", "ruff", "yamllint", "hadolint")


def test_lint_fails_and_names_the_gate_when_a_tool_is_missing(tmp_path: Path) -> None:
    env = _stub_path(tmp_path, installed=LINT_TOOLS, missing="actionlint")

    status, output = _run("lint.sh", env)

    assert status != 0, output
    assert "SKIPPED gate: actionlint is not installed; workflow lint not checked." in output
    assert "Lint gates skipped because a tool is missing:" in output
    assert "  - scripts/lint-workflows.sh" in output
    assert "All lint checks passed." not in output


def test_lint_passes_when_every_tool_is_present(tmp_path: Path) -> None:
    env = _stub_path(tmp_path, installed=(*LINT_TOOLS, "actionlint"), missing=None)

    status, output = _run("lint.sh", env)

    assert status == 0, output
    assert "SKIPPED gate:" not in output
    assert "All lint checks passed." in output


def test_test_suite_fails_and_names_the_step_when_docker_is_missing(tmp_path: Path) -> None:
    env = _stub_path(tmp_path, installed=("python3",), missing="docker")

    status, output = _run("test.sh", env)

    assert "stub-python3" in output, output
    assert status != 0, output
    assert "SKIPPED gate: docker is not installed; compose validation not checked." in output
    assert "Test steps skipped because a tool is missing:" in output
    assert "  - compose validation" in output
    assert "All tests passed." not in output


def test_test_suite_passes_when_docker_is_present(tmp_path: Path) -> None:
    env = _stub_path(tmp_path, installed=("python3", "docker"), missing=None)

    status, output = _run("test.sh", env)

    assert "stub-python3" in output, output
    assert status == 0, output
    assert "SKIPPED gate:" not in output
    assert "All tests passed." in output
