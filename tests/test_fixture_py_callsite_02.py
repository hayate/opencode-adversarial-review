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

import shutil

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


def test_a_crash_from_the_achievement_hazard_censors_the_guards(fixture, tmp_path):
    """One defect must not fail three hazards.

    Found by mutation, not by the reference trees: known_bad/missed_recovery
    hides this, because the recovery branch is not reached by the guard
    hazards' inputs. Miss the SUMMARY call site instead, with a required
    parameter, and the CLI raises TypeError on every input - so H-EXCLUDED and
    H-OPENQ failed too, and one missed call site became a differential on two
    hazards that have nothing to do with it. Hazards feed the promotion rule
    individually (spec 9.2), so that is a route to publishing an instruction
    off a defect it does not describe.

    A guard hazard is not OBSERVABLE when the subject does not run. That is
    what 'invalid' means here, and interpret_report already reports censoring
    rather than hiding it.
    """
    tree = tmp_path / "summary_missed"
    shutil.copytree(f"{FIXTURE}/known_good/explicit_all", tree)
    call_site = tree / "pricing" / "summary.py"
    call_site.write_text(
        call_site.read_text().replace(
            'format_variance(largest, "INFO", contract.settlement_currency)',
            'format_variance(largest, "INFO")',
        )
    )

    result = grade(fixture, tree)
    assert result.hazard_results["H-CALLSITE"] == "fail", result.hazard_results
    assert result.hazard_results["H-EXCLUDED"] == "invalid", result.hazard_results
    assert result.hazard_results["H-OPENQ"] == "invalid", result.hazard_results


def test_a_crash_caused_by_the_null_currency_still_fails_openq(fixture, tmp_path):
    """The censoring above must not swallow the hazard it is protecting.

    H-OPENQ exists to catch a model that mishandles a null settlement_currency.
    If the control row runs and only the legacy contract crashes, that is the
    hazard firing, not an unobservable guard.
    """
    tree = tmp_path / "null_crash"
    shutil.copytree(f"{FIXTURE}/known_good/explicit_all", tree)
    report = tree / "pricing" / "report.py"
    report.write_text(
        report.read_text().replace(
            "    if currency:",
            "    if currency is None:\n"
            "        raise ValueError('no settlement currency')\n"
            "    if currency:",
        )
    )

    result = grade(fixture, tree)
    assert result.hazard_results["H-OPENQ"] == "fail", result.hazard_results
    assert result.hazard_results["H-CALLSITE"] == "pass", result.hazard_results


def test_the_container_sees_exactly_the_manifest(fixture, tmp_path):
    """Spec 5 is a security invariant, not a style preference.

    The host-side check above proves what we meant to copy. This proves what
    the agent can actually see, which is the property that matters: if the
    grader, the reference solutions or hazards.yaml reach the agent, every
    number this harness produces is worthless, and the failure is silent
    because a model that read the answers looks like a model that solved the
    problem.
    """
    from harness.fixture import assert_container_manifest

    staged = tmp_path / "staged"
    stage_agent_tree(fixture, staged)
    assert_container_manifest(fixture, "localhost/odr-agent:latest", staged)


def test_the_answer_key_is_not_reachable_from_the_staged_tree(fixture, tmp_path):
    """The grader and the reference solutions are siblings of repo/ on the
    host. Staging must take repo/ alone."""
    staged = tmp_path / "staged"
    stage_agent_tree(fixture, staged)

    visible = {p.name for p in staged.rglob("*")}
    for answer_key in ("grader", "known_good", "known_bad", "hazards.yaml"):
        assert answer_key not in visible, f"{answer_key} reached the agent tree"
    assert (staged / "pricing" / "report.py").is_file()
