import subprocess

from harness.sandbox import run_in_sandbox

IMAGE = "localhost/odr-grading:latest"


def test_command_runs_and_output_is_captured(tmp_path):
    result = run_in_sandbox(IMAGE, tmp_path, ["echo", "hello"], network="none")
    assert result.exit_code == 0
    assert result.stdout.strip() == "hello"
    assert result.timed_out is False


def test_workspace_is_mounted(tmp_path):
    (tmp_path / "hello.txt").write_text("hi")
    result = run_in_sandbox(IMAGE, tmp_path, ["cat", "hello.txt"], network="none")
    assert result.stdout.strip() == "hi"


def test_grading_sandbox_has_no_network(tmp_path):
    result = run_in_sandbox(
        IMAGE,
        tmp_path,
        [
            "python",
            "-c",
            "import socket,sys;s=socket.socket();s.settimeout(3);"
            "sys.exit(0 if s.connect_ex(('1.1.1.1',443))!=0 else 1)",
        ],
        network="none",
    )
    assert result.exit_code == 0, "grading sandbox reached the network"


def test_host_filesystem_is_not_reachable(tmp_path):
    result = run_in_sandbox(IMAGE, tmp_path, ["ls", "/host"], network="none")
    assert result.exit_code != 0


def test_timeout_is_reported_and_the_container_is_removed(tmp_path):
    """Killing the podman client is not enough; the container must be gone."""
    result = run_in_sandbox(IMAGE, tmp_path, ["sleep", "60"], network="none", timeout_s=3)
    assert result.timed_out is True
    running = subprocess.run(
        ["podman", "ps", "--format", "{{.Names}}"], capture_output=True, text=True
    ).stdout
    assert "odr-" not in running, "container survived the timeout"


def test_extra_mount_is_writable_and_readable_from_the_host(tmp_path):
    """The grader writes its report to a mounted volume; a read-only root
    must not prevent that."""
    out = tmp_path / "out"
    out.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    run_in_sandbox(
        IMAGE, work, ["sh", "-c", "echo report > /out/x.txt"],
        network="none", extra_mounts={out: "/out"},
    )
    assert (out / "x.txt").read_text().strip() == "report"


def test_environment_variables_are_passed(tmp_path):
    result = run_in_sandbox(
        IMAGE, tmp_path, ["sh", "-c", "echo $ODR_TEST"],
        network="none", env={"ODR_TEST": "value"},
    )
    assert result.stdout.strip() == "value"
