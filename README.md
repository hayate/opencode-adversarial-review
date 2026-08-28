# opencode-adversarial-review

Adversarial code and design review for [opencode](https://opencode.ai), run by a
model you choose - independent of the model you are coding with.

You write code with DeepSeek, Qwen or a local model. This reviews it with Opus.
The reviewer is read-only and cannot touch your working tree.

> **Status: not published to npm.** It is installed from a local checkout while
> it is being tested. `plugin/package.json` carries `private: true` precisely so
> that a stray `npm publish` cannot fire.

## Install

Clone this repository, then point opencode at `plugin/` in your `opencode.jsonc`:

```jsonc
{
  "plugin": [
    ["/absolute/path/to/opencode-adversarial-review/plugin",
     { "model": "anthropic/claude-opus-5" }]
  ]
}
```

The path may be the `plugin/` directory (resolved through its `main`) or
`plugin/src/index.js` directly; both were verified against opencode 1.18.23.
Put it in a project's `opencode.json` to scope it to that project, or in
`~/.config/opencode/opencode.jsonc` for every project.

Check it landed:

```bash
opencode debug config | jq -r '.agent, .command | keys[] | select(startswith("adversarial-review"))'
```

Four lines means a healthy install - both agents, then both commands:

```
adversarial-review
adversarial-review-design
adversarial-review
adversarial-review-design
```

Two lines means only the diagnostics installed and the reviewers did not.
No lines means opencode never loaded the plugin. Both cases are covered under
[Troubleshooting](#troubleshooting).

## Use

```
/adversarial-review        review the current change
/adversarial-review src/   review a path
/adversarial-review-design docs/specs/my-spec.md
```

## Choosing a reviewer model

The reviewer should be a model you did NOT write the code with. Asking a model
to review its own output asks it to see its own blind spot.

The default is `anthropic/claude-opus-5`, which needs an **Anthropic API key**.
A Claude Pro or Max subscription does not cover third-party tools.

**No Anthropic API key?** Change one line. Any model your opencode config can
reach works:

```jsonc
["/path/to/plugin", { "model": "deepseek/deepseek-v4-pro" }]
["/path/to/plugin", { "model": "openai/gpt-5.4" }]
```

Your provider must be listed in `enabled_providers`, and the model must be
selectable under `provider.<name>.whitelist` if you use one.

## Cost

Reviews are priced per run by your provider. Switching the reviewer to a cheaper
model is a one-line change.

## What it looks for

Three axes: correctness of construction (code that looks right and cannot
work), architecture and fit, and operational risk. It classifies the changed
surface first, so security leads whenever the change touches untrusted input,
auth, secrets, network or the filesystem.

It is written to be useful on output from weaker models, which fails differently
from strong-model output: plausible shape, unsound wiring.

## If a review looks cut short

Every review ends with a completion marker. If your reviewer model runs out of
credit or hits a rate limit mid-review, you get an **incomplete** review with
partial findings labelled as partial, rather than a half-finished review
presented as a clean one.

## Troubleshooting

**opencode hides plugin failures.** This is the single thing worth knowing
before anything else. When a plugin fails to load, or its `config` hook throws,
opencode exits 0, prints nothing to stderr, and simply leaves the plugin out.
There is no way for a plugin to write to your terminal at that point - both
`console.error` and a direct stderr write are swallowed. So the symptom of every
install problem is the same: nothing happens.

The reason is always recoverable, in one place:

```bash
opencode debug config --print-logs --log-level ERROR 2>&1 | grep -i plugin
```

That prints, for example:

```
level=ERROR message="failed to load plugin" path=file:///.../plugin/src/index.js
  error="opencode-adversarial-review: `model` must be provider/model, got \"opus\"."
```

| Symptom | Cause | Fix |
|---|---|---|
| `/adversarial-review` says **MISCONFIGURED** in its description, and relays an error instead of reviewing | Your `model` option is not a valid `provider/model` reference | Correct it in the plugin options and restart opencode |
| The commands do not exist at all, and the log says `already exists and is not ours` | You already have an agent or command of that name. The plugin refuses to overwrite it | Rename yours, or remove the plugin |
| The commands do not exist and there is no log line | opencode never loaded the plugin - usually a wrong path | Check the path resolves; try `plugin/src/index.js` explicitly |
| A review runs but on the wrong model | Should be impossible: the reviewer refuses at invocation if the serving model is not the configured one, and says both | If you see this, the check has a bug - please report it |

A failed install is never a partial one. opencode discards the whole hook's
mutations when it throws, so you either get both reviewers or neither.

## How it verifies itself

A reviewer that silently runs on your session model instead of the one you
configured is worse than no reviewer, because the output looks identical. Three
checks stand in the way:

1. **Collision, before anything is written.** If an agent or command of either
   name already exists and is not ours, it aborts without mutating.
2. **Fingerprint, after injection.** Model, mode, prompt hash, command template
   hash, every permission and every tool flag are compared against what we
   wrote - not merely checked for presence, which would pass on a same-named
   agent pointing somewhere else.
3. **At invocation.** Every request the reviewer makes is checked against the
   configured model before it leaves. This one runs outside the `config` hook on
   purpose, so a hook that stops firing cannot take the guard with it. It is
   also the only one of the three that is loud: it aborts the review and the
   error reaches you through the calling session.

## Compatibility

Written against **opencode 1.18.23**. Several behaviours it relies on are
undocumented and were established by probe rather than from the published docs,
which are wrong for this version on three counts. They are recorded with their
exact commands and verbatim output in
[`plugin/contracts/README.md`](plugin/contracts/README.md). Re-run those probes
after any opencode upgrade.

## Running it last

It works standalone. If you prefer it as the final lens in a review gauntlet,
say so in your own `AGENTS.md` or `CLAUDE.md`; the plugin does not assume an
ordering.

## The research behind it

This repository also contains a differential evaluation harness. It set out to
derive review instructions by measuring where one model fails and another does
not, and stopped after two fixtures: see
[the design spec](docs/superpowers/specs/2026-08-28-adversarial-review-plugin-design.md)
for what it measured, what it did not, and why that is an economic stop rather
than a null result.

## Licence

MIT
