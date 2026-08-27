"""Containerised opencode runner.

The whole agent lifecycle happens inside the pinned image. This is not a
hardening preference: spec 6.0 established empirically that an isolated HOME is
the only mechanism producing a sterile opencode configuration, so a host
subprocess would silently run against the operator's personal global config.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from harness.fixture import Fixture, stage_agent_tree
from harness.sandbox import run_in_sandbox
from harness.snapshot import Changes, diff_snapshots, snapshot

AGENT_IMAGE = "localhost/odr-agent:latest"
CONTAINER_HOME = "/tmp/agent-home"


class ModelMismatch(Exception):
    """The session used a model other than the one requested."""


# OPENCODE_PERMISSION APPENDS to opencode's defaults rather than replacing them
# (verified in-image 2026-08-27), and resolution is last-match-wins. So an entry
# named here overrides the default of the same name, but a default NOT named
# here survives untouched. This is the same merge semantics spec 6.0 recorded
# for OPENCODE_CONFIG_CONTENT - a fact about one knob that turned out to be a
# fact about the whole configuration system.
#
# The original three-key value therefore left `doom_loop: ask` and
# `external_directory: ask` live, with no human in the container to answer
# either. Round 1 of the review gauntlet caught it: confound #2 had only ever
# been half fixed.
NONINTERACTIVE_PERMISSION: dict[str, str] = {
    # Every tool the build agent exposes.
    "bash": "allow", "edit": "allow", "write": "allow", "read": "allow",
    "glob": "allow", "grep": "allow", "webfetch": "allow", "websearch": "allow",
    "task": "allow", "todowrite": "allow", "skill": "allow", "question": "allow",
    # Not tools - opencode's own guards. doom_loop fires when an agent repeats a
    # call, which is what a struggling model does; external_directory fires on
    # scratch work outside /workspace. Both correlate with model style, so
    # leaving them gated is a differential handicap, not a safety measure:
    # containment is the sandbox's job, never opencode's prompts.
    "doom_loop": "allow", "external_directory": "allow",
    # Allowed together. Denying only the exit would let a model enter plan mode
    # and be unable to leave it.
    "plan_enter": "allow", "plan_exit": "allow",
}


STERILE_ENV: dict[str, str] = {
    "OPENCODE_DISABLE_PROJECT_CONFIG": "1",
    "OPENCODE_DISABLE_CLAUDE_CODE": "1",
    "OPENCODE_DISABLE_CLAUDE_CODE_PROMPT": "1",
    "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS": "1",
    "OPENCODE_DISABLE_EXTERNAL_SKILLS": "1",
    "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1",
    "OPENCODE_DISABLE_AUTOCOMPACT": "1",
    "OPENCODE_DISABLE_MODELS_FETCH": "1",
    "OPENCODE_DISABLE_AUTOUPDATE": "1",
    "OPENCODE_DISABLE_SHARE": "1",
    # There is no human in the container to answer a permission prompt. Without
    # this, opencode denies the call and the agent hits a wall it cannot pass -
    # observed on the first real run 2026-08-27, where a bash call came back
    # "The user rejected permission to use this specific tool call." and the
    # session never reached a `stop` turn.
    #
    # This is the ripgrep confound in another costume: an environmental
    # handicap that reads as model behaviour, and a DIFFERENTIAL one, since a
    # model that asks permission more often is penalised more. Containment is
    # provided by the sandbox, not by opencode's prompts.
    "OPENCODE_PERMISSION": json.dumps(NONINTERACTIVE_PERMISSION),
    "HOME": CONTAINER_HOME,
    "XDG_CONFIG_HOME": f"{CONTAINER_HOME}/.config",
    "XDG_DATA_HOME": f"{CONTAINER_HOME}/.local/share",
    "XDG_CACHE_HOME": f"{CONTAINER_HOME}/.cache",
    "XDG_STATE_HOME": f"{CONTAINER_HOME}/.local/state",
}


@dataclass(frozen=True)
class Arm:
    name: str
    provider: str
    model: str
    credential_key: str
    base_url: str

    @property
    def model_ref(self) -> str:
        return f"{self.provider}/{self.model}"


ARMS: dict[str, Arm] = {
    "deepseek": Arm(
        "deepseek", "deepseek", "deepseek-v4-pro",
        "DEEPSEEK_API_KEY", "https://api.deepseek.com",
    ),
    "opus": Arm(
        "opus", "anthropic", "claude-opus-5",
        "ANTHROPIC_API_KEY", "https://api.anthropic.com/v1",
    ),
}


@dataclass(frozen=True)
class RunResult:
    status: str  # "completed" | "capped" | "invalid"
    changes: Changes
    session: dict = field(default_factory=dict)
    events: str = ""
    turns: int = 0
    cost: float | None = None
    model_verified: bool = False
    error: str | None = None
    opencode_exit: int | None = None
    run_stderr: str = ""


def build_canonical_config(arm: Arm) -> str:
    """One provider, one model, no plugins.

    Safe as a full replacement only because HOME is isolated: with a real HOME
    present, OPENCODE_CONFIG_CONTENT merges rather than replaces (spec 6.0).
    """
    return json.dumps(
        {
            "$schema": "https://opencode.ai/config.json",
            "enabled_providers": [arm.provider],
            "provider": {arm.provider: {"options": {"baseURL": arm.base_url}}},
            "model": arm.model_ref,
            "small_model": arm.model_ref,
            "plugin": [],
        }
    )


def build_auth_content(arm: Arm, key: str) -> str:
    return json.dumps({arm.provider: {"type": "api", "key": key}})


def verify_model_id(session: dict, *, expected: str) -> bool:
    """Contract-pinned: modelID lives at messages[].info.modelID."""
    seen = {
        (m.get("info") or {}).get("modelID")
        for m in session.get("messages", [])
        if (m.get("info") or {}).get("role") == "assistant"
    }
    seen.discard(None)
    if not seen:
        raise ModelMismatch("no assistant message carried a modelID")
    if seen != {expected}:
        raise ModelMismatch(f"expected {expected!r}, session used {sorted(seen)}")
    return True


def count_turns(events_text: str) -> int:
    """Assistant turns so far, from the NDJSON stream.

    Tolerates a trailing partial line: the host tails this file while the
    container is still writing it.
    """
    turns = 0
    for line in events_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "step_start":
            turns += 1
    return turns


def classify_run(
    *,
    capped: bool,
    turns: int,
    opencode_exit: int | None,
    session: dict,
    expected_model: str,
) -> tuple[str, str | None]:
    """Decide a run's status. Returns (status, error).

    Split out of run_agent so the decision is testable without a paid run.

    The opencode exit code is load-bearing and used to be ignored entirely: the
    run script wrote it to /out/run.exit and nothing ever read the file. A run
    aborted by the provider - 429, 5xx, expired key, crash mid-turn - still
    leaves a parseable export whose assistant messages carry the right modelID,
    so it read as `completed` and its half-edited tree was graded. That is the
    cleanest path in the repo from "the vendor's API had a bad minute" to "the
    vendor's model failed the hazard", and provider error rates are per-vendor
    by definition.

    Absent is not non-zero: a missing exit file never invalidates a run.
    """
    if capped:
        return "capped", f"cap hit after {turns} turns"
    if opencode_exit not in (None, 0):
        return "invalid", (
            f"opencode run exited {opencode_exit}; the run did not complete "
            f"normally, so its tree is not evidence about the model"
        )
    if not session:
        return "invalid", "no session export"
    try:
        verify_model_id(session, expected=expected_model)
    except ModelMismatch as exc:
        return "invalid", str(exc)
    return "completed", None


def effective_permissions(image: str) -> dict[str, str]:
    """Resolve the build agent's wildcard permissions inside the image.

    Reports the LAST entry for each permission type at pattern "*", which is
    the one that wins. Used by assert_sterile so a re-gated permission fails
    before a run is paid for rather than showing up as model behaviour.
    """
    with tempfile.TemporaryDirectory() as tmp:
        result = run_in_sandbox(
            image, Path(tmp),
            ["sh", "-c",
             f"mkdir -p {CONTAINER_HOME}/.config && opencode debug agent build"],
            network="none", env=STERILE_ENV,
        )
    if result.exit_code != 0:
        raise AssertionError(f"could not resolve agent permissions: {result.stderr[:400]}")
    effective: dict[str, str] = {}
    for entry in json.loads(result.stdout).get("permission") or []:
        if entry.get("pattern") == "*":
            effective[entry.get("permission")] = entry.get("action")
    return effective


def assert_sterile(image: str) -> None:
    """Spec 6.0, with a positive control.

    Without the control, this passing because the check silently broke is
    indistinguishable from it passing because isolation works.
    """
    seeded = json.dumps({"provider": {"canary-provider": {"options": {}}}})
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "AGENTS.md").write_text("CANARY_PROJECT_INSTRUCTION\n")
        (work / "opencode.json").write_text('{"model":"canary/model"}')

        control = run_in_sandbox(
            image, work,
            ["sh", "-c", f"mkdir -p {CONTAINER_HOME}/.config && opencode debug config"],
            network="none",
            env={**STERILE_ENV, "OPENCODE_CONFIG_CONTENT": seeded},
        )
        if control.exit_code != 0:
            raise AssertionError(f"positive control did not run: {control.stderr[:400]}")
        if "canary-provider" not in (json.loads(control.stdout).get("provider") or {}):
            raise AssertionError(
                "positive control failed: the canary is not observable even "
                "with isolation off, so the assertions below prove nothing"
            )

        for argv, label in (
            (["opencode", "debug", "config", "--pure"], "config"),
            (["opencode", "debug", "skill"], "skill"),
            (["opencode", "debug", "agent", "build"], "agent"),
        ):
            result = run_in_sandbox(
                image, work,
                ["sh", "-c", f"mkdir -p {CONTAINER_HOME}/.config && " + " ".join(argv)],
                network="none", env=STERILE_ENV,
            )
            if result.exit_code != 0:
                raise AssertionError(f"debug {label} failed: {result.stderr[:400]}")
            for canary in ("canary-provider", "canary/model",
                           "CANARY_PROJECT_INSTRUCTION", "superpowers"):
                if canary in result.stdout:
                    raise AssertionError(f"{canary!r} leaked into debug {label}")

        config = json.loads(
            run_in_sandbox(
                image, work,
                ["sh", "-c", f"mkdir -p {CONTAINER_HOME}/.config && opencode debug config --pure"],
                network="none", env=STERILE_ENV,
            ).stdout
        )
        # Do NOT check config["plugin"]: resolved config still LISTS declared
        # plugins even when they are not loaded (observed 2026-08-27). Verify
        # what loaded - providers, skills.paths - not what was declared.
        if config.get("provider"):
            raise AssertionError(f"host providers leaked: {list(config['provider'])}")
        if (config.get("skills") or {}).get("paths"):
            raise AssertionError(f"skill paths leaked: {config['skills']['paths']}")

    # There is no human in the container. A permission left at "ask" is a wall
    # the agent cannot pass, and which model hits it depends on model style.
    asking = {k: v for k, v in effective_permissions(image).items() if v == "ask"}
    if asking:
        raise AssertionError(
            f"permissions still gated with nobody to answer: {sorted(asking)}"
        )


_RUN_SCRIPT = r"""
set -uo pipefail
mkdir -p "$HOME/.config" "$HOME/.local/share/opencode" "$HOME/.cache" "$HOME/.local/state"
printf '%s' "$ODR_AUTH" > "$HOME/.local/share/opencode/auth.json"

