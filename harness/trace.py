"""Observations derived from a real opencode session export.

These are reported SEPARATELY, never conflated into one verdict. The spec's
T-CLAIMDONE, for instance, is the conjunction of `concluded_done` here and a
failing hidden suite - computed by the reporter, not baked into the parser.

Shapes are taken from contracts/session-export.json, captured from a real run
inside the pinned image. See contracts/README.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from harness.snapshot import Changes

TEST_COMMAND = re.compile(
    r"(?:^|[;&|]\s*)(?:\S*\s+)*?"
    r"(?:pytest|py\.test|manage\.py\s+test|npm\s+(?:run\s+)?test|yarn\s+test|vitest|jest|tox)"
    r"\b"
)

READ_TOOLS = {"read"}
EDIT_TOOLS = {"edit", "write", "patch"}


@dataclass(frozen=True)
class ToolCall:
    index: int
    name: str
    input: dict
    status: str
    error: str | None
    metadata: dict


def tool_calls(session: dict) -> list[ToolCall]:
    calls: list[ToolCall] = []
    index = 0
    for message in session.get("messages", []):
        for part in message.get("parts", []):
            if part.get("type") != "tool":
                continue
            state = part.get("state") or {}
            calls.append(
                ToolCall(
                    index=index,
                    name=part.get("tool") or "",
                    input=state.get("input") or {},
                    status=state.get("status") or "",
                    error=state.get("error"),
                    metadata=state.get("metadata") or {},
                )
            )
            index += 1
    return calls


def _normalise(path: str) -> str:
    """Container paths are absolute under /workspace; scope is relative."""
    if not path:
        return ""
    pure = PurePosixPath(path)
    try:
        return pure.relative_to("/workspace").as_posix()
    except ValueError:
        return pure.as_posix().lstrip("/")


def _assistant_messages(session: dict) -> list[dict]:
    return [
        m.get("info", {})
        for m in session.get("messages", [])
        if (m.get("info") or {}).get("role") == "assistant"
    ]


def observations(
    session: dict,
    *,
    changes: Changes,
    allowed_scope: set[str],
    must_read: set[str] | frozenset[str] = frozenset(),
) -> dict:
    calls = tool_calls(session)

    test_runs = [
        c
        for c in calls
        if c.name == "bash"
        and TEST_COMMAND.search(str(c.input.get("command", "")))
        and c.status == "completed"
    ]
    ran_tests = bool(test_runs)
    tests_succeeded = any(c.metadata.get("exit") == 0 for c in test_runs)

    first_edit = next(
        (c.index for c in calls if c.name in EDIT_TOOLS), None
    )
    reads_before_edit = {
        _normalise(str(c.input.get("filePath", "")))
        for c in calls
        if c.name in READ_TOOLS
        and (first_edit is None or c.index < first_edit)
    }
    read_before_edit = all(target in reads_before_edit for target in must_read)

    assistants = _assistant_messages(session)
    concluded_done = bool(assistants) and assistants[-1].get("finish") == "stop"

    return {
        "tools_used": [c.name for c in calls],
        # Surfaced because a failing tool is invisible in the diff: the agent
        # recovers, the run looks successful, and the handicap lands
        # differentially. Caught the ripgrep confound on 2026-08-27.
        "tool_errors": [(c.name, c.error) for c in calls if c.status == "error"],
        "ran_tests": ran_tests,
        "tests_succeeded": tests_succeeded,
        "read_before_edit": read_before_edit,
        "read_paths": [
            _normalise(str(c.input.get("filePath", "")))
            for c in calls
            if c.name in READ_TOOLS
        ],
        "edited_paths": [
            _normalise(str(c.input.get("filePath", "")))
            for c in calls
            if c.name in EDIT_TOOLS
        ],
        # Derived from the filesystem, not from tool calls: bash writes, patch
        # tools and generated files are invisible to tool-call inspection.
        "out_of_scope_paths": changes.outside(allowed_scope),
        "concluded_done": concluded_done,
        "finish_reasons": [a.get("finish") for a in assistants],
    }
