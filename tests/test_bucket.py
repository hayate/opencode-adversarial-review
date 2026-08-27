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
    Counting invalid runs as passes would hide real failures.

    The label is a candidate rather than a verdict because 7 valid runs is
    short of confirmation - which is the honest reading, and is exactly the
    censoring that makes a shrunken denominator worth flagging."""
    assert bucket(ArmTally(7, 7), ArmTally(0, 10)) == "candidate_deepseek_only"


def test_too_few_valid_runs_returns_a_sentinel_rather_than_raising():
    """Raising here aborts the whole report over one transient failure."""
    assert bucket(ArmTally(1, 1), ArmTally(0, 10)) == "insufficient_valid_runs"


def test_zero_valid_runs_does_not_divide_by_zero():
    assert bucket(ArmTally(0, 0), ArmTally(0, 10)) == "insufficient_valid_runs"


# --- Spec 9.2: the threshold must be the rule the spec actually adopted ---
#
# Revision 1 was `D>=6 AND O<=2` at n=10. The spec computes its peak per-hazard
# false-positive rate at 0.0278 and rejects it outright: "That is not acceptable
# for a published artifact." Revision 2 is `D>=8 AND O<=1`, peak 0.00064.
# Round 1 of the review gauntlet found the code still shipping revision 1.


def test_the_rejected_revision_1_boundary_is_not_a_finding():
    """D=6/10, O=2/10 is exactly revision 1's boundary. Under the adopted rule
    it must not name a vendor."""
    assert bucket(ArmTally(6, 10), ArmTally(2, 10)) == "neither"


def test_the_adopted_revision_2_boundary_promotes():
    assert bucket(ArmTally(8, 10), ArmTally(1, 10)) == "deepseek_only"


def test_just_inside_the_revision_2_boundary_does_not_promote():
    assert bucket(ArmTally(7, 10), ArmTally(1, 10)) == "neither"
    assert bucket(ArmTally(8, 10), ArmTally(2, 10)) == "neither"


def test_exploration_stage_yields_candidates_not_verdicts():
    """Spec 9.1: n=3 is exploration and produces CANDIDATES; confirmation is
    fresh runs at n=10. Emitting the same label at both stages invites a
    reader to treat a three-run screen as a published verdict."""
    assert bucket(ArmTally(3, 3), ArmTally(0, 3)) == "candidate_deepseek_only"
    assert bucket(ArmTally(0, 3), ArmTally(3, 3)) == "candidate_opus_only"


def test_confirmation_n_is_where_a_verdict_becomes_unqualified():
    assert bucket(ArmTally(8, 9), ArmTally(0, 9)).startswith("candidate_")
    assert not bucket(ArmTally(8, 10), ArmTally(0, 10)).startswith("candidate_")


def test_both_is_also_qualified_below_confirmation():
    """The `both` branch returned early without the confirmation check, so an
    exploratory 3/3-vs-3/3 screen published as an unqualified verdict."""
    assert bucket(ArmTally(3, 3), ArmTally(3, 3)) == "candidate_both"
    assert bucket(ArmTally(8, 10), ArmTally(7, 10)) == "both"
