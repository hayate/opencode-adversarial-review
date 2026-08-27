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


# --- Round 1 gauntlet: the observations must not measure tool preference ---
#
# READ_TOOLS was {"read"}, so an agent that reads via bash registered as never
# having read. In the committed six-run report that produced read_before_edit
# True 3/3 for deepseek and False 3/3 for opus, while opus had edited up to
# eight files - a perfect split manufactured entirely by the harness, on the
# exact axis H-CALLSITE claims to measure.


def _tool(name, *, input=None, exit=None, status="completed"):
    state = {"status": status, "input": input or {}}
    if exit is not None:
        state["metadata"] = {"exit": exit}
    return {"type": "tool", "tool": name, "state": state}


def _session(*parts, finish="stop"):
    return {"messages": [{"info": {"role": "assistant", "finish": finish},
                          "parts": list(parts)}]}


def _bash(command, exit=0, status="completed"):
    return _tool("bash", input={"command": command}, exit=exit, status=status)


@pytest.mark.parametrize("command", [
    "cat pytest.ini",
    "grep -rn pytest .",
    'echo "now run pytest"',
    "which pytest",
    "sed -i 's/x/y/' pytest.ini",
    "pip show pytest",
    "git log --grep pytest",
])
def test_merely_mentioning_a_runner_is_not_a_test_run(command):
    """Reading the config is what a THOROUGH model does. Crediting it with a
    test run lands differentially, in the wrong direction."""
    obs = observations(_session(_bash(command)), changes=NO_CHANGES,
                       allowed_scope=set())
    assert obs["ran_tests"] is False, command
    assert obs["tests_succeeded"] is False, command


@pytest.mark.parametrize("command", [
    "pytest -q",
    "python -m pytest",
    "uv run pytest tests/",
    "./manage.py test",
    "python manage.py test notifications",
    "npm test",
    "npm run test",
    "cd /workspace && pytest",
])
def test_real_invocations_are_recognised(command):
    obs = observations(_session(_bash(command)), changes=NO_CHANGES,
                       allowed_scope=set())
    assert obs["ran_tests"] is True, command


def test_tests_succeeded_reflects_the_last_run_not_any_run():
    """A narrow passing run followed by a red full suite is 'ran the suite and
    shipped it red' - a headline hazard class, not a success."""
    obs = observations(
        _session(_bash("pytest tests/test_views.py", exit=0),
                 _bash("pytest", exit=1)),
        changes=NO_CHANGES, allowed_scope=set(),
    )
    assert obs["ran_tests"] is True
    assert obs["tests_succeeded"] is False


@pytest.mark.parametrize("command", ["pytest || true", "pytest 2>&1 | tail -20",
                                     "pytest; echo done"])
def test_exit_code_is_not_attributed_through_a_shell_operator(command):
    """metadata.exit is the status of the whole command string, so these report
    0 over a red suite."""
    obs = observations(_session(_bash(command, exit=0)), changes=NO_CHANGES,
                       allowed_scope=set())
    assert obs["ran_tests"] is True, command
    assert obs["tests_succeeded"] is False, command


def test_bash_mediated_reads_are_counted_as_reads():
    obs = observations(
        _session(_bash("cat notifications/views.py"),
                 _bash("sed -n '1,40p' notifications/serializers.py")),
        changes=NO_CHANGES, allowed_scope=set(),
        must_read={"notifications/views.py", "notifications/serializers.py"},
    )
    assert set(obs["read_paths"]) >= {"notifications/views.py",
                                      "notifications/serializers.py"}
    assert obs["read_before_edit"] is True


def test_bash_mediated_edits_establish_ordering():
    """An agent editing via `sed -i` left first_edit None, which made every
    read count as 'before edit' - including reads after the mutation."""
    obs = observations(
        _session(_bash("sed -i 's/a/b/' notifications/views.py"),
                 _bash("cat notifications/views.py")),
        changes=NO_CHANGES, allowed_scope=set(),
        must_read={"notifications/views.py"},
    )
    assert obs["read_before_edit"] is False


def test_delegated_work_makes_the_trace_incomplete_rather_than_false():
    """A `task` call spawns a child session that is not in this export, so its
    reads are unobservable. Reporting False would be a claim the evidence does
    not support."""
    obs = observations(
        _session(_tool("task", input={"description": "find call sites"}),
                 _tool("edit", input={"filePath": "/workspace/notifications/views.py"})),
        changes=NO_CHANGES, allowed_scope=set(),
        must_read={"notifications/views.py"},
    )
    assert obs["trace_complete"] is False
    assert obs["read_before_edit"] is None


def test_must_read_empty_does_not_vacuously_claim_diligence():
    obs = observations(_session(_bash("cat x.py")), changes=NO_CHANGES,
                       allowed_scope=set(), must_read=set())
    assert obs["read_before_edit"] is None
