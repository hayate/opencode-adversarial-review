"""The images are part of the treatment. If they drift, the numbers drift."""

import json
from pathlib import Path

from harness.sandbox import run_in_sandbox

AGENT = "localhost/odr-agent:latest"
GRADING = "localhost/odr-grading:latest"
EXPECTED_OPENCODE_VERSION = "1.18.23"


SANDBOX_HOME = {"HOME": "/tmp/h", "XDG_CONFIG_HOME": "/tmp/h/.config"}


def test_agent_image_has_the_pinned_opencode_version(tmp_path):
    result = run_in_sandbox(
        AGENT, tmp_path,
        ["sh", "-c", "mkdir -p /tmp/h/.config && opencode --version"],
        network="none", env=SANDBOX_HOME,
    )
    assert result.exit_code == 0, result.stderr
    assert result.stdout.strip() == EXPECTED_OPENCODE_VERSION


def test_opencode_requires_a_writable_home_under_readonly_root(tmp_path):
    """Pins a hard runtime constraint discovered on 2026-08-27.

    Without a HOME override, opencode fails with EROFS trying to mkdir
    /root/.local - even for --version. Spec 6.0 wants an isolated HOME for
    sterility; the read-only root independently REQUIRES one to exist. This
    test exists so a refactor that drops the override fails here, loudly,
    rather than somewhere confusing later.
    """
    result = run_in_sandbox(AGENT, tmp_path, ["opencode", "--version"], network="none")
    assert result.exit_code != 0
    assert "EROFS" in result.stderr


def test_opencode_runs_under_readonly_root_with_tmpfs_home(tmp_path):
    """HOME lives on a 512m tmpfs under a read-only root. Prove it works
    rather than assuming it."""
    result = run_in_sandbox(
        AGENT, tmp_path,
        ["sh", "-c", "mkdir -p /tmp/h/.config && opencode --version"],
        network="none", env=SANDBOX_HOME,
    )
    assert result.exit_code == 0
    assert result.stdout.strip() == EXPECTED_OPENCODE_VERSION


def test_grading_image_has_the_fixture_stack(tmp_path):
    result = run_in_sandbox(
        GRADING, tmp_path,
        ["python", "-c", "import django, rest_framework, pytest_django, pytest_jsonreport"],
        network="none",
    )
    assert result.exit_code == 0, result.stderr


def test_grading_find_supports_printf(tmp_path):
    """busybox find has no -printf; the container manifest check needs it."""
    (tmp_path / "a.txt").write_text("x")
    result = run_in_sandbox(
        GRADING, tmp_path, ["find", ".", "-type", "f", "-printf", "%P\n"], network="none"
    )
    assert result.stdout.strip() == "a.txt"


def test_digests_are_recorded():
    """Two runs of the same commit must be able to prove they used the same
    tools. A tag cannot prove that."""
    digests = json.loads(Path("containers/digests.json").read_text())
    for key in ("agent", "grading", "opencode_version", "base_image"):
        assert key in digests, f"digests.json is missing {key}"
    assert digests["agent"].startswith("sha256:")
    assert digests["grading"].startswith("sha256:")


def test_opencode_ripgrep_works_under_container_constraints(tmp_path):
    """Regression for a silent, DIFFERENTIAL confound found 2026-08-27.

    opencode downloads ripgrep at first use and extracts it with tar, which
    cannot chown under rootless podman with --cap-drop ALL. The glob and grep
    tools then fail. The agent recovers by reading files directly, so the run
    still "succeeds" and nothing looks wrong - while a model that leans on
    search to locate call sites is crippled and one that does not is fine.
    H-CALLSITE is precisely about locating non-obvious call sites, so this
    would have been measured and published as a model property.

    The image now ships ripgrep from apt. This test exercises the same code
    path as the glob tool, deterministically and without a model call.
    """
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "other.py").write_text("NEEDLE_TOKEN = 1\n")

    listing = run_in_sandbox(
        AGENT, tmp_path,
        ["sh", "-c", "mkdir -p /tmp/h && opencode debug rg files"],
        network="none", env=SANDBOX_HOME,
    )
    assert listing.exit_code == 0, listing.stderr
    assert "calc.py" in listing.stdout and "other.py" in listing.stdout

    search = run_in_sandbox(
        AGENT, tmp_path,
        ["sh", "-c", "mkdir -p /tmp/h && opencode debug rg search NEEDLE_TOKEN"],
        network="none", env=SANDBOX_HOME,
    )
    assert search.exit_code == 0, search.stderr
    assert "other.py" in search.stdout
    assert "Operation not permitted" not in search.stderr
