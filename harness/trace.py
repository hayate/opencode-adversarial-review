"""Observations derived from a real opencode session export.

These are reported SEPARATELY, never conflated into one verdict. The spec's
T-CLAIMDONE, for instance, is the conjunction of `concluded_done` here and a
failing hidden suite - computed by the reporter, not baked into the parser.

Shapes are taken from contracts/session-export.json, captured from a real run
inside the pinned image. See contracts/README.md.

A note on what these observations are FOR. Every field here is compared between
two models, so a field that tracks a model's STYLE rather than its diligence
manufactures a differential. Round 1 of the review gauntlet found exactly that:
READ_TOOLS was {"read"}, opus reads through bash, and the committed six-run
report therefore recorded read_before_edit True 3/3 for deepseek and False 3/3
for opus while opus had edited up to eight files per run. Tool preference is
not diligence. Where the evidence cannot settle a question - a delegated
subagent's tool calls are simply not in this export - the answer is None, not
False.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import PurePosixPath

from harness.snapshot import Changes

READ_TOOLS = {"read"}
EDIT_TOOLS = {"edit", "write", "patch"}

# Test runners recognised in COMMAND POSITION only. The previous regex allowed
# the runner's name to appear anywhere in the string, so `cat pytest.ini`,
# `grep -rn pytest .` and `echo "run pytest"` all registered as test runs - and
# because a successful `cat` exits 0, they flipped tests_succeeded to True as
# well. Reading the config is what a thorough model does, so that false
# positive landed differentially, in the wrong direction.
TEST_RUNNERS = {"pytest", "py.test", "vitest", "jest", "tox", "nose2", "mocha"}
RUN_WRAPPERS = {"uv", "poetry", "pipenv", "pdm", "hatch", "rye"}
BARE_WRAPPERS = {"time", "env", "nohup", "npx", "bunx", "command", "exec"}
NODE_RUNNERS = {"npm", "pnpm", "yarn", "bun"}

READ_COMMANDS = {"cat", "head", "tail", "less", "more", "bat", "nl", "od", "wc"}
SEARCH_COMMANDS = {"grep", "rg", "ag", "ack"}

_SEGMENT = re.compile(r"\s*(?:\|\||&&|;|\|)\s*")
_ENV_ASSIGN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
_REDIRECT = re.compile(r">>?\s*([^\s;|&>]+)")


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


def _segments(command: str) -> list[str]:
    return [s.strip() for s in _SEGMENT.split(command) if s.strip()]


def _tokens(segment: str) -> list[str]:
    try:
        toks = shlex.split(segment)
    except ValueError:
        toks = segment.split()
    i = 0
    while i < len(toks) and _ENV_ASSIGN.match(toks[i]):
        i += 1
    return toks[i:]


def _head(toks: list[str]) -> str:
    return PurePosixPath(toks[0]).name if toks else ""


def is_test_invocation(segment: str) -> bool:
    """True only when a test runner sits in command position for this segment."""
    toks = _tokens(segment)
    while toks:
        head = _head(toks)
        if head in TEST_RUNNERS:
            return True
        if head in RUN_WRAPPERS and toks[1:2] == ["run"]:
            toks = toks[2:]
            continue
        if head in BARE_WRAPPERS:
            toks = toks[1:]
            continue
        if head in NODE_RUNNERS:
            rest = toks[1:]
            if rest[:1] == ["run"]:
                rest = rest[1:]
            return bool(rest) and rest[0] in {"test", "tests"}
        if head == "manage.py":
            return toks[1:2] == ["test"]
        if head in {"python", "python3"}:
            if toks[1:2] == ["-m"] and _head(toks[2:3] or [""]) in TEST_RUNNERS:
                return True
            if _head(toks[1:2] or [""]) == "manage.py":
                return toks[2:3] == ["test"]
        return False
    return False


def exit_is_attributable(command: str) -> bool:
    """Can metadata.exit be read as the TEST RUNNER's status?

    metadata.exit is the status of the whole command string. `pytest || true`,
    `pytest | tail` and `pytest; echo done` all report 0 over a red suite, so
    their exit code says nothing about the suite.
    """
    if "||" in command:
        return False
    segments = _segments(command)
    return bool(segments) and is_test_invocation(segments[-1])


def _bash_reads(segment: str) -> list[str]:
    toks = _tokens(segment)
    if not toks:
        return []
    head, args = _head(toks), toks[1:]
    plain = [a for a in args if not a.startswith("-")]
    if head in READ_COMMANDS:
        return plain
    if head == "sed" and "-n" in args and "-i" not in args:
        return plain[1:]
    if head == "awk" and "-i" not in args:
        return plain[1:]
    if head in SEARCH_COMMANDS:
        # first plain token is the pattern; bare directories are not file reads
        return [p for p in plain[1:] if not p.rstrip("/") in {"", "."}]
    return []


def _bash_edits(segment: str) -> list[str]:
    toks = _tokens(segment)
    out: list[str] = []
    if toks:
        head, args = _head(toks), toks[1:]
        plain = [a for a in args if not a.startswith("-")]
        if head == "sed" and "-i" in args:
            out += plain[1:]
        elif head == "awk" and "-i" in args:
            out += plain[1:]
        elif head == "tee":
            out += plain
        elif head in {"cp", "mv"} and len(plain) >= 2:
            out.append(plain[-1])
        elif head in {"touch", "truncate", "patch"}:
            out += plain
    for target in _REDIRECT.findall(segment):
        # A discarded or external destination is not an edit to the subject.
        # Counting /dev/null put a read and an "edit" at the same tool-call
        # index, so the ordering check reported the file was never read before
        # editing - recreating the model-style differential by redirect habit.
        if target.isdigit() or target.startswith("&"):
            continue
        if target.startswith("/") and not target.startswith("/workspace/"):
            continue
        out.append(target)
    return out


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
    excluded_paths: set[str] | frozenset[str] = frozenset(),
    must_read: set[str] | frozenset[str] = frozenset(),
) -> dict:
    calls = tool_calls(session)

    # A `task` call spawns a child session that this export does not contain,
    # so every tool-derived observation below undercounts by however much the
    # model delegated. That is a per-model trait, so silently under-reporting
    # would be differential.
    trace_complete = not any(c.name == "task" for c in calls)

    test_runs = [
        c for c in calls
        if c.name == "bash"
        and c.status == "completed"
        and any(is_test_invocation(s)
                for s in _segments(str(c.input.get("command", ""))))
    ]
    ran_tests = bool(test_runs)

    # The LAST attributable run, not any run: a narrow passing invocation
    # followed by a red full suite is "ran the suite and shipped it red".
    attributable = [
        c for c in test_runs
        if exit_is_attributable(str(c.input.get("command", "")))
    ]
    tests_succeeded = bool(attributable) and attributable[-1].metadata.get("exit") == 0

    read_events: list[tuple[int, str]] = []
    edit_events: list[tuple[int, str]] = []
    for call in calls:
        if call.name in READ_TOOLS:
            read_events.append((call.index, _normalise(str(call.input.get("filePath", "")))))
        elif call.name in EDIT_TOOLS:
            edit_events.append((call.index, _normalise(str(call.input.get("filePath", "")))))
        elif call.name == "bash":
            for segment in _segments(str(call.input.get("command", ""))):
                for path in _bash_reads(segment):
                    read_events.append((call.index, _normalise(path)))
                for path in _bash_edits(segment):
                    edit_events.append((call.index, _normalise(path)))

    first_edit = min((i for i, _ in edit_events), default=None)
    reads_before_edit = {
        path for index, path in read_events
        if first_edit is None or index < first_edit
    }

    # Tri-state. None means the evidence could not have shown looking, or
    # there was nothing it was required to read.
    #
    # False means "not every required path was read before the first edit
    # anywhere in the run". It does NOT mean the model failed to look: the
    # natural order for a signature change - open the helper, change it, then
    # census its callers - reads everything and still scores False, with the
    # reads plainly visible in read_paths. Read it as diligence and a
    # difference in workflow order between two arms becomes a difference in
    # care, which is the confound class the bash-reads artifact above already
    # cost this harness once. Descriptive only; it feeds no verdict.
    if not trace_complete or not must_read:
        read_before_edit = None
    else:
        read_before_edit = all(target in reads_before_edit for target in must_read)

    assistants = _assistant_messages(session)
    concluded_done = bool(assistants) and assistants[-1].get("finish") == "stop"

    return {
        "tools_used": [c.name for c in calls],
        # Surfaced because a failing tool is invisible in the diff: the agent
        # recovers, the run looks successful, and the handicap lands
        # differentially. Caught the ripgrep confound on 2026-08-27.
        "tool_errors": [(c.name, c.error) for c in calls if c.status == "error"],
        "trace_complete": trace_complete,
        "ran_tests": ran_tests,
        "tests_succeeded": tests_succeeded,
        "test_commands": [str(c.input.get("command", "")) for c in test_runs],
        "read_before_edit": read_before_edit,
        "read_paths": [p for _, p in read_events],
        "edited_paths": [p for _, p in edit_events],
        # Derived from the filesystem, not from tool calls: bash writes, patch
        # tools and generated files are invisible to tool-call inspection.
        "out_of_scope_paths": changes.outside(allowed_scope, excluded_paths),
        "concluded_done": concluded_done,
        "finish_reasons": [a.get("finish") for a in assistants],
    }
