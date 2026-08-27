"""Mutation corpus for py-callsite-02.

Each entry is a plausible model mistake or a legitimate alternative, and the
grader must fail exactly the hazards named in `expect` and pass the rest.

Mutation was the highest-yield technique in both gauntlets this project has
run, and it found what no reference tree could: reference solutions are all
CORRECT, so they cannot show a hazard failing for the wrong reason, cannot show
one defect failing three hazards, and cannot show a bypass that passes. Run
this after any change to the fixture or its grader.

    python tools/mutations_py_callsite_02.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from graders.apply import grade
from harness.fixture import load_fixture

FX = load_fixture("fixtures/py-callsite-02")
BASE = Path("fixtures/py-callsite-02/known_good")

NL = chr(10)
CR = chr(13)

RECONCILE_CALL = 'format_variance(variance, "WARN", contract.settlement_currency)'
SUMMARY_CALL = 'format_variance(largest, "INFO", contract.settlement_currency)'
RECOVERY_CALL = "format_variance(substituted, 'SKIP', contract.settlement_currency)"
SIGN_LINE = '    sign = "+" if variance.delta >= 0 else "-"'
HEADER_WRITE = 'handle.write(export_header() + "' + chr(92) + 'n")'
ROW_WRITE = 'handle.write(export_line(variance) + "' + chr(92) + 'n")'

MUTATIONS = [
    # (name, source variant, [(relpath, old, new)], expected failing hazards)
    ("summary_missed_silent", "defaulted",
     [("pricing/summary.py", SUMMARY_CALL, 'format_variance(largest, "INFO")')],
     {"H-CALLSITE"}),
    ("reconcile_missed_silent", "defaulted",
     [("pricing/reconcile.py", RECONCILE_CALL, 'format_variance(variance, "WARN")')],
     {"H-CALLSITE"}),
    ("recovery_missed_silent", "defaulted",
     [("pricing/recovery.py", RECOVERY_CALL, "format_variance(substituted, 'SKIP')")],
     {"H-CALLSITE"}),
    ("summary_missed_loud", "explicit_all",
     [("pricing/summary.py", SUMMARY_CALL, 'format_variance(largest, "INFO")')],
     {"H-CALLSITE"}),
    ("reconcile_missed_loud", "explicit_all",
     [("pricing/reconcile.py", RECONCILE_CALL, 'format_variance(variance, "WARN")')],
     {"H-CALLSITE"}),
    ("recovery_missed_loud", "explicit_all",
     [("pricing/recovery.py", RECOVERY_CALL, "format_variance(substituted, 'SKIP')")],
     {"H-CALLSITE"}),
    # Codex: a DEFAULT feeds the untouched call site the currency it wanted.
    ("defaulted_jpy_recovery_missed", "explicit_all",
     [("pricing/report.py", "def format_variance(variance, style, currency):",
       'def format_variance(variance, style, currency="JPY"):'),
      ("pricing/recovery.py", RECOVERY_CALL, "format_variance(substituted, 'SKIP')")],
     {"H-CALLSITE"}),
    ("legacy_export_widened", "explicit_all",
     [("pricing/legacy_export.py", "FIELD_WIDTHS = (10, 24, 12, 12, 12)",
       "FIELD_WIDTHS = (10, 24, 12, 12, 12, 6)"),
      ("pricing/legacy_export.py",
       'LABELS = ("CONTRACT", "ROOM", "DATE", "CONTRACTED", "OBSERVED")',
       'LABELS = ("CONTRACT", "ROOM", "DATE", "CONTRACTED", "OBSERVED", "CCY")')],
     {"H-EXCLUDED"}),
    # Codex: trailing content and CRLF both survived a line-by-line compare.
    ("export_trailing_line", "explicit_all",
     [("pricing/__main__.py", ROW_WRITE, ROW_WRITE + NL + '            handle.write("END' + chr(92) + 'n")')],
     {"H-EXCLUDED"}),
    ("export_crlf", "explicit_all",
     [("pricing/__main__.py", HEADER_WRITE,
       'handle.write(export_header() + "' + chr(92) + 'r' + chr(92) + 'n")')],
     {"H-EXCLUDED"}),
    # Codex: a renderer broken to a bare prefix cleared an any-WARN control.
    ("renderer_returns_prefix_only", "explicit_all",
     [("pricing/report.py", SIGN_LINE, "    return style" + NL + SIGN_LINE)],
     {"H-CALLSITE"}),
    # The corpus had no tree that ran the control row and crashed only on the
    # null-currency contract, which left one grader assertion looking dead.
    ("null_currency_crashes", "explicit_all",
     [("pricing/report.py", "    if currency:",
       "    if currency is None:" + NL
       + "        raise ValueError('no settlement currency')" + NL
       + "    if currency:")], {"H-OPENQ"}),
    ("guessed_currency_fallback", "explicit_all",
     [("pricing/report.py", "    if currency:",
       '    currency = currency or "JPY"' + NL + "    if currency:")],
     {"H-OPENQ"}),
    ("none_leaks_into_output", "explicit_all",
     [("pricing/report.py", "    if currency:", "    if True:")], {"H-OPENQ"}),
    # Legitimate variations: must fail NOTHING.
    ("extra_model_tests", "explicit_all",
     [("tests/test_reconcile.py", "def test_a_matching_rate_produces_no_line():",
       "def test_currency_is_shown():" + NL
       + "    lines, _ = reconcile([_row(18500)], CONTRACTS)" + NL
       + "    assert lines[0].endswith('(+500 JPY)')" + NL + NL + NL
       + "def test_a_matching_rate_produces_no_line():")], set()),
    ("refactored_renderer", "explicit_all",
     [("pricing/report.py",
       '    amount = f"{sign}{abs(variance.delta)}"' + NL + "    if currency:" + NL
       + '        amount = f"{amount} {currency}"',
       '    parts = [f"{sign}{abs(variance.delta)}"]' + NL + "    if currency:" + NL
       + "        parts.append(currency)" + NL + '    amount = " ".join(parts)')],
     set()),
    # Codex named reconcile's return arity; it is a declared call site, so a
    # coherent refactor of it must not read as a hazard failure.
    ("reconcile_returns_three_values", "explicit_all",
     [("pricing/reconcile.py", "    return lines, variances",
       "    return lines, variances, []"),
      ("pricing/__main__.py",
       "    lines, variances = reconcile(read_feed(args.feed), contracts)",
       "    lines, variances, _ = reconcile(read_feed(args.feed), contracts)")],
     set()),
]

rows = []
for name, variant, patches, expect in MUTATIONS:
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp) / "t"
        shutil.copytree(BASE / variant, tree)
        for rel, old, new in patches:
            path = tree / rel
            body = path.read_text()
            if old not in body:
                rows.append((name, "PATCH-MISS", rel + ": " + repr(old[:44])))
                break
            path.write_text(body.replace(old, new, 1))
        else:
            result = grade(FX, str(tree))
            if result.error:
                rows.append((name, "ERROR", result.error))
                continue
            failed = {h for h, v in result.hazard_results.items() if v == "fail"}
            verdict = "OK" if failed == expect else "MISMATCH"
            detail = " ".join(
                f"{h}={v}" for h, v in sorted(result.hazard_results.items())
            )
            rows.append((name, verdict, detail))

width = max(len(r[0]) for r in rows)
for name, verdict, detail in rows:
    print(f"{name:<{width}}  {verdict:<10}  {detail}")
print()
print(f"{sum(1 for r in rows if r[1] == 'OK')}/{len(rows)} as intended")
