#!/usr/bin/env python3
"""Render the conformance report as a GitHub Actions job summary.

The Specification Tests workflow pipes this output into `$GITHUB_STEP_SUMMARY`,
so the per-profile status of a run is visible on the run page instead of only in
the log and the uploaded artifact.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "conformance"))

import runner  # noqa: E402


def _profile_rows(results: list[dict]) -> list[tuple[str, int, int, int, int, str]]:
    """Return one row per claimed profile: total, pass, fail, not tested, status."""

    by_requirement = {entry["requirement"]: entry for entry in results}
    rows = []
    for profile, requirements in runner.PROFILE_REQUIREMENTS.items():
        statuses = [by_requirement[rid]["status"] for rid in requirements if rid in by_requirement]
        passed = statuses.count("pass")
        failed = statuses.count("fail")
        untested = len(requirements) - len(statuses) + statuses.count("not-tested")
        status = "fail" if failed else ("partial" if untested else "pass")
        rows.append((profile, len(requirements), passed, failed, untested, status))
    return rows


def render(report: dict) -> str:
    suite = report.get("suite", {})
    lines = [
        "## Conformance report",
        "",
        f"ConformanceSpec `{report['conformance']}` - suite "
        f"`{suite.get('name')} {suite.get('version')}` - generated "
        f"`{report['generated_at']}`",
        "",
        "| Profile | Requirements | Pass | Fail | Not tested | Status |",
        "| :--- | ---: | ---: | ---: | ---: | :--- |",
    ]
    for profile, total, passed, failed, untested, status in _profile_rows(report["results"]):
        lines.append(f"| `{profile}` | {total} | {passed} | {failed} | {untested} | {status} |")

    summary = report["summary"]
    lines += [
        "",
        f"**{summary['total']} requirement entries** - {summary['passed']} pass, "
        f"{summary['failed']} fail, {summary['not_tested']} not tested.",
    ]

    failures = [entry for entry in report["results"] if entry["status"] == "fail"]
    if failures:
        lines += ["", "### Failures", ""]
        lines += [f"- `{entry['requirement']}`: {entry.get('details', '')}" for entry in failures]

    untested = [entry for entry in report["results"] if entry["status"] == "not-tested"]
    if untested:
        lines += ["", "<details><summary>Requirements not tested</summary>", ""]
        lines += [f"- `{entry['requirement']}`: {entry.get('reason', '')}" for entry in untested]
        lines += ["", "</details>"]
    return "\n".join(lines)


def check() -> int:
    """Render a sample report and verify the table shows every profile."""

    sample = [
        (True, "RS-101", "minimal label accepted"),
        (False, "RS-102", "the document id was not rejected"),
    ]
    markdown = render(runner.build_report(sample))
    expected = [
        "| `CP-RS` |",
        "| `CP-ST` |",
        "| `CP-CAL` |",
        "| fail |",
        "| partial |",
        "1 fail",
        "RS-102",
    ]
    missing = [item for item in expected if item not in markdown]
    if missing:
        print("job summary is missing: " + ", ".join(missing), file=sys.stderr)
        return 1
    print("conformance job summary renders every profile and the failure")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the conformance report as a job summary.")
    parser.add_argument("report", nargs="?", default="conformance-report.json")
    parser.add_argument("--check", action="store_true", help="render a sample report and verify it")
    args = parser.parse_args(argv)

    if args.check:
        return check()

    path = Path(args.report)
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"::warning::no conformance report at {path}; skipping the job summary")
        return 0
    except (OSError, ValueError) as exc:
        print(f"could not read {path}: {exc}", file=sys.stderr)
        return 1

    print(render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
