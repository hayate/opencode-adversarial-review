# Recorded opencode plugin contracts

Real output from opencode 1.18.23 (`~/.opencode/bin/opencode`, not the
`opencode` on PATH - that name is shadowed by an unrelated zsh function on
this machine), captured by the throwaway probes in this directory. The
published opencode plugin docs are wrong for this version on three counts,
so the plugin code in this repo is written against what was actually
observed here, not against the docs. Re-run the probes after any opencode
version bump.

Captured 2026-08-28. See the capture log below for the exact command and
verbatim output behind each answer; every command shown was run on that
date, and most were re-run a second time to confirm they still reproduce
before this file was written.

## What the real behaviour is

| Question | Answer |
|---|---|
| Does the plugin `config` hook fire? | Yes. Confirmed via `probe-injection.js`. |
| Do agent + command keys injected in the `config` hook land in the resolved config? | Yes. `debug config` output contains both `"probe-agent"` and `"probe-cmd"`. |
| What does `cfg.agent` look like *before* the hook mutates it? | Already populated with built-in/global agents (`build, plan, general, scout, explore, title, summary, compaction`, plus this machine's other installed plugins' agents). `cfg.command` is empty - markdown-file-defined commands are not visible to the hook. |
| How do plugin options (the `[path, options]` tuple form in `opencode.json`) arrive? | As the second argument to the exported plugin function, e.g. `options={"model":"anthropic/claude-opus-5"}`. A directory-loaded plugin (no tuple, no `plugin` config entry) gets `options=null`. |
| What syntax does a command template use for arguments? | **`$ARGUMENTS`**, exactly as expected. Confirmed via `probe-arguments.js`: template `echo BEGIN $ARGUMENTS END` invoked with `hello world` produced the literal prompt `echo BEGIN "hello world" END` (opencode wraps a multi-word argument string in double quotes when substituting). |
| How do you actually invoke a plugin-injected command from the CLI? | **`opencode run --command <name> <args...>`.** Typing `/name args` as the plain message to `opencode run "..."` does **not** invoke the command - it is sent as literal chat text to the default agent, which may or may not notice it looks like a command (observed both a plausible-looking echo and a flat "I don't recognize that command" from the same literal input on different runs). This is a real footgun: the intuitive one-shot invocation does not work. |
| What does a user see when a plugin FAILS TO LOAD? | **Nothing.** `opencode debug config` exits 0 with empty stderr and the plugin's agents and commands simply absent. The reason is reachable only via `opencode debug config --print-logs --log-level ERROR`, which prints `level=ERROR message="failed to load plugin" path=... error="<the thrown message>"`. Captured 2026-08-28 with a deliberately invalid `model` option. |
| What does a user see when the `config` hook THROWS? | **Nothing, and the whole hook is rolled back.** Same exit 0 / empty stderr. Verified twice: a CollisionError (thrown before any mutation) and a fingerprint failure (thrown *after* injectInto had already mutated the config). In the second case NEITHER agent nor command survived - opencode discards the entire hook's mutations on a throw. That is the safe direction: a failed install is never a half-install. |
| Can a plugin write to the user's terminal from inside a hook? | **No.** Both `console.error(...)` and a raw `process.stderr.write(...)` immediately before a throw in the `config` hook produced zero bytes on stderr and appeared nowhere in stdout. A plugin has no channel to the user at config time. |
| Does opencode's config schema accept a command with no `agent` and `subtask: false`? | **Yes.** Such a command lands in the resolved config intact, with `agent: null` and its `description` and `template` preserved. This is what makes a visible diagnostic possible at all: it is the one thing a plugin can leave behind that a user will actually see. |
| Does `chat.params` fire for a plugin-INJECTED subagent? | **Yes**, once per LLM request, carrying `agent` as that subagent's own name. Captured 2026-08-28 via `probe-chat-params.js`: `CHAT.PARAMS agent="probe-reviewer" model.providerID="deepseek" model.id="deepseek-v4-flash"`. Input keys are exactly `sessionID, agent, model, provider, message`. It also fires for `title`, `build` and every other agent in the session, so a check here MUST test agent membership or it breaks the user's whole install. |
| How is the serving model spelled? | `model.providerID` plus **`model.id`** on `chat.params`. Note `chat.message` spells the same thing **`model.modelID`** - two different field names for one value, in this one version. Both observed in the same run. Code that reads only one will break on the other. |
| Does throwing from `chat.params` actually stop the review? | **Yes, and loudly.** With `PROBE_THROW=1` the subagent fired `chat.params` once, threw, and produced no further requests (against six requests in the un-thrown run). The calling session's `task` tool part came back `"status":"error"`, `"output":null`, `"error":"Tool execution failed: Subagent failed (task_id: ses_...): PROBE-GUARD-TRIPPED: refusing this review"`, and the parent model relayed that message to the user. It is NOT swallowed, and NOT delivered as an empty-but-successful result. |
| Can a subagent be invoked directly with `opencode run --agent <name>`? | **No.** `opencode run --agent probe-reviewer "say OK"` prints `! agent "probe-reviewer" is a subagent, not a primary agent. Falling back to default agent` and runs `build` instead. Independent corroboration of ruling R18: `mode: "subagent"` is enforced by the platform, not merely advertised. |
| Does `--command` work when the project `opencode.json` overrides `provider`/`enabled_providers`? | **Not observed to.** Three runs with a project-level `provider` override hung past 90-150s with only `LOADED` and `CONFIG HOOK FIRED` in the log - no `command.execute.before`, no `chat.message`, no `chat.params`. The same probe with a minimal `{"$schema":...}` config ran the command to completion in seconds. Cause not isolated; recorded so the next probe does not lose an hour to it. Use a minimal project config when probing the command path. |
| What does the calling session receive when a subagent's provider call fails mid-stream? | **Undetermined.** See `probe-interrupt.md`. The brief's suggested cheap method (invalid `ANTHROPIC_API_KEY`) is silently ignored - opencode's stored `auth.json` credentials win over the env var, so the call succeeds for real (billed) instead of failing. Every method that did produce a genuinely broken provider config (bad `baseURL`, bad `apiKey` via the `config` hook, invalid model id) caused the CLI to hang for 60-110+ seconds with zero output, rather than raising a fast error. No run in this probe surfaced a clean error, a truncated message, or confirmed silence within the cost/time this task could spend. |

