"""Spec section 7.2: grader validation gates everything.

A grader that does not discriminate is a finding factory. These tests are the
gate - if they fail, no eval result may be published.
"""

import os
import shutil

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
