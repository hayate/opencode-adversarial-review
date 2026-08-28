"""Filesystem snapshot and diff.

Git cannot be the baseline inside a tree the agent controls: it can commit,
reset, checkout, or replace .git entirely, and `git diff HEAD` misses untracked
files. A normal agent commit would make a substantial change look like an empty
diff.
"""

from __future__ import annotations

import hashlib
import stat
from dataclasses import dataclass
from pathlib import Path

CHUNK = 1024 * 1024

# Build artefacts a test run creates. These are not model decisions: on the
# first real run they produced 20 entries in out_of_scope_paths and buried the
# single real change. Excluded from the snapshot entirely so that scope
# analysis measures intent rather than the side effects of running pytest.
IGNORED_NAMES = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}


def _is_detritus(rel: str) -> bool:
    parts = rel.split("/")
    if any(part in IGNORED_NAMES for part in parts):
        return True
    return any(rel.endswith(suffix) for suffix in IGNORED_SUFFIXES)


@dataclass(frozen=True)
class Changes:
    added: set[str]
    modified: set[str]
    deleted: set[str]

    def touched(self) -> set[str]:
        return self.added | self.modified | self.deleted

    @staticmethod
    def _covers(entry: str, path: str) -> bool:
        """Scope entries name a file or a directory prefix."""
        return path == entry or path.startswith(f"{entry.rstrip('/')}/")

    def outside(
        self, allowed_scope: set[str], excluded: set[str] | frozenset[str] = frozenset()
    ) -> set[str]:
        """Paths changed outside the ticket's stated scope.

        Derived from what actually changed on disk, never from which tool calls
        the model made - bash writes, patch tools and generated files are
        invisible to tool-call inspection.

        `excluded` is applied here rather than by subtracting from the scope
        set, because scope entries match as directory PREFIXES. Subtracting the
        strings left an excluded file that sits UNDER a scoped directory - scope
        `tests`, excluded `tests/test_digest.py` - still in bounds, so the guard
        could not fire on the case it exists for.
        """
        return {
            path
            for path in self.touched()
            if any(self._covers(e, path) for e in excluded)
            or not any(self._covers(a, path) for a in allowed_scope)
        }


def snapshot(tree: Path) -> dict[str, str]:
    """Map every path to a record of its kind, mode and content.

    Mode is included because a chmod is a real mutation that a content-only
    digest silently misses. Regular files are streamed rather than read whole,
    so a large model-created file cannot exhaust harness memory. Special files
    are recorded but never opened - reading a FIFO would block forever.
    """
    tree = Path(tree)
    out: dict[str, str] = {}
    for path in sorted(tree.rglob("*")):
        rel = path.relative_to(tree).as_posix()
        if _is_detritus(rel):
            continue
        info = path.lstat()
        mode = stat.S_IMODE(info.st_mode)
        if path.is_symlink():
            out[rel] = f"symlink:{mode:04o}:{path.readlink()}"
        elif stat.S_ISDIR(info.st_mode):
            out[rel] = f"dir:{mode:04o}"
        elif stat.S_ISREG(info.st_mode):
            # A model-authored mode-000 file used to raise PermissionError out
            # of snapshot(), out of run_agent and out of the eval - losing
            # summary.json for every already-paid run. The function already
            # refuses to open FIFOs for the same class of reason; this is the
            # same care applied to regular files.
            try:
                digest = hashlib.sha256()
                with path.open("rb") as handle:
                    while chunk := handle.read(CHUNK):
                        digest.update(chunk)
            except OSError:
                out[rel] = f"unreadable:{mode:04o}:{info.st_size}"
                continue
            out[rel] = f"file:{mode:04o}:{digest.hexdigest()}"
        else:
            out[rel] = f"special:{mode:04o}"
    return out


def diff_snapshots(before: dict[str, str], after: dict[str, str]) -> Changes:
    before_keys, after_keys = set(before), set(after)
    return Changes(
        added=after_keys - before_keys,
        deleted=before_keys - after_keys,
        modified={k for k in before_keys & after_keys if before[k] != after[k]},
    )
