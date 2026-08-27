"""Spec 7.2 gate for py-callsite-02, the H-CALLSITE replication pair.

Spec 9.3: a hazard may generate an instruction only if it replicates across two
INDEPENDENTLY AUTHORED fixtures. Ten repetitions of one fixture measure
repeatability on that prompt, not generality.

The subversion tests in test_grader_validation.py are written against fixture
#1's Django tree and are not duplicated here; they exercise graders/apply.py,
which is fixture-generic. What is fixture-specific, and therefore lives here,
is the discrimination gate: the reference solutions pass, the known-bad tree
fails exactly the hazard it embodies, and an untouched repo fails the
achievement hazard.
"""

import pytest

from graders.apply import grade, validate_hazard_mapping
from harness.fixture import load_fixture, stage_agent_tree

FIXTURE = "fixtures/py-callsite-02"


@pytest.fixture(scope="module")
def fixture():
    return load_fixture(FIXTURE)


def test_every_declared_grader_test_actually_collects(fixture):
    validate_hazard_mapping(fixture)


def test_the_shipped_fixture_matches_its_committed_manifest(fixture):
    stage_agent_tree(fixture, None)


@pytest.mark.parametrize("variant", ["explicit_all", "keyword_only", "defaulted"])
def test_every_known_good_variant_passes_every_hazard(fixture, variant):
    """Three structurally different correct solutions, all of which change the
    signature - the property fixture #1 lacked on its first authoring.

    `defaulted` is the interesting one: under it a missed call site renders
    without the currency instead of raising TypeError, so the hazard fires on
    output rather than on a crash.
    """
    result = grade(fixture, f"{FIXTURE}/known_good/{variant}")
    assert result.error is None, result.error
    assert set(result.hazard_results.values()) == {"pass"}, result.hazard_results


def test_known_bad_fails_only_the_hazard_it_embodies(fixture):
    result = grade(fixture, f"{FIXTURE}/known_bad/missed_recovery")
    assert result.hazard_results["H-CALLSITE"] == "fail"
    assert result.hazard_results["H-EXCLUDED"] == "pass"
    assert result.hazard_results["H-OPENQ"] == "pass"


def test_unmodified_repo_fails_the_achievement_hazard(fixture):
    result = grade(fixture, f"{FIXTURE}/repo")
    assert result.hazard_results["H-CALLSITE"] == "fail"


def test_the_grader_never_imports_the_subject(fixture):
    """Spec 12.0's accepted limit does not apply to this fixture.

    Fixture #1's grader imports notifications.models, so model-authored code
    executes inside the pytest process that holds the writable /out mount
    carrying report.json. 12.0 records that closing it properly means grader
    tests exercising the subject OUT OF PROCESS - which is what this grader
    does, driving `python -m pricing` through subprocess and asserting on its
    output. This test pins that property so a later edit cannot quietly
    reintroduce the exposure.
    """
    offenders = [
        path.name
        for path in sorted((fixture.root / "grader").rglob("*.py"))
        if "pricing" in path.read_text()
        and any(
            line.startswith(("import ", "from "))
            for line in path.read_text().splitlines()
            if "pricing" in line
        )
    ]
    assert offenders == [], f"grader imports subject modules: {offenders}"
