"""Three-way bucketing over valid runs only.

Findings sort into three buckets, not two (spec section 4):

1. deepseek_only - prime skill material; the reviewer is demonstrably clean
   here, so an instruction to watch for it can actually fire.
2. both         - a generic LLM failure. Never a model instruction: you cannot
   reliably ask a model to catch its own blind spot. Route to a mechanical
   check, or drop.
3. opus_only    - published honestly. Costs nothing and stops the repo reading
   as vendor-bashing.
"""

from __future__ import annotations

from dataclasses import dataclass

FAIL_HIGH = 0.6
FAIL_LOW = 0.2
MIN_VALID_RUNS = 3

INSUFFICIENT = "insufficient_valid_runs"


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
    transient invalid run cannot abort the whole report."""
    if deepseek.valid_runs < MIN_VALID_RUNS or opus.valid_runs < MIN_VALID_RUNS:
        return INSUFFICIENT

    d, o = deepseek.rate, opus.rate
    if d >= FAIL_HIGH and o <= FAIL_LOW:
        return "deepseek_only"
    if o >= FAIL_HIGH and d <= FAIL_LOW:
        return "opus_only"
    if d >= FAIL_HIGH and o >= FAIL_HIGH:
        return "both"
    return "neither"
