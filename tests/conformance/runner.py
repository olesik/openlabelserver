#!/usr/bin/env python3
"""Fixture-driven conformance runner for OpenLabelServer specifications.

Each case in cases.json names a requirement from
specs/conformance/specification.md, a document to check, and the expected
outcome. Failures report the requirement, the fixture and the observed result.

Usage:
    python3 tests/conformance/runner.py            # run every case
    python3 tests/conformance/runner.py --filter CS  # only CS-* requirements
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

import rules  # noqa: E402


def _failed(message: str) -> tuple[bool, str]:
    return False, message


def run_document_case(case: dict) -> tuple[bool, str]:
    kind = case["spec"]
    document_path = ROOT / case["document"]
    try:
        document = rules.load_document(document_path)
    except (OSError, ValueError) as exc:
        return _failed(f"could not load {case['document']}: {exc}")

    diagnostics = rules.validate(kind, document)
    errors = [d for d in diagnostics if d.severity == "error"]
    warnings = [d for d in diagnostics if d.severity != "error"]
    expected = case["expect"]

    if expected == "accept":
        if errors:
            return _failed("expected acceptance, got: " + "; ".join(d.render() for d in errors))
        return True, f"accepted ({len(warnings)} warning(s))"

    if not errors:
        return _failed("expected rejection, document was accepted")

    expected_rule = case.get("expect_rule")
    if expected_rule and not any(d.requirement == expected_rule for d in errors):
        return _failed(
            f"rejected without {expected_rule}: " + "; ".join(d.render() for d in errors)
        )

    expected_path = case.get("expect_path")
    if expected_path:
        haystack = " | ".join(f"{d.path} {d.message}" for d in errors)
        if expected_path not in haystack:
            return _failed(f"diagnostics do not mention {expected_path!r}: {haystack}")
    return True, "rejected as expected"


def _calibration_worked_example() -> tuple[bool, str]:
    """CS-112: the normative worked example in ConformanceSpec §9.3."""

    transform = {
        "offset": {"x": 2.0, "y": -1.0},
        "scale": {"x": 1.02, "y": 0.98},
        "rotation": {"angle": 1.5, "origin": {"x": 100.0, "y": 50.0}},
    }
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
        f"; 90° maps (10, 0) to ({convention[0]:.6f}, {convention[1]:.6f}), "
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


COMPUTATIONS = {
    "calibration_worked_example": _calibration_worked_example,
    "calibration_identity": _calibration_identity,
    "calibration_yaml_json_equivalence": _calibration_yaml_json_equivalence,
    "diagnostic_location": _diagnostic_location,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run OpenLabelServer conformance cases.")
    parser.add_argument(
        "--filter",
        metavar="PREFIX",
        help="only run requirement IDs starting with this prefix (e.g. SS)",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="only print failures")
    args = parser.parse_args(argv)

    import json

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

    for ok, requirement, detail in results:
        if ok and args.quiet:
            continue
        print(f"{'PASS' if ok else 'FAIL'}  {requirement:<12} {detail}")

    failures = [r for r in results if not r[0]]
    passed = len(results) - len(failures)
    print()
    print(f"{passed}/{len(results)} conformance cases passed.")
    if failures:
        print(f"{len(failures)} case(s) failed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
