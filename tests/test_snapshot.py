"""Change capture must not use git.

The agent owns the tree: it can commit, reset, replace .git, or move HEAD, and
`git diff HEAD` misses untracked files. A normal agent commit would make a
substantial change appear as an empty diff.
"""

import os

from harness.snapshot import diff_snapshots, snapshot


def test_detects_added_modified_and_deleted(tmp_path):
    (tmp_path / "keep.py").write_text("a")
    (tmp_path / "change.py").write_text("b")
    (tmp_path / "gone.py").write_text("c")
    before = snapshot(tmp_path)

    (tmp_path / "change.py").write_text("b2")
    (tmp_path / "gone.py").unlink()
    (tmp_path / "new.py").write_text("d")

    changes = diff_snapshots(before, snapshot(tmp_path))
    assert changes.added == {"new.py"}
    assert changes.modified == {"change.py"}
    assert changes.deleted == {"gone.py"}


def test_untracked_new_file_is_detected(tmp_path):
    """The exact case `git diff HEAD` would have missed."""
    before = snapshot(tmp_path)
    (tmp_path / "sneaky.py").write_text("x")
    assert diff_snapshots(before, snapshot(tmp_path)).added == {"sneaky.py"}


def test_chmod_is_detected(tmp_path):
    """A content-only digest misses a permission change, which is a real
    mutation - an accidentally executable file, or a loosened secret."""
    target = tmp_path / "script.sh"
    target.write_text("echo hi\n")
    target.chmod(0o644)
    before = snapshot(tmp_path)
    target.chmod(0o755)
    assert diff_snapshots(before, snapshot(tmp_path)).modified == {"script.sh"}


def test_file_replaced_by_symlink_of_identical_content_is_detected(tmp_path):
    (tmp_path / "real.py").write_text("payload")
    (tmp_path / "target.py").write_text("payload")
    before = snapshot(tmp_path)
    (tmp_path / "real.py").unlink()
    (tmp_path / "real.py").symlink_to(tmp_path / "target.py")
    assert "real.py" in diff_snapshots(before, snapshot(tmp_path)).modified


def test_directories_are_tracked(tmp_path):
    before = snapshot(tmp_path)
    (tmp_path / "newdir").mkdir()
    assert diff_snapshots(before, snapshot(tmp_path)).added == {"newdir"}


def test_special_files_are_recorded_not_hashed(tmp_path):
    """A FIFO would block forever if opened for reading."""
    os.mkfifo(tmp_path / "pipe")
    snap = snapshot(tmp_path)
    assert snap["pipe"].startswith("special:")


def test_unchanged_tree_produces_no_changes(tmp_path):
    (tmp_path / "a.py").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.py").write_text("y")
    snap = snapshot(tmp_path)
    changes = diff_snapshots(snap, snapshot(tmp_path))
    assert not (changes.added or changes.modified or changes.deleted)


def test_out_of_scope_paths_are_derived_from_real_changes(tmp_path):
    """Scope is measured from what actually changed on disk, not from which
    tool calls the model happened to make - bash writes, patch tools and
    generated files are invisible to tool-call inspection."""
    (tmp_path / "allowed.py").write_text("a")
    before = snapshot(tmp_path)
    (tmp_path / "allowed.py").write_text("a2")
    (tmp_path / "forbidden.py").write_text("b")
    changes = diff_snapshots(before, snapshot(tmp_path))
    assert changes.touched() == {"allowed.py", "forbidden.py"}
    assert changes.outside({"allowed.py"}) == {"forbidden.py"}


def test_build_detritus_is_ignored(tmp_path):
    """A pytest run creates 20+ cache entries. Counting them as out-of-scope
    changes buried the single real change on the first live run."""
    (tmp_path / "real.py").write_text("x")
    before = snapshot(tmp_path)
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "real.cpython-313.pyc").write_bytes(b"\x00")
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / ".pytest_cache" / "CACHEDIR.TAG").write_text("tag")
    (tmp_path / "genuine_new.py").write_text("y")
    changes = diff_snapshots(before, snapshot(tmp_path))
    assert changes.added == {"genuine_new.py"}


def test_an_unreadable_file_does_not_crash_the_whole_eval(tmp_path):
    """snapshot() deliberately never opens a FIFO because reading one blocks
    forever, but it did open unreadable regular files - so a model-authored
    mode-000 file raised PermissionError out of run_agent and out of the eval,
    losing summary.json for every already-paid run."""
    locked = tmp_path / "locked.py"
    locked.write_text("x = 1\n")
    locked.chmod(0o000)
    try:
        result = snapshot(tmp_path)
    finally:
        locked.chmod(0o644)
    assert "locked.py" in result
    assert result["locked.py"].startswith("unreadable:")
