"""Accounting and scope tests for the eval CLI.

eval.py is where the published number is actually assembled, and round 1 of the
review gauntlet found it had no tests at all. What guarded the harness's INPUTS
was well covered; what guarded its OUTPUTS was not.
"""

import pytest

from eval import Accounting, allowed_scope, must_read
from harness.fixture import load_fixture

FIXTURE = "fixtures/py-callsite-01"
HAZARDS = ["H-CALLSITE", "H-EXCLUDED", "H-OPENQ"]


@pytest.fixture(scope="module")
def fixture():
    return load_fixture(FIXTURE)


# --- Scope must come from the fixture, not from fixture #1's paths ---


def test_allowed_scope_is_declared_by_the_fixture(fixture):
    """eval.py hardcoded `notifications/services.py` - fixture #1's own target
    module - in fixture-generic code. On fixture #2 that silently whitelists a
    path that does not exist and omits the real one, so every legitimate edit
    lands in out_of_scope_paths and the observation carries no information."""
    scope = allowed_scope(fixture)
    assert "notifications/services.py" in scope
    assert "notifications/views.py" in scope  # a declared call site
    assert "tests" in scope


def test_excluded_paths_are_never_in_scope(fixture):
    """H-EXCLUDED declares notifications/digest.py out of bounds. The scope
    model and the hazard declarations used to be connected only through
    call_sites, so the observation and the grader measured 'out of scope' by
    two unrelated definitions."""
    scope = allowed_scope(fixture)
    for hazard in fixture.hazards:
        for path in hazard.get("excluded_paths") or []:
            assert path not in scope


def test_must_read_is_the_declared_call_sites(fixture):
    assert must_read(fixture) == {
        "notifications/views.py",
        "notifications/serializers.py",
        "notifications/management/commands/send_digest.py",
    }


# --- n means valid grades PER HAZARD, which is what the docstring promises ---


def _grade(**verdicts):
    return {h: verdicts.get(h, "pass") for h in HAZARDS}


def test_a_run_is_not_complete_until_every_hazard_has_n_valid_grades():
    """`got` used to increment per RUN when ANY hazard graded, while the
    denominators accumulated per HAZARD. A six-hazard fixture could therefore
    end with the headline hazard holding one valid grade after full spend."""
    acc = Accounting(HAZARDS, n=3)
    for _ in range(3):
        acc.record_grade(_grade(**{"H-CALLSITE": "invalid"}), cause="model_output")
    assert acc.valid["H-EXCLUDED"] == 3
    assert acc.valid["H-CALLSITE"] == 0
    assert not acc.complete, "stopped while a hazard still had no valid grades"


def test_complete_once_every_hazard_reaches_n():
    acc = Accounting(HAZARDS, n=2)
    for _ in range(2):
        acc.record_grade(_grade())
    assert acc.complete


def test_failures_and_valid_runs_track_per_hazard():
    acc = Accounting(HAZARDS, n=3)
    acc.record_grade(_grade(**{"H-CALLSITE": "fail"}))
    acc.record_grade(_grade(**{"H-CALLSITE": "fail"}))
    acc.record_grade(_grade())
    assert acc.failures["H-CALLSITE"] == 2
    assert acc.valid["H-CALLSITE"] == 3
    assert acc.failures["H-EXCLUDED"] == 0


# --- The censoring that DF-1 identified must be visible, not silent ---


def test_model_caused_ungradable_runs_are_reported_separately():
    """Retrying to n VALID grades conditions on the model's own output quality.
    A tree so broken that pytest cannot collect it is a tree where the hazard
    test would have failed - so the runs that vanish are systematically the
    worst ones, and refilling the denominator by retry hides the censoring.

    It is not conservative either: the bias is set by failure MODE, not rate,
    so two arms with identical true rates are measured as different and the one
    that fails loudly scores better."""
    acc = Accounting(HAZARDS, n=3)
    acc.record_grade({h: "invalid" for h in HAZARDS}, cause="model_output")
    acc.record_grade({h: "invalid" for h in HAZARDS}, cause="harness")
    summary = acc.summary()
    assert summary["ungradable_model_output"] == 1
    assert summary["invalid_harness"] == 1
    assert summary["valid_runs"]["H-CALLSITE"] == 0


def test_capped_runs_are_counted_because_capping_censors_on_speed():
    acc = Accounting(HAZARDS, n=3)
    acc.record_nongrade("capped")
    acc.record_nongrade("invalid")
    summary = acc.summary()
    assert summary["capped"] == 1
    assert summary["invalid_harness"] == 1


def test_attempts_are_counted_for_every_outcome():
    acc = Accounting(HAZARDS, n=3)
    acc.record_grade(_grade())
    acc.record_nongrade("capped")
    assert acc.summary()["attempts"] == 2


def test_a_hazard_stops_accumulating_once_it_reaches_n():
    """record_grade incremented every valid hazard on every attempt, including
    hazards already at n. If one hazard is repeatedly ungradable, another could
    reach 20 grades on one arm while the other arm stopped at 10 - and bucket()
    then compares different sample sizes and different time windows."""
    acc = Accounting(HAZARDS, n=2)
    for _ in range(5):
        acc.record_grade(_grade(**{"H-CALLSITE": "invalid"}), cause="model_output")
    assert acc.valid["H-EXCLUDED"] == 2, "denominator ran past the preregistered n"
    assert acc.failures["H-EXCLUDED"] == 0
