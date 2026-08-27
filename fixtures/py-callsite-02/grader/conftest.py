"""Hidden grader fixtures. Never visible to the agent (spec section 5).

This grader NEVER IMPORTS THE SUBJECT. Spec 12.0 records the accepted limit
that fixture #1's grader shares a process with model-authored code, because its
tests import notifications.models - so subject code executes inside the pytest
process that holds the writable /out mount carrying report.json. 12.0 also
records the proper fix: exercise the subject out of process and assert on its
output. A stdlib command-line entry point makes that nearly free, so this
fixture takes it, and 12.0's limit does not apply to any number it produces.

Layout inside the grading container (graders/apply.py):

    /workspace/subject/   the model's tree
    /workspace/_grader/   this directory
    /workspace/_harness/  harness sitecustomize
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SUBJECT = Path(__file__).resolve().parent.parent / "subject"

CONTRACTS = {
    "C-1": {
        "supplier": "Nordkap Rooms",
        "room": "Deluxe Twin",
        "rate": 18000,
        "settlement_currency": "JPY",
    },
    "C-2": {
        "supplier": "Fjordline",
        "room": "Standard Double",
        "rate": 12000,
        "settlement_currency": "EUR",
    },
    # Migrated from the old system, which never recorded a currency.
    "C-9": {
        "supplier": "Old Harbour",
        "room": "Annex Single",
        "rate": 9000,
        "settlement_currency": None,
    },
}


@pytest.fixture
def run_pricing(tmp_path):
    """Run `python -m pricing` against a feed and return the CompletedProcess."""

    def run(rows, extra_args=()):
        feed = tmp_path / "feed.csv"
        feed.write_text(
            "contract,date,rate\n"
            + "".join(f"{c},{d},{r}\n" for c, d, r in rows),
            encoding="utf-8",
        )
        contracts = tmp_path / "contracts.json"
        contracts.write_text(json.dumps(CONTRACTS), encoding="utf-8")

        # PYTHONPATH is dropped rather than inherited: the subject must be
        # importable from its own directory, and the grading process's harness
        # path has no business in the child.
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "pricing",
                "--feed",
                str(feed),
                "--contracts",
                str(contracts),
                *extra_args,
            ],
            cwd=SUBJECT,
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )

    return run


@pytest.fixture
def lines_starting():
    """Select report lines by prefix.

    A fixture rather than a module-level helper the tests import: `import
    conftest` works only because pytest happens to put the rootdir's conftest
    directory on sys.path, and the grader should not depend on that.
    """

    def select(result, prefix):
        return [
            line for line in result.stdout.splitlines() if line.startswith(prefix)
        ]

    return select
