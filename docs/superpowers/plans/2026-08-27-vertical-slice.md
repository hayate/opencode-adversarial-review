# Vertical Slice Implementation Plan (revision 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one complete fixture end to end and produce trustworthy per-hazard counts for DeepSeek v4-pro versus Opus 5 on a single hazard.

**Architecture:** Everything that touches a model runs inside a rootless podman container - not for hardening, but because a container's isolated `HOME` is the only thing that produces a sterile opencode configuration (spec §6.0). Two images: an agent sandbox with API-only egress, and a grading sandbox with no network and no credentials. Contracts are captured from real runs *before* any parser is written.

**Tech Stack:** Python 3.13, uv, pytest, podman 5.4.2, opencode 1.18.23, Django/DRF fixture.

**Spec:** `docs/superpowers/specs/2026-08-27-deepseek-review-gauntlet-design.md`

## Revision 2

Revision 1 was rejected by Codex adversarial review (`task-mtb2krly-ljbyws`): *"will not produce trustworthy numbers as written."* Three fatal defects, the worst being that `run_agent` declared it consumed the sandbox and then ran `opencode` as a host subprocess. Subsequent experiment (spec §6.0) proved that shortcut would have run both arms against the operator's personal global config.

The sequencing is the main change: **capture real contracts before writing any parser.** Half of revision 1's bugs came from writing code against a schema I guessed at.

## Global Constraints

- **Nothing that invokes a model runs on the host.** The agent lifecycle happens entirely inside the pinned agent image (spec §6.0, §12).
- **Visibility boundary (spec §5):** only `fixtures/<id>/repo/` contents enter the agent container, enforced by comparing the container-visible manifest against a committed allowlist. Symlinks, hardlinks, `.git` at any depth, `.gitmodules`, and worktree pointers are rejected at load time.
- **Grading isolation (spec §8, §12):** `--network=none`, no credential. Host-side preparation must never follow model-authored symlinks.
- **Tri-state results everywhere.** `pass`, `fail`, `invalid`. An infrastructure error must never be recorded as a model failure, and `invalid` runs never enter a denominator.
- **Model identity (spec §6):** verified against real exports; mismatch fails the run.
- **This slice ships no skill and draws no conclusions** (spec §11). One fixture cannot support a finding; §9.3 requires cross-fixture replication.
- Never commit to `main`; work on `feat/vertical-slice`.

---

## File Structure

| Path | Responsibility |
|---|---|
| `pyproject.toml` | Dependencies, pytest config |
| `contracts/` | **Recorded** opencode outputs used as schema fixtures |
| `harness/preflight.py` | Verify podman, opencode, credentials before spending anything |
| `harness/fixture.py` | Load, validate, stage; enforce the allowlist |
| `harness/sandbox.py` | Podman wrapper for both sandboxes |
| `harness/snapshot.py` | Filesystem snapshot and diff (replaces git-based diffing) |
| `harness/runner.py` | Containerised opencode invocation |
| `harness/trace.py` | Parse real exports into observations |
| `graders/apply.py` | Overlay grader, run once with persistent output, tri-state results |
| `analysis/bucket.py` | Bucketing over valid runs only |
| `containers/` | `agent.Containerfile`, `grading.Containerfile` |
| `fixtures/py-callsite-01/` | The first fixture |

---

## Task 0: Bootstrap and preflight

Revision 1 assumed all of this. None of it exists.

**Files:**
- Create: `pyproject.toml`, `harness/__init__.py`, `graders/__init__.py`, `analysis/__init__.py`, `harness/preflight.py`
- Test: `tests/test_preflight.py`

**Interfaces:**
- Produces: `preflight() -> list[str]` returning a list of problems; empty means ready.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "opencode-deepseek-review"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = ["pyyaml>=6.0"]

