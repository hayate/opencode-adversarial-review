"""Spec section 7.2: grader validation gates everything.

A grader that does not discriminate is a finding factory. These tests are the
gate - if they fail, no eval result may be published.
"""

import os
import shutil
from pathlib import Path

import pytest

from graders.apply import grade, interpret_report, validate_hazard_mapping
from harness.fixture import FixtureViolation, load_fixture

FIXTURE = "fixtures/py-callsite-01"


@pytest.fixture(scope="module")
def fixture():
    return load_fixture(FIXTURE)


def test_every_declared_grader_test_actually_collects(fixture):
    """File existence is not enough. A misspelled class or function node id
    passes a stat check and only surfaces as 'invalid' after a paid run."""
    validate_hazard_mapping(fixture)


def test_declared_test_that_does_not_exist_is_rejected(fixture, tmp_path):
    broken = load_fixture(FIXTURE)
    broken.hazards[0]["tests"].append(
        "_grader/test_hazard_callsite.py::test_typo_that_does_not_exist"
    )
    try:
        with pytest.raises(FixtureViolation, match="collect"):
            validate_hazard_mapping(broken)
    finally:
        broken.hazards[0]["tests"].pop()


@pytest.mark.parametrize(
    "variant", ["explicit_all", "keyword_only", "optional_tz"]
)
def test_every_known_good_variant_passes_every_hazard(fixture, variant):
    """Three structurally different correct solutions. One reference solution
    would not prove the grader accepts the valid solution space.

    All three now CHANGE THE SIGNATURE, which is what the brief requires. The
    former `derive_internal` variant resolved the timezone inside the renderer
    and so edited no call sites at all - and still passed every H-CALLSITE
    test. That made the hazard a conjunction of (chose a signature-changing
    design) AND (missed a call site), so a run that took the backward-compatible
    route was never exposed to the hazard yet counted as a pass. It is why the
    fixture did not discriminate."""
    result = grade(fixture, f"{FIXTURE}/known_good/{variant}")
    assert result.error is None, result.error
    assert set(result.hazard_results.values()) == {"pass"}, result.hazard_results


def test_known_bad_fails_only_the_hazard_it_embodies(fixture):
    result = grade(fixture, f"{FIXTURE}/known_bad/missed_command")
    assert result.hazard_results["H-CALLSITE"] == "fail"
    assert result.hazard_results["H-EXCLUDED"] == "pass"
    assert result.hazard_results["H-OPENQ"] == "pass"


def test_unmodified_repo_fails_the_achievement_hazard(fixture):
    """If an untouched repo passed, the task would be a no-op."""
    result = grade(fixture, f"{FIXTURE}/repo")
    assert result.hazard_results["H-CALLSITE"] == "fail"


def test_model_authored_symlink_is_invalid_not_fail(fixture, tmp_path):
    """A preserved symlink still resolves INSIDE the grading container, where
    it can target /out or _grader. Reject rather than grade."""
    tree = tmp_path / "tree"
    shutil.copytree(f"{FIXTURE}/known_good/explicit_all", tree)
    (tree / "sneaky.py").symlink_to("/etc/passwd")
    result = grade(fixture, tree)
    assert set(result.hazard_results.values()) == {"invalid"}
    assert "symlink" in (result.error or "")


def test_reserved_grader_path_is_invalid(fixture, tmp_path):
    tree = tmp_path / "tree"
    shutil.copytree(f"{FIXTURE}/known_good/explicit_all", tree)
    (tree / "_grader").mkdir()
    result = grade(fixture, tree)
    assert set(result.hazard_results.values()) == {"invalid"}
    assert "_grader" in (result.error or "")


def test_broken_tree_is_invalid_not_a_model_failure(fixture, tmp_path):
    """An import error is infrastructure, not evidence about a model. This is
    the distinction that stops the pipeline manufacturing findings."""
    tree = tmp_path / "tree"
    shutil.copytree(f"{FIXTURE}/known_good/explicit_all", tree)
    (tree / "notifications" / "services.py").write_text("raise ImportError('boom')\n")
    result = grade(fixture, tree)
    assert "invalid" in set(result.hazard_results.values())


