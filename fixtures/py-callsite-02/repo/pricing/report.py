"""Operator-facing rendering of a rate variance."""


def format_variance(variance, style):
    """Render one variance line for an operator."""
    sign = "+" if variance.delta >= 0 else "-"
    return (
        f"{style} {variance.contract_code} {variance.room} {variance.date}: "
        f"contracted {variance.contracted}, observed {variance.observed} "
        f"({sign}{abs(variance.delta)})"
    )
