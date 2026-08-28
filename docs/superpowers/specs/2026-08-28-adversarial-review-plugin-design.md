# Adversarial review plugin for opencode - design

**Date:** 2026-08-28
**Status:** approved in brainstorming; revised after Codex adversarial review
(section 9). Not yet planned or implemented.
**Supersedes the delivery half of:** `2026-08-27-deepseek-review-gauntlet-design.md`
(sections 10 and 11). That spec's harness, containment and statistics sections
still stand.

---

## 1. Why this exists, and what changed

The original project derived review instructions from a measured differential
between DeepSeek and Opus, then shipped them as a skill. Two fixtures in, we
stopped.

**This is an economic stop, not a scientific null.** The distinction matters and
an earlier draft of this spec got it wrong. What the evidence licenses is
"the first replication pair did not justify further spend." It does NOT license
"the 12-fixture programme cannot work": only one hazard family received a
replication pair, both fixtures are Python, no TypeScript fixture exists, and
the other planned hazard classes were never built.

### 1.1 The corpus, stated exactly

Seven report directories exist. An earlier draft published `4/20`, computed by a
script that silently skipped two reports whose summary schema predates the
`arms` key. That exclusion was technical, not methodological, and was not
disclosed. The corrected figures:

| Report | Arm | H-CALLSITE | Stage |
|---|---|---|---|
| 20260827T084906Z-py-callsite-01 | opus | 0/1 | smoke |
| 20260827T085214Z-py-callsite-01 | deepseek / opus | 0/3 / 0/3 | exploration |
| 20260827T103656Z-py-callsite-01 | deepseek | 1/3 | exploration |
| 20260827T214912Z-py-callsite-02 | deepseek | 0/3 | exploration |
| 20260827T222108Z-py-callsite-02 | opus | 0/1 | smoke |
| 20260828T022344Z-py-callsite-02 | opus | 0/3 | exploration |
| 20260828T023617Z-py-callsite-01 | deepseek | 3/10 | confirmation |

**Totals: 4 failures / 27 valid runs.** H-EXCLUDED and H-OPENQ: 0 failures.

That total pools a smoke run, exploration and confirmation, which spec 9.1
forbids. It is recorded here as a corpus census, not as an estimate of anything.
The only cell with power is the last row.

Also corrected: an earlier draft said Opus had never run on py-callsite-01. It
has - 0/4 across the two excluded reports.

**Any future report published from this repo must name the exact report
directories constituting each cell.** The absence of such a manifest is what
allowed the error above.

### 1.2 What the one powered cell says

DeepSeek fails H-CALLSITE **3 of 10** on py-callsite-01 (Wilson 95% CI
0.11-0.60). Spec 9.2's promotion rule needs 0.8. Observing 3 or fewer failures
in 10 at a true rate of 0.8 has probability 0.00086, so **that fixture cannot
meet the rule**, whatever the control arm does. This is a fixture-level
conclusion and is stated as one.

### 1.3 What the traces do and do not show

All ten runs name all three declared call sites in both `read_paths` and
`edited_paths`, the three failures included, with `trace_complete` and
`read_before_edit` true throughout.

An earlier draft concluded from this that the hazard "does not measure what it
is named for." **That overreaches.** `edited_paths` is derived from tool-call
inputs, not from the final diff, so it establishes that a file was opened for
editing - not that the call expression was correctly updated. A model that opens
all three callers and updates them *wrongly* is still a call-site correctness
failure.

What the traces license is narrower and still useful: **these are not
"never found the call site" failures.** The failure lives in the content of an
edit. We cannot say more, because the harness discards `result.session` and the
final tree.

### 1.4 Why derivation is nonetheless not the path

Three reasons, only the first of which is statistical:

1. On the one fixture with power, effect size is far below the promotion bar,
   and the bar was chosen to control family-wise error without being checked
   against achievable effects.
2. **An instruction needs a mechanism, and this pipeline records rates.** Even
   knowing H-CALLSITE fails 3/10, we cannot say what to tell a reviewer,
   because nothing retained distinguishes a failing run from a passing one.
3. A derived instruction is scoped to a model version and expires with it.

Reason 2 is the decisive one, and it is a property of the instrument rather
than of the effect size.

### 1.5 The inversion

The eval is retained and pointed at **validation** rather than derivation. The
skill is written from judgment and then measured (section 5). The plugin ships
the structural insight that never needed an eval: a reviewer pinned to a model
the author did not use.

---

## 2. What we are building

**An opencode plugin that runs adversarial review using a model the user
configures, independent of the model driving their session.**

Two reviewers, because they are different jobs with different attack surfaces:

- **`/adversarial-review`** - reviews code: a diff, a branch, a path.
- **`/adversarial-review-design`** - reviews a **document**: a spec, a plan, an
  RFC, a runbook.

The reference point is `openai/codex-plugin-cc`, which gives Claude Code users a
Codex reviewer. This is the mirror: it gives opencode users an Opus reviewer -
or whichever model they choose.

### 2.1 The job it does that codex-plugin-cc does not

codex-plugin-cc reviews Claude-grade output. This reviews **potentially
weak-model output**. opencode users frequently drive with smaller or local
models, and their failure modes differ: code that is plausible in shape and
unsound in construction, rather than subtle runtime risk in basically sound
code.

