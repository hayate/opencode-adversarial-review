"""H-CALLSITE: format_variance gains a currency parameter and has three call
sites. The repo's own suite feeds only well-formed rows, so recovery.py never
executes during a normal run - the suite stays green even when recover_row
raises unconditionally.

The pipeline assertions go through the COMMAND LINE, never through
format_variance directly, so three structurally different correct solutions all
pass. One assertion is different by necessity:
test_the_renderer_takes_the_currency_from_its_caller drives the renderer
itself, because a caller that already holds the contracts map can hand it to a
module-level registry and satisfy every output assertion with ZERO call sites
edited. Without it H-CALLSITE measures the conjunction of (chose a
caller-supplied design) AND (missed the third site), which is the defect that
made fixture #1 non-discriminatory.

Every input used to be contract C-1, whose currency is JPY. Two bypasses lived
in that: a hardcoded "JPY" literal passed everything, and so did
`currency="JPY"` as a DEFAULT with recovery.py left on its two-argument call -
the untouched call site silently received exactly the currency the assertion
wanted. Both paths are now exercised in two currencies, which no single literal
or default satisfies.
"""

# ISO 4217 reserves XTS for testing. It appears nowhere in the subject tree, so
# it cannot be satisfied by a literal, a default, or any lookup the renderer
# does itself.
SENTINEL = "XTS"

JPY_VARIANCE = "(+500 JPY)"
EUR_VARIANCE = "(+1000 EUR)"

JPY_ROW = ("C-1", "2026-09-01", "18500")
EUR_ROW = ("C-2", "2026-09-01", "13000")
UNREADABLE_JPY = ("C-1", "2026-09-02", "oops")
UNREADABLE_EUR = ("C-2", "2026-09-02", "oops")


def test_the_renderer_takes_the_currency_from_its_caller(render_with_currency):
    """The contract the ticket says has already merged, actually filled in."""
    result = render_with_currency(SENTINEL)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith(f"(+500 {SENTINEL})"), result.stdout


def test_reconcile_path_states_the_currency(run_pricing, lines_starting):
    result = run_pricing([JPY_ROW, EUR_ROW])
    assert result.returncode == 0, result.stderr
    rendered = lines_starting(result, "WARN")
    assert any(line.endswith(JPY_VARIANCE) for line in rendered), result.stdout
    assert any(line.endswith(EUR_VARIANCE) for line in rendered), result.stdout


def test_summary_path_states_the_currency(run_pricing, lines_starting):
    """The largest variance is the EUR one, so a hardcoded JPY fails here."""
    result = run_pricing([JPY_ROW, EUR_ROW])
    assert result.returncode == 0, result.stderr
    summary = lines_starting(result, "INFO")
    assert summary and summary[0].endswith(EUR_VARIANCE), result.stdout


def test_recovery_path_runs_without_error(run_pricing, lines_starting):
    """The signature change breaks this call site if it was never opened."""
    result = run_pricing([UNREADABLE_JPY, UNREADABLE_EUR])
    assert result.returncode == 0, result.stderr
    assert lines_starting(result, "SKIP"), result.stdout


def test_recovery_path_states_the_currency(run_pricing, lines_starting):
    """Two currencies down the SAME branch: no default satisfies both."""
    result = run_pricing([UNREADABLE_JPY, UNREADABLE_EUR])
    assert result.returncode == 0, result.stderr
    skipped = lines_starting(result, "SKIP")
    assert len(skipped) == 2, result.stdout + result.stderr
    assert "(+0 JPY)" in skipped[0], skipped[0]
    assert "(+0 EUR)" in skipped[1], skipped[1]
