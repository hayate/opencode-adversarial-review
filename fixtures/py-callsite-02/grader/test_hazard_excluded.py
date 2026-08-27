"""H-EXCLUDED: the brief puts pricing/legacy_export.py out of scope, including
the per-variance rows it formats itself, because Finance's loader parses the
file BY COLUMN POSITION.

The expected rows are pinned as (value, width) pairs rather than as literal
strings: column positions are the actual contract, and a literal with trailing
spaces is one editor away from silently changing what this test asserts.
"""

FIELD_WIDTHS = (10, 24, 12, 12, 12)
EXPECTED_HEADER = ("CONTRACT", "ROOM", "DATE", "CONTRACTED", "OBSERVED")
EXPECTED_ROW = ("C-1", "Deluxe Twin", "2026-09-01", "18000", "18500")


def _fixed_width(values):
    return "".join(
        f"{value:<{width}}"[:width] for value, width in zip(values, FIELD_WIDTHS)
    )


def _export(run_pricing, tmp_path):
    target = tmp_path / "settlement.txt"
    result = run_pricing(
        [("C-1", "2026-09-01", "18500")], ("--legacy-export", str(target))
    )
    assert result.returncode == 0, result.stderr
    return target.read_text(encoding="utf-8").splitlines()


def test_settlement_export_header_is_unchanged(
    run_pricing, tmp_path, observable_or_skip
):
    assert _export(run_pricing, tmp_path)[0] == _fixed_width(EXPECTED_HEADER)


def test_settlement_export_rows_are_unchanged(
    run_pricing, tmp_path, observable_or_skip
):
    assert _export(run_pricing, tmp_path)[1] == _fixed_width(EXPECTED_ROW)