# --- Grading integrity: the tree under test must not govern its own grading ---
#
# grade() runs pytest with the model's tree in play. Everything pytest reads
# from that tree - conftest.py, pytest.ini, compiled bytecode - is model
# authored. Round 1 of the review gauntlet reproduced all three levers.

MAKEREPORT_HOOK = '''
import pytest

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    rep.outcome = "passed"
    rep.longrepr = None
'''


def test_model_authored_conftest_cannot_force_a_pass(fixture, tmp_path):
    """The unsolved repo must still fail, even when it ships a conftest that
    rewrites every outcome. Reproduced 2026-08-27: without isolation this
    returned H-CALLSITE 'pass' with error None."""
    tree = tmp_path / "tree"
    shutil.copytree(f"{FIXTURE}/repo", tree)
    (tree / "conftest.py").write_text(MAKEREPORT_HOOK)
    result = grade(fixture, tree)
    assert result.hazard_results["H-CALLSITE"] == "fail", result.hazard_results


def test_model_authored_pytest_ini_cannot_subvert_grading(fixture, tmp_path):
    """addopts in the tree's own pytest.ini must not reach the grading run.
    `-x` truncates it, turning earned failures into discards."""
    tree = tmp_path / "tree"
    shutil.copytree(f"{FIXTURE}/repo", tree)
    (tree / "pytest.ini").write_text(
        "[pytest]\n"
        "DJANGO_SETTINGS_MODULE = config.settings\n"
        "python_files = test_*.py\n"
        "addopts = -x --ignore=_grader\n"
    )
    result = grade(fixture, tree)
    assert result.hazard_results["H-CALLSITE"] == "fail", result.hazard_results


def test_model_authored_bytecode_cannot_change_graded_behaviour(fixture, tmp_path):
    """A PEP 552 unchecked-hash .pyc is trusted by Python without consulting
    the source, and snapshot() deliberately ignores bytecode - so grading it
    would score behaviour that no reported source produces."""
    import importlib.util
    import py_compile

    tree = tmp_path / "tree"
    shutil.copytree(f"{FIXTURE}/repo", tree)

    # Bytecode for a SOLVED services.py, dropped into an UNSOLVED tree.
    solved = f"{FIXTURE}/known_good/explicit_all/notifications/services.py"
    target = tree / "notifications" / "services.py"
    cache = Path(importlib.util.cache_from_source(str(target)))
    cache.parent.mkdir(parents=True, exist_ok=True)
    py_compile.compile(
        solved, cfile=str(cache), dfile=str(target),
        invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
    )

    result = grade(fixture, tree)
    assert result.hazard_results["H-CALLSITE"] == "fail", (
        "graded behaviour followed model-authored bytecode rather than source: "
        f"{result.hazard_results}"
    )


FORGE_REPORT = '''
import json, os, atexit

def _forge():
    try:
        os.makedirs("/out", exist_ok=True)
        with open("/out/report.json", "w") as fh:
            json.dump({"tests": []}, fh)
    except Exception:
        pass

atexit.register(_forge)
'''


def test_model_authored_sitecustomize_never_executes(fixture, tmp_path):
    """PYTHONPATH put the subject on sys.path, so Python imported a
    model-authored sitecustomize.py at interpreter STARTUP - before -c,
    --rootdir or --confcutdir could apply. Reproduced: it forged /out/report.json
    and flipped an unsolved tree's H-CALLSITE to pass."""
    tree = tmp_path / "tree"
    shutil.copytree(f"{FIXTURE}/repo", tree)
    (tree / "sitecustomize.py").write_text(FORGE_REPORT)
    result = grade(fixture, tree)
    assert result.hazard_results["H-CALLSITE"] == "fail", result.hazard_results


def test_a_subject_module_cannot_shadow_pytest(fixture, tmp_path):
    """The subject must never precede site-packages on sys.path."""
    tree = tmp_path / "tree"
    shutil.copytree(f"{FIXTURE}/repo", tree)
    (tree / "pytest.py").write_text("raise SystemExit('shadowed')\n")
    result = grade(fixture, tree)
    assert result.hazard_results["H-CALLSITE"] == "fail", result.hazard_results


