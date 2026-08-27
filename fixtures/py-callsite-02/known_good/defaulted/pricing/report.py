"""Operator-facing rendering of a rate variance."""


def format_variance(variance, style, currency=None):
    """Render one variance line for an operator."""
    sign = "+" if variance.delta >= 0 else "-"
    amount = f"{sign}{abs(variance.delta)}"
    if currency:
        amount = f"{amount} {currency}"
    return (
        f"{style} {variance.contract_code} {variance.room} {variance.date}: "
        f"contracted {variance.contracted}, observed {variance.observed} "
        f"({amount})"
    )
