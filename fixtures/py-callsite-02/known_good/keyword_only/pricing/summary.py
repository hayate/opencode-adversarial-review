"""End-of-run summary for the operator report."""

from pricing.report import format_variance


def summarise(variances, contracts):
    if not variances:
        return ["SUMMARY no variances"]
    largest = max(variances, key=lambda v: abs(v.delta))
    contract = contracts[largest.contract_code]
    return [
        f"SUMMARY largest variance from {contract.supplier}",
        format_variance(largest, "INFO", currency=contract.settlement_currency),
    ]
