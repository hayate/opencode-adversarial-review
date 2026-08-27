"""Spec section 5 is a security invariant, not a style preference.

If the answer key reaches the agent, every number the harness ever produces is
worthless - and the failure is silent, because a model that read the answers
looks like a model that solved the problem.
"""

import os

import pytest

from harness.fixture import (
    FixtureViolation,
    load_fixture,
    stage_agent_tree,
)


def _make_fixture(tmp_path):
    fx = tmp_path / "py-demo-01"
    (fx / "repo" / "app").mkdir(parents=True)
    (fx / "repo" / "app" / "services.py").write_text("def f():\n    return 1\n")
    (fx / "grader").mkdir()
    (fx / "grader" / "test_hazard.py").write_text("def test_x():\n    assert True\n")
    (fx / "known_good").mkdir()
    (fx / "known_bad").mkdir()
    (fx / "task.md").write_text("Add a thing.")
    (fx / "hazards.yaml").write_text(
        "hazards:\n"
        "  - id: H-DEMO\n"
        "    origin: invented\n"
        "    tests: ['_grader/test_hazard.py::test_x']\n"
    )
    (fx / "manifest.txt").write_text("app/services.py\n")
    return fx


def test_stages_only_repo_contents(tmp_path):
    fx = _make_fixture(tmp_path)
    dest = tmp_path / "staged"
    stage_agent_tree(load_fixture(fx), dest)
    staged = {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()}
    assert staged == {"app/services.py"}


def test_answer_key_is_never_staged(tmp_path):
    fx = _make_fixture(tmp_path)
    dest = tmp_path / "staged"
    stage_agent_tree(load_fixture(fx), dest)
    for forbidden in ("grader", "known_good", "known_bad", "hazards.yaml", "task.md", "manifest.txt"):
        assert not (dest / forbidden).exists()


def test_task_brief_is_read_on_the_host_not_staged(tmp_path):
    fx = _make_fixture(tmp_path)
    assert load_fixture(fx).task_brief == "Add a thing."


def test_rejects_symlink_escaping_repo(tmp_path):
    fx = _make_fixture(tmp_path)
    (fx / "repo" / "leak").symlink_to(fx / "grader")
    with pytest.raises(FixtureViolation, match="symlink"):
        stage_agent_tree(load_fixture(fx), tmp_path / "staged")


def test_rejects_hardlink_to_the_answer_key(tmp_path):
    """A hardlink has no path target to resolve, so a symlink check misses it
    entirely and copytree copies the contents."""
    fx = _make_fixture(tmp_path)
    os.link(fx / "grader" / "test_hazard.py", fx / "repo" / "innocent.py")
    with pytest.raises(FixtureViolation, match="hardlink"):
        stage_agent_tree(load_fixture(fx), tmp_path / "staged")


def test_rejects_git_metadata_at_any_depth(tmp_path):
    """Git history can carry deleted answer keys, and alternates/worktree
    pointers can reference paths outside the fixture entirely."""
    fx = _make_fixture(tmp_path)
    (fx / "repo" / "app" / ".git").mkdir()
    (fx / "repo" / "app" / ".git" / "config").write_text("[core]\n")
    with pytest.raises(FixtureViolation, match="git"):
        stage_agent_tree(load_fixture(fx), tmp_path / "staged")


def test_rejects_repo_itself_being_a_symlink(tmp_path):
    """resolve() on a symlinked repo/ would silently trust an external tree."""
    fx = tmp_path / "py-sym-01"
    fx.mkdir()
    (tmp_path / "elsewhere").mkdir()
    (fx / "repo").symlink_to(tmp_path / "elsewhere")
    (fx / "task.md").write_text("x")
    (fx / "hazards.yaml").write_text("hazards: []\n")
    (fx / "manifest.txt").write_text("")
    with pytest.raises(FixtureViolation, match="repo"):
        stage_agent_tree(load_fixture(fx), tmp_path / "staged")


def test_rejects_special_files(tmp_path):
    fx = _make_fixture(tmp_path)
    os.mkfifo(fx / "repo" / "a_fifo")
    with pytest.raises(FixtureViolation, match="special"):
        stage_agent_tree(load_fixture(fx), tmp_path / "staged")


def test_unlisted_file_fails_the_manifest(tmp_path):
    """The allowlist is committed and human-reviewed. Generating it from
    whatever happens to be in repo/ would bless an accidental secret."""
    fx = _make_fixture(tmp_path)
    (fx / "repo" / "surprise.py").write_text("leaked = 1\n")
    with pytest.raises(FixtureViolation, match="manifest"):
        stage_agent_tree(load_fixture(fx), tmp_path / "staged")


def test_missing_listed_file_fails_the_manifest(tmp_path):
    fx = _make_fixture(tmp_path)
    (fx / "repo" / "app" / "services.py").unlink()
    with pytest.raises(FixtureViolation, match="manifest"):
        stage_agent_tree(load_fixture(fx), tmp_path / "staged")
