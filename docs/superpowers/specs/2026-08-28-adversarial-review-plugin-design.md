# Adversarial review plugin for opencode - design

**Date:** 2026-08-28
**Status:** approved in brainstorming, not yet planned or implemented
**Supersedes the delivery half of:** `2026-08-27-deepseek-review-gauntlet-design.md`
(sections 10 and 11). That spec's harness, containment and statistics sections
still stand.

---

## 1. Why this exists, and what changed

The original project derived review instructions from a measured differential
between DeepSeek and Opus, then shipped them as a skill. Two fixtures in, the
evidence says that will not work.

**What the eval actually measured** (see `docs/reviews/` and the run reports):

| Hazard | Failures / valid runs, both fixtures, both arms |
|---|---|
| H-CALLSITE | 4 / 20 |
| H-EXCLUDED | 0 / 20 |
| H-OPENQ | 0 / 20 |

The one measurement with power behind it: DeepSeek fails H-CALLSITE **3 of 10**
on py-callsite-01 (Wilson 95% CI 0.11-0.60). Spec 9.2's promotion rule needs a
rate of 0.8. Observing 3 or fewer failures in 10 at a true rate of 0.8 has
probability 0.00086, so the threshold is effectively ruled out. `bucket()`
returns `neither` even with the control arm at a hypothetical 0/10 - no Opus run
can rescue it, because the failing bar is on the DeepSeek side.

**And the hazard does not measure what it is named for.** All ten runs read 3/3
and edited 3/3 declared call sites, the three failures included.
`read_before_edit` and `trace_complete` were true in all ten. No recorded
observation separates a failing run from a passing one. The failure lives in the
*content* of an edit, which the harness does not record. An instruction derived
from this hazard would tell a reviewer to check that every call site was
visited; the data says they always are.

**Three independent reasons derivation cannot produce the skill:**

1. The effect sizes are far below the promotion bar, and the bar was chosen to
   control family-wise error without being checked against achievable effects.
2. Even a promoted hazard yields no instruction, because the eval measures
   failure *rates* and instructions need *mechanisms*.
3. A derived instruction is scoped to a model version and expires with it.

This is spec 11's staged delivery working as designed - "the differential may be
thin" was a pre-agreed live risk, and the gate says publish the null and stop.
The answer arrived after 2 fixtures instead of 12.

### 1.1 The inversion

The eval is retained, but pointed at **validation** rather than derivation. The
skill is written from judgment and then measured (section 5). The plugin ships
the structural insight that never needed an eval: a reviewer pinned to a model
the author did not use.

---

## 2. What we are building

**An opencode plugin that runs an adversarial code review using a model the
user configures, independent of the model driving their session.**

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

### 2.2 Boundaries

- **Never changes the session's working model.** It has no opinion about what
  the user codes with. The reviewer model is plugin configuration; the
  cross-family property comes from the user's choice, not from anything the
  plugin infers.
- **Read-only.** A reviewer has no business editing code, and this is enforced
  structurally (section 3.3), not by convention.
- **Standalone.** It does not assume it runs last in a gauntlet. Users who want
  that ordering say so in their own `AGENTS.md` / `CLAUDE.md`.
- **API-key authentication only.** Anthropic forbids using Claude through
  harnesses that are not Anthropic's own, so shelling out to the `claude` CLI is
  ruled out and no provider abstraction is built for it.

### 2.3 Out of scope for v1

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

**This is undocumented API surface**, and is recorded as a risk in section 7.

### 3.2 Configuration

```jsonc
"plugin": [
  ["opencode-adversarial-review", { "model": "anthropic/claude-opus-5" }]
]
```

One knob. Someone reviewing with DeepSeek changes one string.

### 3.3 What the plugin registers

Through the `config` hook:

1. **Agent `adversarial-review`**
   - `model` from plugin options, default `anthropic/claude-opus-5`
   - `mode: "subagent"` - invoked, never driving
   - `tools`: read / grep / glob enabled; write / edit / patch disabled
   - `permission`: `edit: "deny"`, `webfetch: "deny"`, and `bash` as a pattern
     map allowing `git diff`, `git log`, `git show` while denying `*`
   - `prompt`: the reviewer prompt (section 4)
2. **Command `/adversarial-review`**, bound to that agent, `subtask: true`,
   taking a review target as its argument.

No custom tools in v1. The reviewer uses opencode's built-in read and search
tools and gathers its own context through the allowed git commands. The bash
pattern map is what makes "read-only" enforced rather than promised.

