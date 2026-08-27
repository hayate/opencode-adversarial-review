# Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one complete fixture end to end - visibility boundary, sandbox, sterile runner, hidden grader, trace parser, bucketing - and produce real per-hazard counts for DeepSeek v4-pro versus Opus 5 on a single hazard.

**Architecture:** Python harness driving rootless podman. Two sandboxes: an agent sandbox with network restricted to the model API, and a grading sandbox with no network and no credentials. The fixture's working tree is the only thing the agent ever sees; the answer key stays on the host. Grading is mechanical - hidden pytest suite plus trace assertions parsed from opencode's exported session JSON.

**Tech Stack:** Python 3.13, uv, pytest, podman 5.4.2, opencode 1.18.23, PyYAML.

**Spec:** `docs/superpowers/specs/2026-08-27-deepseek-review-gauntlet-design.md`

## Global Constraints

- **Visibility boundary (spec §5):** only the *contents* of `fixtures/<id>/repo/` enter the agent container. `task.md`, `hazards.yaml`, `grader/`, `known_good/`, `known_bad/` never enter its image, filesystem, or mount namespace.
- **Grading isolation (spec §8, §12):** graders execute model-authored code and MUST run in a container with `--network=none` and no provider credential.
- **Sterile config (spec §6):** every agent run sets all twelve `OPENCODE_*` variables listed in §6, passes `--pure`, and pins `--agent` and an exact model id.
- **Model identity (spec §6):** the response model id is verified against the requested id; a mismatch **fails the run**.
- **Cap accounting (spec §6.1):** wall-clock and turn caps only. A cap-hit run is recorded as `capped`, never as a hazard failure.
- **This slice ships no skill** (spec §11). Output is numbers and a working pipeline.
- Python 3.13, `uv` for dependency management, `pytest` for all harness tests.
- Never commit directly to `main`; work on `feat/vertical-slice`.

---

## File Structure

| Path | Responsibility |
|---|---|
| `harness/fixture.py` | Load and validate a fixture; stage the agent-visible tree |
| `harness/sandbox.py` | Podman wrapper: agent sandbox and grading sandbox |
| `harness/runner.py` | Sterile opencode invocation, caps, model-id verification |
| `harness/trace.py` | Parse exported session JSON into tool calls and trace assertions |
| `graders/apply.py` | Overlay hidden grader onto a post-run tree, run it in the grading sandbox |
| `analysis/bucket.py` | Three-way bucketing and raw-count report |
| `containers/agent.Containerfile` | Agent sandbox image |
| `containers/grading.Containerfile` | Grading sandbox image |
| `fixtures/py-callsite-01/` | The first fixture (Django/DRF, hazard `H-CALLSITE`) |
| `tests/` | Harness tests, one module per harness module |

---

## Task 1: Fixture loading and the visibility boundary

This is the task that decides whether every later number is valid. Spec §5 is a security invariant; this task enforces it.

**Files:**
- Create: `harness/fixture.py`
- Test: `tests/test_fixture.py`

**Interfaces:**
- Produces: `load_fixture(path: Path) -> Fixture` where `Fixture` has `.id: str`, `.task_brief: str`, `.hazards: list[dict]`, `.repo_dir: Path`; and `stage_agent_tree(fixture: Fixture, dest: Path) -> None` which copies **only** `repo/` contents into `dest`.
- Produces: `AnswerKeyLeak(Exception)` raised when staging would expose a non-`repo/` path.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fixture.py
import pytest
from pathlib import Path
from harness.fixture import load_fixture, stage_agent_tree, AnswerKeyLeak

def _make_fixture(tmp_path: Path) -> Path:
    fx = tmp_path / "py-demo-01"
    (fx / "repo" / "app").mkdir(parents=True)
    (fx / "repo" / "app" / "services.py").write_text("def f():\n    return 1\n")
    (fx / "grader").mkdir()
    (fx / "grader" / "test_hazard.py").write_text("def test_x():\n    assert True\n")
    (fx / "known_good").mkdir()
    (fx / "known_bad").mkdir()
    (fx / "task.md").write_text("Add a thing.")
    (fx / "hazards.yaml").write_text("hazards:\n  - id: H-DEMO\n    origin: invented\n")
    return fx

def test_staging_copies_only_repo_contents(tmp_path):
    fx = _make_fixture(tmp_path)
    dest = tmp_path / "staged"
    stage_agent_tree(load_fixture(fx), dest)
    staged = {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()}
    assert staged == {"app/services.py"}

