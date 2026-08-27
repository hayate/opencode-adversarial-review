"""Nightly rate reconciliation.

    python -m pricing --feed FEED.csv --contracts CONTRACTS.json
"""

import argparse
import json
import sys

from pricing.feeds import read_feed
from pricing.legacy_export import export_header, export_line
from pricing.model import Contract
from pricing.reconcile import reconcile
from pricing.summary import summarise


def load_contracts(path):
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    return {
        code: Contract(
            code=code,
            supplier=entry["supplier"],
            room=entry["room"],
            rate=entry["rate"],
            settlement_currency=entry.get("settlement_currency"),
        )
        for code, entry in raw.items()
    }


def main(argv=None):
    parser = argparse.ArgumentParser(prog="pricing")
    parser.add_argument("--feed", required=True)
    parser.add_argument("--contracts", required=True)
    parser.add_argument(
        "--legacy-export",
        help="also write Finance's fixed-width settlement file to this path",
    )
    args = parser.parse_args(argv)

    contracts = load_contracts(args.contracts)
    lines, variances = reconcile(read_feed(args.feed), contracts)
    for line in lines + summarise(variances, contracts):
        print(line)

    if args.legacy_export:
        with open(args.legacy_export, "w", encoding="utf-8") as handle:
            handle.write(export_header() + "\n")
            for variance in variances:
                handle.write(export_line(variance) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
