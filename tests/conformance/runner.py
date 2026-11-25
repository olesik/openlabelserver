#!/usr/bin/env python3
"""Fixture-driven conformance runner for OpenLabelServer specifications.

Each case in cases.json names a requirement from
specs/conformance/specification.md, a document to check, and the expected
outcome. Failures report the requirement, the fixture and the observed result.

Usage:
    python3 tests/conformance/runner.py              # run every case
    python3 tests/conformance/runner.py --filter CS  # only CS-* requirements
    python3 tests/conformance/runner.py --json       # ConformanceSpec report

The `--json` report follows Section 16 of ConformanceSpec v1.0 and is validated
against rules CR-1 to CR-7 before it is printed.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import zlib
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

import engine_cases  # noqa: E402
import renderer_cases  # noqa: E402
import rules  # noqa: E402

REPORT_SCHEMA = ROOT / "specs" / "conformance" / "schema.json"

CONFORMANCE_VERSION = "1.0"
SUITE_NAME = "openlabelserver-conformance"
SUITE_VERSION = "1.0.0"
STATUSES = ("pass", "fail", "not-applicable", "not-tested")


def _ids(prefix: str, first: int, last: int) -> list[str]:
    return [f"{prefix}-{number}" for number in range(first, last + 1)]


COMMON_IDS = _ids("CN", 101, 106)

# Section 3 of ConformanceSpec: the document-level profiles this suite claims.
# Renderer (CP-RND), API (CP-API) and physical (CP-PIPE) profiles are not
# claimed because their requirements need a renderer, a server or a printer.
PROFILE_REQUIREMENTS: dict[str, list[str]] = {
    "CP-RS": COMMON_IDS + _ids("RS", 101, 119),
    "CP-ST": COMMON_IDS + _ids("SS", 101, 120),
    "CP-CAL": COMMON_IDS + _ids("CS", 101, 111) + _ids("CS", 120, 122),
    "CP-CE": COMMON_IDS + _ids("CS", 112, 119),
}

DEFAULT_NOT_TESTED_REASON = "not executed by the suite yet"

# Only requirements of the claimed profiles are ever reported as not-tested, so
# reasons exist for those alone; CP-CE requirements are not claimed.
NOT_TESTED_REASONS = {
    "SS-116": "StockSpec to RenderSpec translation belongs to the API profile",
    "SS-117": "conflicting inline stock needs the API pipeline",
    "SS-120": "catalog uniqueness needs the API server",
    "CS-110": "strict mode rejection is the common rule CN-104; no separate case",
}


def _failed(message: str) -> tuple[bool, str]:
    return False, message


def _listing(diagnostics: list[rules.Diagnostic]) -> str:
    return "none emitted" if not diagnostics else "; ".join(d.render() for d in diagnostics)


def run_document_case(case: dict) -> tuple[bool, str]:
    kind = case["spec"]
    try:
        document = rules.load_document(ROOT / case["document"])
    except (OSError, ValueError) as exc:
        return _failed(f"could not load {case['document']}: {exc}")

    diagnostics = rules.validate(kind, document)
    errors = [d for d in diagnostics if d.severity == "error"]
    warnings = [d for d in diagnostics if d.severity != "error"]
    accepting = case["expect"] == "accept"
    # A reject case is judged on its errors and an accept case on its warnings,
    # so one pair of assertions serves both kinds of case.
    relevant = warnings if accepting else errors

    if accepting and errors:
        return _failed("expected acceptance, got: " + _listing(errors))
    if not accepting and not errors:
        return _failed("expected rejection, document was accepted")

    expected_rule = case.get("expect_rule")
    if expected_rule and not any(d.requirement == expected_rule for d in relevant):
        return _failed(f"no {expected_rule} diagnostic: " + _listing(relevant))

    expected_path = case.get("expect_path")
    if expected_path and not any(d.path == expected_path for d in relevant):
        return _failed(f"no diagnostic path equals {expected_path!r}: " + _listing(relevant))

    if accepting:
        return True, f"accepted ({len(warnings)} warning(s))"
    return True, "rejected as expected"


def _git_revision() -> str | None:
    """The checkout's commit, or `None` when this is not a repository."""

    try:
        done = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    revision = done.stdout.strip()
    if done.returncode != 0 or re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        return None
    return revision


