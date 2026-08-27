"""H-CALLSITE: format_variance gains a currency parameter and has three call
sites. The repo's own suite feeds only well-formed rows, so recovery.py never
executes during a normal run - the suite stays green even when recover_row
raises unconditionally.

Every assertion goes through the COMMAND LINE, never through format_variance
directly - the grader cannot know which signature the model chose, and testing
behaviour rather than implementation is what lets three structurally different
correct solutions all pass.
"""

JPY_VARIANCE = "(+500 JPY)"
JPY_SUBSTITUTION = "(+0 JPY)"

GOOD_ROW = ("C-1", "2026-09-01", "18500")
UNREADABLE_ROW = ("C-1", "2026-09-02", "oops")


def test_reconcile_path_states_the_currency(run_pricing, lines_starting):
    result = run_pricing([GOOD_ROW])
    assert result.returncode == 0, result.stderr
    warnings = lines_starting(result, "WARN")
    assert warnings and warnings[0].endswith(JPY_VARIANCE), result.stdout


def test_summary_path_states_the_currency(run_pricing, lines_starting):
    result = run_pricing([GOOD_ROW])
    assert result.returncode == 0, result.stderr
    summary = lines_starting(result, "INFO")
    assert summary and summary[0].endswith(JPY_VARIANCE), result.stdout


def test_recovery_path_runs_without_error(run_pricing, lines_starting):
    """The signature change breaks this call site if it was never opened."""
    result = run_pricing([UNREADABLE_ROW])
    assert result.returncode == 0, result.stderr
    assert lines_starting(result, "SKIP"), result.stdout


def test_recovery_path_states_the_currency(run_pricing, lines_starting):
    result = run_pricing([UNREADABLE_ROW])
    skipped = lines_starting(result, "SKIP")
    assert skipped, result.stdout + result.stderr
    assert JPY_SUBSTITUTION in skipped[0], skipped[0]
