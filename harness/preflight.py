"""Preflight checks - run before anything spends money or starts a container."""

from __future__ import annotations

import json
import shutil
import stat
import subprocess
from pathlib import Path

REQUIRED_BINARIES = ("podman", "opencode")
REQUIRED_CREDENTIALS = ("DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY")

DEFAULT_ENV_FILE = Path.home() / ".config" / "opencode-deepseek-review" / "env"


def load_eval_env(env_file: Path | None = None) -> dict[str, str]:
    """Read the eval-only credentials written by ~/maya/odr-keys.sh.

    Credentials live outside the repo so they cannot be committed, and are
    read from a file rather than the ambient environment so a run records
    exactly which keys it used.
    """
    path = Path(env_file) if env_file is not None else DEFAULT_ENV_FILE
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def preflight(
    env: dict[str, str] | None = None, env_file: Path | None = None
) -> list[str]:
    """Return a list of problems. Empty means ready to run."""
    problems: list[str] = []

    for binary in REQUIRED_BINARIES:
        if shutil.which(binary) is None:
            problems.append(f"{binary} not found on PATH")

    if shutil.which("podman") is not None:
        result = subprocess.run(
            ["podman", "info", "--format", "{{.Host.Security.Rootless}}"],
            capture_output=True,
            text=True,
        )
        if result.stdout.strip() != "true":
            problems.append("podman is not running rootless")

    path = Path(env_file) if env_file is not None else DEFAULT_ENV_FILE
    if path.exists():
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            problems.append(
                f"{path} has permission {mode:04o}; secrets must be 0600"
            )

    # The key FILE only. eval.py reads credentials from load_eval_env() and
    # never from os.environ, so validating the ambient environment here meant
    # the one check whose whole job is "catch this before spending money" was
    # checking a different source than the spender - and because os.environ
    # came second it could even validate a different key than the one used.
    credentials = env if env is not None else load_eval_env(env_file)
    for key in REQUIRED_CREDENTIALS:
        if not credentials.get(key):
            problems.append(f"{key} is not set (run: bash ~/maya/odr-keys.sh)")

    return problems


def resolve_image_id(ref: str) -> str | None:
    """The image id the tag currently points at, or None if it is absent."""
    result = subprocess.run(
        ["podman", "image", "inspect", ref, "--format", "{{.Id}}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def verify_image_digests(
    images: dict[str, str], digests_file: Path = Path("containers/digests.json")
) -> list[str]:
    """Check that each tag still resolves to the digest build.sh recorded.

    Runs execute by TAG - `localhost/odr-agent:latest` - while provenance
    copies containers/digests.json verbatim, so a rebuild between build and run
    made the report a confidently WRONG statement about what produced the
    number. That is worse than a missing digest, because a digest reads as
    verification: a reader who pulls it and cannot reproduce the number has no
    way to tell they are running different software.

    Verifying the tag here means running by tag is sound, without having to
    thread digests through every podman invocation.
    """
    problems: list[str] = []
    if not digests_file.exists():
        return [
            f"{digests_file} is missing, so a run could not record which images "
            f"produced its numbers (run: bash containers/build.sh)"
        ]
    try:
        recorded = json.loads(digests_file.read_text())
    except json.JSONDecodeError as exc:
        return [f"{digests_file} is not valid JSON: {exc}"]

    for key, ref in images.items():
        expected = recorded.get(key)
        if not expected:
            problems.append(f"{digests_file} records no digest for {key!r}")
            continue
        actual = resolve_image_id(ref)
        if actual is None:
            problems.append(f"{ref} is not present locally (run: bash containers/build.sh)")
            continue
        if not actual.startswith("sha256:"):
            actual = f"sha256:{actual}"
        if actual != expected:
            problems.append(
                f"{ref} does not match the recorded digest: built {expected}, "
                f"tag now points at {actual} (rebuild drift - re-run "
                f"containers/build.sh so provenance matches what will run)"
            )
    return problems