The product goal is therefore **raise the floor**, not only guard the ceiling.

It also covers a gap that tool structurally leaves. `codex-plugin-cc`'s
`adversarial-review` subcommand reviews a **git diff only**; reviewing a spec or
a plan means driving its `task` subcommand directly. A design defect caught at
the spec gate costs one edit; caught after implementation it costs the branch.
This spec is itself the evidence: the Codex review in section 9 found a blocker
in a document, where no code existed to review.

### 2.2 Boundaries

- **Never changes the session's working model.** The reviewer model is plugin
  configuration; the cross-family property comes from the user's choice, not
  from anything the plugin infers.
- **Read-only, enforced by construction** (section 3.3), not by permission
  patterns over a shell.
- **Standalone.** It does not assume it runs last in a gauntlet. Users who want
  that ordering say so in their own `AGENTS.md` / `CLAUDE.md`.
- **API-key authentication only.** Anthropic forbids using Claude through
  harnesses that are not Anthropic's own, so shelling out to the `claude` CLI is
  ruled out and no provider abstraction is built for it.

### 2.3 Why a plugin at all

`opencode agent create` is documented and supports `--model`, `--mode`,
`--permissions` and `--description`, writing an agent file. A model-pinned
read-only subagent is therefore achievable without a plugin, and an earlier
draft of this spec did not justify the difference.

**The plugin earns its place on exactly one capability: a safe git inspection
tool** (section 3.3). An agent file cannot ship a tool, and the alternative -
granting the agent general bash and constraining it with permission patterns -
does not work (section 9, finding 6). Config-driven model selection and one-line
install are conveniences on top; they are not the justification.

The design reviewer needs no tool at all - read and grep suffice - so it does
not add to this justification. It rides along on machinery the git tool already
pays for: model pinning, the config knob, verification, and one-line install.

If the git tool is ever removed from scope, the plugin should be reduced to
distributed agent templates.

### 2.4 Out of scope for v1

Background job management (`status` / `result` / `cancel`), multi-turn review
threads, and mechanical or AST checks. The last of these was spec 4's "bucket 2"
material, and bucket 2 is empty - neither arm has failed a hazard at the
required rate.

---

## 3. Architecture

### 3.1 Verified against opencode 1.18.23

The published docs at `https://opencode.ai/docs/plugins/` state that no `config`
hook exists, show plugins receiving no options, and describe tool registration
as the only extension point. **All three statements are wrong for this
version.** Verified empirically with throwaway probe plugins, not inferred:

| Behaviour | Docs | Observed |
|---|---|---|
| `config` hook fires | "No `config` hook exists" | Fires |
| Agent injection via `config` | Not mentioned | Agent appears in resolved config |
| Command injection via `config` | Not mentioned | Command appears in resolved config |
| Plugin options tuple | Bare strings only | `options={"model":"anthropic/claude-opus-5"}` received |

The types agree: `index.d.ts` declares `config?: (input: Config) => Promise<void>`
in `Hooks`, `plugin?: Array<string | [string, PluginOptions]>` in `Config`, and
`AgentConfig` carries `model`, `prompt`, `tools`, `permission`, `mode`,
`description`.

Tool registration - `Hooks.tool` - is the one documented mechanism we rely on,
and it carries the capability that justifies the plugin.

**Agent and command injection are undocumented surface**, recorded as the top
risk in section 7.

### 3.2 Configuration

```jsonc
"plugin": [
  ["opencode-adversarial-review", { "model": "anthropic/claude-opus-5" }]
]
```

One knob. Someone reviewing with DeepSeek changes one string.

### 3.3 What the plugin registers

**1. A git inspection tool, `review_context`.** This is the security boundary
and the reason the plugin exists.

- Invoked through `execFile` with a fixed argument vector. **No shell.**
- Subcommand allowlist: `diff`, `log`, `show`, `status`, `ls-files`.
- Option **allowlist**, not blocklist. `--output` and any option taking a
  filesystem destination are absent from it.
- Always passes `--no-ext-diff` and `--no-textconv`, so configured external
  drivers cannot execute.
- `-c` and `--exec-path` rejected outright.
- stdout captured and returned; nothing written.

**2. Agent `adversarial-review`**
- `model` from plugin options, default `anthropic/claude-opus-5`
- `mode: "subagent"` - invoked, never driving
- `tools`: read / grep / glob and `review_context` enabled; write / edit /
  patch / **bash** disabled
- `permission`: `edit: "deny"`, `bash: "deny"`, `webfetch: "deny"`
- `prompt`: the reviewer prompt (Appendix A)

**3. Agent `adversarial-review-design`**
- same `model` from plugin options
- `mode: "subagent"`
- `tools`: read / grep / glob only. **No `review_context`**, no bash, no write.
  A document reviewer that cannot write cannot damage the document it doubts.
- `permission`: `edit: "deny"`, `bash: "deny"`, `webfetch: "deny"`
- `prompt`: the design reviewer prompt (Appendix B)

**4. Commands `/adversarial-review` and `/adversarial-review-design`**, each
bound to its agent with `subtask: true`.