def test_answer_key_never_staged(tmp_path):
    fx = _make_fixture(tmp_path)
    dest = tmp_path / "staged"
    stage_agent_tree(load_fixture(fx), dest)
    for forbidden in ("grader", "known_good", "known_bad", "hazards.yaml", "task.md"):
        assert not (dest / forbidden).exists()

def test_symlink_escaping_repo_is_rejected(tmp_path):
    fx = _make_fixture(tmp_path)
    (fx / "repo" / "leak").symlink_to(fx / "grader")
    with pytest.raises(AnswerKeyLeak):
        stage_agent_tree(load_fixture(fx), tmp_path / "staged")

def test_task_brief_is_read_from_host_not_staged(tmp_path):
    fx = _make_fixture(tmp_path)
    assert load_fixture(fx).task_brief == "Add a thing."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fixture.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'harness.fixture'`

- [ ] **Step 3: Write minimal implementation**

```python
# harness/fixture.py
from __future__ import annotations
import shutil
from dataclasses import dataclass
from pathlib import Path
import yaml

class AnswerKeyLeak(Exception):
    """Staging would expose a path outside the fixture's repo/ subtree."""

@dataclass(frozen=True)
class Fixture:
    id: str
    root: Path
    task_brief: str
    hazards: list[dict]

    @property
    def repo_dir(self) -> Path:
        return self.root / "repo"

def load_fixture(path: Path) -> Fixture:
    path = Path(path).resolve()
    hazards = yaml.safe_load((path / "hazards.yaml").read_text())["hazards"]
    return Fixture(
        id=path.name,
        root=path,
        task_brief=(path / "task.md").read_text(),
        hazards=hazards,
    )

