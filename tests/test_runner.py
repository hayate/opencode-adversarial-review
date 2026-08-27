"""Runner unit tests. The paid path is exercised by the end-to-end run."""

import json
from pathlib import Path

import pytest

from harness.runner import (
    ARMS,
    STERILE_ENV,
    ModelMismatch,
    assert_sterile,
    build_canonical_config,
    classify_run,
    count_turns,
    effective_permissions,
    verify_model_id,
)

EXPORT = json.loads(Path("contracts/session-export.json").read_text())

SPEC_SWITCHES = [
    "OPENCODE_DISABLE_PROJECT_CONFIG",
    "OPENCODE_DISABLE_CLAUDE_CODE",
    "OPENCODE_DISABLE_CLAUDE_CODE_PROMPT",
    "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS",
    "OPENCODE_DISABLE_EXTERNAL_SKILLS",
    "OPENCODE_DISABLE_DEFAULT_PLUGINS",
    "OPENCODE_DISABLE_AUTOCOMPACT",
    "OPENCODE_DISABLE_MODELS_FETCH",
    "OPENCODE_DISABLE_AUTOUPDATE",
    "OPENCODE_DISABLE_SHARE",
]


def test_every_spec_mandated_switch_is_set():
    missing = [k for k in SPEC_SWITCHES if STERILE_ENV.get(k) != "1"]
    assert missing == [], f"spec section 6 switches not set: {missing}"


def test_home_is_isolated_and_outside_the_workspace():
    """Spec 6.0: an isolated HOME is what makes the config sterile, and a
    read-only root independently requires one to exist."""
    assert STERILE_ENV["HOME"].startswith("/tmp/")
    assert not STERILE_ENV["HOME"].startswith("/workspace")


def test_model_id_is_read_from_message_info():
    """Pinned by contract: modelID lives at messages[].info.modelID. Reading
    messages[].modelID finds nothing and fails every run."""
    assert verify_model_id(EXPORT, expected="deepseek-v4-flash") is True


def test_model_mismatch_raises():
    with pytest.raises(ModelMismatch):
        verify_model_id(EXPORT, expected="deepseek-v4-pro")


def test_export_without_any_model_id_raises():
    with pytest.raises(ModelMismatch):
        verify_model_id({"messages": []}, expected="anything")


def test_canonical_config_pins_one_provider_and_no_plugins():
    config = json.loads(build_canonical_config(ARMS["deepseek"]))
    assert config["enabled_providers"] == ["deepseek"]
    assert config["plugin"] == []
    assert config["model"] == "deepseek/deepseek-v4-pro"


def test_count_turns_matches_the_assistant_turns_in_the_export():
    """Cross-check the two contract files against each other rather than a
    magic number: a hardcoded count silently rots the moment contracts are
    re-captured, which is exactly what happened on 2026-08-27."""
    events = Path("contracts/run-events.ndjson").read_text()
    assistant_turns = sum(
        1 for m in EXPORT["messages"] if (m.get("info") or {}).get("role") == "assistant"
    )
    assert count_turns(events) == assistant_turns
    assert assistant_turns > 0


def test_count_turns_tolerates_partial_lines():
    """The host tails this file while it is being written."""
    assert count_turns('{"type":"step_start"}\n{"type":"step_st') == 1


def test_agent_image_is_sterile():
    """Deterministic isolation check with a positive control, inside the real
    image. Spends no tokens."""
    assert_sterile("localhost/odr-agent:latest")


def test_tool_permissions_are_granted():
    """No human is in the container to approve a permission prompt. Without
    this the agent hits a wall that reads as model behaviour and penalises
    models that ask permission more often."""
    import json as _json

    permission = _json.loads(STERILE_ENV["OPENCODE_PERMISSION"])
    assert permission["bash"] == "allow"
    assert permission["edit"] == "allow"


# --- Round 1 gauntlet: a provider abort must not be graded as a model failure ---


def test_a_nonzero_opencode_exit_is_invalid_not_completed():
    """`opencode run` exiting non-zero means the run did not finish normally -
    a 429, a 5xx, an expired key, a crash mid-turn. The session export still
    exists and still carries the right modelID, so without this the half-edited
    tree is graded and the failure lands in the vendor's numerator. Provider
    error rates are per-vendor by definition, so this is arm-correlated."""
    status, error = classify_run(
        capped=False, turns=8, opencode_exit=1,
        session=EXPORT, expected_model="deepseek-v4-pro",
    )
    assert status == "invalid"
    assert "exited 1" in (error or "")


def test_a_clean_exit_with_a_verified_session_completes():
    status, error = classify_run(
        capped=False, turns=8, opencode_exit=0,
        session=EXPORT, expected_model=EXPORT["messages"][1]["info"]["modelID"],
    )
    assert status == "completed", error


def test_a_missing_exit_code_does_not_invalidate_a_good_run():
    """Absent is not non-zero: an older report or a container that died before
    writing the file must not retroactively invalidate a graded run."""
    status, _ = classify_run(
        capped=True, turns=99, opencode_exit=None,
        session=EXPORT, expected_model=EXPORT["messages"][1]["info"]["modelID"],
    )
    assert status == "capped"


def test_capping_takes_precedence_over_the_exit_code():
    status, _ = classify_run(
        capped=True, turns=99, opencode_exit=137,
        session=EXPORT, expected_model=EXPORT["messages"][1]["info"]["modelID"],
    )
    assert status == "capped"


def test_no_permission_is_left_asking_inside_the_container():
    """Confound #2 was only half fixed. OPENCODE_PERMISSION APPENDS rather than
    replaces, so `doom_loop: ask` and `external_directory: ask` survived the
    three allow entries - with no human in the container to answer either.
    doom_loop fires on an agent that repeats a tool call, which is what a
    struggling model does, so the handicap is arm-correlated."""
    effective = effective_permissions("localhost/odr-agent:latest")
    asking = {k: v for k, v in effective.items() if v == "ask"}
    assert asking == {}, f"permissions still gated with no human to answer: {asking}"