**Bash is denied entirely.** An earlier draft allowed `git diff`, `git log` and
`git show` through a permission pattern map and claimed that made the reviewer
structurally read-only. It does not: all three accept `--output=<path>`, which
creates or truncates that file. Verified - `git diff --output=f.txt` truncated a
tracked file to the empty blob. Denying bash also removes any dependence on
opencode's permission-pattern match ordering, which we have not verified.

### 3.4 Verifying the agent actually exists, and is ours

An existence check is not sufficient, and an earlier draft's was worse than
insufficient: it lived inside the `config` hook, so if opencode ever stops
invoking that hook the guard never runs. That is a guard that cannot fire -
item 2 of our own attack list, in our own design.

Three separate checks:

1. **Collision, before mutation.** If an agent or command of that name already
   exists in the incoming config and was not written by us, **abort without
   mutating** and report the collision. Silently overwriting a user's agent is
   the worst available outcome.
2. **Fingerprint, after the config resolves.** Verify model, prompt hash, mode,
   tool set, permissions, and the command's agent binding and `subtask` flag -
   not merely that the name is present. This detects a same-named user agent and
   a later merge phase overriding our fields.
3. **At invocation.** Verify the model actually serving the review matches the
   configured one, independent of the `config` hook, so a hook that stops firing
   surfaces as a loud failure rather than a session-model review.

All three checks apply to **both** agents and **both** commands.

Any check failing produces an actionable error naming what differed. A plugin
that silently does nothing, or silently reviews with the wrong model, is the
failure this design exists to prevent.

### 3.5 Compatibility

Declare a tested opencode version range. Test both plugin orderings and the
same-name user agent and command cases.

### 3.6 Interrupted and failed reviews

**A review that did not finish must never render as a review that found
nothing.** Those two outcomes are indistinguishable to a reader, and the user
acts on the second by shipping.

This is the failure mode the reviewer itself is built to hunt - the harvest's
"a truncated listing looked like a short one" - and a reviewer that commits it
is worse than no reviewer, because it manufactures confidence.

The likely trigger is mundane: the reviewer model's credit runs out, or a rate
limit lands, part-way through. The stream dies after the reviewer has read two
of seven files and found nothing yet. Whatever text arrived reads as a clean
review.

**Three outcomes, not two.** This mirrors `classify_run`'s
`completed` / `capped` / `invalid` in the harness, and exists for the same
reason recorded there: an infrastructure failure counted as a model result is
how a pipeline manufactures the finding you were hoping for.

1. Completed, findings reported
2. Completed, nothing material found
3. **Did not complete** - and this must never present as 2

**Mechanism.** Detection cannot depend on opencode surfacing a provider error,
because we do not control that and have not measured it (see the probe below).
So it is made independent of the transport:

- Both reviewer prompts **must end their output with a line containing only
  `REVIEW-COMPLETE`**. It is the last thing they emit, after the findings.
- The command template instructs the calling session: **if that marker is
  absent, the review did not finish.** Report it as incomplete, show whatever
  partial findings arrived clearly labelled as partial, and name what was not
  covered. Do not summarise it as clean.

Belt and braces: the prompt emits the marker, the caller checks for it. Neither
half requires opencode to report the underlying failure.

**Error surfacing.** Where a provider error IS available, surface it verbatim.
"Credit balance too low" is actionable; "review failed" is not.

**Retry policy, split by cause.** Bounded retry on rate limits and transient
network failures. **Never retry** on credit exhaustion or authentication
failure: those are terminal, and retrying only reproduces the same error more
slowly and more expensively.

**Probe required before relying on any of this.** Force a provider failure
mid-subagent and observe what opencode hands back to the calling session: a
raised error, a truncated assistant message, or silence. If it swallows the
failure into partial text, the completion marker is load-bearing rather than
defence in depth. If it turns out an injected subagent cannot detect its own
truncation at all, that is an argument for running the review through our own
tool layer instead - a larger change, and one to make on the probe's evidence
rather than on a guess.

---

## 4. The reviewer prompts

Full text in Appendix A (code) and Appendix B (design).

### 4.1 Where the content comes from

Two empirical sources:

1. **`openai/codex-plugin-cc`'s adversarial-review prompt**, for the operational
   axis and three framing devices: no credit for good intent or likely
   follow-up work; grounding rules requiring findings to be defensible with
   inferences named; calibration preferring one strong finding to several weak.
2. **A harvest of ~60 merged PRs in `Wayfarer-Group/materia-api`**, a production
   Python codebase whose PR bodies record what review found, what was fixed, and
   what was *cleared after triage*.

### 4.2 What the harvest changed

**Tests that cannot fail is the most recurring serious defect class** in that
corpus, by a wide margin. Observed shapes include tests passing for an unrelated
reason, tautologies computing the expectation with the code under test,
substring collisions, fixtures that structurally cannot discriminate, the unit
under test mocked at every appearance, test infrastructure hiding the condition,
assertions encoding the defect as the requirement, and containers collapsing the
signal.

**Triage is as important as detection.** The harvest catalogues six shapes of
*cleared* finding, which become `<verification_before_reporting>`. This is the
differentiator: codex-plugin-cc has grounding rules but no taxonomy of how
review findings go wrong.

### 4.3 Priority is threat-sensitive, not a fixed ranking

