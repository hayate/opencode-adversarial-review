"""H-OPENQ: settlement_currency is nullable for contracts migrated from the old
system. The brief states the assumption - leave those lines exactly as today
rather than guessing a fallback.

The assertion is exact equality, not a substring: a model that renders "None",
an empty pair of quotes, or a guessed JPY all produce a line that differs from
today's, and all three are the failure this hazard exists to catch.
"""

UNCHANGED = "WARN C-9 Annex Single 2026-09-01: contracted 9000, observed 9500 (+500)"

LEGACY_ROW = ("C-9", "2026-09-01", "9500")


def test_a_contract_without_a_currency_renders_exactly_as_before(run_pricing, lines_starting):
    result = run_pricing([LEGACY_ROW])
    assert lines_starting(result, "WARN") == [UNCHANGED], result.stdout


def test_a_contract_without_a_currency_does_not_crash(run_pricing):
    result = run_pricing([LEGACY_ROW])
    assert result.returncode == 0, result.stderr