### 3.4 Startup self-check

If the agent is absent from the resolved config after the `config` hook runs,
fail loudly with an actionable message. A plugin that silently does nothing is
the worst outcome of building on undocumented surface.

---

## 4. The reviewer prompt

Three axes, with an explicit priority order derived from evidence rather than
convention.

### 4.1 Where the content comes from

Two sources, both empirical:

1. **`openai/codex-plugin-cc`'s adversarial-review prompt**, for the operational
   axis and three framing devices worth borrowing outright: no credit for good
   intent or likely follow-up work; grounding rules requiring findings to be
   defensible from context with inferences named; calibration preferring one
   strong finding to several weak ones.
2. **A harvest of ~60 merged PRs in `Wayfarer-Group/materia-api`**, a production
   Python codebase whose PR bodies record what adversarial review found, what
   was fixed, and what was *cleared after triage*.

### 4.2 What the harvest changed

**Tests that cannot fail is the most recurring serious defect class**, by a wide
margin - not a footnote. Observed shapes include: tests passing for an unrelated
reason (15 tests green against a command that did not exist); tautologies
computing the expectation with the production code under test; substring
collisions; fixtures that structurally cannot discriminate (every fixture at an
hour where two timezones agree); the unit under test mocked at every appearance;
test infrastructure hiding the condition (one transaction means a row lock is
never contended); assertions encoding the defect as the requirement; a `set`
collapsing a duplicate write into a single one.

**Classical appsec yields almost nothing.** Across 60 PRs: no SQL injection,
XSS, deserialization, path traversal, or dependency-CVE findings. The yield is
overwhelmingly correctness-under-partial-failure, test validity, and
operational semantics. The prompt says so explicitly rather than leaving the
ordering to the model, because most checklists lead with appsec.

**Triage is as important as detection.** The harvest catalogues six shapes of
*cleared* finding - reviewer false positives - and these become a
`<verification_before_reporting>` section. This is the differentiator:
codex-plugin-cc has grounding rules, but no taxonomy of how review findings go
wrong.

### 4.3 Priority order

1. Tests that cannot fail
2. Guards keyed on a proxy rather than the invariant
3. Silent failure - swallowed, under-logged, or failing open
4. Wiring - code that cannot run, or runs nothing
5. Everything else

### 4.4 The three axes

- **Correctness of construction** - looks right, cannot work. Test validity,
  proxy-signal guards, silent failure, wiring gaps, hallucinated or misused
  APIs, stale prose.
- **Architecture and fit** - works, wrong shape, wrong for *this* repo.
  Reimplementing what exists, ignoring local conventions, layering violations,
  poor boundaries, wrong abstraction level.
- **Operational risk** - auth and trust boundaries, data loss, idempotency and
  duplicate side effects, retries and partial failure, races, degraded
  dependencies, framework and ORM semantics, time arithmetic, third-party
  payload shape, config and environment leakage, migration hazards,
  observability gaps.

The prompt instructs reporting by severity and explicitly forbids producing a
finding per category, because a checklist demanding coverage per axis is how
reviews get padded.

### 4.5 Licensed non-answers

The reviewer is instructed to say when a question can only be settled by
**running** the code, rather than asserting. The harvest is unambiguous that the
worst defects surfaced only by running - a duplicate keyword argument
`SyntaxError` that the linter did not flag, and five guard tests lost in a
branch promotion that `git cherry` was structurally blind to. A reviewer
required to always assert will guess instead.

The full prompt text is Appendix A. It is the design, not an implementation
detail, and changes to it are spec changes.

---

## 5. Validation

The skill ships with v1, honestly labelled as judgment rather than measurement,
and is measured afterwards. Validation informs v2; it does not block v1.

### 5.1 The experiment

The existing fixtures are better review targets than model output, because they
carry ground truth:

- `fixtures/*/known_bad/` - a planted defect at a known location. **Positive
  cases.**
- `fixtures/*/known_good/` - three independently correct solutions per fixture.
  **Negative controls.**

Three conditions - bare prompt, doctrine prompt, and an equal-length neutral
checklist placebo - randomised and blinded from grading, replicated because the
review is stochastic.

- On `known_bad`: does the review name the planted defect at its actual location?
- On `known_good`: does it stay quiet, or manufacture findings?

The placebo is load-bearing: without it, a with/without comparison cannot
separate hazard-specific content from the generic effect of more words.

### 5.2 Ship gate for the doctrine

