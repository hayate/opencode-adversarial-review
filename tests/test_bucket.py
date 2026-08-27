"""Three-way bucketing. Bucket 3 exists so the report is not one-directional."""

from analysis.bucket import ArmTally, bucket


def test_deepseek_only_is_prime_skill_material():
    assert bucket(ArmTally(8, 10), ArmTally(1, 10)) == "deepseek_only"


def test_both_failing_is_a_generic_llm_failure():
    """Never a model instruction - a model cannot reliably catch its own blind
    spot. Routes to a mechanical check instead."""
    assert bucket(ArmTally(8, 10), ArmTally(7, 10)) == "both"


def test_opus_only_is_reported_not_hidden():
    """Publishing this is what stops the repo reading as vendor-bashing."""
    assert bucket(ArmTally(1, 10), ArmTally(8, 10)) == "opus_only"


def test_neither_failing_is_not_a_finding():
    assert bucket(ArmTally(0, 10), ArmTally(1, 10)) == "neither"


def test_invalid_runs_are_excluded_from_the_denominator():
    """Three of ten attempts were invalid, so the rate is 7/7 not 7/10.
    Counting invalid runs as passes would hide real failures."""
    assert bucket(ArmTally(7, 7), ArmTally(0, 10)) == "deepseek_only"


def test_too_few_valid_runs_returns_a_sentinel_rather_than_raising():
    """Raising here aborts the whole report over one transient failure."""
    assert bucket(ArmTally(1, 1), ArmTally(0, 10)) == "insufficient_valid_runs"


def test_zero_valid_runs_does_not_divide_by_zero():
    assert bucket(ArmTally(0, 0), ArmTally(0, 10)) == "insufficient_valid_runs"
