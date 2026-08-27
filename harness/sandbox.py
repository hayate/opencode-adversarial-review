"""Rootless podman wrapper for the two sandboxes.

The agent sandbox is not merely a hardening layer: per spec section 6.0, an
isolated HOME is the only mechanism that yields a sterile opencode
configuration, so a host subprocess cannot substitute for it.
"""

from __future__ import annotations

import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

NAME_PREFIX = "odr-"


@dataclass(frozen=True)
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool


def _as_text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value or ""


def run_in_sandbox(
    image: str,
    workdir: Path,
    argv: list[str],
    *,
    network: str,
    env: dict[str, str] | None = None,
    timeout_s: int = 600,
    extra_mounts: dict[Path, str] | None = None,
) -> SandboxResult:
    """Run argv in a fresh container, destroyed afterwards.

    On timeout the container is killed by name. Killing only the podman client
    leaves the container running, which would let a capped run keep spending.
    """
    name = f"{NAME_PREFIX}{uuid.uuid4().hex[:12]}"
    cmd = [
        "podman", "run", "--rm", "--name", name,
        # --network none constrains the CONTAINER; without this podman would
        # still reach a registry FROM THE HOST when the image is missing, and
        # a substituted local tag would then execute while provenance reported
        # the digest recorded at build time.
        "--pull=never",
        "--network", network,
        "--security-opt", "no-new-privileges",
        "--cap-drop", "ALL",
        "--memory", "2g",
        "--cpus", "2",
        "--pids-limit", "512",
        "--read-only",
        "--tmpfs", "/tmp:rw,size=512m",
        "-v", f"{Path(workdir).resolve()}:/workspace:rw,Z",
        "-w", "/workspace",
    ]
    for host_path, container_path in (extra_mounts or {}).items():
        cmd += ["-v", f"{Path(host_path).resolve()}:{container_path}:rw,Z"]
    for key, value in (env or {}).items():
        cmd += ["-e", f"{key}={value}"]
    cmd += [image, *argv]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_s, errors="replace"
        )
        return SandboxResult(proc.returncode, proc.stdout, proc.stderr, False)
    except subprocess.TimeoutExpired as exc:
        subprocess.run(["podman", "kill", name], capture_output=True)
        subprocess.run(["podman", "rm", "-f", name], capture_output=True)
        return SandboxResult(-1, _as_text(exc.stdout), _as_text(exc.stderr), True)
