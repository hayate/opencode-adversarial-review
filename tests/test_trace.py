"""Trace observations, tested against the REAL recorded session export.

These catch what the diff cannot: whether the model ran anything, whether it
looked before it edited, and whether the harness itself misbehaved.
"""

import json
from pathlib import Path

import pytest

from harness.snapshot import Changes
from harness.trace import observations

SESSION = json.loads(Path("contracts/session-export.json").read_text())
NO_CHANGES = Changes(set(), set(), set())


def test_extracts_tool_calls_in_order():
    obs = observations(SESSION, changes=NO_CHANGES, allowed_scope=set())
    assert obs["tools_used"] == ["read", "edit", "bash"]


def test_ran_tests_distinguishes_invocation_from_success():
    """`ran_tests` means a test command was executed. `tests_succeeded` means
    it exited zero. A model that runs the suite and ignores a red result is a
    different failure from one that never ran it."""
    obs = observations(SESSION, changes=NO_CHANGES, allowed_scope=set())
    assert isinstance(obs["ran_tests"], bool)
    assert isinstance(obs["tests_succeeded"], bool)


def test_ran_tests_is_false_when_only_a_non_test_command_ran():
    """The captured session ran `python -c import calc`, not a test runner.
    Matching on command text alone would call that a test run."""
    obs = observations(SESSION, changes=NO_CHANGES, allowed_scope=set())
    assert obs["ran_tests"] is False


def test_concluded_done_reads_the_finish_reason_not_the_prose():
    """finish == 'stop' on the last assistant turn means the model chose to
    stop. Mechanical, unlike parsing the final message for confidence."""
    obs = observations(SESSION, changes=NO_CHANGES, allowed_scope=set())
    assert obs["concluded_done"] is True


def test_tool_errors_are_surfaced():
    """The observation that caught the ripgrep confound on 2026-08-27: glob
    failed because tar could not chown under rootless podman, the agent
    recovered by reading files directly, and the run still looked successful.
    Only the per-tool status showed it."""
    obs = observations(SESSION, changes=NO_CHANGES, allowed_scope=set())
    assert obs["tool_errors"] == []


def test_tool_errors_are_detected_when_present():
    broken = {
        "messages": [
            {
                "info": {"role": "assistant", "finish": "stop"},
                "parts": [
                    {
                        "type": "tool",
                        "tool": "glob",
                        "state": {"status": "error", "input": {}, "error": "tar: cannot chown"},
                    }
                ],
            }
        ]
    }
    obs = observations(broken, changes=NO_CHANGES, allowed_scope=set())
    assert obs["tool_errors"] == [("glob", "tar: cannot chown")]


def test_read_before_edit_is_true_when_the_path_was_read_first():
    obs = observations(
        SESSION, changes=NO_CHANGES, allowed_scope=set(),
        must_read={"calc.py"},
    )
    assert obs["read_before_edit"] is True


def test_read_before_edit_is_false_for_a_path_never_opened():
    obs = observations(
        SESSION, changes=NO_CHANGES, allowed_scope=set(),
        must_read={"notifications/management/commands/send_digest.py"},
    )
    assert obs["read_before_edit"] is False


def test_out_of_scope_comes_from_real_changes_not_tool_calls():
    changes = Changes(added={"evil.py"}, modified=set(), deleted=set())
    obs = observations(SESSION, changes=changes, allowed_scope={"calc.py"})
    assert obs["out_of_scope_paths"] == {"evil.py"}


def test_in_scope_change_is_not_flagged():
    changes = Changes(added=set(), modified={"calc.py"}, deleted=set())
    obs = observations(SESSION, changes=changes, allowed_scope={"calc.py"})
    assert obs["out_of_scope_paths"] == set()
