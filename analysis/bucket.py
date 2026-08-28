"""Three-way bucketing over valid runs only.

Findings sort into three buckets, not two (spec section 4):

1. deepseek_only - prime skill material; the reviewer is demonstrably clean
   here, so an instruction to watch for it can actually fire.
2. both         - a generic LLM failure. Never a model instruction: you cannot
   reliably ask a model to catch its own blind spot. Route to a mechanical
   check, or drop.
3. opus_only    - published honestly. Costs nothing and stops the repo reading
   as vendor-bashing.

The thresholds are not interchangeable, and the asymmetry is deliberate.
`deepseek_only` and `opus_only` put a named vendor in a published claim, so
they use the promotion rule the spec actually adopted. `both` names nobody and
routes to a mechanical check or a drop, so it does not need to buy down a
family-wise false-promotion rate.
"""

from __future__ import annotations

from dataclasses import dataclass

# Spec 9.2. Revision 1 was `D>=6 AND O<=2` at n=10; the spec computes its peak
# per-hazard false-positive rate at 0.0278 under the null and rejects it - "not
# acceptable for a published artifact" - because it gives a 68-86% chance of at
# least one false promotion across 40-70 hazards. Revision 2 is `D>=8 AND O<=1`,
# peak 0.00064, a 4.4% chance across 70. Expressed as rates so they generalise
# when an arm ends with fewer than n valid runs.
#
# Round 1 of the review gauntlet found this file still shipping revision 1. The
# spec says the threshold "lives in one config constant so it is revised
# deliberately rather than drifting per finding" - the constant existed and had
# simply never been moved.
PROMOTE_HIGH = 0.8   # D>=8 at n=10
PROMOTE_LOW = 0.1    # O<=1 at n=10

# `both` is a routing decision, not a vendor claim, so it keeps the looser bar.
BOTH_HIGH = 0.6

MIN_VALID_RUNS = 3

# Spec 9.1: n=3 is EXPLORATION and produces candidates; confirmation is entirely
# fresh runs at n=10. Below this, a label is a screening result and is marked as
# one - at n=3 the only reachable rates are 0, 1/3, 2/3 and 1, and a one-sided
# label carries roughly a 40% chance across three hazards of being pure noise.
CONFIRMATION_N = 10

INSUFFICIENT = "insufficient_valid_runs"
CANDIDATE_PREFIX = "candidate_"


@dataclass(frozen=True)
class ArmTally:
    """`valid_runs` counts runs that produced a pass or fail for this hazard.

    Capped runs, model-id mismatches and invalid grades are excluded. `n` in
    the eval means valid grades per arm, not attempts.
    """

    failures: int
    valid_runs: int

    @property
    def rate(self) -> float:
        return self.failures / self.valid_runs


def bucket(deepseek: ArmTally, opus: ArmTally) -> str:
    """Classify one hazard. Returns a sentinel rather than raising, so one
    transient invalid run cannot abort the whole report.

    A one-sided verdict below CONFIRMATION_N valid runs on either arm comes
    back prefixed `candidate_`: it is a screening result awaiting fresh
    confirmation runs, never something to publish.
    """
    if deepseek.valid_runs < MIN_VALID_RUNS or opus.valid_runs < MIN_VALID_RUNS:
        return INSUFFICIENT

    d, o = deepseek.rate, opus.rate
    confirmed = min(deepseek.valid_runs, opus.valid_runs) >= CONFIRMATION_N

    if d >= PROMOTE_HIGH and o <= PROMOTE_LOW:
        label = "deepseek_only"
    elif o >= PROMOTE_HIGH and d <= PROMOTE_LOW:
        label = "opus_only"
    elif d >= BOTH_HIGH and o >= BOTH_HIGH:
        # Names no vendor, so it keeps the looser bar - but it is still a
        # screening result below confirmation and must say so, or an
        # exploratory 3-vs-3 screen routes noise to a mechanical check.
        label = "both"
    else:
        return "neither"

    return label if confirmed else CANDIDATE_PREFIX + label
