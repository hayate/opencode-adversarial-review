"""Fallback for feed rows the parser rejects.

Reached only from reconcile's error path: the supplier resends a corrected feed
the next morning, so a bad row is reported and the contracted rate stands for
the night rather than failing the whole run.
"""

from pricing.model import Variance
from pricing.report import format_variance


def recover_row(raw, contract, reason):
    """Report a rejected row, with the contracted rate standing in for it."""
    substituted = Variance(
        contract_code=contract.code,
        room=contract.room,
        date=(raw.get("date") or "unknown").strip() or "unknown",
        contracted=contract.rate,
        observed=contract.rate,
    )
    return f"{format_variance(substituted, 'SKIP', contract.settlement_currency)} [{reason}]"
