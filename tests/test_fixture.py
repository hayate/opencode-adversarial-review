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
    manifest_lines,
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
    (fx / "manifest.txt").write_text(
        "\n".join(manifest_lines(fx / "repo")) + "\n"
    )
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


def test_rejects_build_detritus(tmp_path):
    """__pycache__ varies per run, so it breaks byte-identical reset - and a
    manifest generated while it was present would have blessed it."""
    fx = _make_fixture(tmp_path)
    (fx / "repo" / "app" / "__pycache__").mkdir()
    (fx / "repo" / "app" / "__pycache__" / "services.cpython-313.pyc").write_bytes(b"\x00")
    with pytest.raises(FixtureViolation, match="__pycache__"):
        stage_agent_tree(load_fixture(fx), tmp_path / "staged")


# --- Identity is content, not just a path list ---


def test_same_path_content_drift_is_rejected(tmp_path):
    """The manifest compared paths only, so an edit that kept every filename
    was accepted. Provenance records HEAD, so a published run could claim the
    committed fixture while measuring a locally modified one - and fixture
    drift can interact differently with the two models."""
    fx = _make_fixture(tmp_path)
    (fx / "repo" / "app" / "services.py").write_text("def f():\n    return 2\n")
    with pytest.raises(FixtureViolation, match="manifest"):
        stage_agent_tree(load_fixture(fx), tmp_path / "staged")


def test_mode_drift_is_rejected(tmp_path):
    fx = _make_fixture(tmp_path)
    (fx / "repo" / "app" / "services.py").chmod(0o755)
    with pytest.raises(FixtureViolation, match="manifest"):
        stage_agent_tree(load_fixture(fx), tmp_path / "staged")


def test_an_intact_fixture_still_stages(tmp_path):
    fx = _make_fixture(tmp_path)
    stage_agent_tree(load_fixture(fx), tmp_path / "staged")


def test_the_shipped_fixture_matches_its_committed_manifest():
    """test_fixture.py otherwise only ever exercises synthetic trees, so drift
    on the real fixture was uncaught by the suite."""
    stage_agent_tree(load_fixture("fixtures/py-callsite-01"), None)


def test_the_container_sees_exactly_the_manifest(tmp_path):
    """The host check proves what we meant to copy; this proves what the agent
    can actually see. It had no callers anywhere in the repo until round 1."""
    from harness.fixture import assert_container_manifest

    fixture = load_fixture("fixtures/py-callsite-01")
    staged = tmp_path / "staged"
    stage_agent_tree(fixture, staged)
    assert_container_manifest(fixture, "localhost/odr-agent:latest", staged)


def test_an_extra_file_visible_in_the_container_is_a_violation(tmp_path):
    from harness.fixture import assert_container_manifest

    fixture = load_fixture("fixtures/py-callsite-01")
    staged = tmp_path / "staged"
    stage_agent_tree(fixture, staged)
    (staged / "ANSWERS.md").write_text("the timezone goes in three call sites\n")
    with pytest.raises(FixtureViolation, match="container manifest"):
        assert_container_manifest(fixture, "localhost/odr-agent:latest", staged)


def _with_reference(tmp_path, declared, variants=("explicit_all", "keyword_only")):
    """A fixture carrying several known-good trees, like a real one does."""
    fx = _make_fixture(tmp_path)
    for name in variants:
        (fx / "known_good" / name).mkdir(parents=True)
    hazards = (fx / "hazards.yaml").read_text()
    if declared is not None:
        hazards = f"reference: {declared}\n" + hazards
    (fx / "hazards.yaml").write_text(hazards)
    return fx


def test_the_reference_tree_is_declared_not_guessed(tmp_path):
    """known_good_dir hardcoded `explicit_all` - fixture #1's variant name baked
    into fixture-generic code, the same bug class as eval.py's hardcoded
    `notifications/services.py`. Its one caller (validate_hazard_mapping) needs
    a tree where every grader test collects, not a particular name."""
    fixture = load_fixture(_with_reference(tmp_path, "keyword_only"))
    assert fixture.known_good_dir.name == "keyword_only"


def test_an_undeclared_reference_tree_is_a_violation(tmp_path):
    """Silently guessing a name points the grader-collection stage at a tree
    that may not exist, which surfaces as a confusing copytree error."""
    fixture = load_fixture(_with_reference(tmp_path, None))
    with pytest.raises(FixtureViolation, match="reference"):
        fixture.known_good_dir


def test_a_reference_tree_that_does_not_exist_is_a_violation(tmp_path):
    fixture = load_fixture(_with_reference(tmp_path, "no_such_variant"))
    with pytest.raises(FixtureViolation, match="no_such_variant"):
        fixture.known_good_dir


@pytest.mark.parametrize("hostile", ["/etc", "../repo", "a/b", "."])
def test_a_reference_that_is_not_a_plain_directory_name_is_refused(
    tmp_path, hostile
):
    """`reference` is joined onto the fixture root, and pathlib drops
    everything left of an absolute part - so `/etc` yields Path('/etc'),
    is_dir() passes, and validate_reference_solution would copytree it as the
    subject. `..` escapes the same way. hazards.yaml is host-authored so this
    is not an attack surface, but _validate one function away is explicitly
    paranoid about this exact shape.
    """
    fixture = load_fixture(_with_reference(tmp_path, hostile))
    with pytest.raises(FixtureViolation, match="plain directory name"):
        fixture.known_good_dir