## Capture log

Date: 2026-08-28. All commands run from the repo root unless shown with a
`cd` into a scratch directory. Most commands in this log were re-run on the
capture date to confirm they still produce the output shown, immediately
before this file was written - Step 4's negative-result command is the one
exception, noted at the point it appears below.

### Step 1: write the probe

No command to run - `probe-injection.js` is the artifact itself, written to
`plugin/contracts/probe-injection.js`. See the file for its content.

### Step 2: does the config hook fire, and does agent + command injection land

```
P=$(mktemp -d); mkdir -p "$P/.opencode/plugin"
cp plugin/contracts/probe-injection.js "$P/.opencode/plugin/"
echo '{"$schema":"https://opencode.ai/config.json"}' > "$P/opencode.json"
cd "$P" && PROBE_LOG=$P/probe.log ~/.opencode/bin/opencode debug config > cfg.json 2>err.txt
cat "$P/probe.log"
grep -o '"probe-agent"' cfg.json | head -1
grep -o '"probe-cmd"' cfg.json | head -1
```

Observed output:

```
LOADED options=null
CONFIG HOOK FIRED
EXISTING agent keys=build,plan,general,scout,explore,title,summary,compaction,opencode-memory-recall,opencode-memory-extract
EXISTING command keys=
"probe-agent"
"probe-cmd"
```

`err.txt` was empty; exit code 0.

### Step 3: does the plugin options tuple arrive

```
P=$(mktemp -d); mkdir -p "$P/ext"
cp plugin/contracts/probe-injection.js "$P/ext/"
cat > "$P/opencode.json" <<'JSON'
{"$schema":"https://opencode.ai/config.json",
 "plugin":[["./ext/probe-injection.js",{"model":"anthropic/claude-opus-5"}]]}
JSON
cd "$P" && PROBE_LOG=$P/probe.log ~/.opencode/bin/opencode debug config > cfg.json 2>err.txt
cat "$P/probe.log"
```

Observed output:

```
LOADED options={"model":"anthropic/claude-opus-5"}
CONFIG HOOK FIRED
EXISTING agent keys=build,plan,general,scout,explore,title,summary,compaction,opencode-memory-recall,opencode-memory-extract
EXISTING command keys=
```