def _suite_commit() -> str:
    """The suite's commit: the CI revision, the checkout's, or `unknown`."""

    return os.environ.get("GITHUB_SHA") or _git_revision() or "unknown"


def _zlib_build() -> str:
    """The zlib that deflates the artifacts, naming the headers when they differ."""

    runtime, headers = zlib.ZLIB_RUNTIME_VERSION, zlib.ZLIB_VERSION
    return runtime if runtime == headers else f"{runtime} (headers {headers})"


def _summarize(entries: list[dict]) -> dict[str, int]:
    counts = Counter(entry.get("status") for entry in entries)
    return {
        "total": len(entries),
        "passed": counts["pass"],
        "failed": counts["fail"],
        "not_applicable": counts["not-applicable"],
        "not_tested": counts["not-tested"],
    }


def build_report(results: list[tuple[bool, str, str]]) -> dict:
    """Build a ConformanceSpec Section 16 report from case results.

    Requirements in a claimed profile that the suite does not execute are
    reported as `not-tested` with a reason, so CR-2 holds for every profile.
    """

    by_requirement: dict[str, list[tuple[bool, str]]] = {}
    for ok, requirement, detail in results:
        by_requirement.setdefault(requirement, []).append((ok, detail))

    ordered = list(
        dict.fromkeys(
            requirement
            for requirements in PROFILE_REQUIREMENTS.values()
            for requirement in requirements
        )
    )
    ordered += [requirement for requirement in by_requirement if requirement not in ordered]

    entries: list[dict] = []
    for requirement in ordered:
        cases = by_requirement.get(requirement)
        if cases is None:
            entries.append(
                {
                    "requirement": requirement,
                    "status": "not-tested",
                    "reason": NOT_TESTED_REASONS.get(requirement, DEFAULT_NOT_TESTED_REASON),
                }
            )
            continue
        failures = [detail for ok, detail in cases if not ok]
        if failures:
            entries.append(
                {"requirement": requirement, "status": "fail", "details": "; ".join(failures)}
            )
        else:
            entries.append(
                {
                    "requirement": requirement,
                    "status": "pass",
                    "details": f"{len(cases)} case(s) passed",
                }
            )

    return {
        "conformance": CONFORMANCE_VERSION,
        "profiles": list(PROFILE_REQUIREMENTS),
        "implementation": {"name": "OpenLabelServer published specifications", "version": "1.0"},
        "specifications": {
            "renderspec": "1.0",
            "stockspec": "1.0",
            "calibrationspec": "1.0",
            "api": "1.0",
        },
        "suite": {"name": SUITE_NAME, "version": SUITE_VERSION},
        "environment": {
            "os": platform.system().lower() or "unknown",
            "arch": platform.machine() or "unknown",
            "runtime": f"python {platform.python_version()}",
            "suite_commit": _suite_commit(),
            "zlib": _zlib_build(),
        },
        "results": entries,
        "summary": _summarize(entries),
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def validate_report(report: dict) -> list[str]:
    """Check a report against CR-1 to CR-7; return the problems found."""

    problems: list[str] = []

    if report.get("conformance") != CONFORMANCE_VERSION:
        problems.append(f"CR-1: conformance must be {CONFORMANCE_VERSION!r}")

    profiles = report.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        problems.append("CR-2: profiles must be a non-empty list")
        profiles = []
    unknown = [name for name in profiles if name not in PROFILE_REQUIREMENTS]
    if unknown:
        problems.append(f"CR-2: unknown profile(s) {unknown}")

    results = report.get("results")
    if not isinstance(results, list) or not results:
        problems.append("CR-2: results must be a non-empty list")
        results = []

    seen: set[str] = set()
    for entry in results:
        requirement = entry.get("requirement")
        status = entry.get("status")
        if not requirement:
            problems.append("CR-2: an entry has no requirement")
            continue
        if requirement in seen:
            problems.append(f"CR-2: duplicate entry for {requirement}")
        seen.add(requirement)
        if status not in STATUSES:
            problems.append(f"CR-3: {requirement} has status {status!r}")
        if status in {"not-applicable", "not-tested"} and not entry.get("reason"):
            problems.append(f"CR-4/CR-5: {requirement} is {status} without a reason")
        if status == "fail" and not entry.get("details"):
            problems.append(f"CR-7: {requirement} failed without details")

    for profile in profiles:
        for requirement in PROFILE_REQUIREMENTS.get(profile, []):
            if requirement not in seen:
                problems.append(f"CR-2: {profile} requires an entry for {requirement}")

    summary = report.get("summary") or {}
    expected_summary = _summarize(results)
    if summary != expected_summary:
        problems.append(f"CR-6: summary is {summary!r}, expected {expected_summary!r}")

    generated_at = report.get("generated_at")
    try:
        datetime.strptime(str(generated_at), "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        problems.append(f"CR-6: generated_at {generated_at!r} is not an ISO 8601 UTC timestamp")

    return problems


def validate_report_schema(report: dict) -> list[str]:
    """Validate a report against the schema published with ConformanceSpec §16."""

    if not REPORT_SCHEMA.is_file():
        return [f"{REPORT_SCHEMA.relative_to(ROOT)} is missing"]
    schema = json.loads(REPORT_SCHEMA.read_text(encoding="utf-8"))
    validator = jsonschema.validators.validator_for(schema)(schema)
    problems: list[str] = []
    for error in validator.iter_errors(report):
        location = "/".join(str(part) for part in error.absolute_path) or "document"
        problems.append(f"{location}: {error.message}")
    return problems


def _calibration_worked_example() -> tuple[bool, str]:
    """CS-112: the normative worked example in ConformanceSpec Section 9.3."""

    # The worked example lives in the file ConformanceSpec §9.3 embeds, so the
    # asserted result and the documented transform cannot drift apart.
    example = ROOT / "specs" / "conformance" / "examples" / "worked_transform.yaml"
    transform = yaml.safe_load(example.read_text(encoding="utf-8"))["transform"]
    observed = rules.apply_calibration((30.0, 40.0), transform)
    expected = (30.881001, 37.334324)
    ok = abs(observed[0] - expected[0]) <= 1e-4 and abs(observed[1] - expected[1]) <= 1e-4
    detail = (
        f"(30, 40) -> ({observed[0]:.6f}, {observed[1]:.6f}); "
        f"expected ({expected[0]}, {expected[1]}) within 1e-4 mm"
    )

    convention = rules.apply_calibration((10.0, 0.0), {"rotation": {"angle": 90}})
    convention_ok = abs(convention[0]) <= 1e-9 and abs(convention[1] - 10.0) <= 1e-9
    detail += (
        f"; 90 degrees maps (10, 0) to ({convention[0]:.6f}, {convention[1]:.6f}), "
        "expected (0, 10) page-clockwise"
    )
    return ok and convention_ok, detail


def _calibration_identity() -> tuple[bool, str]:
    """CS-118: an identity profile leaves coordinates unchanged."""

    document = rules.load_document(
        HERE / "fixtures" / "calibrationspec" / "valid" / "identity_minimal.yaml"
    )
    transform = document.get("transform")
    samples = [(0.0, 0.0), (10.0, 20.0), (50.5, 30.25)]
    for point in samples:
        observed = rules.apply_calibration(point, transform)
        if abs(observed[0] - point[0]) > 1e-9 or abs(observed[1] - point[1]) > 1e-9:
            return _failed(f"identity profile moved {point} to {observed}")
    return True, f"identity profile leaves {len(samples)} sample points unchanged"


def _calibration_yaml_json_equivalence() -> tuple[bool, str]:
    """CS-120: YAML and JSON forms parse to the same object model."""

    base = HERE / "fixtures" / "calibrationspec" / "valid"
    as_yaml = rules.load_document(base / "profile.yaml")
    as_json = rules.load_document(base / "profile.json")
    if as_yaml != as_json:
        return _failed("YAML and JSON forms produce different object models")

    samples = [(0.0, 0.0), (30.0, 40.0)]
    for point in samples:
        from_yaml = rules.apply_calibration(point, as_yaml.get("transform"))
        from_json = rules.apply_calibration(point, as_json.get("transform"))
        if abs(from_yaml[0] - from_json[0]) > 1e-12 or abs(from_yaml[1] - from_json[1]) > 1e-12:
            return _failed(f"forms disagree for {point}: {from_yaml} vs {from_json}")
    return True, f"YAML and JSON profiles agree on {len(samples)} sampled coordinates"


def _calibration_angle_normalization() -> tuple[bool, str]:
    """CS-106: any finite rotation angle is normalized for evaluation."""

    point = (10.0, 0.0)
    pairs = [(450.0, 90.0), (-395.5, -35.5), (720.0, 0.0)]
    for raw, normalized in pairs:
        observed = rules.apply_calibration(point, {"rotation": {"angle": raw}})
        reference = rules.apply_calibration(point, {"rotation": {"angle": normalized}})
        if abs(observed[0] - reference[0]) > 1e-9 or abs(observed[1] - reference[1]) > 1e-9:
            return _failed(f"angle {raw} gave {observed}, expected the {normalized} result")
    return True, "450, -395.5 and 720 degrees match their normalized equivalents"


def _stockspec_yaml_json_equivalence() -> tuple[bool, str]:
    """SS-101: YAML is canonical and equivalent JSON has the same object model."""

    base = HERE / "fixtures" / "stockspec" / "valid"
    as_yaml = rules.load_document(base / "generic_3x7.yaml")
    as_json = rules.load_document(base / "generic_3x7.json")
    if as_yaml != as_json:
        return _failed("YAML and JSON forms produce different object models")
    diagnostics = rules.validate("stockspec", as_json)
    if diagnostics:
        return _failed("the JSON form is rejected: " + "; ".join(d.render() for d in diagnostics))
    return True, "YAML and JSON forms parse to the same model and both validate"


def _diagnostic_location() -> tuple[bool, str]:
    """CN-106: a rejection names the offending path, not just the document."""

    document = rules.load_document(
        HERE / "fixtures" / "renderspec" / "invalid" / "duplicate_object_id.json"
    )
    errors = [d for d in rules.validate("renderspec", document) if d.severity == "error"]
    if not errors:
        return _failed("expected a rejection, document was accepted")
    missing = [d for d in errors if not d.path]
    if missing:
        return _failed("diagnostics without a path: " + "; ".join(d.render() for d in missing))
    return True, f"{len(errors)} diagnostic(s) name a path, e.g. {errors[0].path}"


def _report_is_well_formed() -> tuple[bool, str]:
    """CR-1 to CR-7: the report the runner emits satisfies the format."""

    sample = [
        (True, "RS-101", "minimal label accepted"),
        (False, "RS-102", "document id with a space was accepted"),
        (True, "SS-105", "pitch smaller than label rejected"),
    ]
    report = build_report(sample)
    problems = validate_report(report) + validate_report_schema(report)
    if problems:
        return _failed("; ".join(problems))

    statuses = {entry["requirement"]: entry["status"] for entry in report["results"]}
    environment = report["environment"]
    commit = environment.get("suite_commit")
    build = environment.get("zlib")
    revision = os.environ.get("GITHUB_SHA") or _git_revision()
    checks = {
        "RS-101 passes": statuses.get("RS-101") == "pass",
        "RS-102 fails": statuses.get("RS-102") == "fail",
        "unexecuted requirements are not-tested": any(
            entry["status"] == "not-tested" for entry in report["results"]
        ),
        "summary counts the failure": report["summary"]["failed"] == 1,
        "every profile is listed": report["profiles"] == list(PROFILE_REQUIREMENTS),
        # A report whose environment does not say which revision and which zlib
        # built the artifacts cannot explain a digest that differs by platform.
        "environment names the suite commit": commit
        == (revision or "unknown")
        or (revision is None and re.fullmatch(r"[0-9a-f]{40}", str(commit)) is not None),
        "environment names the zlib build": isinstance(build, str)
        and build.startswith(zlib.ZLIB_RUNTIME_VERSION),
    }
    broken = [name for name, passed in checks.items() if not passed]
    if broken:
        return _failed("report checks failed: " + ", ".join(broken))

    summary = report["summary"]
    return True, (
        f"{summary['total']} entries across {len(report['profiles'])} profiles: "
        f"{summary['passed']} pass, {summary['failed']} fail, {summary['not_tested']} not-tested, "
        f"from commit {str(commit)[:12]} built with zlib {build}"
    )


COMPUTATIONS = {
    **engine_cases.CHECKS,
    **renderer_cases.CHECKS,
    "calibration_worked_example": _calibration_worked_example,
    "calibration_identity": _calibration_identity,
    "calibration_yaml_json_equivalence": _calibration_yaml_json_equivalence,
    "calibration_angle_normalization": _calibration_angle_normalization,
    "stockspec_yaml_json_equivalence": _stockspec_yaml_json_equivalence,
    "diagnostic_location": _diagnostic_location,
    "report_is_well_formed": _report_is_well_formed,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run OpenLabelServer conformance cases.")
    parser.add_argument(
        "--filter",
        metavar="PREFIX",
        help="only run requirement IDs starting with this prefix (e.g. SS)",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="only print failures")
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit a ConformanceSpec report as JSON instead of the per-case lines",
    )
    args = parser.parse_args(argv)

    if args.json and args.filter:
        parser.error(
            "--json cannot be combined with --filter: a report must cover every "
            "requirement of its claimed profiles (CR-2)"
        )

    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    prefix = (args.filter or "").upper()

    results: list[tuple[bool, str, str]] = []
    for case in cases["documents"]:
        requirement = case["requirement"]
        if prefix and not requirement.startswith(prefix):
            continue
        ok, detail = run_document_case(case)
        results.append((ok, requirement, f"{case['description']} — {detail}"))

    for case in cases["computations"]:
        requirement = case["requirement"]
        if prefix and not requirement.startswith(prefix):
            continue
        check = COMPUTATIONS.get(case["check"])
        if check is None:
            results.append((False, requirement, f"unknown computation {case['check']!r}"))
            continue
        ok, detail = check()
        results.append((ok, requirement, f"{case['description']} — {detail}"))

    failures = [result for result in results if not result[0]]

    if args.json:
        report = build_report(results)
        problems = validate_report(report) + validate_report_schema(report)
        if problems:
            for problem in problems:
                print(f"report: schema: {problem}", file=sys.stderr)
            return 1
        print(json.dumps(report, indent=2))
        if failures:
            print(f"{len(failures)} case(s) failed.", file=sys.stderr)
            return 1
        return 0

    for ok, requirement, detail in results:
        if ok and args.quiet:
            continue
        print(f"{'PASS' if ok else 'FAIL'}  {requirement:<12} {detail}")

    passed = len(results) - len(failures)
    print()
    print(f"{passed}/{len(results)} conformance cases passed.")
    if failures:
        print(f"{len(failures)} case(s) failed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
