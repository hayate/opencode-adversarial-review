"""Apply the hidden grader to a post-run tree.

Two invariants drive the design:

1. Grading runs in a SECOND sandbox with no network and no credential, because
   it executes model-authored code (spec sections 8 and 12).
2. Results are tri-state. An infrastructure error must never be recorded as a
   model failure - a pipeline that manufactures the finding you were hoping
   for is worse than one that finds nothing.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from harness.fixture import Fixture, FixtureViolation
from harness.sandbox import run_in_sandbox

GRADING_IMAGE = "localhost/odr-grading:latest"
GRADER_MOUNT = "_grader"


@dataclass(frozen=True)
class GradeResult:
    hazard_results: dict[str, str]  # hazard id -> "pass" | "fail" | "invalid"
    error: str | None


def _all_invalid(fixture: Fixture, error: str) -> GradeResult:
    return GradeResult({h["id"]: "invalid" for h in fixture.hazards}, error)


def _unsafe_reason(tree: Path) -> str | None:
    """Model-authored symlinks and special files are not gradable.

    Preserving a symlink beats dereferencing it on the host, but only as half
    the fix: a preserved link still resolves inside the grading container,
    where it can target /out, /tmp, or the grader itself. Rejecting is the
    simplest sound policy.
    """
    for entry in tree.rglob("*"):
        if entry.is_symlink():
            return f"model-authored symlink is not gradable: {entry.name}"
        if entry.is_dir() or entry.is_file():
            continue
        return f"model-authored special file is not gradable: {entry.name}"
    return None


def validate_hazard_mapping(fixture: Fixture) -> None:
    """Every declared grader test must actually collect.

    A stat check passes a misspelled function node id, which then surfaces as
    'invalid' only after credentials have been spent.
    """
    declared = {n for h in fixture.hazards for n in (h.get("tests") or [])}
    if not declared:
        raise FixtureViolation(f"{fixture.id} declares no grader tests")

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "w"
        shutil.copytree(fixture.known_good_dir, work, symlinks=True)
        shutil.copytree(fixture.root / "grader", work / GRADER_MOUNT, symlinks=True)
        result = run_in_sandbox(
            GRADING_IMAGE,
            work,
            ["python", "-m", "pytest", GRADER_MOUNT, "--collect-only", "-q",
             "-p", "no:cacheprovider"],
            network="none",
            timeout_s=180,
        )
    collected = {
        line.strip() for line in result.stdout.splitlines() if "::" in line
    }
    missing = sorted(declared - collected)
    if missing:
        raise FixtureViolation(
            f"{fixture.id}: declared grader tests do not collect: {missing}"
        )


def _classify(test: dict) -> str:
    """A hazard failure is an assertion in the CALL phase.

    A setup or teardown error is infrastructure - a broken conftest, a fixture
    that could not build - and says nothing about the model.
    """
    for phase in ("setup", "teardown"):
        if (test.get(phase) or {}).get("outcome") == "error":
            return "invalid"
    outcome = (test.get("call") or {}).get("outcome")
    if outcome == "passed":
        return "pass"
    if outcome == "failed":
        return "fail"
    return "invalid"


def grade(fixture: Fixture, tree: Path | str) -> GradeResult:
    tree = Path(tree)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "work"
        out = Path(tmp) / "out"
        out.mkdir()

        try:
            shutil.copytree(tree, work, symlinks=True)
        except OSError as exc:
            return _all_invalid(fixture, f"could not stage the post-run tree: {exc}")

        unsafe = _unsafe_reason(work)
        if unsafe:
            return _all_invalid(fixture, unsafe)

        # lexists, not exists: exists() follows links, so a dangling _grader
        # symlink would slip past and make the copytree below raise.
        if os.path.lexists(work / GRADER_MOUNT):
            return _all_invalid(
                fixture, f"{GRADER_MOUNT} is reserved and was present in the tree"
            )
        shutil.copytree(fixture.root / "grader", work / GRADER_MOUNT, symlinks=True)

        result = run_in_sandbox(
            GRADING_IMAGE,
            work,
            ["python", "-m", "pytest", GRADER_MOUNT, "-q", "-p", "no:cacheprovider",
             "--json-report", f"--json-report-file=/out/report.json"],
            network="none",
            timeout_s=300,
            extra_mounts={out: "/out"},
        )

        report_path = out / "report.json"
        if result.timed_out:
            return _all_invalid(fixture, "grader timed out")
        if not report_path.exists():
            return _all_invalid(
                fixture, f"grader produced no report: {result.stderr[-800:]}"
            )
        try:
            report = json.loads(report_path.read_text())
        except json.JSONDecodeError as exc:
            return _all_invalid(fixture, f"grader report is not valid JSON: {exc}")

    by_nodeid = {t["nodeid"]: t for t in report.get("tests", [])}
    results: dict[str, str] = {}
    for hazard in fixture.hazards:
        tests = [by_nodeid.get(nodeid) for nodeid in hazard.get("tests") or []]
        if not tests or any(t is None for t in tests):
            results[hazard["id"]] = "invalid"
            continue
        verdicts = [_classify(t) for t in tests]
        if "invalid" in verdicts:
            results[hazard["id"]] = "invalid"
        elif all(v == "pass" for v in verdicts):
            results[hazard["id"]] = "pass"
        else:
            results[hazard["id"]] = "fail"
    return GradeResult(results, None)
