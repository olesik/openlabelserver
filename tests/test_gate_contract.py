"""Regression tests for the skipped-gate contract of the check entrypoints.

A gate whose tool is missing exits `77` after printing
`SKIPPED gate: <tool> is not installed; <what> not checked.` No entrypoint may
then report success: `scripts/lint.sh` names the gates that never ran and fails,
and `scripts/test.sh` does the same for its steps. These tests run both
entrypoints with a `PATH` whose tools are stubs, so the contract is pinned without
needing the real linters, a Docker CLI or Ghostscript.

Each test also covers the passing case, which proves the stubbed `PATH` really is
what the entrypoint sees: without it, a `PATH` that hid everything would satisfy
the failure assertion for the wrong reason.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Stubs that keep the gates that should run cheap and deterministic: `find` and
# `sort` feed the file lists the shell and Dockerfile gates lint, and the linters
# themselves only have to succeed.
QUIET_STUBS = ("find", "sort")

# Interpreter and shell utilities the scripts invoke besides their gates. They are
# taken from the real `PATH` and copied into the stub directory when the directory
# holding them is the one being removed to hide the missing tool.
UTILITIES = ("bash", "env", "dirname")


def _write_stub(directory: Path, name: str) -> Path:
    path = directory / name
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _stub_path(tmp_path: Path, *, installed: tuple[str, ...], missing: str | None) -> dict[str, str]:
    """Build an environment whose `PATH` resolves `installed` to stubs."""

    stub_dir = tmp_path / "bin"
    stub_dir.mkdir(exist_ok=True)
    for name in (*QUIET_STUBS, *installed):
        _write_stub(stub_dir, name)

    directories = [entry for entry in os.environ.get("PATH", "").split(os.pathsep) if entry]
    if missing is not None:
        # Drop every directory that holds the tool, so no real copy can be found.
        directories = [entry for entry in directories if shutil.which(missing, path=entry) is None]

    for utility in UTILITIES:
        if shutil.which(utility, path=os.pathsep.join(directories)) is not None:
            continue
        real = shutil.which(utility)
        if real is None:
            pytest.skip(f"cannot build an isolated PATH: {utility} is not installed")
        try:
            os.symlink(real, stub_dir / utility)
        except OSError as error:  # pragma: no cover - Windows without symlink support
            pytest.skip(f"cannot build an isolated PATH: {error}")

    env = {name: value for name, value in os.environ.items() if name != "PYTHONPATH"}
    env["PATH"] = os.pathsep.join([str(stub_dir), *directories])
    return env


def _run(scripts: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    assert bash is not None
    return subprocess.run(
        [bash, str(ROOT / "scripts" / scripts)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def _resolution(name: str, env: dict[str, str]) -> str:
    bash = shutil.which("bash")
    assert bash is not None
    result = subprocess.run(
        [bash, "-c", f"command -v {name} || true"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return result.stdout.strip().replace("\\", "/")


LINT_TOOLS = ("shellcheck", "ruff", "yamllint", "hadolint")


def test_lint_fails_and_names_the_gate_when_a_tool_is_missing(tmp_path: Path) -> None:
    env = _stub_path(tmp_path, installed=LINT_TOOLS, missing="actionlint")

    result = _run("lint.sh", env)
    output = result.stdout + result.stderr

    assert result.returncode != 0, output
    assert "SKIPPED gate: actionlint is not installed; workflow lint not checked." in output
    assert "Lint gates skipped because a tool is missing:" in output
    assert "  - scripts/lint-workflows.sh" in output
    assert "All lint checks passed." not in output


def test_lint_passes_when_every_tool_is_present(tmp_path: Path) -> None:
    env = _stub_path(tmp_path, installed=(*LINT_TOOLS, "actionlint"), missing=None)

    result = _run("lint.sh", env)
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "SKIPPED gate:" not in output
    assert "All lint checks passed." in output


def test_test_suite_fails_and_names_the_step_when_docker_is_missing(tmp_path: Path) -> None:
    env = _stub_path(tmp_path, installed=("python3",), missing="docker")

    # The stubbed interpreter must shadow the real one; otherwise this test would
    # re-enter the suite it runs in.
    assert _resolution("python3", env).endswith("/bin/python3")

    result = _run("test.sh", env)
    output = result.stdout + result.stderr

    assert result.returncode != 0, output
    assert "SKIPPED gate: docker is not installed; compose validation not checked." in output
    assert "Test steps skipped because a tool is missing:" in output
    assert "  - compose validation" in output
    assert "All tests passed." not in output


def test_test_suite_passes_when_docker_is_present(tmp_path: Path) -> None:
    env = _stub_path(tmp_path, installed=("python3", "docker"), missing=None)

    assert _resolution("python3", env).endswith("/bin/python3")

    result = _run("test.sh", env)
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "SKIPPED gate:" not in output
    assert "All tests passed." in output