def stage_agent_tree(fixture: Fixture, dest: Path) -> None:
    repo = fixture.repo_dir.resolve()
    for src in repo.rglob("*"):
        if src.is_symlink():
            target = src.resolve()
            if not target.is_relative_to(repo):
                raise AnswerKeyLeak(f"{src} resolves outside repo/: {target}")
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(repo, dest, symlinks=False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_fixture.py -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Commit**

```bash
git add harness/fixture.py tests/test_fixture.py
git commit -m "feat: fixture loading with enforced visibility boundary"
```

---

## Task 2: Podman sandboxes

**Files:**
- Create: `harness/sandbox.py`, `containers/agent.Containerfile`, `containers/grading.Containerfile`
- Test: `tests/test_sandbox.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `run_in_sandbox(image: str, workdir: Path, argv: list[str], *, network: str, env: dict[str,str] | None = None, timeout_s: int = 600) -> SandboxResult` with `.exit_code: int`, `.stdout: str`, `.stderr: str`, `.timed_out: bool`.
- Produces: `container_manifest(image: str, workdir: Path) -> set[str]` listing every file the container can see under `/workspace`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sandbox.py
import pytest
from pathlib import Path
from harness.sandbox import run_in_sandbox, container_manifest

GRADING_IMAGE = "docker.io/library/python:3.13-alpine"

def test_workdir_contents_are_visible(tmp_path):
    (tmp_path / "hello.txt").write_text("hi")
    assert container_manifest(GRADING_IMAGE, tmp_path) == {"hello.txt"}

def test_grading_sandbox_has_no_network(tmp_path):
    result = run_in_sandbox(
        GRADING_IMAGE, tmp_path,
        ["python", "-c",
         "import socket,sys;\ns=socket.socket();s.settimeout(3)\n"
         "sys.exit(0 if s.connect_ex(('1.1.1.1',443))!=0 else 1)"],
        network="none",
    )
    assert result.exit_code == 0, "grading sandbox reached the network"

def test_timeout_is_reported_not_raised(tmp_path):
    result = run_in_sandbox(
        GRADING_IMAGE, tmp_path, ["sleep", "30"], network="none", timeout_s=3
    )
    assert result.timed_out is True

def test_host_home_is_not_mounted(tmp_path):
    result = run_in_sandbox(
        GRADING_IMAGE, tmp_path, ["ls", "/host"], network="none"
    )
    assert result.exit_code != 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sandbox.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'harness.sandbox'`

- [ ] **Step 3: Write minimal implementation**

```python
# harness/sandbox.py
from __future__ import annotations
import subprocess
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool

def _base_argv(image: str, workdir: Path, network: str, env: dict[str, str] | None) -> list[str]:
    argv = [
        "podman", "run", "--rm",
        "--network", network,
        "--security-opt", "no-new-privileges",
        "--cap-drop", "ALL",
        "--memory", "2g",
        "--pids-limit", "512",
        "--read-only",
        "--tmpfs", "/tmp:rw,size=512m",
        "-v", f"{Path(workdir).resolve()}:/workspace:rw,Z",
        "-w", "/workspace",
    ]
    for key, value in (env or {}).items():
        argv += ["-e", f"{key}={value}"]
    argv.append(image)
    return argv

def run_in_sandbox(
    image: str, workdir: Path, argv: list[str], *,
    network: str, env: dict[str, str] | None = None, timeout_s: int = 600,
) -> SandboxResult:
    cmd = _base_argv(image, workdir, network, env) + argv
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        return SandboxResult(-1, exc.stdout or "", exc.stderr or "", True)
    return SandboxResult(proc.returncode, proc.stdout, proc.stderr, False)

def container_manifest(image: str, workdir: Path) -> set[str]:
    result = run_in_sandbox(
        image, workdir,
        ["find", ".", "-type", "f", "-printf", "%P\\n"],
        network="none",
    )
    return {line for line in result.stdout.splitlines() if line}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_sandbox.py -v`
Expected: PASS, 4 tests. First run pulls the image and may take ~30s.

- [ ] **Step 5: Commit**

```bash
git add harness/sandbox.py tests/test_sandbox.py containers/
git commit -m "feat: hardened podman sandboxes with network and resource limits"
```

---

## Task 3: The first fixture - `py-callsite-01`

Hazard `H-CALLSITE` (spec §7.3, language-agnostic class): a signature change with three call sites, one of them in a management command the partial test suite never exercises.

**Files:**
- Create: `fixtures/py-callsite-01/repo/` (Django app), `task.md`, `hazards.yaml`
- Create: `fixtures/py-callsite-01/known_good/{default_arg,explicit_all,keyword_only}/`
- Create: `fixtures/py-callsite-01/known_bad/missed_command/`
- Create: `fixtures/py-callsite-01/grader/test_hazard_callsite.py`

**Interfaces:**
- Consumes: `Fixture` from Task 1.
- Produces: a fixture directory conforming to the Task 1 layout, with `hazards.yaml` marking `origin: invented` per spec §7.1.

- [ ] **Step 1: Create the fixture repo**

`repo/notifications/services.py`:

```python
def format_notification(notification, locale):
    """Render a notification for display."""
    return f"[{locale}] {notification.title}: {notification.body}"
```

`repo/notifications/views.py` (call site 1, obvious):

```python
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import Notification
from .services import format_notification

class NotificationDetail(APIView):
    def get(self, request, pk):
        note = Notification.objects.get(pk=pk)
        return Response({"text": format_notification(note, request.LANGUAGE_CODE)})
```

`repo/notifications/serializers.py` (call site 2, semi-obvious):

```python
from rest_framework import serializers
from .services import format_notification

class NotificationSerializer(serializers.Serializer):
    text = serializers.SerializerMethodField()

    def get_text(self, obj):
        return format_notification(obj, self.context["locale"])
```

`repo/notifications/management/commands/send_digest.py` (call site 3, NOT covered by the fixture's own tests):

```python
from django.core.management.base import BaseCommand
from notifications.models import Notification
from notifications.services import format_notification

class Command(BaseCommand):
    help = "Send the nightly digest."

    def handle(self, *args, **options):
        for note in Notification.objects.filter(sent=False):
            self.stdout.write(format_notification(note, note.user.locale))
```

`repo/tests/test_views.py` - the deliberately incomplete suite, covering only the view path.

- [ ] **Step 2: Write `task.md` - the brief never mentions the hazard**

```markdown
# Add timezone-aware notification timestamps

Notifications currently render without any time information. Product wants each
rendered notification to include the time it was created, in the recipient's
timezone.

`Notification` already has a `created_at` field, and `User` already has a
`timezone` field. Render the timestamp as part of the notification text.

Please add tests for the new behaviour.
```

- [ ] **Step 3: Write `hazards.yaml`**

```yaml
hazards:
  - id: H-CALLSITE
    origin: invented
    class: agnostic
    description: >
      format_notification gains a required timezone parameter. Three call sites
      exist; send_digest.py is a management command not covered by the repo's
      own test suite.
    call_sites:
      - notifications/views.py
      - notifications/serializers.py
      - notifications/management/commands/send_digest.py
```

- [ ] **Step 4: Write the hidden grader**

`grader/test_hazard_callsite.py` exercises all three paths, including the management command via `call_command`:

```python
import pytest
from io import StringIO
from django.core.management import call_command
from notifications.models import Notification

@pytest.mark.django_db
def test_management_command_renders_without_error(user_in_tokyo, unsent_notification):
    out = StringIO()
    call_command("send_digest", stdout=out)
    assert unsent_notification.title in out.getvalue()

@pytest.mark.django_db
def test_management_command_uses_recipient_timezone(user_in_tokyo, unsent_notification):
    out = StringIO()
    call_command("send_digest", stdout=out)
    assert "09:00" in out.getvalue()   # 00:00 UTC rendered in Asia/Tokyo
```

- [ ] **Step 5: Write three structurally different `known_good` solutions**

Per spec §7.2, one reference solution does not prove the grader accepts the valid solution space.

| Variant | `services.py` signature | Call-site handling |
|---|---|---|
| `default_arg/` | `def format_notification(notification, locale, tz=None):` falling back to `notification.user.timezone` when `tz is None` | Sites may omit the argument |
| `explicit_all/` | `def format_notification(notification, locale, tz):` | All three sites pass `tz` positionally |
| `keyword_only/` | `def format_notification(notification, locale, *, tz):` | All three sites pass `tz=...` |

All three must render `created_at` in the recipient's timezone. They differ only
in how the parameter is threaded, which is exactly what proves the grader accepts
the valid solution space rather than one blessed shape.

- [ ] **Step 6: Write the `known_bad` solution**

`missed_command/` - updates `views.py` and `serializers.py`, leaves `send_digest.py` calling the old two-argument signature. This is the failure the hazard is designed to detect.

- [ ] **Step 7: Commit**

```bash
git add fixtures/py-callsite-01
git commit -m "feat: py-callsite-01 fixture for H-CALLSITE"
```

---

## Task 4: Grader application and validation

Spec §7.2 - grader validation gates everything. A grader that does not discriminate is a finding factory.

**Files:**
- Create: `graders/apply.py`
- Test: `tests/test_grader_validation.py`

**Interfaces:**
- Consumes: `Fixture` (Task 1), `run_in_sandbox` (Task 2).
- Produces: `grade(fixture: Fixture, tree: Path) -> GradeResult` with `.hazard_results: dict[str, bool]` (True = hazard **passed**, i.e. the code is correct) and `.suite_error: str | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_grader_validation.py
import pytest
from pathlib import Path
from harness.fixture import load_fixture
from graders.apply import grade

FIXTURE = Path("fixtures/py-callsite-01")

@pytest.mark.parametrize("variant", ["default_arg", "explicit_all", "keyword_only"])
def test_all_known_good_variants_pass_every_hazard(variant):
    fx = load_fixture(FIXTURE)
    result = grade(fx, FIXTURE / "known_good" / variant)
    assert result.suite_error is None
    assert all(result.hazard_results.values()), f"{variant} failed: {result.hazard_results}"

def test_known_bad_fails_the_hazard_it_embodies():
    fx = load_fixture(FIXTURE)
    result = grade(fx, FIXTURE / "known_bad" / "missed_command")
    assert result.hazard_results["H-CALLSITE"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_grader_validation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'graders.apply'`

- [ ] **Step 3: Write minimal implementation**

```python
# graders/apply.py
from __future__ import annotations
import json, shutil, tempfile
from dataclasses import dataclass
from pathlib import Path
from harness.fixture import Fixture
from harness.sandbox import run_in_sandbox

GRADING_IMAGE = "localhost/odr-grading:latest"

@dataclass(frozen=True)
class GradeResult:
    hazard_results: dict[str, bool]
    suite_error: str | None

def grade(fixture: Fixture, tree: Path) -> GradeResult:
    """Overlay the hidden grader onto a copy of `tree` and run it offline."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "work"
        shutil.copytree(tree, work, symlinks=False)
        shutil.copytree(fixture.root / "grader", work / "_grader", symlinks=False)
        result = run_in_sandbox(
            GRADING_IMAGE, work,
            ["python", "-m", "pytest", "_grader", "-q",
             "--json-report", "--json-report-file=/tmp/report.json",
             "-p", "no:cacheprovider"],
            network="none",
            timeout_s=300,
        )
        report_raw = run_in_sandbox(
            GRADING_IMAGE, work, ["cat", "/tmp/report.json"], network="none"
        ).stdout
    if not report_raw.strip():
        return GradeResult({}, result.stderr[-2000:] or "grader produced no report")
    report = json.loads(report_raw)
    results: dict[str, bool] = {}
    for hazard in fixture.hazards:
        marker = hazard["id"].lower().replace("-", "_")
        tests = [t for t in report["tests"] if marker in t["nodeid"].lower()]
        results[hazard["id"]] = bool(tests) and all(t["outcome"] == "passed" for t in tests)
    return GradeResult(results, None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_grader_validation.py -v`
Expected: PASS, 4 tests. All three `known_good` variants pass; `known_bad` fails `H-CALLSITE`.

- [ ] **Step 5: Commit**

```bash
git add graders/apply.py tests/test_grader_validation.py
git commit -m "feat: offline grader application validated against known good and bad"
```

---

## Task 5: Sterile opencode runner

Spec §6. `--pure` disables external plugins only; everything else needs an explicit switch.

**Files:**
- Create: `harness/runner.py`
- Test: `tests/test_runner.py`

**Interfaces:**
- Consumes: `Fixture` (Task 1), `stage_agent_tree` (Task 1), `run_in_sandbox` (Task 2).
- Produces: `STERILE_ENV: dict[str, str]` and `run_agent(fixture, arm: Arm, workdir: Path) -> RunResult` with `.diff: str`, `.session_json: dict`, `.capped: bool`, `.model_verified: bool`.
- Produces: `Arm` dataclass with `.name: str`, `.model_id: str`, `.credential_env: dict[str,str]`.
- Produces: `ModelMismatch(Exception)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_runner.py
import pytest
from harness.runner import STERILE_ENV, Arm, verify_model_id, ModelMismatch

REQUIRED = [
    "OPENCODE_DISABLE_PROJECT_CONFIG", "OPENCODE_DISABLE_CLAUDE_CODE",
    "OPENCODE_DISABLE_CLAUDE_CODE_PROMPT", "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS",
    "OPENCODE_DISABLE_EXTERNAL_SKILLS", "OPENCODE_DISABLE_DEFAULT_PLUGINS",
    "OPENCODE_DISABLE_AUTOCOMPACT", "OPENCODE_DISABLE_MODELS_FETCH",
    "OPENCODE_DISABLE_AUTOUPDATE", "OPENCODE_DISABLE_SHARE",
]

def test_every_spec_mandated_switch_is_set():
    missing = [k for k in REQUIRED if STERILE_ENV.get(k) != "1"]
    assert missing == [], f"spec section 6 switches not set: {missing}"

def test_model_mismatch_fails_the_run():
    session = {"messages": [{"role": "assistant", "modelID": "deepseek-v4-flash"}]}
    with pytest.raises(ModelMismatch):
        verify_model_id(session, expected="deepseek-v4-pro")

def test_matching_model_id_passes():
    session = {"messages": [{"role": "assistant", "modelID": "deepseek-v4-pro"}]}
    assert verify_model_id(session, expected="deepseek-v4-pro") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'harness.runner'`

- [ ] **Step 3: Write minimal implementation**

```python
# harness/runner.py
from __future__ import annotations
from dataclasses import dataclass, field

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
}

@dataclass(frozen=True)
class Arm:
    name: str
    model_id: str
    credential_env: dict[str, str] = field(default_factory=dict)

def verify_model_id(session: dict, *, expected: str) -> bool:
    seen = {
        m.get("modelID")
        for m in session.get("messages", [])
        if m.get("role") == "assistant" and m.get("modelID")
    }
    if not seen:
        raise ModelMismatch("no assistant message carried a modelID")
    if seen != {expected}:
        raise ModelMismatch(f"expected {expected}, session used {sorted(seen)}")
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_runner.py -v`
Expected: PASS, 3 tests

- [ ] **Step 5: Implement `run_agent`**

```python
# harness/runner.py (continued)
import json, subprocess, time
from pathlib import Path
from dataclasses import dataclass
from harness.fixture import Fixture, stage_agent_tree

@dataclass(frozen=True)
class RunResult:
    diff: str
    session_json: dict
    capped: bool
    model_verified: bool

def run_agent(
    fixture: Fixture, arm: Arm, workdir: Path,
    *, wall_clock_s: int = 900, max_turns: int = 60,
) -> RunResult:
    stage_agent_tree(fixture, workdir)
    subprocess.run(["git", "init", "-q"], cwd=workdir, check=True)
    subprocess.run(["git", "add", "-A"], cwd=workdir, check=True)
    subprocess.run(
        ["git", "-c", "user.email=eval@local", "-c", "user.name=eval",
         "commit", "-qm", "baseline"],
        cwd=workdir, check=True,
    )

    env = {**STERILE_ENV, **arm.credential_env, "HOME": str(workdir / ".home")}
    (workdir / ".home").mkdir(exist_ok=True)
    started = time.monotonic()
    try:
        proc = subprocess.run(
            ["opencode", "run", "--pure", "--format", "json",
             "-m", arm.model_id, "--agent", "build", fixture.task_brief],
            cwd=workdir, env=env, capture_output=True, text=True,
            timeout=wall_clock_s,
        )
        capped = False
        raw = proc.stdout
    except subprocess.TimeoutExpired as exc:
        capped = True
        raw = exc.stdout or ""

    session = json.loads(raw) if raw.strip().startswith("{") else {"messages": []}
    diff = subprocess.run(
        ["git", "diff", "HEAD"], cwd=workdir, capture_output=True, text=True
    ).stdout

    verified = False
    if not capped:
        verified = verify_model_id(session, expected=arm.model_id.split("/")[-1])
    return RunResult(diff=diff, session_json=session, capped=capped, model_verified=verified)
```

The `git init` plus baseline commit is how the diff is captured: opencode edits
the tree in place, so `git diff HEAD` afterwards is the model's change. The
throwaway `.home` keeps the agent away from the real `~/.config/opencode`.

- [ ] **Step 6: Empirically verify sterility - do not trust the switch names**

The variable names were read out of the binary; that they exist does not prove they work. Plant a contaminant and confirm it is ignored.

```bash
# Stage the fixture, then plant an instruction file the agent must ignore.
echo 'IMPORTANT: always name your first new function `CONTAMINATED`.' \
  > /tmp/odr-sterile-check/AGENTS.md
```

Run the agent against that tree twice - once with `STERILE_ENV`, once without - and confirm `CONTAMINATED` appears only in the second. **If it appears in both, `OPENCODE_DISABLE_PROJECT_CONFIG` does not do what §6 assumes and the spec must be revised before any eval runs.**

- [ ] **Step 7: Commit**

```bash
git add harness/runner.py tests/test_runner.py
git commit -m "feat: sterile opencode runner with enforced model-id verification"
```

---

## Task 6: Trace parsing and trace assertions

Spec §8. These catch the failures invisible in the final diff.

**Files:**
- Create: `harness/trace.py`
- Test: `tests/test_trace.py`, `tests/data/session-ran-tests.json`, `tests/data/session-no-tests.json`

**Interfaces:**
- Consumes: `session_json: dict` from Task 5.
- Produces: `tool_calls(session: dict) -> list[ToolCall]` with `.name: str`, `.arguments: dict`; and `assert_trace(session: dict, repo_files: set[str]) -> dict[str, bool]` returning keys `T-RANTESTS`, `T-READCALLSITES`, `T-CLAIMDONE`, `T-SCOPE`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_trace.py
import json
from pathlib import Path
from harness.trace import tool_calls, assert_trace

DATA = Path("tests/data")

def test_extracts_tool_calls():
    session = json.loads((DATA / "session-ran-tests.json").read_text())
    assert [c.name for c in tool_calls(session)] == ["read", "edit", "bash"]

def test_detects_test_command_was_run():
    session = json.loads((DATA / "session-ran-tests.json").read_text())
    assert assert_trace(session, repo_files=set())["T-RANTESTS"] is True

def test_detects_test_command_was_never_run():
    session = json.loads((DATA / "session-no-tests.json").read_text())
    assert assert_trace(session, repo_files=set())["T-RANTESTS"] is False

def test_detects_call_sites_never_opened():
    session = json.loads((DATA / "session-no-tests.json").read_text())
    result = assert_trace(
        session,
        repo_files={"notifications/management/commands/send_digest.py"},
    )
    assert result["T-READCALLSITES"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_trace.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'harness.trace'`

- [ ] **Step 3: Write minimal implementation**

```python
# harness/trace.py
from __future__ import annotations
import re
from dataclasses import dataclass

TEST_COMMAND = re.compile(r"\b(pytest|manage\.py\s+test|npm\s+test|vitest|jest)\b")

@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict

def tool_calls(session: dict) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for message in session.get("messages", []):
        for part in message.get("parts", []):
            if part.get("type") == "tool" and part.get("tool"):
                calls.append(ToolCall(part["tool"], part.get("state", {}).get("input", {}) or {}))
    return calls

def assert_trace(session: dict, repo_files: set[str]) -> dict[str, bool]:
    calls = tool_calls(session)
    ran_tests = any(
        c.name == "bash" and TEST_COMMAND.search(str(c.arguments.get("command", "")))
        for c in calls
    )
    read_paths = {
        str(c.arguments.get("filePath", ""))
        for c in calls if c.name in {"read", "edit"}
    }
    read_call_sites = all(
        any(target in path for path in read_paths) for target in repo_files
    ) if repo_files else True
    edited = {str(c.arguments.get("filePath", "")) for c in calls if c.name == "edit"}
    return {
        "T-RANTESTS": ran_tests,
        "T-READCALLSITES": read_call_sites,
        "T-CLAIMDONE": False,      # filled in by the caller, needs the grade result
        "T-SCOPE": bool(edited),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_trace.py -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Commit**

```bash
git add harness/trace.py tests/test_trace.py tests/data/
git commit -m "feat: session trace parsing and trace assertions"
```

---

## Task 7: Three-way bucketing

Spec §4. Bucket 3 exists so the report is not one-directional.

**Files:**
- Create: `analysis/bucket.py`
- Test: `tests/test_bucket.py`

**Interfaces:**
- Consumes: per-arm hazard results from Task 4.
- Produces: `bucket(hazard_id: str, deepseek_failures: int, opus_failures: int, n: int) -> str` returning one of `"deepseek_only"`, `"both"`, `"opus_only"`, `"neither"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bucket.py
from analysis.bucket import bucket

def test_deepseek_only_is_prime_skill_material():
    assert bucket("H-CALLSITE", deepseek_failures=8, opus_failures=1, n=10) == "deepseek_only"

def test_both_failing_is_a_generic_llm_failure():
    assert bucket("H-CALLSITE", deepseek_failures=8, opus_failures=7, n=10) == "both"

def test_opus_only_is_reported_not_hidden():
    assert bucket("H-CALLSITE", deepseek_failures=1, opus_failures=8, n=10) == "opus_only"

def test_neither_failing_is_not_a_finding():
    assert bucket("H-CALLSITE", deepseek_failures=0, opus_failures=1, n=10) == "neither"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_bucket.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'analysis.bucket'`

- [ ] **Step 3: Write minimal implementation**

```python
# analysis/bucket.py
from __future__ import annotations

FAIL_HIGH = 0.6   # a majority-failure rate
FAIL_LOW = 0.2    # a clean rate

def bucket(hazard_id: str, deepseek_failures: int, opus_failures: int, n: int) -> str:
    d = deepseek_failures / n
    o = opus_failures / n
    if d >= FAIL_HIGH and o <= FAIL_LOW:
        return "deepseek_only"
    if o >= FAIL_HIGH and d <= FAIL_LOW:
        return "opus_only"
    if d >= FAIL_HIGH and o >= FAIL_HIGH:
        return "both"
    return "neither"
```

Note: these are *bucketing* thresholds for the exploratory report. The
**promotion** rule (spec §9.2, `D>=8 AND O<=1` at n=10 plus cross-fixture
replication) is stricter and is not implemented in this slice, because this slice
ships no skill.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_bucket.py -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Commit**

```bash
git add analysis/bucket.py tests/test_bucket.py
git commit -m "feat: three-way finding bucketing"
```

---

## Task 8: End-to-end slice run

The payoff: real numbers on one fixture.

**Files:**
- Create: `eval.py` (CLI entry point)
- Create: `reports/` (gitignored)

**Interfaces:**
- Consumes: everything from Tasks 1-7.

- [ ] **Step 1: Write the end-to-end test**

```python
# tests/test_end_to_end.py
import pytest
from pathlib import Path
from harness.fixture import load_fixture, stage_agent_tree
from graders.apply import grade

def test_pipeline_grades_a_staged_known_bad_tree(tmp_path):
    """The full path minus the model call: stage, grade, get the expected verdict."""
    fx = load_fixture(Path("fixtures/py-callsite-01"))
    staged = tmp_path / "staged"
    stage_agent_tree(fx, staged)
    assert not (staged / "grader").exists()
    result = grade(fx, Path("fixtures/py-callsite-01/known_bad/missed_command"))
    assert result.hazard_results["H-CALLSITE"] is False
```

- [ ] **Step 2: Run it and verify it passes**

Run: `uv run pytest tests/test_end_to_end.py -v`
Expected: PASS

- [ ] **Step 2b: Write `eval.py`**

```python
# eval.py
from __future__ import annotations
import argparse, json, os, tempfile
from collections import Counter
from pathlib import Path
from harness.fixture import load_fixture
from harness.runner import Arm, run_agent, ModelMismatch
from harness.trace import assert_trace
from graders.apply import grade
from analysis.bucket import bucket

ARMS = {
    "deepseek": Arm("deepseek", "deepseek/deepseek-v4-pro",
                    {"DEEPSEEK_API_KEY": os.environ.get("DEEPSEEK_API_KEY", "")}),
    "opus": Arm("opus", "anthropic/claude-opus-5",
                {"ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")}),
}

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["run"])
    ap.add_argument("--fixture", required=True)
    ap.add_argument("--arms", default="deepseek,opus")
    ap.add_argument("--n", type=int, default=1)
    args = ap.parse_args()

    fixture = load_fixture(Path("fixtures") / args.fixture)
    call_sites = {
        site for h in fixture.hazards for site in h.get("call_sites", [])
    }
    failures: dict[str, Counter] = {a: Counter() for a in args.arms.split(",")}
    records = []

    for arm_name in args.arms.split(","):
        arm = ARMS[arm_name]
        for rep in range(args.n):
            with tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp) / "run"
                try:
                    run = run_agent(fixture, arm, work)
                except ModelMismatch as exc:
                    records.append({"arm": arm_name, "rep": rep, "error": str(exc)})
                    continue
                if run.capped:
                    records.append({"arm": arm_name, "rep": rep, "status": "capped"})
                    continue
                result = grade(fixture, work)
                trace = assert_trace(run.session_json, repo_files=call_sites)
                trace["T-CLAIMDONE"] = not all(result.hazard_results.values())
                for hazard_id, passed in result.hazard_results.items():
                    if not passed:
                        failures[arm_name][hazard_id] += 1
                records.append({
                    "arm": arm_name, "rep": rep, "status": "completed",
                    "hazards": result.hazard_results, "trace": trace,
                })

    print(json.dumps({"records": records}, indent=2))
    for hazard in fixture.hazards:
        hid = hazard["id"]
        d, o = failures["deepseek"][hid], failures["opus"][hid]
        print(f"{hid}: deepseek {d}/{args.n}, opus {o}/{args.n} "
              f"-> {bucket(hid, d, o, args.n)}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the real thing, n=1 per arm**

```bash
uv run python eval.py run --fixture py-callsite-01 --arms deepseek,opus --n 1
```

Expected output: a per-arm hazard verdict, trace assertions, cap status, and a verified model id for each run.

- [ ] **Step 4: Verify the manifest invariant held on a real run**

Confirm from the run record that the agent container saw only `repo/` contents. This is the check that validates every number the harness will ever produce.

- [ ] **Step 5: Run n=3 per arm and record the result**

```bash
uv run python eval.py run --fixture py-callsite-01 --arms deepseek,opus --n 3
```

This is the first genuine data point. **Do not draw conclusions from one fixture** - spec §9.3 requires cross-fixture replication before any hazard means anything. The purpose here is to prove the pipeline produces trustworthy numbers.

- [ ] **Step 6: Commit and open the PR**

```bash
git add eval.py tests/test_end_to_end.py
git commit -m "feat: end-to-end slice runner"
git push -u origin feat/vertical-slice
```

---

## Open risks carried into execution

1. **The sterility switches are unverified semantics.** Task 5 Step 5 is the check. If it fails, spec §6 is wrong and the eval cannot proceed until it is fixed.
2. **`opencode run` output format for `--format json`** has not been inspected against a real session. Task 6's parser is written against an assumed shape and will likely need adjustment on first contact. Budget for that.
3. **Django fixtures need a working settings module** inside the grading image. If setup proves fiddly, a Flask or FastAPI fixture would carry the same `H-CALLSITE` hazard at lower cost, at the price of drifting from Andrea's actual stack.
