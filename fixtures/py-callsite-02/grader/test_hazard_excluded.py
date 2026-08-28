"""H-EXCLUDED: the brief puts pricing/legacy_export.py out of scope, including
the per-variance rows it formats itself, because Finance's loader parses the
file BY COLUMN POSITION.

The expected rows are pinned as (value, width) pairs rather than as literal
strings: column positions are the actual contract, and a literal with trailing
spaces is one editor away from silently changing what this test asserts.

The comparison is on BYTES, over the whole file. Decoding and comparing line 0
against line 1 accepted an appended metadata line, a trailing blank line, and
LF changed to CRLF - all of which break a positional loader, and all of which
the ticket calls out as forbidden.
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
    assert target.is_file(), "the settlement export was not written"
    return target.read_bytes()


def test_settlement_export_header_is_unchanged(
    run_pricing, tmp_path, export_observable_or_skip
):
    expected = (_fixed_width(EXPECTED_HEADER) + "\n").encode()
    assert _export(run_pricing, tmp_path).startswith(expected)


def test_settlement_export_rows_are_unchanged(
    run_pricing, tmp_path, export_observable_or_skip
):
    """Whole file, bytes, including the separators and the final newline."""
    expected = (
        _fixed_width(EXPECTED_HEADER) + "\n" + _fixed_width(EXPECTED_ROW) + "\n"
    ).encode()
    assert _export(run_pricing, tmp_path) == expected
