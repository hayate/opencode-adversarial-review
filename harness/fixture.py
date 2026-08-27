"""Fixture loading and the spec section 5 visibility boundary.

Only the contents of `fixtures/<id>/repo/` may ever reach the agent. Everything
else - the brief, the hazard list, the hidden grader, the reference solutions -
stays on the host. A leak here is silent: a model that read the answers is
indistinguishable from a model that solved the problem.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

from harness.sandbox import run_in_sandbox

# __pycache__ is build detritus: it varies per run, breaks byte-identical
# fixture reset, and a manifest generated while it was present would bless it.
# Caught 2026-08-27 when a container test run left it inside a fixture.
FORBIDDEN_NAMES = {".git", ".gitmodules", "__pycache__", ".pytest_cache"}


class FixtureViolation(Exception):
    """The fixture violates the visibility boundary or its committed manifest."""


@dataclass(frozen=True)
class Fixture:
    id: str
    root: Path
    task_brief: str
    hazards: list[dict]
    manifest: set[str]
    scope: list[str]

    @property
    def repo_dir(self) -> Path:
        return self.root / "repo"

    @property
    def known_good_dir(self) -> Path:
        """Reference tree used to collect grader tests before any paid run."""
        return self.root / "known_good" / "explicit_all"


def load_fixture(path: Path) -> Fixture:
    path = Path(path).resolve()
    data = yaml.safe_load((path / "hazards.yaml").read_text()) or {}
    manifest_file = path / "manifest.txt"
    manifest = (
        {line.strip() for line in manifest_file.read_text().splitlines() if line.strip()}
        if manifest_file.exists()
        else set()
    )
    return Fixture(
        id=path.name,
        root=path,
        task_brief=(path / "task.md").read_text(),
        hazards=data.get("hazards") or [],
        manifest=manifest,
        scope=data.get("scope") or [],
    )


def _validate(repo: Path) -> None:
    # lstat the literal path first: resolve() on a symlinked repo/ would
    # silently adopt an external tree as the trusted root.
    if repo.is_symlink():
        raise FixtureViolation(f"repo must be a real directory, not a symlink: {repo}")
    if not repo.is_dir():
        raise FixtureViolation(f"repo is not a directory: {repo}")

    resolved_repo = repo.resolve(strict=True)

    # rglob defaults to recurse_symlinks=False on Python 3.13, so a symlinked
    # directory is yielded as an entry and rejected rather than descended into.
    for entry in repo.rglob("*"):
        if entry.name in FORBIDDEN_NAMES:
            raise FixtureViolation(f"git metadata is forbidden in repo/: {entry}")
        if entry.is_symlink():
            raise FixtureViolation(f"symlink is forbidden in repo/: {entry}")
        if entry.is_dir():
            continue
        if not entry.is_file():
            raise FixtureViolation(f"special file is forbidden in repo/: {entry}")
        # A hardlink has no path target, so a symlink check cannot see it.
        # Policy is no hardlinks at all - deliberately stricter than "no
        # hardlinks leaving repo/", because link counts cannot tell us where
        # the other names live.
        if entry.stat().st_nlink > 1:
            raise FixtureViolation(f"hardlink is forbidden in repo/: {entry}")
        if not entry.resolve().is_relative_to(resolved_repo):
            raise FixtureViolation(f"path escapes repo/: {entry}")


def _relative_files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def stage_agent_tree(fixture: Fixture, dest: Path) -> None:
    repo = fixture.repo_dir
    _validate(repo)

    present = _relative_files(repo)
    if present != fixture.manifest:
        missing = sorted(fixture.manifest - present)
        unlisted = sorted(present - fixture.manifest)
        raise FixtureViolation(
            f"manifest mismatch for {fixture.id}: missing={missing} unlisted={unlisted}"
        )

    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(repo, dest, symlinks=True)


def assert_container_manifest(fixture: Fixture, image: str, staged: Path) -> None:
    """Spec section 5 rule 6: enforce against what the CONTAINER can see.

    The host-side check above proves what we intended to copy. This proves what
    actually became visible, which is the claim that matters.
    """
    result = run_in_sandbox(
        image, staged, ["find", ".", "-type", "f", "-printf", "%P\n"], network="none"
    )
    if result.exit_code != 0 or result.timed_out:
        raise FixtureViolation(
            f"manifest check could not run (timed_out={result.timed_out}): "
            f"{result.stderr[-500:]}"
        )
    seen = {line for line in result.stdout.splitlines() if line}
    if seen != fixture.manifest:
        raise FixtureViolation(
            f"container manifest mismatch for {fixture.id}: "
            f"unlisted={sorted(seen - fixture.manifest)} "
            f"missing={sorted(fixture.manifest - seen)}"
        )
