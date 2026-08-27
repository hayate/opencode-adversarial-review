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
