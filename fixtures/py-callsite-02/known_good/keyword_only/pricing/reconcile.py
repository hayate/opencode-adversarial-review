"""Reconcile a supplier feed against contracted rates."""

from pricing.feeds import FeedRowError, parse_row
from pricing.model import Variance
from pricing.recovery import recover_row
from pricing.report import format_variance


def reconcile(rows, contracts):
    """Return (operator lines, variances found) for one feed."""
    lines = []
    variances = []
    for raw in rows:
        contract = contracts.get((raw.get("contract") or "").strip())
        if contract is None:
            lines.append(f"NOCONTRACT {(raw.get('contract') or '').strip()!r}")
            continue
        try:
            code, date, observed = parse_row(raw)
        except FeedRowError as exc:
            lines.append(recover_row(raw, contract, str(exc)))
            continue
        variance = Variance(code, contract.room, date, contract.rate, observed)
        if variance.delta == 0:
            continue
        variances.append(variance)
        lines.append(format_variance(variance, "WARN", currency=contract.settlement_currency))
    return lines, variances
