"""Fixed-width settlement export consumed by Finance.

Finance's loader parses this file BY COLUMN POSITION. It is versioned against
that loader rather than against the operator report, which is why it formats
its own lines instead of calling report.format_variance.
"""

FIELD_WIDTHS = (10, 24, 12, 12, 12)
LABELS = ("CONTRACT", "ROOM", "DATE", "CONTRACTED", "OBSERVED")


def _row(values):
    return "".join(f"{value:<{width}}"[:width] for value, width in zip(values, FIELD_WIDTHS))


def export_header():
    return _row(LABELS)


def export_line(variance):
    return _row(
        (
            variance.contract_code,
            variance.room,
            variance.date,
            str(variance.contracted),
            str(variance.observed),
        )
    )