An earlier draft instructed reviewers not to lead with classical appsec,
generalising from zero appsec findings across 60 PRs of one Django codebase.
**That was unsafe.** The harvest has no exposure denominator - those PRs may
simply not have touched parsers, auth, network handlers or templating - and the
plugin ships to users writing Node request handlers and Go services, where a
global search-order bias could suppress real vulnerabilities.

The prompt therefore classifies the changed surface first:

- **When the change touches untrusted input, trust boundaries, auth, secrets,
  network access, filesystem access, dependency boundaries or multi-tenancy,
  security is first tier.**
- Otherwise, lead with test validity, proxy-signal guards, silent failure and
  wiring, which is where the yield is in ordinary application work.
- **Severity always overrides corpus frequency.**

The anti-padding instruction is kept; the general claim that appsec is "rarely
where the yield is" is removed.

### 4.4 The three axes

- **Correctness of construction** - looks right, cannot work.
- **Architecture and fit** - works, wrong shape, wrong for *this* repo.
- **Operational risk** - including security, elevated per 4.3.

The prompt instructs reporting by severity and forbids producing a finding per
category.

### 4.5 Licensed non-answers

The reviewer is instructed to say when a question can only be settled by
**running** the code. The harvest is unambiguous that the worst defects surfaced
only by running. A reviewer required to always assert will guess instead.

### 4.6 The design reviewer's attack list

Appendix B attacks how documents fail rather than how code fails, so almost
nothing transfers from Appendix A - "tests that cannot fail" is meaningless
against a spec.

Its taxonomy is derived from the Codex review recorded in section 9, which is
an unusually good source: seven findings against a real spec, six accepted. Each
finding shape became an attack. The document you are reading was the corpus.

---

## 5. Validation

**Validation does not gate v1.** The skill ships with v1, labelled as judgment
rather than measurement. An earlier draft contradicted itself here, describing
validation as happening after ship and also as a ship gate; that is resolved in
favour of the former.

### 5.1 What the fixture experiment is, and is not

Running the three conditions - bare, doctrine, and an equal-length neutral
placebo - against `fixtures/*/known_bad` and `fixtures/*/known_good` is a
**smoke test**. It is not a ship gate and cannot become one, for reasons worth
recording so nobody re-derives them:

- The `known_good` variants differ by one to four one-line edits and were
  authored together. They are near-clones, not independent controls.
- There are **two distinct planted defects** across the whole corpus. Catch rate
  therefore moves in 16.7-point increments; the effective sample is 2, not 72.
- Even 0 false positives in 18 calls has a Wilson 95% upper bound near 17.6%.
- The defects are synthetic and exposed through tiny curated repositories. They
  do not represent the distribution of weak-model output.
- **These fixtures were used to develop and repeatedly repair the harness.** They
  are development data, not a held-out evaluation set.
- Passing the planted grader does not prove a tree is otherwise defect-free, so
  a genuine unrelated finding would be miscounted as a false positive.

What it is good for: catching gross regressions - a prompt that finds nothing, or
one that floods every tree with findings. That is worth having and worth ~$10-15.

**Staging must strip fixture provenance**: no `known_good` / `known_bad` path
components, no fixture names, so the reviewer cannot recognise the setup.

### 5.2 What a real gate would require

Deferred, and specified so it is not reinvented casually:

- Held-out **whole repositories**, not variants of one tree, across more than one
  language and stack.
- Real weak-model diffs with an expert-adjudicated issue inventory.
- Finding-level precision and recall, a paired comparison, the clustering unit
  named, a non-inferiority margin for false positives, and a confidence
  criterion - all pre-registered.
- The prompt frozen before a locked test set consulted exactly once.

Until that exists, no claim stronger than "did not regress on a smoke test" may
be published about the prompt.

### 5.3 What the harness keeps and loses

**Keeps:** rootless podman sandboxing, image digest pinning, model verification
via `messages[].info.modelID`, provenance capture, and accounting that refuses
to let invalid runs into a denominator.

**Loses:** `run_agent`, the arms, the differential, and `bucket()`.

**Changes:** grading moves from "run pytest against a model's tree" to "did this
review name this defect".

### 5.4 Retention

`records.jsonl` keeps only derived observations and discards `result.session`
and the final tree, which is why section 1.3 cannot say why the three failures
failed. Four parser fixes landed on 2026-08-28 and every earlier report is
frozen wrong.

For the smoke test this does not bite, because the trees are fixed and known.
It becomes blocking again the moment we want to review real model-authored
diffs, and it is the prerequisite for ever explaining an H-CALLSITE failure.

---

## 6. Repository, distribution, README

- **Rename** the repository to `opencode-adversarial-review`.
- **Merge PRs #1 and #2** before building.
- **Layout:** plugin source in `plugin/`; the harness stays where it is.
- **Distribution:** publish to npm as `opencode-adversarial-review`, so install
  is `opencode plugin opencode-adversarial-review`.
- **README order**, treated as a requirement:
  1. What it does
  2. One-line install
  3. How to set your reviewer model
  4. **What to do if you have no Anthropic API key**
  5. How to run it
  6. Link to the research, stated as an economic stop rather than a null result

---

## 7. Risks

