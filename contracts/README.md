# Recorded opencode contracts

Real output from opencode 1.18.23, captured **inside the pinned agent image**
by `capture.sh`. Parsers are written and tested against these files rather than
against an assumed schema - plan revision 1 guessed, and half its bugs came
from that.

Re-record with `bash contracts/capture.sh` after any opencode version bump.
Costs a few cents on `deepseek-v4-flash`.

## What the real shapes are

| Question | Answer |
|---|---|
| Is `run --format json` one object or a stream? | **NDJSON**, one event per line. `json.loads(stdout)` raises. |
| Event types seen | `step_start`, `step_finish`, `tool_use`, `text` |
| Where is the session id? | Top level `sessionID` on every event |
| Where is a tool call? | `event.part` with `type: "tool"`, `tool`, `callID`, `state.status`, `state.input` |
| Tool statuses | `completed`, `error` (also `running`, `pending`) |
| Export top-level keys | `info`, `messages` |
| **Where is `modelID`?** | **`messages[].info.modelID`** - NOT `messages[].modelID`, which is always absent |

## Files

- `run-events.ndjson` - the event stream from one real run
- `session-export.json` - `opencode export` of that session
- `debug-config-sterile.json` - resolved config with isolation ON
- `debug-config-seeded.json` - **positive control**, a synthetic canary provider
  injected via `OPENCODE_CONFIG_CONTENT` and observed. Without it, a sterile
  assertion passing because the capture broke looks identical to one passing
  because isolation works.
- `debug-skill.txt`, `debug-agent-build.txt` - what actually loads

The positive control is deliberately synthetic. Capturing the operator's real
resolved config would publish their provider settings to a public repo.

## Verified isolation

With the switches set, the sterile config carries `agent: {}`, `plugin: []`, no
`provider`, and `compaction.auto: false`. `superpowers` appears zero times in
the skill listing.

Note: the resolved config still *lists* declared plugins even when they are not
loaded, so isolation must be checked by what loaded - providers, `skills.paths`,
agents - never by the `plugin` key.
