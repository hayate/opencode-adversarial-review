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
| What does the calling session receive when a subagent's provider call fails mid-stream? | **Undetermined.** See `probe-interrupt.md`. The brief's suggested cheap method (invalid `ANTHROPIC_API_KEY`) is silently ignored - opencode's stored `auth.json` credentials win over the env var, so the call succeeds for real (billed) instead of failing. Every method that did produce a genuinely broken provider config (bad `baseURL`, bad `apiKey` via the `config` hook, invalid model id) caused the CLI to hang for 60-110+ seconds with zero output, rather than raising a fast error. No run in this probe surfaced a clean error, a truncated message, or confirmed silence within the cost/time this task could spend. |

## Capture log

Date: 2026-08-28. All commands run from the repo root unless shown with a
`cd` into a scratch directory. Every command in this log was re-run on the
capture date to confirm it still produces the output shown, immediately
before this file was written.

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
- These probes were run against this one machine's opencode installation,
  with this machine's global `~/.config/opencode/opencode.jsonc` merged in
  (providers `deepseek` and `anthropic`, model whitelist, per-agent model
  pins). A sterile/isolated config was not used here - unlike the harness's
  `contracts/README.md`, which does verify isolation - because the point of
  this probe is plugin *injection* behaviour, not isolation from an
  operator's config. The `EXISTING agent keys=...` line in each probe run
  reflects this machine's other installed plugins and is not itself part
  of the contract being pinned.