| Risk | Mitigation |
|---|---|
| **Undocumented agent/command injection.** Works in 1.18.23, absent from the docs, can change without deprecation. | Three-stage verification (3.4) including an invocation-time check outside the hook. Tested version range (3.5). Fallback: the prompt ships as a documented agent template. |
| **The git tool is the security boundary.** A gap in its option allowlist is a write primitive. | Allowlist not blocklist; `execFile` with no shell; `--no-ext-diff` / `--no-textconv`; adversarial tests for output options, redirects, substitutions, compound arguments, config injection, pagers, aliases, external diff drivers and submodules. |
| **Prompt length assumes a capable reviewer.** A small local model as *reviewer* may follow a layered instruction set badly. | README note. Compact variant deferred. |
| **The harvest is from strong-model output** in one language and framework. | Treated as a floor, not a map. Threat-sensitive priority (4.3) stops it from suppressing security review on other stacks. |
| **Reviewer cost is per-review and uncapped.** | README states the cost characteristic; the model is one config line. |
| **`command.template` placeholder syntax unverified.** Expected `$ARGUMENTS`. | Confirm during implementation. |
| **A review interrupted by credit exhaustion or a rate limit could read as a clean review.** | Three-state outcome and the `REVIEW-COMPLETE` marker checked by the caller (3.6), independent of whether opencode surfaces the provider error. Probe required before relying on it. |
| **The design reviewer's taxonomy comes from a single review of a single spec.** | Stated as such in 4.6. It is a starting point to be revised as more design reviews accumulate, not a validated instrument. |

---

## 8. What we are giving up

The ability to say "this instruction exists because DeepSeek failed X 8/10 times
where Opus failed 0/10". That provenance was the original point, and the one
powered cell says we are unlikely to earn it cheaply.

The eval is not discarded, and its result is stated honestly: **the first
replication pair did not justify further spend.** That is an economic stop on a
programme that remains, strictly speaking, unfinished. The harness becomes the
instrument that keeps the shipped prompt from regressing.

---

## 9. Codex adversarial review, 2026-08-28

Run against the first draft, per the spec-gate rule. Verdict: DO-NOT-BUILD as
written, seven findings. Six were accepted and are folded in above; the
disposition is recorded so the next reader does not re-derive it.

| # | Finding | Disposition |
|---|---|---|
| 1 | Fixture-level result generalised to a programme-level null; `4/20` not reproducible and mixes stages | **Accepted.** Section 1 reframed as an economic stop; corpus census corrected to 4/27 with a per-report manifest; stage-mixing disclosed |
| 2 | "H-CALLSITE does not measure what it is named for" overreaches - `edited_paths` is tool-call input, not the final diff | **Accepted.** Narrowed to "not a missed-call-site failure" in 1.3 |
| 3 | The self-check cannot detect a wrong or overridden agent, and lives inside the hook it checks | **Accepted.** Rewritten as 3.4, three checks including one outside the hook |
| 4 | Validation has ~2 experimental units, not 72; and 5.1/5.2 contradicted each other on whether it gates | **Accepted.** Demoted to an explicit smoke test; a real gate specified in 5.2 |
| 5 | Globally demoting appsec is unsafe for other stacks; no exposure denominator | **Accepted.** Priority is now threat-sensitive (4.3) |
| 6 | The bash permission map does not enforce read-only: `git diff/log/show --output=<path>` writes | **Accepted, blocker.** Reproduced - a tracked file was truncated. Bash denied entirely; a `review_context` tool replaces it (3.3) |
| 7 | v1 recreates a documented `opencode agent create` feature using undocumented hooks | **Accepted.** The plugin is now justified by the git tool alone (2.3), which an agent file cannot ship |

Findings Codex raised and then cleared itself, recorded so they are not
re-litigated: git aliases do not shadow built-in subcommands; `git -c
core.pager=` and `git -c include.path=` are excluded by an anchored subcommand
pattern; `git submodule` likewise.

One claim in the review is **unverified**: that opencode's permission patterns
are last-match-wins. Denying bash outright removes any dependence on it.

---

## Appendix A - The reviewer prompt

This is the `prompt` field of the injected `adversarial-review` agent.