[dependency-groups]
dev = ["pytest>=8.0", "pytest-json-report>=1.5"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_preflight.py
from harness.preflight import preflight

def test_preflight_returns_a_list():
    assert isinstance(preflight(), list)

def test_preflight_detects_missing_binary(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    problems = preflight()
    assert any("podman" in p for p in problems)
    assert any("opencode" in p for p in problems)
```

- [ ] **Step 3: Run it and confirm it fails**

Run: `uv run pytest tests/test_preflight.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'harness.preflight'`

- [ ] **Step 4: Implement**

```python
# harness/preflight.py
from __future__ import annotations
import os, shutil, subprocess

REQUIRED_BINARIES = ("podman", "opencode")
REQUIRED_CREDENTIALS = ("DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY")

def preflight() -> list[str]:
    problems: list[str] = []
    for binary in REQUIRED_BINARIES:
        if shutil.which(binary) is None:
            problems.append(f"{binary} not found on PATH")
    if shutil.which("podman"):
        result = subprocess.run(
            ["podman", "info", "--format", "{{.Host.Security.Rootless}}"],
            capture_output=True, text=True,
        )
        if result.stdout.strip() != "true":
            problems.append("podman is not running rootless")
    for key in REQUIRED_CREDENTIALS:
        if not os.environ.get(key):
            problems.append(f"{key} is not set")
    return problems
```

- [ ] **Step 5: Confirm it passes, then commit**

```bash
uv run pytest tests/test_preflight.py -v
git add pyproject.toml harness/ graders/ analysis/ tests/test_preflight.py
git commit -m "feat: project bootstrap and preflight checks"
```

---

## Task 1: Capture the real opencode contracts

**This task must complete before any parser is written.** Revision 1's trace parser was written against an invented schema; this task replaces guessing with recording.

**Files:**
- Create: `contracts/README.md`, `contracts/capture.sh`
- Create (recorded, committed): `contracts/run-events.ndjson`, `contracts/session-export.json`, `contracts/debug-config-sterile.json`, `contracts/debug-config-host.json`
- Test: `tests/test_contracts.py`

**Interfaces:**
- Produces: committed real artifacts every later task's parser is written and tested against.

- [ ] **Step 1: Write the capture script**

Use the cheapest model on a trivial task. The goal is schema, not behaviour.

```bash
#!/usr/bin/env bash
# contracts/capture.sh - record real opencode outputs as schema fixtures.
set -euo pipefail
OUT="$(cd "$(dirname "$0")" && pwd)"
WORK=$(mktemp -d)
HOME_DIR="$WORK/home"
mkdir -p "$WORK/repo" "$HOME_DIR"
printf 'def add(a, b):\n    return a + b\n' > "$WORK/repo/calc.py"

# Sterile vs host resolved config, for the isolation assertions in Task 6.
env HOME="$HOME_DIR" XDG_CONFIG_HOME="$HOME_DIR/.config" PATH="$PATH" \
    OPENCODE_DISABLE_PROJECT_CONFIG=1 OPENCODE_DISABLE_DEFAULT_PLUGINS=1 \
    opencode debug config --pure > "$OUT/debug-config-sterile.json"
opencode debug config > "$OUT/debug-config-host.json"

# One cheap real run, capturing the event stream verbatim.
cd "$WORK/repo"
env HOME="$HOME_DIR" XDG_CONFIG_HOME="$HOME_DIR/.config" PATH="$PATH" \
    OPENCODE_DISABLE_PROJECT_CONFIG=1 OPENCODE_DISABLE_DEFAULT_PLUGINS=1 \
    opencode run --pure --format json -m deepseek/deepseek-v4-flash \
    "Add a subtract function to calc.py and run python -c 'import calc'." \
    > "$OUT/run-events.ndjson"

SESSION=$(grep -om1 '"sessionID":"[^"]*"' "$OUT/run-events.ndjson" | cut -d'"' -f4)
opencode export "$SESSION" > "$OUT/session-export.json"
echo "captured session $SESSION"
```

- [ ] **Step 2: Run it**

```bash
bash contracts/capture.sh
```

Costs a few cents on `deepseek-v4-flash`.

- [ ] **Step 3: Inspect what actually came back and write it down**

```bash
head -c 2000 contracts/run-events.ndjson
jq -r 'keys[]' contracts/session-export.json
jq -c '.messages[0] | keys' contracts/session-export.json
```

Record in `contracts/README.md`: is the run output NDJSON or one object? Where does the session ID appear? Where does the model id live on an assistant message? What shape is a tool call, and does it carry an outcome?

**These answers, not my assumptions, define Tasks 6 and 7.**

- [ ] **Step 4: Write contract tests that pin the shape**

```python
# tests/test_contracts.py
import json
from pathlib import Path

C = Path("contracts")

def test_export_has_messages():
    export = json.loads((C / "session-export.json").read_text())
    assert "messages" in export and export["messages"]

def test_some_assistant_message_carries_a_model_id():
    export = json.loads((C / "session-export.json").read_text())
    ids = [m for m in export["messages"] if _model_id_of(m)]
    assert ids, "no assistant message carried a model id - Task 6 assumption is wrong"

def test_sterile_config_has_no_host_provider_block():
    sterile = json.loads((C / "debug-config-sterile.json").read_text())
    assert not (sterile.get("provider") or {}), "isolation did not strip host providers"

def test_host_config_does_have_a_provider_block():
    """Positive control: proves the previous assertion can fail."""
    host = json.loads((C / "debug-config-host.json").read_text())
    assert host.get("provider"), "positive control failed - check the capture"
```

`_model_id_of` is written in Step 3 once the real shape is known.

- [ ] **Step 5: Commit**

```bash
git add contracts/ tests/test_contracts.py
git commit -m "feat: capture real opencode contracts as committed schema fixtures"
```

---

## Task 2: Build and pin both container images

**Files:**
- Create: `containers/agent.Containerfile`, `containers/grading.Containerfile`, `containers/build.sh`
- Test: `tests/test_images.py`

**Interfaces:**
- Produces: `localhost/odr-agent@sha256:...` and `localhost/odr-grading@sha256:...`, digests written to `containers/digests.json`.

- [ ] **Step 1: Write the grading image**

Note: **not alpine.** Busybox `find` lacks `-printf`, which the manifest check needs.

```dockerfile
# containers/grading.Containerfile
FROM docker.io/library/python:3.13-slim
RUN pip install --no-cache-dir \
      "django>=5.0" "djangorestframework>=3.15" \
      "pytest>=8.0" "pytest-django>=4.8" "pytest-json-report>=1.5" "tzdata"
WORKDIR /workspace
```

- [ ] **Step 2: Write the agent image**

```dockerfile
# containers/agent.Containerfile
FROM docker.io/library/python:3.13-slim
ARG OPENCODE_VERSION=1.18.23
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://opencode.ai/install | VERSION=${OPENCODE_VERSION} bash
ENV PATH="/root/.opencode/bin:${PATH}"
RUN pip install --no-cache-dir "django>=5.0" "djangorestframework>=3.15" "pytest>=8.0" "pytest-django>=4.8" "tzdata"
WORKDIR /workspace
```

- [ ] **Step 3: Write `build.sh` recording digests**

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
for img in agent grading; do
  podman build -t "localhost/odr-$img:latest" -f "$img.Containerfile" .
done
podman image inspect localhost/odr-agent:latest localhost/odr-grading:latest \
  --format '{{.RepoTags}} {{.Id}}' | tee digests.txt
```

- [ ] **Step 4: Write the test**

```python
# tests/test_images.py
from harness.sandbox import run_in_sandbox
from pathlib import Path

def test_agent_image_has_opencode(tmp_path):
    r = run_in_sandbox("localhost/odr-agent:latest", tmp_path,
                       ["opencode", "--version"], network="none")
    assert r.exit_code == 0 and r.stdout.strip()

def test_grading_image_can_import_django(tmp_path):
    r = run_in_sandbox("localhost/odr-grading:latest", tmp_path,
                       ["python", "-c", "import django, rest_framework, pytest_django"],
                       network="none")
    assert r.exit_code == 0

def test_grading_find_supports_printf(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    r = run_in_sandbox("localhost/odr-grading:latest", tmp_path,
                       ["find", ".", "-type", "f", "-printf", "%P\\n"], network="none")
    assert r.stdout.strip() == "a.txt"
```

- [ ] **Step 5: Build, test, commit**

```bash
bash containers/build.sh
uv run pytest tests/test_images.py -v
git add containers/ tests/test_images.py
git commit -m "feat: pinned agent and grading images"
```

---

## Task 3: Sandbox wrapper with cleanup and limits

**Files:**
- Create: `harness/sandbox.py`
- Test: `tests/test_sandbox.py`

**Interfaces:**
- Produces: `run_in_sandbox(image, workdir, argv, *, network, env=None, timeout_s=600, extra_mounts=None) -> SandboxResult` with `.exit_code`, `.stdout`, `.stderr`, `.timed_out`.

Revision 1's version killed only the podman *client* on timeout, leaving the container alive. This version names the container and removes it explicitly.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sandbox.py
import subprocess
from harness.sandbox import run_in_sandbox

IMG = "localhost/odr-grading:latest"

def test_no_network_in_grading_sandbox(tmp_path):
    r = run_in_sandbox(IMG, tmp_path, ["python", "-c",
        "import socket,sys;s=socket.socket();s.settimeout(3);"
        "sys.exit(0 if s.connect_ex(('1.1.1.1',443))!=0 else 1)"], network="none")
    assert r.exit_code == 0

def test_timeout_reported_and_container_removed(tmp_path):
    r = run_in_sandbox(IMG, tmp_path, ["sleep", "60"], network="none", timeout_s=3)
    assert r.timed_out is True
    running = subprocess.run(["podman", "ps", "--format", "{{.Names}}"],
                             capture_output=True, text=True).stdout
    assert "odr-" not in running, "container survived the timeout"

def test_extra_mount_is_writable_from_host(tmp_path):
    out = tmp_path / "out"; out.mkdir()
    work = tmp_path / "work"; work.mkdir()
    run_in_sandbox(IMG, work, ["sh", "-c", "echo hi > /out/x.txt"],
                   network="none", extra_mounts={out: "/out"})
    assert (out / "x.txt").read_text().strip() == "hi"
```

- [ ] **Step 2: Confirm it fails, then implement**

```python
# harness/sandbox.py
from __future__ import annotations
import subprocess, uuid
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool

def run_in_sandbox(
    image: str, workdir: Path, argv: list[str], *,
    network: str, env: dict[str, str] | None = None,
    timeout_s: int = 600, extra_mounts: dict[Path, str] | None = None,
) -> SandboxResult:
    name = f"odr-{uuid.uuid4().hex[:12]}"
    cmd = [
        "podman", "run", "--rm", "--name", name,
        "--network", network,
        "--security-opt", "no-new-privileges",
        "--cap-drop", "ALL",
        "--memory", "2g", "--cpus", "2", "--pids-limit", "512",
        "--read-only", "--tmpfs", "/tmp:rw,size=512m",
        "-v", f"{Path(workdir).resolve()}:/workspace:rw,Z",
        "-w", "/workspace",
    ]
    for host_path, container_path in (extra_mounts or {}).items():
        cmd += ["-v", f"{Path(host_path).resolve()}:{container_path}:rw,Z"]
    for key, value in (env or {}).items():
        cmd += ["-e", f"{key}={value}"]
    cmd += [image, *argv]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout_s, errors="replace")
        return SandboxResult(proc.returncode, proc.stdout, proc.stderr, False)
    except subprocess.TimeoutExpired as exc:
        subprocess.run(["podman", "kill", name], capture_output=True)
        subprocess.run(["podman", "rm", "-f", name], capture_output=True)
        def _text(v): return v.decode("utf-8", "replace") if isinstance(v, bytes) else (v or "")
        return SandboxResult(-1, _text(exc.stdout), _text(exc.stderr), True)
```

- [ ] **Step 3: Confirm it passes, then commit**

```bash
uv run pytest tests/test_sandbox.py -v
git add harness/sandbox.py tests/test_sandbox.py
git commit -m "feat: sandbox wrapper with explicit container cleanup and resource limits"
```

---

## Task 4: Fixture validation and manifest enforcement

Revision 1 checked symlinks only. Hardlinks, `.git`, and a symlinked `repo/` all walked straight through.

**Files:**
- Create: `harness/fixture.py`
- Create: `fixtures/py-callsite-01/manifest.txt` (the committed allowlist)
- Test: `tests/test_fixture.py`

**Interfaces:**
- Produces: `load_fixture(path) -> Fixture`; `stage_agent_tree(fixture, dest) -> None`; `assert_container_manifest(fixture, image, staged) -> None`; `FixtureViolation(Exception)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fixture.py
import os, pytest
from pathlib import Path
from harness.fixture import (load_fixture, stage_agent_tree,
                             assert_container_manifest, FixtureViolation)

def _fixture(tmp_path):
    fx = tmp_path / "py-demo-01"
    (fx / "repo" / "app").mkdir(parents=True)
    (fx / "repo" / "app" / "s.py").write_text("x = 1\n")
    (fx / "grader").mkdir(); (fx / "grader" / "answers.py").write_text("SECRET = 1\n")
    (fx / "task.md").write_text("Do a thing.")
    (fx / "hazards.yaml").write_text(
        "hazards:\n  - id: H-DEMO\n    origin: invented\n    tests: [test_demo]\n")
    (fx / "manifest.txt").write_text("app/s.py\n")
    return fx

def test_stages_only_repo_contents(tmp_path):
    fx = _fixture(tmp_path); dest = tmp_path / "staged"
    stage_agent_tree(load_fixture(fx), dest)
    assert {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()} == {"app/s.py"}

def test_rejects_symlink_escaping_repo(tmp_path):
    fx = _fixture(tmp_path)
    (fx / "repo" / "leak").symlink_to(fx / "grader")
    with pytest.raises(FixtureViolation, match="symlink"):
        stage_agent_tree(load_fixture(fx), tmp_path / "s")

def test_rejects_hardlink_to_answer_key(tmp_path):
    fx = _fixture(tmp_path)
    os.link(fx / "grader" / "answers.py", fx / "repo" / "innocent.py")
    with pytest.raises(FixtureViolation, match="hardlink"):
        stage_agent_tree(load_fixture(fx), tmp_path / "s")

def test_rejects_git_directory_at_any_depth(tmp_path):
    fx = _fixture(tmp_path)
    (fx / "repo" / "app" / ".git").mkdir()
    (fx / "repo" / "app" / ".git" / "config").write_text("[core]\n")
    with pytest.raises(FixtureViolation, match="git"):
        stage_agent_tree(load_fixture(fx), tmp_path / "s")

def test_rejects_repo_itself_being_a_symlink(tmp_path):
    fx = tmp_path / "py-sym-01"; fx.mkdir()
    (tmp_path / "elsewhere").mkdir()
    (fx / "repo").symlink_to(tmp_path / "elsewhere")
    (fx / "task.md").write_text("x"); (fx / "hazards.yaml").write_text("hazards: []\n")
    (fx / "manifest.txt").write_text("")
    with pytest.raises(FixtureViolation, match="repo"):
        stage_agent_tree(load_fixture(fx), tmp_path / "s")

def test_staged_tree_must_match_committed_manifest(tmp_path):
    fx = _fixture(tmp_path)
    (fx / "repo" / "unlisted.py").write_text("surprise = 1\n")
    with pytest.raises(FixtureViolation, match="manifest"):
        stage_agent_tree(load_fixture(fx), tmp_path / "s")
```

- [ ] **Step 2: Confirm it fails, then implement**

```python
# harness/fixture.py
from __future__ import annotations
import shutil
from dataclasses import dataclass
from pathlib import Path
import yaml
from harness.sandbox import run_in_sandbox

class FixtureViolation(Exception):
    """The fixture violates the spec section 5 visibility boundary."""

FORBIDDEN_NAMES = {".git", ".gitmodules"}

@dataclass(frozen=True)
class Fixture:
    id: str
    root: Path
    task_brief: str
    hazards: list[dict]
    manifest: set[str]

    @property
    def repo_dir(self) -> Path:
        return self.root / "repo"

def load_fixture(path: Path) -> Fixture:
    path = Path(path).resolve()
    data = yaml.safe_load((path / "hazards.yaml").read_text()) or {}
    manifest_file = path / "manifest.txt"
    manifest = {
        line.strip() for line in manifest_file.read_text().splitlines() if line.strip()
    } if manifest_file.exists() else set()
    return Fixture(
        id=path.name, root=path,
        task_brief=(path / "task.md").read_text(),
        hazards=data.get("hazards") or [],
        manifest=manifest,
    )

def _validate(repo: Path) -> None:
    if repo.is_symlink() or not repo.is_dir():
        raise FixtureViolation(f"repo must be a real directory, got {repo}")
    resolved_repo = repo.resolve(strict=True)
    for entry in repo.rglob("*"):
        if entry.name in FORBIDDEN_NAMES:
            raise FixtureViolation(f"git metadata is forbidden in repo/: {entry}")
        if entry.is_symlink():
            raise FixtureViolation(f"symlink is forbidden in repo/: {entry}")
        if entry.is_file() and entry.stat().st_nlink != 1:
            raise FixtureViolation(f"hardlink is forbidden in repo/: {entry}")
        if entry.is_file() and not entry.resolve().is_relative_to(resolved_repo):
            raise FixtureViolation(f"path escapes repo/: {entry}")

def stage_agent_tree(fixture: Fixture, dest: Path) -> None:
    repo = fixture.repo_dir
    _validate(repo)
    staged_paths = {
        p.relative_to(repo).as_posix() for p in repo.rglob("*") if p.is_file()
    }
    if staged_paths != fixture.manifest:
        missing = sorted(fixture.manifest - staged_paths)
        extra = sorted(staged_paths - fixture.manifest)
        raise FixtureViolation(
            f"manifest mismatch; missing={missing} unlisted={extra}"
        )
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(repo, dest, symlinks=True)

def assert_container_manifest(fixture: Fixture, image: str, staged: Path) -> None:
    """Spec section 5 rule 6: enforce against what the CONTAINER can see."""
    result = run_in_sandbox(
        image, staged, ["find", ".", "-type", "f", "-printf", "%P\\n"], network="none"
    )
    seen = {line for line in result.stdout.splitlines() if line}
    if seen != fixture.manifest:
        raise FixtureViolation(
            f"container manifest mismatch; unlisted={sorted(seen - fixture.manifest)}"
        )
```

- [ ] **Step 3: Confirm all six tests pass, then commit**

```bash
uv run pytest tests/test_fixture.py -v
git add harness/fixture.py tests/test_fixture.py
git commit -m "feat: fixture validation rejecting symlinks, hardlinks and git metadata"
```

---

## Task 5: The complete `py-callsite-01` fixture

Revision 1 sketched this. It must be an actually-runnable Django project.

**Files:** everything under `fixtures/py-callsite-01/`.

- [ ] **Step 1: Build a minimal but real Django project in `repo/`**

`manage.py`, `config/settings.py` (with `USE_TZ = True`, sqlite, `notifications` installed), `config/urls.py`, `notifications/` with `models.py`, `services.py`, `views.py`, `serializers.py`, `management/commands/send_digest.py`, and `apps.py`.

`notifications/models.py`:

```python
from django.conf import settings
from django.db import models

class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    sent = models.BooleanField(default=False)
```

`notifications/services.py` - the function that will gain a parameter:

```python
def format_notification(notification, locale):
    """Render a notification for display."""
    return f"[{locale}] {notification.title}: {notification.body}"
```

The three call sites are as described in the hazard: `views.py`, `serializers.py`, and `management/commands/send_digest.py`. A `UserProfile` model carries `timezone`.

- [ ] **Step 2: Write the deliberately incomplete test suite in `repo/tests/`**

Covers the view path only. **It must not exercise `send_digest`** - that gap is the hazard.

- [ ] **Step 3: Verify the fixture runs green before any model touches it**

```bash
podman run --rm --network=none -v "$PWD/fixtures/py-callsite-01/repo:/workspace:rw,Z" \
  -w /workspace localhost/odr-grading:latest python -m pytest tests -q
```

Expected: PASS. **A fixture whose own suite is red is unusable** - the agent would spend its turn fixing unrelated breakage.

- [ ] **Step 4: Write `task.md`, `hazards.yaml` with explicit test mapping, and `manifest.txt`**

`hazards.yaml` now names its grader tests explicitly, so attribution is not substring matching:

```yaml
hazards:
  - id: H-CALLSITE
    origin: invented
    class: agnostic
    description: >
      format_notification gains a timezone parameter. Three call sites exist;
      send_digest.py is a management command the repo's own suite never runs.
    call_sites:
      - notifications/views.py
      - notifications/serializers.py
      - notifications/management/commands/send_digest.py
    tests:
      - "_grader/test_hazard_callsite.py::test_view_path_uses_timezone"
      - "_grader/test_hazard_callsite.py::test_serializer_path_uses_timezone"
      - "_grader/test_hazard_callsite.py::test_management_command_renders"
      - "_grader/test_hazard_callsite.py::test_management_command_uses_timezone"
```

Generate `manifest.txt`:

```bash
cd fixtures/py-callsite-01/repo && find . -type f -printf '%P\n' | sort > ../manifest.txt
```

- [ ] **Step 5: Write the hidden grader covering all three call sites**

`grader/test_hazard_callsite.py` plus `grader/conftest.py` defining `user_in_tokyo` and `unsent_notification`. All four tests named in `hazards.yaml` must exist.

- [ ] **Step 6: Write three full `known_good` trees and one `known_bad`**

These are **complete trees**, not overlays - `grade()` treats them as such.

| Variant | Signature | Call sites |
|---|---|---|
| `known_good/default_arg` | `format_notification(notification, locale, tz=None)`, falling back to `notification.user.profile.timezone` | may omit |
| `known_good/explicit_all` | `format_notification(notification, locale, tz)` | all three pass positionally |
| `known_good/keyword_only` | `format_notification(notification, locale, *, tz)` | all three pass `tz=` |
| `known_bad/missed_command` | required `tz` added | `views.py` and `serializers.py` updated, `send_digest.py` left on the old signature |

- [ ] **Step 7: Commit**

```bash
git add fixtures/py-callsite-01
git commit -m "feat: complete py-callsite-01 Django fixture with explicit hazard test mapping"
```

---

## Task 6: Grader with persistent output and tri-state results

Revision 1 wrote the report to a `--rm` container's tmpfs and then tried to read it from a *different* container. It could never have worked.

**Files:**
- Create: `graders/apply.py`
- Test: `tests/test_grader_validation.py`

**Interfaces:**
- Produces: `grade(fixture, tree) -> GradeResult` with `.hazard_results: dict[str, str]` valued `"pass"`, `"fail"`, or `"invalid"`, plus `.error: str | None`.
- Produces: `validate_hazard_mapping(fixture) -> None` raising if a declared test does not exist.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_grader_validation.py
import pytest
from pathlib import Path
from harness.fixture import load_fixture
from graders.apply import grade, validate_hazard_mapping

FX = Path("fixtures/py-callsite-01")

def test_declared_hazard_tests_all_exist():
    validate_hazard_mapping(load_fixture(FX))   # raises if not

@pytest.mark.parametrize("variant", ["default_arg", "explicit_all", "keyword_only"])
def test_every_known_good_variant_passes(variant):
    result = grade(load_fixture(FX), FX / "known_good" / variant)
    assert result.error is None
    assert result.hazard_results["H-CALLSITE"] == "pass", result.hazard_results

def test_known_bad_fails_the_hazard():
    result = grade(load_fixture(FX), FX / "known_bad" / "missed_command")
    assert result.hazard_results["H-CALLSITE"] == "fail"

def test_missing_grader_test_is_invalid_not_fail(tmp_path):
    """Infrastructure error must never look like a model failure."""
    fx = load_fixture(FX)
    broken = tmp_path / "broken"
    import shutil; shutil.copytree(FX / "known_good" / "explicit_all", broken)
    (broken / "notifications" / "services.py").write_text("raise ImportError('boom')\n")
    result = grade(fx, broken)
    assert result.hazard_results["H-CALLSITE"] == "invalid"
```

- [ ] **Step 2: Confirm it fails, then implement**

```python
# graders/apply.py
from __future__ import annotations
import json, shutil, tempfile
from dataclasses import dataclass
from pathlib import Path
from harness.fixture import Fixture, FixtureViolation
from harness.sandbox import run_in_sandbox

GRADING_IMAGE = "localhost/odr-grading:latest"

@dataclass(frozen=True)
class GradeResult:
    hazard_results: dict[str, str]
    error: str | None

def validate_hazard_mapping(fixture: Fixture) -> None:
    for hazard in fixture.hazards:
        tests = hazard.get("tests") or []
        if not tests:
            raise FixtureViolation(f"{hazard['id']} declares no grader tests")
        for nodeid in tests:
            rel = nodeid.split("::")[0].removeprefix("_grader/")
            if not (fixture.root / "grader" / rel).exists():
                raise FixtureViolation(f"{hazard['id']} names missing file {rel}")

def _safe_copy(src: Path, dest: Path) -> None:
    """Never dereference model-authored symlinks on the host."""
    shutil.copytree(src, dest, symlinks=True)

def grade(fixture: Fixture, tree: Path) -> GradeResult:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "work"
        out = Path(tmp) / "out"
        out.mkdir()
        _safe_copy(tree, work)
        if (work / "_grader").exists():
            return GradeResult(
                {h["id"]: "invalid" for h in fixture.hazards},
                "_grader is reserved and was present in the post-run tree",
            )
        _safe_copy(fixture.root / "grader", work / "_grader")

        result = run_in_sandbox(
            GRADING_IMAGE, work,
            ["python", "-m", "pytest", "_grader", "-q", "-p", "no:cacheprovider",
             "--json-report", "--json-report-file=/out/report.json"],
            network="none", timeout_s=300, extra_mounts={out: "/out"},
        )
        report_path = out / "report.json"
        if result.timed_out or not report_path.exists():
            return GradeResult(
                {h["id"]: "invalid" for h in fixture.hazards},
                f"grader produced no report (timed_out={result.timed_out}): "
                f"{result.stderr[-1000:]}",
            )
        report = json.loads(report_path.read_text())

    by_nodeid = {t["nodeid"]: t["outcome"] for t in report.get("tests", [])}
    results: dict[str, str] = {}
    for hazard in fixture.hazards:
        outcomes = [by_nodeid.get(nodeid) for nodeid in hazard["tests"]]
        if any(o is None for o in outcomes):
            results[hazard["id"]] = "invalid"
        elif all(o == "passed" for o in outcomes):
            results[hazard["id"]] = "pass"
        else:
            results[hazard["id"]] = "fail"
    return GradeResult(results, None)
```

- [ ] **Step 3: Confirm it passes, then commit**

```bash
uv run pytest tests/test_grader_validation.py -v
git add graders/apply.py tests/test_grader_validation.py
git commit -m "feat: grader with mounted report output and tri-state results"
```

---

## Task 7: Filesystem snapshot diffing

Git cannot be the baseline inside a tree the agent controls: it can commit, reset, or replace `.git`, and `git diff HEAD` misses untracked files.

**Files:**
- Create: `harness/snapshot.py`
- Test: `tests/test_snapshot.py`

**Interfaces:**
- Produces: `snapshot(tree) -> dict[str, str]` mapping relative path to sha256; `diff_snapshots(before, after) -> Changes` with `.added`, `.modified`, `.deleted` as `set[str]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_snapshot.py
from harness.snapshot import snapshot, diff_snapshots

def test_detects_added_modified_and_deleted(tmp_path):
    (tmp_path / "keep.py").write_text("a")
    (tmp_path / "change.py").write_text("b")
    (tmp_path / "gone.py").write_text("c")
    before = snapshot(tmp_path)
    (tmp_path / "change.py").write_text("b2")
    (tmp_path / "gone.py").unlink()
    (tmp_path / "new.py").write_text("d")
    changes = diff_snapshots(before, snapshot(tmp_path))
    assert changes.added == {"new.py"}
    assert changes.modified == {"change.py"}
    assert changes.deleted == {"gone.py"}

def test_untracked_new_file_is_detected(tmp_path):
    """The exact case git diff HEAD would have missed."""
    before = snapshot(tmp_path)
    (tmp_path / "sneaky.py").write_text("x")
    assert diff_snapshots(before, snapshot(tmp_path)).added == {"sneaky.py"}
```

- [ ] **Step 2: Confirm it fails, then implement**

```python
# harness/snapshot.py
from __future__ import annotations
import hashlib
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Changes:
    added: set[str]
    modified: set[str]
    deleted: set[str]

def snapshot(tree: Path) -> dict[str, str]:
    tree = Path(tree)
    out: dict[str, str] = {}
    for path in sorted(tree.rglob("*")):
        if path.is_symlink():
            out[path.relative_to(tree).as_posix()] = "symlink:" + str(path.readlink())
        elif path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            out[path.relative_to(tree).as_posix()] = digest
    return out

def diff_snapshots(before: dict[str, str], after: dict[str, str]) -> Changes:
    before_keys, after_keys = set(before), set(after)
    return Changes(
        added=after_keys - before_keys,
        deleted=before_keys - after_keys,
        modified={k for k in before_keys & after_keys if before[k] != after[k]},
    )
```

- [ ] **Step 3: Confirm it passes, then commit**

```bash
uv run pytest tests/test_snapshot.py -v
git add harness/snapshot.py tests/test_snapshot.py
git commit -m "feat: filesystem snapshot diffing, replacing git-based change capture"
```

---

## Task 8: Containerised runner

**Files:**
- Create: `harness/runner.py`
- Test: `tests/test_runner.py`

**Interfaces:**
- Produces: `Arm(name, model_id, credential_env)`; `STERILE_ENV`; `build_canonical_config(arm) -> str`; `run_agent(fixture, arm, workdir) -> RunResult` with `.changes: Changes`, `.session: dict`, `.status: str` in `{"completed","capped","invalid"}`, `.model_verified: bool`; `assert_sterile(image) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_runner.py
import json, pytest
from pathlib import Path
from harness.runner import STERILE_ENV, Arm, verify_model_id, ModelMismatch, assert_sterile

REQUIRED = [
    "OPENCODE_DISABLE_PROJECT_CONFIG", "OPENCODE_DISABLE_CLAUDE_CODE",
    "OPENCODE_DISABLE_CLAUDE_CODE_PROMPT", "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS",
    "OPENCODE_DISABLE_EXTERNAL_SKILLS", "OPENCODE_DISABLE_DEFAULT_PLUGINS",
    "OPENCODE_DISABLE_AUTOCOMPACT", "OPENCODE_DISABLE_MODELS_FETCH",
    "OPENCODE_DISABLE_AUTOUPDATE", "OPENCODE_DISABLE_SHARE",
]

def test_all_ten_switches_set():
    assert [k for k in REQUIRED if STERILE_ENV.get(k) != "1"] == []

def test_model_mismatch_raises():
    session = json.loads(Path("contracts/session-export.json").read_text())
    with pytest.raises(ModelMismatch):
        verify_model_id(session, expected="definitely-not-the-model")

def test_container_config_is_sterile():
    """Deterministic isolation check inside the real agent image."""
    assert_sterile("localhost/odr-agent:latest")   # raises on contamination
```

- [ ] **Step 2: Confirm it fails, then implement**

`verify_model_id` is written against the **real** export shape recorded in Task 1, not an assumed one. `run_agent` runs the whole lifecycle in the agent container: isolated `HOME` on tmpfs outside `/workspace`, canonical config via `OPENCODE_CONFIG_CONTENT`, credential via `OPENCODE_AUTH_CONTENT`, snapshot before and after, `opencode export` inside the same container before it is destroyed.

```python
# harness/runner.py  (skeleton - the parsing details come from contracts/README.md)
from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path
from harness.sandbox import run_in_sandbox
from harness.snapshot import snapshot, diff_snapshots, Changes

class ModelMismatch(Exception): ...

STERILE_ENV = {
    "OPENCODE_DISABLE_PROJECT_CONFIG": "1", "OPENCODE_DISABLE_CLAUDE_CODE": "1",
    "OPENCODE_DISABLE_CLAUDE_CODE_PROMPT": "1", "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS": "1",
    "OPENCODE_DISABLE_EXTERNAL_SKILLS": "1", "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1",
    "OPENCODE_DISABLE_AUTOCOMPACT": "1", "OPENCODE_DISABLE_MODELS_FETCH": "1",
    "OPENCODE_DISABLE_AUTOUPDATE": "1", "OPENCODE_DISABLE_SHARE": "1",
    "HOME": "/tmp/agent-home", "XDG_CONFIG_HOME": "/tmp/agent-home/.config",
}

@dataclass(frozen=True)
class Arm:
    name: str
    model_id: str
    credential_env: dict[str, str] = field(default_factory=dict)

@dataclass(frozen=True)
class RunResult:
    changes: Changes
    session: dict
    status: str
    model_verified: bool

def assert_sterile(image: str) -> None:
    """Spec 6.0: verify isolation deterministically, with a positive control."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "AGENTS.md").write_text("CANARY_PROJECT_INSTRUCTION\n")
        (work / "opencode.json").write_text('{"model":"canary/model"}')
        sterile = run_in_sandbox(image, work, ["opencode", "debug", "config", "--pure"],
                                 network="none", env=STERILE_ENV)
        config = json.loads(sterile.stdout)
        if config.get("provider") or config.get("plugin") or config.get("skills"):
            raise AssertionError(f"agent image is not sterile: {sterile.stdout[:500]}")
        if config.get("model") == "canary/model":
            raise AssertionError("project config leaked into the sterile run")
```

- [ ] **Step 3: Confirm it passes, then commit**

```bash
uv run pytest tests/test_runner.py -v
git add harness/runner.py tests/test_runner.py
git commit -m "feat: containerised runner with deterministic sterility assertion"
```

---

## Task 9: Trace observations from real exports

Written **after** Task 1, against real data. Revision 1's version had `T-SCOPE` measuring "did any edit happen" and `T-CLAIMDONE` never looking at what the model claimed.

**Files:**
- Create: `harness/trace.py`
- Test: `tests/test_trace.py`

**Interfaces:**
- Produces: `observations(session, *, changes, allowed_scope) -> dict` with keys `ran_tests`, `tests_succeeded`, `read_before_edit`, `out_of_scope_paths`, `claimed_success`.

Note these are **observations**, reported separately, not a single conflated verdict. `T-CLAIMDONE` in spec §8 is the conjunction of `claimed_success` and a failing hidden suite, and is computed by the reporter - not baked into the parser.

- [ ] **Step 1: Write the failing test against the recorded contract**

```python
# tests/test_trace.py
import json
from pathlib import Path
from harness.trace import observations
from harness.snapshot import Changes

SESSION = json.loads(Path("contracts/session-export.json").read_text())

def test_out_of_scope_is_derived_from_real_changes_not_tool_calls():
    changes = Changes(added={"evil.py"}, modified=set(), deleted=set())
    obs = observations(SESSION, changes=changes, allowed_scope={"calc.py"})
    assert obs["out_of_scope_paths"] == {"evil.py"}

def test_in_scope_change_is_not_flagged():
    changes = Changes(added=set(), modified={"calc.py"}, deleted=set())
    obs = observations(SESSION, changes=changes, allowed_scope={"calc.py"})
    assert obs["out_of_scope_paths"] == set()

def test_ran_tests_requires_successful_execution_not_just_the_string():
    obs = observations(SESSION, changes=Changes(set(), set(), set()), allowed_scope=set())
    assert isinstance(obs["ran_tests"], bool)
    assert isinstance(obs["tests_succeeded"], bool)
```

- [ ] **Step 2: Confirm it fails, then implement against the real shape**

Derive mutations from `changes` (the snapshot diff), never from tool calls - bash writes, patch tools, and generated files are invisible to tool-call inspection. `ran_tests` requires an observed exit status, not a matching command string.

- [ ] **Step 3: Confirm it passes, then commit**

```bash
uv run pytest tests/test_trace.py -v
git add harness/trace.py tests/test_trace.py
git commit -m "feat: trace observations derived from real exports and snapshot diffs"
```

---

## Task 10: Bucketing over valid runs only

**Files:**
- Create: `analysis/bucket.py`
- Test: `tests/test_bucket.py`

**Interfaces:**
- Produces: `bucket(deepseek: ArmTally, opus: ArmTally) -> str`; `ArmTally(failures: int, valid_runs: int)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bucket.py
import pytest
from analysis.bucket import bucket, ArmTally

def test_deepseek_only():
    assert bucket(ArmTally(8, 10), ArmTally(1, 10)) == "deepseek_only"

def test_both():
    assert bucket(ArmTally(8, 10), ArmTally(7, 10)) == "both"

def test_opus_only_is_reported():
    assert bucket(ArmTally(1, 10), ArmTally(8, 10)) == "opus_only"

def test_capped_and_invalid_runs_are_excluded_from_the_denominator():
    """3 of 10 runs were invalid; the rate is 7/7, not 7/10."""
    assert bucket(ArmTally(7, 7), ArmTally(0, 10)) == "deepseek_only"

def test_too_few_valid_runs_refuses_to_classify():
    with pytest.raises(ValueError, match="insufficient"):
        bucket(ArmTally(1, 1), ArmTally(0, 10))
```

- [ ] **Step 2: Confirm it fails, then implement**

```python
# analysis/bucket.py
from __future__ import annotations
from dataclasses import dataclass

FAIL_HIGH = 0.6
FAIL_LOW = 0.2
MIN_VALID_RUNS = 3

@dataclass(frozen=True)
class ArmTally:
    failures: int
    valid_runs: int

    @property
    def rate(self) -> float:
        return self.failures / self.valid_runs

def bucket(deepseek: ArmTally, opus: ArmTally) -> str:
    for name, tally in (("deepseek", deepseek), ("opus", opus)):
        if tally.valid_runs < MIN_VALID_RUNS:
            raise ValueError(
                f"insufficient valid runs for {name}: {tally.valid_runs}"
            )
    d, o = deepseek.rate, opus.rate
    if d >= FAIL_HIGH and o <= FAIL_LOW: return "deepseek_only"
    if o >= FAIL_HIGH and d <= FAIL_LOW: return "opus_only"
    if d >= FAIL_HIGH and o >= FAIL_HIGH: return "both"
    return "neither"
```

These are **exploratory** thresholds. The promotion rule (spec §9.2, `D>=8 AND O<=1` plus cross-fixture replication) is stricter and is not implemented here, because this slice ships no skill.

- [ ] **Step 3: Confirm it passes, then commit**

```bash
uv run pytest tests/test_bucket.py -v
git add analysis/bucket.py tests/test_bucket.py
git commit -m "feat: bucketing that excludes invalid runs from the denominator"
```

---

## Task 11: End to end

**Files:**
- Create: `eval.py`
- Test: `tests/test_end_to_end.py`

- [ ] **Step 1: Write the integration test that spends no model tokens**

```python
# tests/test_end_to_end.py
from pathlib import Path
from harness.fixture import load_fixture, stage_agent_tree, assert_container_manifest
from graders.apply import grade, validate_hazard_mapping

FX = Path("fixtures/py-callsite-01")

def test_full_pipeline_minus_the_model_call(tmp_path):
    fixture = load_fixture(FX)
    validate_hazard_mapping(fixture)
    staged = tmp_path / "staged"
    stage_agent_tree(fixture, staged)
    assert_container_manifest(fixture, "localhost/odr-grading:latest", staged)
    assert not (staged / "grader").exists()
    assert grade(fixture, FX / "known_bad" / "missed_command").hazard_results["H-CALLSITE"] == "fail"
    assert grade(fixture, FX / "known_good" / "explicit_all").hazard_results["H-CALLSITE"] == "pass"
```

- [ ] **Step 2: Write `eval.py`**

Records per run: status, hazard results, observations, model id, config hash, image digest, opencode version. Tallies only `completed` runs into denominators.

- [ ] **Step 3: Preflight, then a single real run**

```bash
uv run python -c "from harness.preflight import preflight; print(preflight() or 'ready')"
uv run python eval.py run --fixture py-callsite-01 --arms deepseek --n 1
```

Inspect the record before spending more: was the model id verified? Did the container manifest match? Did the snapshot diff capture the change?

- [ ] **Step 4: Both arms, n=3**

```bash
uv run python eval.py run --fixture py-callsite-01 --arms deepseek,opus --n 3
```

**Draw no conclusions.** One fixture cannot support a finding (spec §9.3). The deliverable is a pipeline whose numbers can be trusted.

- [ ] **Step 5: Push and open the PR**

```bash
git push -u origin feat/vertical-slice
```

---

## Carried risks

1. **Task 1 may invalidate Tasks 8 and 9.** If the real export shape differs from what those tasks assume, they change - that is the point of capturing first.
2. **`opencode` install inside the agent image** may not work as scripted; the installer may need a pinned tarball instead.
3. **Egress allowlisting is not implemented in this slice.** The agent container gets full network. Spec §12 requires a proxy; deferred with this explicitly recorded, and it must exist before any unattended multi-run session.
4. **One hazard, not the spec's 3-6.** A deliberate prototype simplification (spec §7), not a hidden shortcut.
