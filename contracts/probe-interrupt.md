# Probe: mid-stream provider failure (Step 5)

Date: 2026-08-28. opencode 1.18.23 (`~/.opencode/bin/opencode`).

## Question

Force a provider failure part-way through a subagent's response and record
what the calling session receives: a raised error, a truncated assistant
message, or silence.

## Result: could not determine cheaply within budget

Five methods were tried. The two "cheap" methods the brief expected to work
did not fail at all - they silently used real credentials and made a real,
billed API call. The three methods that did break the provider call did not
fail fast; they hung past a 60-110 second wait with no output at all, so the
shape of the failure the calling session would eventually receive was never
observed. No method produced the target signal (a clean error, a truncated
message, or confirmed silence) inside a reasonable time or cost budget.

### Attempt 1: `ANTHROPIC_API_KEY=sk-invalid` (the method the brief specifies)

```
P=$(mktemp -d); mkdir -p "$P/.opencode/plugin"
cp contracts/probe-injection.js "$P/.opencode/plugin/"
echo '{"$schema":"https://opencode.ai/config.json"}' > "$P/opencode.json"
cd "$P" && ANTHROPIC_API_KEY=sk-invalid PROBE_LOG=$P/probe.log \
  ~/.opencode/bin/opencode run --command probe-cmd "review this" --format json
```

Did not fail. opencode has its own credential store
(`~/.local/share/opencode/auth.json`, populated by `opencode auth login`) and
that store won over the env var. The subagent ran on real
`anthropic/claude-opus-5` and returned a normal completed result:

```
"model":{"providerID":"anthropic","modelID":"claude-opus-5"}
"state":{"status":"completed", ...}
```

This is a real, billed call (visible cost on the parent step: `0.00670335`).
**Contract fact:** `ANTHROPIC_API_KEY` set at invocation time does not
override opencode's stored credentials. A throwaway invalid-key probe like
this one is not a safe way to force a provider failure on a machine that has
already run `opencode auth login` for that provider.

### Attempt 2: `ANTHROPIC_BASE_URL=http://127.0.0.1:1` + invalid key

Same reasoning: try to force a connection failure via the env var an AI SDK
provider conventionally reads. Also silently ignored - the call again went to
the real endpoint with real credentials and completed normally (cost
`0.007611195`, also billed). Two real API calls were made trying the
env-var route before it was clear neither env var has any effect here.

### Attempt 3: config-hook override of `provider.anthropic.options.baseURL`

Since Steps 2-3 already proved the plugin's `config` hook can inject into the
resolved config (agent/command keys land; options tuple lands), the same
mechanism was used to point the anthropic provider at a closed local port:

```js
cfg.provider.anthropic.options.baseURL = "http://127.0.0.1:1"
```

`curl` to that address fails instantly with "Connection refused" at the OS
level (confirmed separately, 5ms). But the `opencode run` process did not
fail fast: it produced no stdout, no stderr (even with `--print-logs
--log-level DEBUG`), and no process exit for 110 seconds, at which point the
attempt was killed via `timeout`. The config hook was confirmed to have
fired (`probe.log` shows `CONFIG HOOK FIRED`), so the override was at least
attempted; whether it actually reached the SDK client construction is
unconfirmed.

### Attempt 4: config-hook override of `provider.anthropic.options.apiKey`

Same idea, but leaving `baseURL` untouched (so the request would hit the
real Anthropic endpoint with bad credentials, which should return a fast
401 with no tokens billed). Also hung with no output for 90 seconds, killed
via `timeout`.

### Attempt 5: invalid model id (`anthropic/claude-does-not-exist-xyz`)

No provider tampering at all this time, just an unrecognized model id on the
injected agent. Also hung for 60 seconds with no output, killed via
`timeout`. This scratch directory's `.opencode/node_modules` had already
been fully populated (npm install of `@opencode-ai/plugin` etc. completed),
so the hang was not plugin-bootstrap time - it happened after that, somewhere
in config resolution or the provider/model lookup path.

## What this does establish

- The brief's suggested cheap method (`ANTHROPIC_API_KEY=sk-invalid`) is
  **not reliable on a machine with `opencode auth login` credentials
  already stored** - it silently falls through to the real key. Any future
  probe of this kind needs a machine/session with no stored credentials for
  the target provider, or a way to force opencode to prefer the env var.
- Every method that *did* produce a broken provider configuration (verified
  via the same config-hook mechanism proven to work in Steps 2-3) caused the
  CLI to hang rather than raise a fast, observable error. This was
  reproduced three times with three different breakages (bad baseURL, bad
  apiKey, bad model id), each killed after 60-110 seconds with zero output.
  opencode 1.18.23 does not appear to fail fast on a broken provider call in
  this codepath - or the failure surfaces on a timescale outside what a cheap
  probe can afford to wait for.
- Two real (billed, but each on the order of a cent) API calls to
  `anthropic/claude-opus-5` were made incidental to attempts 1 and 2, before
  it was clear the env var overrides were not taking effect. No further live
  spend was attempted once that was established, per the "few cents" budget
  in the task brief.

## Consequence for Task 6 and the README

Because clean error propagation on a provider failure could not be
confirmed, and the observed alternative was either "the failure never
became observable" or "hangs rather than errors," **treat the
`REVIEW-COMPLETE` marker in Task 6 as load-bearing, not defense in depth.**
The plugin/command layer cannot assume opencode will surface a mid-stream
provider failure to the calling session as a clean, promptly-delivered
error. A caller waiting on that marker (rather than trusting a bare
tool-success signal) is the only verified-safe way to know a subagent
actually finished its review. The `contracts/README.md`
troubleshooting section states this plainly.