```text
<role>
You are an adversarial code reviewer. Your job is to break confidence in a
change, not to validate it. You did not write this code and you have no stake
in it shipping.

The code you are reviewing was very likely written by another AI model, often a
smaller or weaker one. Expect code that LOOKS right and cannot work: correct
shape, plausible names, confident comments, and a defect in the wiring or the
premise. Your value is catching what a plausible-sounding author cannot see.
</role>

<target>
Review: {{TARGET}}
If the user named a focus, weight it heavily but still report any other
material issue you can defend.
</target>

<operating_stance>
Default to skepticism. Assume the change can fail in subtle, high-cost or
user-visible ways until the evidence says otherwise.

Do not give credit for good intent, partial fixes, or likely follow-up work.
If something only works on the happy path, that is a real weakness.

You have read and search tools. USE THEM. A reviewer who reasons only from the
diff will invent hazards that the surrounding code already excludes, and miss
the ones that only the surrounding code reveals. Open the callers. Open the
thing being mocked. Check that the symbol exists.
</operating_stance>

<priority_order>
FIRST, classify the surface this change touches. The right search order depends
on it, and getting this backwards is how a reviewer misses the thing that
mattered.

IF the change touches untrusted input, trust boundaries, authentication or
authorization, secrets, network access, filesystem paths, deserialization,
templating, dependency boundaries, or multi-tenancy - then SECURITY IS FIRST
TIER. Injection, SSRF, authorization gaps, path traversal, unsafe
deserialization and tenant-isolation failures belong at the top of your search,
ahead of everything below.

OTHERWISE, for ordinary application and library work, look here first. This
ordering reflects what adversarial review actually finds, which is not what
checklists usually list first:

1. TESTS THAT CANNOT FAIL. The most common serious defect, and the one that
   makes every other guarantee hollow.
2. Guards keyed on a proxy rather than the invariant.
3. Silent failure - errors swallowed, logged below alert level, or failing open.
4. Wiring: code that cannot run, or runs nothing.
5. Everything else below.

Severity always overrides this ordering. A high-severity finding outranks the
list wherever you found it.

Do not pad a review with generic security speculation on code that touches none
of the surfaces above - but do not skip security on code that does.
</priority_order>

<attack_surface>

## Axis 1 - Correctness of construction: looks right, cannot work

TESTS THAT CANNOT FAIL. For each test touching the change, ask: what single
edit to the production code would make this test fail? If you cannot name one,
the test is decorative. Specific shapes, all seen in the wild:
- Passing for a reason unrelated to what it names (a test asserting an error
  type that the framework raises for an unrelated reason, e.g. an unknown
  command name)
- Tautologies: the expected value computed with the production code under test,
  or imported from the constant being verified
- Substring and prefix collisions, so the assertion passes on the wrong case
- Fixtures that structurally cannot discriminate - every fixture sharing the
  one property that would expose the bug (all timestamps at an hour where two
  timezones agree; every input with exactly one instance of the pattern)
- The thing under test mocked at every appearance, so it never executes
- Test infrastructure hiding the condition: a test transaction meaning a row
  lock is never contended; a re-entrant lock never blocking
- Assertions that encode the defect as the requirement
- Containers that collapse the signal - a set making a duplicate write
  indistinguishable from a single one
- Test commands in docs that collect nothing and exit zero

GUARDS THAT CANNOT FIRE, or key on a proxy:
- Absence treated as proof (no holder means unowned; NULL means mid-flight)
- A partial or truncated read reported with a success status
- A count offered where only a denominator is evidence
- A vendor's status field trusted over the thing it claims to describe
- A check reading a field the producer never writes

SILENT FAILURE:
- Exceptions caught and logged below the level that alerts
- Fail-open on a path that must fail closed, especially money and access
- Detection that fires but does not block the write it was added to prevent
- Fallbacks that return the input on error, so "changed and non-empty" is not
  proof of success
- Exception hierarchy traps: BaseException, SystemExit, timeouts and
  cancellations not caught by `except Exception`

WIRING:
- A symbol used but never imported, or a function never called by anything
- A unit thoroughly tested in isolation and wired up nowhere
- Hallucinated or misused APIs - a library call that does not exist, or does
  not behave as assumed. VERIFY IT, do not assume it
- Dead branches and unreachable code

STALE PROSE:
- Comments, docstrings, runbooks and plans describing code that no longer
  exists. Trigger: when a signature or a write path changed, re-read the
  docstring above it for the old shape
- A comment describing the defect as if it were the mechanism

## Axis 2 - Architecture and fit: works, wrong shape, wrong for THIS repo

- Reimplementing something the repo already has. Search before accepting a new
  helper as necessary
- Ignoring the conventions of the surrounding code - a foreign style, a second
  way to do something the repo already does one way
- Layering violations: business logic in a controller, I/O in a pure function
- Poor boundaries: units doing several things, leaked internals, state in the
  wrong place
- Wrong abstraction level: premature generality, config knobs nobody sets, a
  parameter with exactly one caller
- Duplication that will drift - the same rule expressed in two places

## Axis 3 - Operational risk

- Auth, permissions, tenant isolation, trust boundaries
- Data loss, corruption, duplication, irreversible state
- Idempotency and duplicate side effects. Note the asymmetry: a duplicate
  charge that can be refunded may retry; an irreversible external order, or a
  message to a person, must not
- Retries, partial failure, rollback safety. Rollback restores behaviour, not
  what the behaviour did
- Races, ordering assumptions, stale reads, re-entrancy
- Empty, null, timeout and degraded-dependency behaviour
- Framework and ORM semantics that differ from the obvious reading - a negated
  membership test matching NULL, an upsert firing save hooks when nothing
  changed, a bulk update skipping automatic timestamps, a transaction giving
  rollback but not lost-update protection
- Time and timezone arithmetic: two-digit year pivots, day-boundary truncation,
  values stored as normalised anchors rather than real instants
- Third-party payload shape: an error body that parses as valid but empty, and
  reads downstream as "no more results"
- Config and environment leakage: credentials in code, a non-production
  environment that writes to production systems, an env var consumed on a tier
  that does not load it
- Migration and deploy hazards, schema drift, version skew
- Observability gaps that would hide the failure
</attack_surface>

<verification_before_reporting>
Before you report anything, try to kill it. Most bad review findings are
confident, well-written, and wrong in one of these six ways:

1. UNREACHABLE. The hazard is real in the abstract but no call site can reach
   it. Open the callers and check.
2. EXCLUDED BY THIS DOMAIN. A genuine language or library hazard that this
   system's constraints rule out.
3. RIGHT DIAGNOSIS, WRONG FIX. Diagnosis and remedy are separate claims. Your
   proposed fix must satisfy every existing caller; a fix scoped to the hazard
   rather than to real usage breaks working code.
4. "MAKE IT CONSISTENT" WHERE BOTH OPTIONS ARE WORSE. Asymmetry is sometimes
   deliberate. Ask what each consistent version would cost.
5. EQUIVALENT OR DELIBERATE. The change you propose has no observable effect,
   or the invariant you want pinned is intentionally not one.
6. THE PREMISE DOES NOT HOLD. The most dangerous shape: a well-evidenced
   finding built on a misreading of what the data or the code means. Check what
   the numbers you are citing actually measure before building on them.

If a conclusion rests on an inference you could not verify with the tools you
have, say so in the finding and lower your confidence. If a question can only
be settled by RUNNING the code - a live payload, a real dependency, a deploy -
say that explicitly rather than asserting an answer. "This needs a probe" is a
useful finding. A confident wrong answer is not.
</verification_before_reporting>

<finding_bar>
Report only material findings. No style, naming, or low-value cleanup.

Every finding must answer:
1. What can go wrong?
2. Why is this code path vulnerable - cite the location.
3. What is the concrete failure scenario: which inputs or state produce which
   wrong outcome?
4. What would reduce the risk?

If you cannot write the failure scenario concretely, you do not have a finding
yet.
</finding_bar>

<output_contract>
Open with a one-line verdict: SHIP or DO-NOT-SHIP, and why, in a sentence.

Then findings, ordered by severity, worst first. For each: location, the defect
in one sentence, the failure scenario, and a recommendation. Mark confidence
where it is not high, and name what would settle it.

Close with what you checked and cleared, briefly - so the next reader does not
re-derive it.

You are read-only. Recommend changes; do not write them.

FINALLY, emit a line containing only:

REVIEW-COMPLETE

This must be the last line of your output, always, including when you found
nothing. Its absence means the review was cut short, and the caller will treat
it that way. Never emit it early.
</output_contract>

<calibration>
Prefer one strong finding to several weak ones. Do not dilute a serious issue
with filler, and do not manufacture a finding per category to look thorough -
the axes above are where to look, not a quota to fill.

If the change is sound, say so plainly and report nothing. That is a real
outcome, not a failure to find something.
</calibration>
```

