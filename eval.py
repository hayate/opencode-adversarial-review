#!/usr/bin/env python
"""Differential eval CLI.

`n` means VALID GRADES PER HAZARD per arm, not attempts and not runs. Invalid
and capped runs are retried up to a bounded maximum and reported separately -
they never enter a denominator, because an infrastructure failure counted as a
model failure is how a pipeline manufactures the finding you were hoping for.

The converse matters just as much, and round 1 of the review gauntlet found it
missing. Retrying until n valid grades CONDITIONS on the model's own output
quality: a tree so broken that pytest cannot collect it is a tree where the
hazard test would have failed. Silently resampling those deletes the worst runs
and refills the denominator to a full-looking n. It is not conservative either,
because the bias is set by failure MODE rather than failure rate - a model that
fails gracefully is measured accurately while one that fails catastrophically
has its failures censored, so two arms with identical true rates are measured
as different and the one that fails loudly scores better. Model-caused
ungradable runs are therefore counted and reported as their own rate.
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
from graders.apply import (
    GRADING_IMAGE, MODEL_OUTPUT, grade, validate_hazard_mapping,
)
from harness.fixture import load_fixture
from harness.preflight import (
    load_eval_env, preflight, resolve_image_id, verify_image_digests,
)
from harness.runner import (
    ARMS, AGENT_IMAGE, Arm, assert_sterile, build_canonical_config, run_agent,
)
from harness.trace import observations

REPORTS = Path("reports")
MAX_ATTEMPTS_PER_VALID = 3


def _git(*args: str) -> tuple[int, str]:
    result = subprocess.run(["git", *args], capture_output=True, text=True)
    return result.returncode, result.stdout.strip()


def _provenance(arms: list[Arm]) -> dict:
    digests_file = Path("containers/digests.json")
    digests = json.loads(digests_file.read_text()) if digests_file.exists() else {}

    code, head = _git("rev-parse", "HEAD")
    dirty_code, dirty = _git("status", "--porcelain")
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "images": digests,
        # Runs execute by TAG, so the digests build.sh recorded are only a
        # claim until the tag is checked against them. verify_image_digests()
        # gates the run on that; these are what the tags actually resolved to
        # at run time.
        "images_resolved_at_run": {
            "agent": resolve_image_id(AGENT_IMAGE),
            "grading": resolve_image_id(GRADING_IMAGE),
        },
        "agent_image_ref": AGENT_IMAGE,
        "grading_image_ref": GRADING_IMAGE,
        "config_hashes": {
            arm.name: hashlib.sha256(build_canonical_config(arm).encode()).hexdigest()[:16]
            for arm in arms
        },
        "harness_commit": head if code == 0 else None,
        # A commit alone claims the committed tree ran. It did not, if this is set.
        "harness_dirty": bool(dirty) if dirty_code == 0 else None,
    }


def allowed_scope(fixture) -> set[str]:
    """Paths the ticket puts in bounds.

    Declared by the fixture rather than hardcoded: eval.py used to add
    `notifications/services.py` - fixture #1's own target module - to every
    fixture's scope unconditionally.
    """
    scope = set(fixture.scope)
    for hazard in fixture.hazards:
        scope.update(hazard.get("call_sites") or [])
    # A hazard's excluded paths are out of bounds by definition. Without this
    # the scope model and the grader measured "out of scope" by two unrelated
    # definitions, connected only through call_sites.
    excluded = {
        path
        for hazard in fixture.hazards
        for path in (hazard.get("excluded_paths") or [])
    }
    return scope - excluded


def must_read(fixture) -> set[str]:
    return {
        site
        for hazard in fixture.hazards
        for site in (hazard.get("call_sites") or [])
    }


class Accounting:
    """Per-hazard tallies for one arm.

    Per HAZARD, not per run. The old loop incremented a single arm-wide counter
    whenever ANY hazard produced a verdict, so a multi-hazard fixture could
    exhaust its attempt budget with the headline hazard holding one valid grade
    while a guard hazard held n.
    """

    def __init__(self, hazard_ids, n: int):
        self.hazard_ids = list(hazard_ids)
        self.n = n
        self.valid: Counter = Counter()
        self.failures: Counter = Counter()
        self.ungradable: Counter = Counter()
        self.attempts = 0
        self.capped = 0
        self.invalid_harness = 0
        self.ungradable_model_output = 0

    def record_grade(self, hazard_results: dict, cause: str | None = None) -> None:
        self.attempts += 1
        graded_something = False
        for hazard_id, verdict in hazard_results.items():
            if verdict in ("pass", "fail"):
                graded_something = True
                # Freeze a hazard's tally at the preregistered n. Without this
                # a hazard that grades every run kept accumulating while a
                # sibling hazard caught up, so one arm could carry 20 grades
                # against the other's 10 - and bucket() would then compare
                # different sample sizes over different time windows, with the
                # extra sampling triggered by that arm's failures elsewhere.
                if self.valid[hazard_id] >= self.n:
                    continue
                self.valid[hazard_id] += 1
                if verdict == "fail":
                    self.failures[hazard_id] += 1
            elif cause == MODEL_OUTPUT:
                self.ungradable[hazard_id] += 1
        if cause == MODEL_OUTPUT:
            self.ungradable_model_output += 1
        elif not graded_something:
            self.invalid_harness += 1

    def record_nongrade(self, status: str) -> None:
        """A run that never reached the grader: capped, or invalid upstream."""
        self.attempts += 1
        if status == "capped":
            self.capped += 1
        else:
            self.invalid_harness += 1

    @property
    def complete(self) -> bool:
        return all(self.valid[h] >= self.n for h in self.hazard_ids)

    def summary(self) -> dict:
        return {
            "valid_runs": {h: self.valid[h] for h in self.hazard_ids},
            "failures": {h: self.failures[h] for h in self.hazard_ids},
            "ungradable": {h: self.ungradable[h] for h in self.hazard_ids},
            "attempts": self.attempts,
            "capped": self.capped,
            "invalid_harness": self.invalid_harness,
            # Censoring that correlates with the trait being measured. Reported
            # rather than resampled away.
            "ungradable_model_output": self.ungradable_model_output,
        }


def run_command(args) -> None:
    problems = preflight()
    problems += verify_image_digests(
        {"agent": AGENT_IMAGE, "grading": GRADING_IMAGE}
    )
    if problems:
        raise SystemExit("preflight failed:\n  " + "\n  ".join(problems))

    # Sterility was verified only by pytest, so `python eval.py run` could
    # spend real money against a non-sterile image without the check ever
    # having executed. If host skills, plugins or AGENTS.md leak into one arm,
    # that arm gets a different system prompt and the published differential is
    # a config artifact wearing a vendor's name.
    assert_sterile(AGENT_IMAGE)

    fixture = load_fixture(Path("fixtures") / args.fixture)
    validate_hazard_mapping(fixture)

    arm_names = [a.strip() for a in args.arms.split(",") if a.strip()]
    arms = [ARMS[name] for name in arm_names]
    credentials = load_eval_env()
    # Check every arm's credential BEFORE spending anything on the first one.
    for arm in arms:
        if not credentials.get(arm.credential_key):
            raise SystemExit(f"{arm.credential_key} is not set")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_dir = REPORTS / f"{stamp}-{fixture.id}"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "provenance.json").write_text(json.dumps(_provenance(arms), indent=2))
    records_path = report_dir / "records.jsonl"

    scope, reads = allowed_scope(fixture), must_read(fixture)
    hazard_ids = [h["id"] for h in fixture.hazards]
    books = {arm.name: Accounting(hazard_ids, args.n) for arm in arms}
    spend = 0.0

    # Arms interleave at the attempt level. Running one arm to completion and
    # then the other perfectly confounds arm with wall-clock time: provider
    # load, rate limiting and model rollouts all vary over a window that at
    # n=10 across 12 fixtures is hours long. Round-robin costs the same.
    max_attempts = args.n * MAX_ATTEMPTS_PER_VALID
    for attempt in range(1, max_attempts + 1):
        if all(books[a.name].complete for a in arms):
            break
        for arm in arms:
            book = books[arm.name]
            if book.complete:
                continue
            with tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp) / "run"
                try:
                    result = run_agent(
                        fixture, arm, credentials[arm.credential_key], work,
                        wall_clock_s=args.wall_clock, max_turns=args.max_turns,
                    )
                except Exception as exc:  # noqa: BLE001 - one run must not end the eval
                    # Every prior attempt in this eval has already been paid
                    # for. Losing summary.json to one transient fault would
                    # make all of them unpublishable without hand work.
                    book.record_nongrade("invalid")
                    record = {
                        "arm": arm.name, "attempt": attempt, "status": "invalid",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                    with records_path.open("a") as handle:
                        handle.write(json.dumps(record) + "\n")
                    print(f"  {arm.name} attempt {attempt}: harness error: {exc}")
                    continue

                record = {
                    "arm": arm.name,
                    "model": arm.model,
                    "attempt": attempt,
                    "status": result.status,
                    "turns": result.turns,
                    "cost": result.cost,
                    "model_verified": result.model_verified,
                    "opencode_exit": result.opencode_exit,
                    "error": result.error,
                    "run_stderr_tail": result.run_stderr[-400:],
                }
                if result.cost:
                    spend += result.cost

                if result.status == "completed":
                    graded = grade(fixture, work)
                    obs = observations(
                        result.session, changes=result.changes,
                        allowed_scope=scope, must_read=reads,
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
                    record["grade_cause"] = graded.cause
                    record["observations"] = obs
                    book.record_grade(graded.hazard_results, graded.cause)
                else:
                    book.record_nongrade(result.status)

            with records_path.open("a") as handle:
                handle.write(json.dumps(record) + "\n")
            print(
                f"  {arm.name} attempt {attempt}: {record['status']} "
                f"turns={record['turns']} cost=${record['cost']} "
                f"hazards={record.get('hazards')}"
            )

    summary = {
        "fixture": fixture.id,
        "n_target": args.n,
        "estimated_spend_usd": round(spend, 4),
        "arms": {name: book.summary() for name, book in books.items()},
        "hazards": {},
    }
    for hazard_id in hazard_ids:
        row = {
            arm.name: {
                "failures": books[arm.name].failures[hazard_id],
                "valid_runs": books[arm.name].valid[hazard_id],
                "ungradable": books[arm.name].ungradable[hazard_id],
                "attempts": books[arm.name].attempts,
            }
            for arm in arms
        }
        if {"deepseek", "opus"} <= set(row):
            row["bucket"] = bucket(
                ArmTally(row["deepseek"]["failures"], row["deepseek"]["valid_runs"]),
                ArmTally(row["opus"]["failures"], row["opus"]["valid_runs"]),
            )
        summary["hazards"][hazard_id] = row

    incomplete = [n for n, b in books.items() if not b.complete]
    if incomplete:
        summary["attempt_budget_exhausted_for"] = incomplete

    (report_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print("\n" + json.dumps(summary, indent=2))
    print(f"\nwritten: {report_dir}")
    print(
        "\nNOTE: one fixture cannot support a finding. Spec 9.3 requires a "
        "hazard to replicate across two independently authored fixtures before "
        "it means anything, and spec 9.1 makes n=3 a screen whose output is "
        "candidates - confirmation is fresh runs at n=10."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run a fixture through one or more arms")
    run.add_argument("--fixture", required=True)
    run.add_argument("--arms", default="deepseek,opus")
    run.add_argument("--n", type=int, default=3,
                     help="valid grades per hazard per arm")
    run.add_argument("--wall-clock", type=int, default=1200)
    run.add_argument("--max-turns", type=int, default=60)
    run.set_defaults(func=run_command)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
