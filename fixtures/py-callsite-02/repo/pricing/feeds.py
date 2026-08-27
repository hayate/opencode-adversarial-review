"""Reading and validating supplier rate feeds."""

import csv


class FeedRowError(Exception):
    """A feed row that cannot be turned into an observation."""


def read_feed(path):
    with open(path, newline="", encoding="utf-8") as handle:
        yield from csv.DictReader(handle)


def parse_row(raw):
    """Return (contract_code, date, observed_rate) or raise FeedRowError."""
    code = (raw.get("contract") or "").strip()
    date = (raw.get("date") or "").strip()
    if not date:
        raise FeedRowError("missing date")
    try:
        observed = int(raw.get("rate"))
    except (TypeError, ValueError):
        raise FeedRowError(f"unreadable rate {raw.get('rate')!r}") from None
    if observed <= 0:
        raise FeedRowError(f"non-positive rate {observed}")
    return code, date, observed