### A.1 Provenance of the prompt

- `<operating_stance>` no-credit clause, `<finding_bar>` four questions, and
  `<calibration>` adapted from `openai/codex-plugin-cc`'s adversarial-review
  prompt.
- `<priority_order>`, the Axis 1 shapes, and `<verification_before_reporting>`
  derived from a harvest of ~60 merged PRs in `Wayfarer-Group/materia-api`,
  whose PR bodies record findings and, crucially, findings *cleared after
  triage*.
- Axis 3 is close to codex-plugin-cc's attack surface, deliberately: it is
  well-made and we spend our originality on axes 1 and 2.

---

## Appendix B - The design reviewer prompt

This is the `prompt` field of the injected `adversarial-review-design` agent.

```text
<role>
You are an adversarial design reviewer. Your target is a DOCUMENT - a spec, a
plan, an RFC, a runbook - not a diff. Your job is to find the strongest reasons
it should not be built as written.

A design defect caught here costs one edit. Caught after implementation it costs
the branch.
</role>

<target>
Review: {{TARGET}}
If the user named a focus, weight it heavily but still report any other
material issue you can defend.
</target>

<operating_stance>
A document is a set of CLAIMS. Attack the claims, not the prose.

Read the codebase the document describes. USE YOUR FILE AND SEARCH TOOLS. A
document can describe code that does not exist, misdescribe code that does, cite
numbers that do not reproduce, or depend on behaviour nobody verified. You
cannot find any of that by reading the document alone.

Where the document cites a number, a file, a version or an experiment, GO AND
CHECK IT. A citation you did not verify is a claim, not evidence.

Do not give credit for good intent, for a section being well written, or for
work the document promises to do later.
</operating_stance>

<priority_order>
1. CLAIMS THAT EXCEED THEIR EVIDENCE. The most common serious defect in design
   documents, and the hardest to see because the reasoning is usually valid -
   it is the scope of the conclusion that is wrong.
2. A safety or correctness claim that the named mechanism does not actually
   enforce.
3. Guards, checks and gates that cannot fire.
4. Experiments and metrics with fewer independent units, or less power, than
   they appear to have.
5. Unstated assumptions and unhandled failure paths.
6. Scope that does not justify its cost or its risk.
</priority_order>

<attack_surface>

EVIDENCE
- Does every cited number reproduce from the data the document points at? Run it.
- Is the SELECTION of data disclosed? Silently excluded cases are the classic
  defect - a number computed over "the data that parsed" reported as if it were
  the corpus.
- Are populations or stages pooled that the document's own rules separate?
- Is a sample size doing less work than it looks like? Count INDEPENDENT units,
  not observations. Near-clones of one case are one case.
- Is a negative control actually independent of the positive case?

INFERENCE
- Is a measured proxy being read as the thing it proxies for? "The file was
  opened for editing" is not "the call was correctly updated".
- Does the conclusion's scope match the evidence's scope? A result about one
  case, one language, one repository, one version, is not a result about the
  programme.
- Is absence of evidence being reported as evidence of absence? Ask what the
  exposure denominator was - a category with no findings may simply never have
  been touched.

MECHANISM
- Does the named mechanism actually produce the claimed property? Verify it
  rather than accepting it. If the document says a constraint makes something
  impossible, try to do it.
- Can the proposed check DETECT the failure it exists for? An existence check
  cannot tell a wrong thing from a missing thing.
- Does the check run somewhere that survives the failure it guards against? A
  guard living inside the mechanism it validates fails silently when that
  mechanism does.
- What happens on collision with something the user already has?

ALTERNATIVES AND SCOPE
- Does a documented, simpler, or first-party mechanism already do this? Look for
  it before accepting a bespoke one.
- What does this buy over doing nothing, or over the obvious cheaper option?
- Is the document taking on a dependency on undocumented or unversioned
  behaviour, and is the mitigation real or nominal?
- Is anything irreversible, and is that acknowledged?

INTERNAL INTEGRITY
- Do sections contradict each other? Check especially where one section defines
  a gate and another describes when it runs.
- Are there placeholders, unresolved options, or requirements that could be read
  two ways?
- Does the document's own history contain a decision this draft silently
  reverses?
</attack_surface>

<verification_before_reporting>
Before you report anything, try to kill it. Design-review findings go wrong in
these ways:

1. THE DOCUMENT ALREADY SAYS IT. Re-read the surrounding sections; a concern
   answered three paragraphs later is not a finding.
2. OUT OF SCOPE BY DECLARATION. The document explicitly deferred it and gave a
   reason. Attack the reason if it is weak; do not report the deferral as an
   oversight.
3. A DIFFERENT DESIGN, NOT A DEFECT. Preferring another approach is not a
   finding unless you can name what breaks in this one.
4. RIGHT DIAGNOSIS, WRONG FIX. Your remedy must be compatible with the
   constraints the document actually operates under.
5. THE PREMISE DOES NOT HOLD. Check what the numbers you are citing actually
   measure before building on them.
6. UNVERIFIED ASSERTION OF YOUR OWN. If you claim the document is wrong about an
   API, a version or a behaviour, verify it in the repository or the installed
   package first. Reasoning from vendor documentation against a system someone
   has actually measured is how a review earns distrust.

Say explicitly when a finding rests on an inference you could not verify, and
lower your confidence accordingly.
</verification_before_reporting>

<finding_bar>
Report only material findings. No wording, structure, or presentation notes.

Every finding must answer:
1. What goes wrong if this is built as written?
2. Which part of the document is vulnerable - quote or cite it by section.
3. What is the concrete consequence?
4. What specific change would fix it?
</finding_bar>

<output_contract>
Open with a verdict: BUILD, BUILD-WITH-CHANGES, or DO-NOT-BUILD-AS-WRITTEN, and
name the decisive sections in one line.

Then findings, ordered by severity. For each: the section, what goes wrong, why
that section is vulnerable, the consequence, and a concrete fix.

SAY PLAINLY WHICH SECTIONS ARE SOUND. A design review that reports only
problems gives the author no way to tell what survived scrutiny from what you
did not examine. Name what you checked and cleared, and say when you cleared it
against evidence rather than by not looking.

State what you read. You are read-only; recommend changes, do not make them.

FINALLY, emit a line containing only:

REVIEW-COMPLETE

This must be the last line of your output, always, including when you found
nothing. Its absence means the review was cut short, and the caller will treat
it that way. Never emit it early.
</output_contract>

<calibration>
Prefer one strong finding to several weak ones. Do not manufacture a finding per
category to look thorough.

If the design is sound, say so directly and report nothing. That is a real
outcome.
</calibration>
```

### B.1 Provenance

Derived from the Codex adversarial review recorded in section 9: seven findings
against the first draft of this spec, six accepted. Each accepted finding shape
became an entry in `<priority_order>` or `<attack_surface>`:

| Finding | Became |
|---|---|
| Fixture result generalised to a programme; number not reproducible | EVIDENCE: selection disclosure, pooled stages, reproduce the number |
| `edited_paths` read as "correctly updated" | INFERENCE: proxy read as the thing it proxies for |
| Self-check inside the hook it checks; existence-only | MECHANISM: can the check detect it, does it survive the failure |
| 72 calls, effective n of 2; near-clone controls | EVIDENCE: count independent units |
| Appsec demoted from one codebase's yield | INFERENCE: exposure denominator |
| Read-only claimed, `--output` writes | MECHANISM: verify the mechanism produces the property |
| Undocumented hooks recreating a documented feature | ALTERNATIVES AND SCOPE |

`<verification_before_reporting>` item 6 comes from the opposite direction: the
standing triage rule that a reviewer reasoning from vendor documentation
sometimes contradicts behaviour we have measured.
