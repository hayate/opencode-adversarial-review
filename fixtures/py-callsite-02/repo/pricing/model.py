"""Value types for the nightly rate reconciliation.

A Variance carries the contract CODE rather than the Contract itself. The
contracts map is loaded once at the entry point and threaded to whoever needs
supplier or settlement data, which keeps report.py a pure formatter with no
lookups of its own.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Contract:
    code: str
    supplier: str
    room: str
    rate: int
    # None for contracts migrated from the old system, which never recorded one.
    settlement_currency: str | None


@dataclass(frozen=True)
class Variance:
    contract_code: str
    room: str
    date: str
    contracted: int
    observed: int

    @property
    def delta(self) -> int:
        return self.observed - self.contracted
