"""Round 3: does every grader assertion actually discriminate?

Round 1 enumerated designs. Round 2 mutated SUBJECTS. This asks the mirror
question about the grader itself: is there any tree in the corpus that makes
each grader test fail? A grader test that passes against every subject we can
construct - correct, broken, and bypassing - is a guard that cannot fire, and
it is invisible to every technique used so far, because hazard verdicts
aggregate its result away.
"""
import json
import shutil
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from graders.apply import (
    GRADING_IMAGE,
    _GRADING_ENV,
    _PYTEST_ARGV,
    _stage,
)
from harness.fixture import load_fixture
from harness.sandbox import run_in_sandbox

from tools.mutations_py_callsite_02 import BASE, MUTATIONS

FX = load_fixture(ROOT / "fixtures" / "py-callsite-02")
REPO = ROOT / "fixtures" / "py-callsite-02" / "repo"


def report_for(tree):
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "work"
        out = Path(tmp) / "out"
        out.mkdir()
        if _stage(FX, tree, work):
            return None
        run_in_sandbox(
            GRADING_IMAGE, work,
            _PYTEST_ARGV + ["-q", "--json-report",
                            "--json-report-file=/out/report.json"],
            network="none", env=_GRADING_ENV, timeout_s=300,
            extra_mounts={out: "/out"},
        )
        path = out / "report.json"
        return json.loads(path.read_text()) if path.exists() else None


def build(variant, patches, dest):
    shutil.copytree(BASE / variant, dest)
    for rel, old, new in patches:
        p = dest / rel
        body = p.read_text()
        if old not in body:
            return False
        p.write_text(body.replace(old, new, 1))
    return True


corpus = [("repo", REPO, None)]
for variant in ("explicit_all", "keyword_only", "defaulted"):
    corpus.append((f"known_good/{variant}", BASE / variant, None))
corpus.append(("known_bad/missed_recovery",
               ROOT / "fixtures" / "py-callsite-02" / "known_bad" / "missed_recovery", None))
for name, variant, patches, _ in MUTATIONS:
    corpus.append((name, None, (variant, patches)))

outcomes = defaultdict(set)
for label, tree, mutation in corpus:
    with tempfile.TemporaryDirectory() as tmp:
        if mutation is not None:
            tree = Path(tmp) / "t"
            if not build(mutation[0], mutation[1], tree):
                print(f"  ! {label}: patch miss")
                continue
        report = report_for(tree)
        if report is None:
            print(f"  ! {label}: no report")
            continue
        for t in report.get("tests", []):
            outcomes[t["nodeid"]].add(t["outcome"])

print()
declared = [n for h in FX.hazards for n in (h.get("tests") or [])]
dead = []
for nodeid in declared:
    seen = outcomes.get(nodeid, set())
    discriminates = bool(seen & {"failed", "error"})
    flag = "     " if discriminates else "DEAD "
    if not discriminates:
        dead.append(nodeid)
    print(f"{flag}{sorted(seen)!s:<34} {nodeid.split('::')[-1]}")

print()
print(f"{len(declared) - len(dead)}/{len(declared)} grader assertions discriminate "
      f"over {len(corpus)} trees")
if dead:
    print("CANNOT FIRE:", *dead, sep="\n  ")