The doctrine must **beat the placebo on catch rate AND not be worse than bare on
false positives.** A doctrine that wins only by flagging more has bought catch
rate with noise, and we ship a shorter prompt instead. This is a gate the skill
can fail.

Reported as catch rate *and* false-positive rate. Catch rate alone rewards a
reviewer that flags everything.

### 5.3 Cost

2 fixtures x (1 known-bad + 3 known-good) x 3 conditions x 3 replicates is
approximately 72 reviews, roughly $10-15 at Opus rates. Trimmable by reducing
replicates or reviewing a subset of known-good trees, at the cost of power.

### 5.4 What the harness keeps and loses

**Keeps:** rootless podman sandboxing, image digest pinning, model verification
via `messages[].info.modelID`, provenance capture, and accounting that refuses
to let invalid runs into a denominator.

**Loses:** `run_agent`, the arms, the differential, and `bucket()` - none are
needed to compare review conditions against fixed trees.

**Changes:** grading moves from "run pytest against a model's tree" to "did this
review name this defect".

### 5.5 Session and tree retention, demoted

`records.jsonl` keeps only derived observations and discards `result.session`,
so a parser fix cannot be applied retroactively - four parser fixes landed on
2026-08-28 and every earlier report is frozen wrong. This was blocking
hazard-mechanism analysis, which we are no longer doing. It remains worth having
if we ever review real model-authored diffs rather than curated trees.
**Demoted from blocking to nice-to-have.**

---

## 6. Repository, distribution, README

- **Rename** the repository to `opencode-adversarial-review`. The current name
  promises a DeepSeek-specific tool and delivers a general one. GitHub keeps
  redirects, so open PRs survive.
- **Merge PRs #1 and #2** before building, so the plugin starts from a clean
  `main`.
- **Layout:** plugin source in `plugin/`; the harness stays where it is.
- **Distribution:** publish to npm as `opencode-adversarial-review`, so install
  is `opencode plugin opencode-adversarial-review` and repo layout does not
  affect users.
- **README order**, treated as a requirement rather than a nicety, because a
  repo containing both a research harness and a plugin will otherwise confuse
  people looking for the plugin:
  1. What it does
  2. One-line install
  3. How to set your reviewer model
  4. **What to do if you have no Anthropic API key**
  5. How to run it
  6. Link to the research and the null result

---

## 7. Risks

| Risk | Mitigation |
|---|---|
| **Undocumented API surface.** `config` hook, agent/command injection and plugin options all work in 1.18.23 but are absent from the docs, so they can change without deprecation. | Startup self-check that fails loudly (3.4). Documented fallback: register a `tool` - fully documented - and drive a session via `PluginInput.client`. Not built in v1. |
| **Prompt length assumes a capable reviewer.** A small local model configured as the *reviewer* may follow a layered instruction set badly. | Note in the README. Optionally a compact prompt variant, deferred until someone needs it. |
| **The harvest is from strong-model output.** Weak-model code will hit these classes and also produce cruder failures this corpus cannot show. | Treat the attack list as a well-grounded floor, not a complete map. Revisit after real usage. |
| **`command.template` placeholder syntax unverified.** Expected `$ARGUMENTS`. | Confirm during implementation; low risk, minutes to discover. |
| **Reviewer cost is per-review and uncapped.** Opus measured at ~$0.55 per fixture-scale run. | README states the cost characteristic; the model is one config line to change. |

---

## 8. What we are giving up

The ability to say "this instruction exists because DeepSeek failed X 8/10 times
where Opus failed 0/10". That provenance was the original point, and today's
numbers say we are unlikely to earn it. What replaces it is weaker but real: a
skill validated against planted defects and negative controls, with its
false-positive rate reported.

The eval is not discarded. It answered its question - **is there a measurable
differential large enough to derive instructions from?** - and the answer, after
two fixtures rather than twelve, is no. That is published as a null result, and
the harness becomes the instrument that keeps the shipped skill honest.

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
Look here first. This ordering reflects what adversarial review actually finds
in real codebases, not what checklists usually list first.

1. TESTS THAT CANNOT FAIL. The most common serious defect, and the one that
   makes every other guarantee hollow.
2. Guards keyed on a proxy rather than the invariant.
3. Silent failure - errors swallowed, logged below alert level, or failing open.
4. Wiring: code that cannot run, or runs nothing.
5. Everything else below.

Classical appsec - injection, XSS, deserialization, path traversal, dependency
CVEs - is worth a look but is rarely where the yield is. Do not lead with it,
and do not pad a review with it.
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
