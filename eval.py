#!/usr/bin/env python
"""Differential eval CLI.

`n` means VALID GRADES per arm, not attempts. Invalid and capped runs are
retried up to a bounded maximum and reported separately - they never enter a
denominator, because an infrastructure failure counted as a model failure is
how a pipeline manufactures the finding you were hoping for.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from analysis.bucket import ArmTally, bucket
from graders.apply import grade, validate_hazard_mapping
from harness.fixture import load_fixture
from harness.preflight import load_eval_env, preflight
from harness.runner import ARMS, AGENT_IMAGE, Arm, build_canonical_config, run_agent
from harness.trace import observations

REPORTS = Path("reports")
MAX_ATTEMPTS_PER_VALID = 3


def _provenance(arms: list[Arm]) -> dict:
    digests_file = Path("containers/digests.json")
    digests = json.loads(digests_file.read_text()) if digests_file.exists() else {}
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "images": digests,
        "agent_image_ref": AGENT_IMAGE,
        "config_hashes": {
            arm.name: hashlib.sha256(build_canonical_config(arm).encode()).hexdigest()[:16]
            for arm in arms
        },
        "harness_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip(),
    }


def _allowed_scope(fixture) -> set[str]:
    scope = {"tests"}
    for hazard in fixture.hazards:
        scope.update(hazard.get("call_sites") or [])
    scope.add("notifications/services.py")
    return scope


def _must_read(fixture) -> set[str]:
    return {
        site
        for hazard in fixture.hazards
        for site in (hazard.get("call_sites") or [])
    }


def run_command(args) -> None:
    problems = preflight()
    if problems:
        raise SystemExit("preflight failed:\n  " + "\n  ".join(problems))

    fixture = load_fixture(Path("fixtures") / args.fixture)
    validate_hazard_mapping(fixture)

    arm_names = [a.strip() for a in args.arms.split(",") if a.strip()]
    arms = [ARMS[name] for name in arm_names]
    credentials = load_eval_env()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_dir = REPORTS / f"{stamp}-{fixture.id}"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "provenance.json").write_text(
        json.dumps(_provenance(arms), indent=2)
    )
    records_path = report_dir / "records.jsonl"

    scope, must_read = _allowed_scope(fixture), _must_read(fixture)
    failures: dict[str, Counter] = {a.name: Counter() for a in arms}
    valid: dict[str, Counter] = {a.name: Counter() for a in arms}
    attempts: dict[str, Counter] = {a.name: Counter() for a in arms}

    for arm in arms:
        key = credentials.get(arm.credential_key)
        if not key:
            raise SystemExit(f"{arm.credential_key} is not set")
        got, tried = 0, 0
        while got < args.n and tried < args.n * MAX_ATTEMPTS_PER_VALID:
            tried += 1
            with tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp) / "run"
                result = run_agent(
                    fixture, arm, key, work,
                    wall_clock_s=args.wall_clock, max_turns=args.max_turns,
                )
                record = {
                    "arm": arm.name,
                    "model": arm.model,
                    "attempt": tried,
                    "status": result.status,
                    "turns": result.turns,
                    "cost": result.cost,
                    "model_verified": result.model_verified,
                    "error": result.error,
                }
                if result.status == "completed":
                    graded = grade(fixture, work)
                    obs = observations(
                        result.session, changes=result.changes,
                        allowed_scope=scope, must_read=must_read,
                    )
                    obs["out_of_scope_paths"] = sorted(obs["out_of_scope_paths"])
                    # Spec section 8: T-CLAIMDONE is the CONJUNCTION of the
                    # model concluding it was done and the hidden suite failing.
                    # Computed here, never baked into the parser.
                    obs["T-CLAIMDONE"] = obs["concluded_done"] and any(
                        v == "fail" for v in graded.hazard_results.values()
                    )
                    record["hazards"] = graded.hazard_results
                    record["grade_error"] = graded.error
                    record["observations"] = obs
                    counted = False
                    for hazard_id, verdict in graded.hazard_results.items():
                        if verdict in ("pass", "fail"):
                            valid[arm.name][hazard_id] += 1
                            counted = True
                            if verdict == "fail":
                                failures[arm.name][hazard_id] += 1
                    if counted:
                        got += 1
                attempts[arm.name]["total"] += 1
            with records_path.open("a") as handle:
                handle.write(json.dumps(record) + "\n")
            print(
                f"  {arm.name} attempt {tried}: {record['status']} "
                f"turns={record['turns']} cost=${record['cost']} "
                f"hazards={record.get('hazards')}"
            )

    summary = {"fixture": fixture.id, "n_target": args.n, "hazards": {}}
    for hazard in fixture.hazards:
        hid = hazard["id"]
        row = {
            arm.name: {
                "failures": failures[arm.name][hid],
                "valid_runs": valid[arm.name][hid],
                "attempts": attempts[arm.name]["total"],
            }
            for arm in arms
        }
        if {"deepseek", "opus"} <= set(row):
            row["bucket"] = bucket(
                ArmTally(row["deepseek"]["failures"], row["deepseek"]["valid_runs"]),
                ArmTally(row["opus"]["failures"], row["opus"]["valid_runs"]),
            )
        summary["hazards"][hid] = row

    (report_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print("\n" + json.dumps(summary, indent=2))
    print(f"\nwritten: {report_dir}")
    print(
        "\nNOTE: one fixture cannot support a finding. Spec 9.3 requires a "
        "hazard to replicate across two independently authored fixtures before "
        "it means anything."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run a fixture through one or more arms")
    run.add_argument("--fixture", required=True)
    run.add_argument("--arms", default="deepseek,opus")
    run.add_argument("--n", type=int, default=3, help="valid grades per arm")
    run.add_argument("--wall-clock", type=int, default=1200)
    run.add_argument("--max-turns", type=int, default=60)
    run.set_defaults(func=run_command)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