`err.txt` was empty; exit code 0.

### Step 4: what syntax does a command template use for arguments

The brief's literal prescribed command does **not** work - typing `/name
args` as the plain message to `opencode run` sends it as literal chat text
instead of dispatching the command definition:

```
P=$(mktemp -d); mkdir -p "$P/.opencode/plugin"
cp plugin/contracts/probe-arguments.js "$P/.opencode/plugin/"
echo '{"$schema":"https://opencode.ai/config.json"}' > "$P/opencode.json"
cd "$P" && PROBE_LOG=$P/probe.log ~/.opencode/bin/opencode run "/probe-cmd hello world" --format json
```

Observed output (relevant events; captured 2026-08-28 during this task, not
re-run again for this fix since it is a documented negative result and the
working form below was reconfirmed instead):

```
{"type":"text", ... "text":"I don't recognize a `/probe-cmd` command. Did you mean to run something specific, or ask about a particular tool/skill?" ...}
```

The exported session transcript showed the user message text arrived as the
literal string `"/probe-cmd hello world"` (quotes included), sent to the
default `build` agent - the command was never dispatched.

The working invocation is `opencode run --command <name> <args...>`:

```
P=$(mktemp -d); mkdir -p "$P/.opencode/plugin"
cp plugin/contracts/probe-arguments.js "$P/.opencode/plugin/"
echo '{"$schema":"https://opencode.ai/config.json"}' > "$P/opencode.json"
cd "$P" && PROBE_LOG=$P/probe.log ~/.opencode/bin/opencode run --command probe-cmd "hello world" --format json
```

Observed output (relevant event):

```
{"type":"tool_use", ... "part":{... "tool":"task","state":{"status":"completed",
  "input":{"prompt":"echo BEGIN \"hello world\" END","description":"",
           "subagent_type":"probe-agent","command":"probe-cmd"},
  "metadata":{... "model":{"providerID":"deepseek","modelID":"deepseek-v4-flash"} ...},
  "output":"<task ...><task_result>\nBEGIN hello world END\n</task_result></task>" ...}}}
```

`$ARGUMENTS` expanded to `"hello world"` (double-quoted, since it is a
multi-word argument), and the subagent's task result was the clean literal
`BEGIN hello world END` - confirming both the placeholder syntax and the
quoting behaviour.

### Step 5: mid-stream provider failure

Full command transcript and dated log in `probe-interrupt.md` - not
duplicated here since that file already carries its own date and every
command tried.

## Files

- `probe-injection.js` - the throwaway plugin used for Steps 2 and 3: does
  the `config` hook fire, do injected agent/command keys land in the
  resolved config, and do plugin options arrive.
### Step 6: does chat.params fire for an injected subagent, and does a throw stop it

Captured 2026-08-28. Question 1, the observation run:

```
P=$(mktemp -d); mkdir -p "$P/.opencode/plugin"
cp plugin/contracts/probe-chat-params.js "$P/.opencode/plugin/"
echo '{"$schema":"https://opencode.ai/config.json"}' > "$P/opencode.json"
cd "$P" && PROBE_LOG=$P/probe.log ~/.opencode/bin/opencode run --command probe-reviewer "the login handler" --format json > out.txt
cat "$P/probe.log"
```

Observed output:

```
LOADED options=null
CONFIG HOOK FIRED
COMMAND.EXECUTE.BEFORE command="probe-reviewer" args="\"the login handler\""
CHAT.MESSAGE agent="build" model={"providerID":"deepseek","modelID":"deepseek-v4-pro"}
CHAT.MESSAGE agent="probe-reviewer" model={"modelID":"deepseek-v4-flash","providerID":"deepseek"}
CHAT.PARAMS agent="title" model.providerID="deepseek" model.id="deepseek-v4-flash" provider="deepseek" inputKeys=["sessionID","agent","model","provider","message"]
CHAT.PARAMS agent="probe-reviewer" model.providerID="deepseek" model.id="deepseek-v4-flash" ...   (x6)
CHAT.PARAMS agent="build" model.providerID="deepseek" model.id="deepseek-v4-pro" ...              (x2)
```

Note the two spellings of the model id in that single log: `chat.message`
reports `modelID`, `chat.params` reports `id`.

Question 2, the same command with `PROBE_THROW=1`:

```
cd "$P" && PROBE_LOG=$P/probe2.log PROBE_THROW=1 ~/.opencode/bin/opencode run --command probe-reviewer "the login handler" --format json > out2.txt
```

The `probe-reviewer` line appears ONCE, followed by `THROWING NOW`, then
control returns to `build` - against six `probe-reviewer` requests in the run
above. The `task` tool part in `out2.txt`:

```
"status":"error"
"output":null
"error":"Tool execution failed: Subagent failed (task_id: ses_fb73e0756ffeyvyLgdDgoUOEnR): PROBE-GUARD-TRIPPED: refusing this review"
```

and the parent's final text began `The probe-reviewer subagent refused to run,
returning PROBE-GUARD-TRIPPED: refusing this review.`

Negative results from the same step, recorded so they are not re-derived:

- Pointing the provider `baseURL` at a dead port (`http://127.0.0.1:9/dead`)
  to make the probe free does work for a PLAIN message - `chat.params` fires
  for `title` and `build` before the HTTP call, then the SDK retries five
  times and the CLI hangs. It does NOT work for `--command`, which never got
  past `CONFIG HOOK FIRED` in three attempts (90s, 120s, 150s).
