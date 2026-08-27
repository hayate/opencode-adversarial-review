from pathlib import Path

from harness.preflight import load_eval_env, preflight


def test_preflight_returns_a_list_of_problems():
    assert isinstance(preflight(), list)


def test_missing_binaries_are_reported(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    problems = preflight(env={"DEEPSEEK_API_KEY": "x", "ANTHROPIC_API_KEY": "y"})
    assert any("podman" in p for p in problems)
    assert any("opencode" in p for p in problems)


def test_missing_credentials_are_reported():
    problems = preflight(env={})
    assert any("DEEPSEEK_API_KEY" in p for p in problems)
    assert any("ANTHROPIC_API_KEY" in p for p in problems)


def test_credentials_present_are_not_reported():
    problems = preflight(env={"DEEPSEEK_API_KEY": "x", "ANTHROPIC_API_KEY": "y"})
    assert not any("API_KEY" in p for p in problems)


def test_load_eval_env_reads_the_key_file(tmp_path):
    env_file = tmp_path / "env"
    env_file.write_text("DEEPSEEK_API_KEY=sk-abc\nANTHROPIC_API_KEY=sk-ant-def\n")
    assert load_eval_env(env_file) == {
        "DEEPSEEK_API_KEY": "sk-abc",
        "ANTHROPIC_API_KEY": "sk-ant-def",
    }


def test_load_eval_env_returns_empty_when_absent(tmp_path):
    assert load_eval_env(tmp_path / "nope") == {}


def test_load_eval_env_rejects_a_world_readable_key_file(tmp_path):
    """A secrets file readable by other users is a finding, not a warning."""
    env_file = tmp_path / "env"
    env_file.write_text("DEEPSEEK_API_KEY=sk-abc\n")
    env_file.chmod(0o644)
    problems = preflight(env={"DEEPSEEK_API_KEY": "x", "ANTHROPIC_API_KEY": "y"},
                         env_file=env_file)
    assert any("permission" in p.lower() for p in problems)


def test_the_key_file_wins_over_the_ambient_environment(tmp_path, monkeypatch):
    """preflight validated {**file, **os.environ} while the spender read the
    file ONLY, so it could green-light a run that then died after one arm had
    already been paid for. It also contradicted load_eval_env's own docstring:
    credentials are read from a file rather than the ambient environment
    precisely so a run records which keys it used."""
    env_file = tmp_path / "env"
    env_file.write_text("DEEPSEEK_API_KEY=from-file\nANTHROPIC_API_KEY=from-file\n")
    env_file.chmod(0o600)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "from-ambient")
    assert load_eval_env(env_file)["DEEPSEEK_API_KEY"] == "from-file"
    assert preflight(env_file=env_file) == [] or all(
        "API_KEY" not in p for p in preflight(env_file=env_file)
    )


def test_a_key_only_in_the_ambient_environment_does_not_satisfy_preflight(
    tmp_path, monkeypatch
):
    """The spender never reads os.environ, so a key that lives only there is
    not a key the run can use."""
    env_file = tmp_path / "env"
    env_file.write_text("DEEPSEEK_API_KEY=from-file\n")
    env_file.chmod(0o600)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "only-ambient")
    problems = preflight(env_file=env_file)
    assert any("ANTHROPIC_API_KEY" in p for p in problems), problems
