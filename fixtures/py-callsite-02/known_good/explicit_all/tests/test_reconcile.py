from pricing.model import Contract
from pricing.reconcile import reconcile
from pricing.summary import summarise

CONTRACTS = {
    "C-1": Contract("C-1", "Nordkap Rooms", "Deluxe Twin", 18000, "JPY"),
    "C-2": Contract("C-2", "Fjordline", "Standard Double", 12000, "JPY"),
}


def _row(rate, date="2026-09-01", contract="C-1"):
    return {"contract": contract, "date": date, "rate": str(rate)}


def test_a_matching_rate_produces_no_line():
    lines, variances = reconcile([_row(18000)], CONTRACTS)
    assert lines == []
    assert variances == []


def test_a_higher_feed_rate_is_reported():
    lines, variances = reconcile([_row(18500)], CONTRACTS)
    assert len(variances) == 1
    assert "contracted 18000, observed 18500" in lines[0]


def test_an_unknown_contract_is_flagged():
    lines, variances = reconcile([_row(18500, contract="C-9")], CONTRACTS)
    assert lines == ["NOCONTRACT 'C-9'"]
    assert variances == []


def test_the_summary_names_the_supplier_of_the_largest_variance():
    _, variances = reconcile(
        [_row(18500), _row(13500, contract="C-2")], CONTRACTS
    )
    out = summarise(variances, CONTRACTS)
    assert "Fjordline" in out[0]
    assert "13500" in out[1]
