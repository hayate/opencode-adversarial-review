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
    "OPENCODE_PERMISSION": '{"bash":"allow","edit":"allow","webfetch":"allow"}',
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
        turns = 0

        while proc.poll() is None:
            time.sleep(2)
            if events_file.exists():
                turns = count_turns(events_file.read_text(errors="replace"))
            if turns > max_turns or time.monotonic() > deadline:
                capped = True
                subprocess.run(["podman", "kill", name], capture_output=True)
                subprocess.run(["podman", "rm", "-f", name], capture_output=True)
                break
        proc.wait(timeout=60)

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

    after = snapshot(workdir)
    changes = diff_snapshots(before, after)

    if capped:
        return RunResult("capped", changes, session, events, turns,
                         error=f"cap hit after {turns} turns")
    if not session:
        return RunResult("invalid", changes, {}, events, turns,
                         error=f"no session export; run stderr: {run_err[-600:]}")

    try:
        verified = verify_model_id(session, expected=arm.model)
    except ModelMismatch as exc:
        return RunResult("invalid", changes, session, events, turns, error=str(exc))

    cost = (session.get("info") or {}).get("cost")
    return RunResult("completed", changes, session, events, turns,
                     cost=cost, model_verified=verified)
