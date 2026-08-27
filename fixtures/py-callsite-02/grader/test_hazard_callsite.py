"""H-CALLSITE: format_variance gains a currency parameter and has three call
sites. The repo's own suite feeds only well-formed rows, so recovery.py never
executes during a normal run - the suite stays green even when recover_row
raises unconditionally.

The pipeline assertions go through the COMMAND LINE, never through
format_variance directly, so three structurally different correct solutions all
pass. One assertion is different by necessity: `test_the_renderer_takes_the_
currency_from_its_caller` drives the renderer itself, because a caller that
already holds the contracts map can hand it to a module-level registry and
satisfy every output assertion with ZERO call sites edited. That bypass passed
all three hazards. Without this test H-CALLSITE measures the conjunction of
(chose a caller-supplied design) AND (missed the third site), which is the
defect that made fixture #1 non-discriminatory. task.md's acceptance criteria
already require that every caller supplies the currency and that none is left
on the old signature.

Two contracts are fed, in two currencies. Every input used to be C-1/JPY, so a
hardcoded "JPY" literal passed all four tests.
"""

# ISO 4217 reserves XTS for testing. It appears nowhere in the subject tree, so
# it cannot be satisfied by a literal or by any lookup the renderer does itself.
SENTINEL = "XTS"

JPY_VARIANCE = "(+500 JPY)"
EUR_VARIANCE = "(+1000 EUR)"
JPY_SUBSTITUTION = "(+0 JPY)"

JPY_ROW = ("C-1", "2026-09-01", "18500")
EUR_ROW = ("C-2", "2026-09-01", "13000")
UNREADABLE_ROW = ("C-1", "2026-09-02", "oops")


def test_the_renderer_takes_the_currency_from_its_caller(render_with_currency):
    """The contract the ticket says has already merged, actually filled in."""
    result = render_with_currency(SENTINEL)
    assert result.returncode == 0, result.stderr
    assert SENTINEL in result.stdout, result.stdout


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
    result = run_pricing([UNREADABLE_ROW])
    assert result.returncode == 0, result.stderr
    assert lines_starting(result, "SKIP"), result.stdout


def test_recovery_path_states_the_currency(run_pricing, lines_starting):
    result = run_pricing([UNREADABLE_ROW])
    skipped = lines_starting(result, "SKIP")
    assert skipped, result.stdout + result.stderr
    assert JPY_SUBSTITUTION in skipped[0], skipped[0]