opencode run --pure --format json --agent build -m "$ODR_MODEL" "$ODR_BRIEF" \
  > /out/run-events.ndjson 2>/out/run.err
echo "$?" > /out/run.exit

SESSION=$(python3 - <<'PY'
import json, sys
found = None
for line in open("/out/run-events.ndjson", errors="replace"):
    line = line.strip()
    if not line:
        continue
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        continue
    if isinstance(obj, dict) and isinstance(obj.get("sessionID"), str):
        found = obj["sessionID"]
        break
print(found or "", end="")
PY
)
if [ -n "$SESSION" ]; then
  opencode export "$SESSION" > /out/session-export.json 2>/out/export.err
  printf '%s' "$SESSION" > /out/session-id.txt
fi
"""


def _kill_container(name: str) -> str | None:
    """Kill and remove by name. Returns a message if it did not take.

    Both return codes used to be discarded. Killing only the podman client
    leaves the container running, which lets a capped run keep spending against
    a live credential - the one failure here that costs real money silently.
    """
    problems: list[str] = []
    for argv in (["podman", "kill", name], ["podman", "rm", "-f", name]):
        result = subprocess.run(argv, capture_output=True, text=True)
        if result.returncode != 0:
            err = (result.stderr or "").strip()
            if "no such container" in err.lower():
                continue  # already gone is success
            problems.append(f"podman {argv[1]} failed: {err[:200]}")
    return "; ".join(problems) or None


def _read_exit(path: Path) -> int | None:
    """The opencode exit code, or None when it was never written."""
    if not path.exists():
        return None
    raw = path.read_text(errors="replace").strip()
    return int(raw) if raw.lstrip("-").isdigit() else None


def run_agent(
    fixture: Fixture,
    arm: Arm,
    credential: str,
    workdir: Path,
    *,
    wall_clock_s: int = 1200,
    max_turns: int = 60,
) -> RunResult:
    """Stage, run in the agent container, and capture the result.

    The turn cap is enforced, not merely declared: the container streams its
    event log to a mounted volume and the host kills it by name once the cap is
    crossed. A capped run is a distinct observation, never a hazard failure.
    """
    workdir = Path(workdir)
    stage_agent_tree(fixture, workdir)
    before = snapshot(workdir)

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        out.mkdir()
        name = f"odr-run-{uuid.uuid4().hex[:12]}"
        env = {
            **STERILE_ENV,
            "OPENCODE_CONFIG_CONTENT": build_canonical_config(arm),
            "ODR_AUTH": build_auth_content(arm, credential),
            "ODR_MODEL": arm.model_ref,
            "ODR_BRIEF": fixture.task_brief,
        }
        cmd = [
            "podman", "run", "--rm", "--name", name,
            "--network", "bridge",
            "--security-opt", "no-new-privileges",
            "--cap-drop", "ALL",
            "--memory", "4g", "--cpus", "2", "--pids-limit", "512",
            "--read-only", "--tmpfs", "/tmp:rw,size=2g",
            "-v", f"{workdir.resolve()}:/workspace:rw,Z",
            "-v", f"{out.resolve()}:/out:rw,Z",
            "-w", "/workspace",
        ]
        for key, value in env.items():
            cmd += ["-e", f"{key}={value}"]
        cmd += [AGENT_IMAGE, "bash", "-c", _RUN_SCRIPT]

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        events_file = out / "run-events.ndjson"
        deadline = time.monotonic() + wall_clock_s
        capped = False
        cap_reason = ""
        cleanup_problem: str | None = None
        turns = 0

        while proc.poll() is None:
            time.sleep(2)
            if events_file.exists():
                turns = count_turns(events_file.read_text(errors="replace"))
            over_turns = turns > max_turns
            over_clock = time.monotonic() > deadline
            if over_turns or over_clock:
                capped = True
                # Name the cap that actually fired. Reporting "turn cap" for a
                # wall-clock timeout points triage at the wrong cause, and
                # wall-clock exhaustion is among the most arm-correlated
                # failure modes available: provider latency, retries, thinking
                # budget.
                cap_reason = "turn cap" if over_turns else "wall clock"
                cleanup_problem = _kill_container(name)
                break

        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            # Reachable only when the kill did not take, which is exactly the
            # state where a paid container is still running. This used to
            # propagate and abort the whole eval mid-arm, losing the in-flight
            # record and summary.json for every already-paid run.
            proc.kill()
            cleanup_problem = "; ".join(
                filter(None, [cleanup_problem, "podman client did not exit after kill"])
            )

        events = events_file.read_text(errors="replace") if events_file.exists() else ""
        turns = count_turns(events) if events else turns
        export_path = out / "session-export.json"
        session: dict = {}
        if export_path.exists() and export_path.stat().st_size:
            try:
                session = json.loads(export_path.read_text())
            except json.JSONDecodeError:
                session = {}
        run_err = (out / "run.err").read_text(errors="replace") if (out / "run.err").exists() else ""
        # Written by _RUN_SCRIPT since day one and never read until now.
        opencode_exit = _read_exit(out / "run.exit")

    after = snapshot(workdir)
    changes = diff_snapshots(before, after)

    status, error = classify_run(
        capped=capped, turns=turns, opencode_exit=opencode_exit,
        session=session, expected_model=arm.model,
    )
    if status == "capped" and cap_reason:
        error = f"{cap_reason} cap hit after {turns} turns"
    if error == "no session export":
        error = f"no session export; run stderr: {run_err[-600:]}"
    if cleanup_problem:
        error = f"{error or ''} [container cleanup: {cleanup_problem}]".strip()

    cost = (session.get("info") or {}).get("cost")
    return RunResult(
        status, changes, session if status != "invalid" or session else {},
        events, turns,
        cost=cost,
        model_verified=(status == "completed"),
        error=error,
        opencode_exit=opencode_exit,
        # Surfaced on every status, not just the empty-session branch: a
        # completed run's opencode stderr used to be discarded outright.
        run_stderr=run_err[-2000:],
    )
