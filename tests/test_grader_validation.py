"""Spec section 7.2: grader validation gates everything.

A grader that does not discriminate is a finding factory. These tests are the
gate - if they fail, no eval result may be published.
"""

import os
import shutil
from pathlib import Path

import pytest

from graders.apply import grade, validate_hazard_mapping
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
    "variant", ["derive_internal", "explicit_all", "keyword_only"]
)
def test_every_known_good_variant_passes_every_hazard(fixture, variant):
    """Three structurally different correct solutions. One reference solution
    would not prove the grader accepts the valid solution space."""
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
    solved = f"{FIXTURE}/known_good/derive_internal/notifications/services.py"
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