- `opencode run --agent <subagent-name>` cannot be used to reach an injected
  subagent cheaply: opencode refuses and silently falls back to the default
  agent.

- `probe-chat-params.js` - the Step 6 probe. Logs `command.execute.before`,
  `chat.message` and `chat.params`, and throws from `chat.params` when
  `PROBE_THROW=1` is set, to test whether a guard there actually stops a
  review and what the caller receives.
### Step 7: what a user actually sees when this plugin refuses to install

Captured 2026-08-28. Three faults, each run twice - once plain, once with
logging - from a scratch directory whose `opencode.json` points `plugin` at
`plugin/src/index.js` (an absolute path; a path to `plugin/` itself also works,
resolving through `main`).

```
cd "$P" && ~/.opencode/bin/opencode debug config > cfg.json 2>err.txt; echo $?
cd "$P" && ~/.opencode/bin/opencode debug config --print-logs --log-level ERROR >/dev/null 2>logs.txt
```

| Fault | plain exit | plain stderr | agents installed | reason findable |
|---|---|---|---|---|
| `{"model":"opus"}` - options rejected at load | 0 | 0 bytes | none | only in `logs.txt` |
| user already has an agent named `adversarial-review` | 0 | 0 bytes | none (user's own agent untouched) | only in `logs.txt` |
| `verify.js` made to disagree with `inject.js` - throw AFTER mutation | 0 | 0 bytes | **none** - whole hook rolled back | only in `logs.txt` |

The logged line for the first, verbatim:

```
level=ERROR message="failed to load plugin" path=file:///.../plugin/src/index.js error="opencode-adversarial-review: `model` must be provider/model, got \"opus\". Example: \"anthropic/claude-opus-5\""
```

A `console.error` and a `process.stderr.write` placed immediately before the
throw both produced nothing, on either stream.

**Consequence for this plugin.** Throwing is still correct - it fails closed,
and the rollback means a failed install is never a partial one. But a throw
alone is indistinguishable from the plugin not existing, which is the outcome
spec 3.4 names as the worst available. `index.js` therefore catches the one
fault a user causes by hand, a bad `model` value, and installs the two command
names as agent-less diagnostics whose `description` and `template` carry the
error. Confirmed present in the resolved config afterwards:

```
adversarial-review -> description "MISCONFIGURED - opencode-adversarial-review: `model` must be provider/model, got \"opus\"..."
                      subtask False, agent None, no reviewer agent installed
```

Collisions and fingerprint failures are deliberately NOT given this treatment:
a collision means the user's own agent owns the name and a diagnostic would be
the overwrite we refuse on principle, and a fingerprint failure means
`inject.js` and `verify.js` disagree, which is our own bug and fails the test
suite long before a user sees it.

- `probe-arguments.js` - a copy of the injection probe with the injected
  command template changed to `echo BEGIN $ARGUMENTS END` and bound to
  `deepseek/deepseek-v4-flash` (the cheapest configured model on this
  machine), used for Step 4.
- `probe-interrupt.md` - full write-up of Step 5: every method tried to
  force a mid-stream provider failure, what actually happened, and why the
  question is recorded as undetermined rather than guessed at.

## Undocumented behaviour - may change without deprecation

None of the following appear in opencode's published plugin docs for this
version. They were established empirically and could change in a future
release with no changelog entry:

- The exact shape and non-emptiness of `cfg.agent` at the time the `config`
  hook receives it (it already carries every built-in and other-plugin
  agent, not an empty object).
- The asymmetry between `cfg.agent` (pre-populated) and `cfg.command`
  (empty at hook time even when markdown-file commands exist on disk).
- The plugin-options tuple delivering `options=null` for a directory-loaded
  plugin versus a populated object for the `[path, options]` config form.
- `$ARGUMENTS` substitution quoting behaviour (multi-word arguments get
  wrapped in double quotes in the expanded template).
- That `opencode run "/cmd args"` does not dispatch the command definition
  at all, while `opencode run --command <name> <args>` does. Nothing in
  `opencode run --help` states this; it was found only by comparing the two
  invocation forms' actual output.
- Whether `ANTHROPIC_API_KEY` (or `ANTHROPIC_BASE_URL`) set in the
  environment ever overrides opencode's own stored credential store. On
  this machine, with `opencode auth login` already run, it did not.
- What a calling session receives on a genuinely broken provider call.
  Unverified either way - see the limits below.
- That `chat.params` fires at all for a plugin-injected subagent, that its
  `agent` field carries that subagent's own name, and that it fires once per
  LLM request rather than once per review.
- That `chat.params` spells the model id `model.id` while `chat.message`
  spells the same value `model.modelID`, in one version.
- That a throw from `chat.params` aborts the subagent and reaches the caller
  as a `task` part with `status: "error"` and the thrown message attached.
- That `opencode run --agent <name>` silently downgrades to the default agent
  when the named agent is a subagent, rather than failing.
- That plugin load errors and `config`-hook throws are swallowed entirely -
  exit 0, empty stderr - and surface only under `--print-logs --log-level
  ERROR`.
- That a `config`-hook throw rolls back the whole hook's mutations, so a
  failed install is never a partial one.
- That a plugin cannot write to the user's terminal from inside a hook on
  either stream.
- That a command with no `agent` and `subtask: false` is accepted and
  preserved by the config schema.

## Limits of this probe

- Step 5 (mid-stream provider failure) is **not answered**. Every attempt
  to force a cheap failure either silently succeeded for real money (env
  var overrides ignored) or hung past the time this task could afford to
  wait (60-110+ seconds, three separate breakages, all killed via
  `timeout` with zero output). Two real, billed API calls to
  `anthropic/claude-opus-5` happened incidentally while establishing that
  the env var route does not work; no further live spend was attempted
  once that was clear, per the task's "a few cents" budget. Full detail
  in `probe-interrupt.md`.
- Because Step 5 is unresolved, `plugin/index.js` and its callers must
  treat the `REVIEW-COMPLETE` completion marker (Task 6) as load-bearing,
  not defense-in-depth - there is no verified guarantee that a broken
  subagent call surfaces to the calling session as a clean, promptly
  delivered error.
- Step 6 does **not** close Step 5, and must not be read as doing so. It
  shows that one specific subagent failure - a plugin hook throwing - is
  delivered to the caller as a named `status: "error"`. A provider call
  dying mid-stream is a different failure at a different layer, and the
  hang behaviour recorded in `probe-interrupt.md` is still the only
  evidence about it. Step 6 makes the good outcome look more likely; it
  does not make it verified, and the completion marker stays load-bearing.
- These probes were run against this one machine's opencode installation,
  with this machine's global `~/.config/opencode/opencode.jsonc` merged in
  (providers `deepseek` and `anthropic`, model whitelist, per-agent model
  pins). A sterile/isolated config was not used here - unlike the harness's
  `contracts/README.md`, which does verify isolation - because the point of
  this probe is plugin *injection* behaviour, not isolation from an
  operator's config. The `EXISTING agent keys=...` line in each probe run
  reflects this machine's other installed plugins and is not itself part
  of the contract being pinned.
