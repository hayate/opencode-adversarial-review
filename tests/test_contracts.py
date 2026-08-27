"""Contract tests, pinned against REAL recorded opencode output.

Plan revision 1 wrote parsers against an imagined schema and half the bugs came
from that. These fixtures are captured by contracts/capture.sh from inside the
pinned agent image. If opencode changes shape, these fail here rather than
somewhere confusing after credentials have been spent.
"""

import json
from pathlib import Path

C = Path("contracts")


def _events() -> list[dict]:
    events = []
    for line in (C / "run-events.ndjson").read_text(errors="replace").splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events


def test_run_output_is_ndjson_not_a_single_object():
    """--format json emits one event per line. json.loads on the whole stream
    raises - which is exactly what revision 1 of the runner did."""
    text = (C / "run-events.ndjson").read_text(errors="replace")
    assert len(text.strip().splitlines()) > 1
    assert len(_events()) > 1


def test_events_carry_a_type_and_session_id():
    events = _events()
    assert {e["type"] for e in events} <= {
        "step_start", "step_finish", "tool_use", "text", "error", "reasoning"
    }
    assert all(e.get("sessionID") for e in events)


def test_tool_events_expose_tool_name_and_status():
    tools = [e for e in _events() if e["type"] == "tool_use"]
    assert tools, "no tool_use events captured"
    for event in tools:
        part = event["part"]
        assert part["type"] == "tool"
        assert isinstance(part["tool"], str)
        assert part["state"]["status"] in {"completed", "error", "running", "pending"}


def test_export_has_info_and_messages():
    export = json.loads((C / "session-export.json").read_text())
    assert set(export) >= {"info", "messages"}
    assert export["messages"]


def test_model_id_lives_under_message_info_not_on_the_message():
    """Pins the exact location. Revision 1 read messages[].modelID, which is
    always absent - every run would have failed model verification."""
    export = json.loads((C / "session-export.json").read_text())
    assistants = [
        m["info"] for m in export["messages"]
        if m.get("info", {}).get("role") == "assistant"
    ]
    assert assistants, "no assistant messages in the export"
    assert all(a.get("modelID") for a in assistants)
    assert all(a.get("providerID") for a in assistants)
    # And confirm the naive path really is empty, so this test has teeth.
    assert not any(m.get("modelID") for m in export["messages"])


def test_sterile_config_has_no_host_state():
    sterile = json.loads((C / "debug-config-sterile.json").read_text())
    assert not sterile.get("provider"), "host providers leaked into a sterile run"
    assert sterile.get("plugin") == [], "plugins leaked into a sterile run"
    assert sterile.get("agent") == {}, "agents leaked into a sterile run"


def test_autocompact_is_actually_disabled():
    """Divergent compaction between arms is an invisible confound."""
    sterile = json.loads((C / "debug-config-sterile.json").read_text())
    assert sterile["compaction"]["auto"] is False


def test_positive_control_proves_the_sterile_assertions_have_teeth():
    """Without this, a sterile assertion passing because the capture broke is
    indistinguishable from one passing because isolation works."""
    seeded = json.loads((C / "debug-config-seeded.json").read_text())
    assert "canary-provider" in (seeded.get("provider") or {})