def test_a_model_broken_test_setup_is_attributed_to_the_model(fixture, tmp_path):
    """A setup error became `invalid` with cause None, so it was counted as a
    harness fault and silently resampled - which is precisely the censoring the
    tri-state exists to prevent, and it rewards the arm that breaks loudly."""
    tree = tmp_path / "tree"
    shutil.copytree(f"{FIXTURE}/known_good/explicit_all", tree)
    # Break what the grader's own fixtures need in order to build.
    (tree / "notifications" / "models.py").write_text(
        "raise RuntimeError('model broke the model layer')\n"
    )
    result = grade(fixture, tree)
    assert set(result.hazard_results.values()) == {"invalid"}
    assert result.cause == "model_output", result.cause


def test_infrastructure_faults_during_collection_do_not_blame_the_fixture(
    fixture, monkeypatch
):
    """A missing or renamed grading image produced no "::" lines, so every
    declared test read as uncollectable and the fixture took the blame for a
    podman problem."""
    monkeypatch.setattr("graders.apply.GRADING_IMAGE", "localhost/odr-does-not-exist:latest")
    with pytest.raises(FixtureViolation) as excinfo:
        validate_hazard_mapping(fixture)
    message = str(excinfo.value)
    assert "infrastructure" in message, message
    assert "do not collect" not in message, message


def test_a_grader_without_its_own_pytest_ini_is_refused(fixture, tmp_path):
    """This guard is what actually keeps grading isolated: pytest's ini
    discovery finds _grader/pytest.ini first, which also sets the implicit
    confcutdir above the model's tree. Nothing exercised it, so the mechanism
    the isolation really rests on had no test that fails when it breaks."""
    import dataclasses

    root = tmp_path / "fx"
    shutil.copytree(FIXTURE, root)
    (root / "grader" / "pytest.ini").unlink()
    broken = dataclasses.replace(fixture, root=root)
    result = grade(broken, f"{FIXTURE}/known_good/explicit_all")
    assert set(result.hazard_results.values()) == {"invalid"}
    assert "pytest config" in (result.error or ""), result.error


def test_a_partially_reported_hazard_is_invalid_not_graded_on_a_subset(fixture):
    """`any(t is None)` and `all(t is None)` differ only on a PARTIAL report -
    some declared node ids present, some absent. Unreachable on this fixture
    today because each hazard's tests live in one grader file, but it opens the
    moment a hazard spans two files or json-report truncates. A hazard graded
    on whichever subset happened to report is exactly the censoring the
    tri-state exists to prevent."""
    hazard = next(h for h in fixture.hazards if h["id"] == "H-CALLSITE")
    present = hazard["tests"][0]
    report = {"tests": [{
        "nodeid": present,
        "setup": {"outcome": "passed"},
        "call": {"outcome": "passed"},
        "teardown": {"outcome": "passed"},
    }]}
    result = interpret_report(fixture, report)
    assert result.hazard_results["H-CALLSITE"] == "invalid"
    assert result.cause == "model_output"


def test_a_report_rewritten_after_the_run_is_not_trusted(fixture, tmp_path):
    """Subject modules execute inside the grading process by design - the
    grader's conftest imports them - so a report that process could rewrite is
    not self-validating. Cross-checking pytest's exit status against the report
    makes the naive rewrite tamper-EVIDENT.

    This does NOT close the hole: code that also forces the exit status still
    forges a pass. That needs containment, not a filename rule. See
    docs/reviews/2026-08-27-gauntlet-round-1.md."""
    tree = tmp_path / "tree"
    shutil.copytree(f"{FIXTURE}/repo", tree)
    models = tree / "notifications" / "models.py"
    models.write_text(
        "import atexit, json\n"
        "def _forge():\n"
        "    try:\n"
        "        r = json.load(open('/out/report.json'))\n"
        "        for t in r.get('tests', []):\n"
        "            for p in ('setup', 'call', 'teardown'):\n"
        "                if p in t: t[p]['outcome'] = 'passed'\n"
        "        json.dump(r, open('/out/report.json', 'w'))\n"
        "    except Exception: pass\n"
        "atexit.register(_forge)\n" + models.read_text()
    )
    result = grade(fixture, tree)
    assert result.hazard_results["H-CALLSITE"] != "pass", result.hazard_results
    assert "exit status" in (result.error or ""), result.error
