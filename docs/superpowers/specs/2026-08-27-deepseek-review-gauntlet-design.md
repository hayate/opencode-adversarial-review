# DeepSeek Review Gauntlet - Design

**Date:** 2026-08-27
**Status:** Revision 2, after Codex adversarial review (`task-mtb0ryfl-uhgl8f`)
**Author:** Andrea + Maya

Revision 2 rewrites sections 4-9 in response to eight findings. Codex's verdict
on revision 1 was "I would not build or publish this as written." The idea
survived; the method did not. Changes are summarised in section 13.

---

## 1. Purpose

Build a reviewer tuned to the failure modes of DeepSeek-authored code, so that
Opus 5 reviewing DeepSeek's output in opencode catches what DeepSeek actually
gets wrong, not what LLMs generically get wrong.

Every claim the reviewer makes must trace to a reproducible, mechanically-graded
run.

### The core inversion, stated accurately

**Evidence is generated. The skill is editorially maintained against it.**

Revision 1 claimed the skill would be pure build output and that this made
maintenance a recompile. That was too strong. Re-running a fixed suite only
re-measures old hypotheses; it cannot discover failure modes a new model version
invents. The genuinely hard work - fixture selection, construct validity, grader
design, instruction wording - stays hand-authored.

What generation *does* buy, and what matters:

- Every instruction cites specific evidence, with model versions and dates.
- A rerun **expires** instructions whose evidence no longer holds, so staleness
  becomes visible instead of silent.
- Regeneration after a model bump is a reviewed diff, not a fresh research
  project.

That is a weaker claim than revision 1 made, and it is the true one.

---

## 2. What this measures, and what it does not

**The estimand is operational, not intrinsic.** The treatment under test is:

> DeepSeek v4-pro **as driven by** opencode 1.18.23, under a pinned agent
> configuration, tool set, and budget.

It is not "DeepSeek's code quality." A differential could arise from tool-call
reliability, prompt-format sensitivity, context compaction behaviour, effective
context window, provider latency causing wall-clock censoring, or default
propensity to inspect and test. This design does not separate those from code
quality and does not try to.

That is acceptable because the goal is a reviewer for the exact system Andrea
runs. It is not acceptable as a vendor-level claim, so **no published artifact
may say "DeepSeek writes X"**. The permitted form is:

> Under opencode 1.18.23 with configuration hash `<hash>`, DeepSeek v4-pro
> failed hazard `H-CALLSITE` in 8/10 runs where Opus 5 failed 1/10.

Every report, README line, and generated instruction carries this scoping.

---

## 3. Non-goals

- Not a general model benchmark. Fixtures target Python/Django/DRF and
  TypeScript/React only.
- Not a leaderboard. Raw per-hazard counts, never a composite score.
- Not single-shot evaluation. Agentic only, because that is the only mode used.
- Not a causal decomposition of *why* an arm fails (see section 2).
- Not a replacement for the existing gauntlet lenses.

---

## 4. Decisions locked

| Decision | Choice | Rationale |
|---|---|---|
| Audience | Andrea's stack first, publishing secondary | Findings verifiable by eye |
| Elicitation | Agentic only, `opencode run` | Matches real usage |
| Control arm | `claude-opus-5`, single control | Answers "what does DeepSeek do that its reviewer does not" |
| Task shape | Instrumented realistic fixtures | Realistic *and* mechanically gradable |
| Repo shape | Single repo | Keeps claims welded to evidence |
| Containment | Rootless podman, two sandboxes | Agent sandbox and grading sandbox are separate |
| Languages | Python (Django/DRF) + TypeScript (React/Node), 6 fixtures each | Andrea's stack; a third language may be added only if it brings its own replication pairs |
| Delivery | Staged: 12 fixtures, signal gate, then decide | Do not double fixture spend before knowing a differential exists |
| Published product | The skill plus its evidence reports; harness optional | The skill is the deliverable, the eval is the justification |
| Harness scope | opencode only | Consequence of the section 2 estimand, not a preference |
| Licence | MIT | Permissive, no friction to install |

### Why a control arm

Findings sort into three buckets:

1. **DeepSeek fails, Opus passes** - prime skill material; the reviewer is
   demonstrably clean, so an instruction can actually fire.
2. **Both fail** - generic LLM failure. Never a model instruction: a model
   cannot reliably catch its own blind spot. Route to a mechanical check
   (linter, test, CI gate) or drop.
3. **Opus fails, DeepSeek passes** - published honestly. Costs nothing and stops
   the repo reading as vendor-bashing.

---

## 5. The visibility boundary (normative)

Revision 1 placed the answer key beside the working repo and said only that the
runner materialises "a pristine fixture copy". The natural reading copies
`fixtures/<id>/`, which hands the agent the hazard list, hidden tests, mutants,
and both reference solutions.

**This section is a security invariant, not an implementation note.**

```
fixtures/<id>/
  repo/          <-- THE ONLY SUBTREE THE AGENT EVER SEES
  task.md            read by the host, passed as the prompt
  hazards.yaml       answer key
  grader/            hidden suite, static assertions, mutants
  known_good/        reference solutions (plural, see 7.2)
  known_bad/         hazardous reference solutions
```

Rules:

1. Only the **contents** of `repo/` are copied to `/workspace` in the agent
   container.
2. `task.md` is read on the host and supplied as the prompt string. It never
   lands in the container filesystem.
3. `hazards.yaml`, `grader/`, `known_good/`, `known_bad/` never enter the agent
   image, filesystem, mount namespace, or any image layer.
4. Symlinks, hardlinks, submodules, and `.git` indirections that resolve outside
   `repo/` are rejected at fixture-load time.
5. The agent container is **destroyed before grading**. Grading happens in a
   separate container (section 8).
6. A harness test compares the container-visible file manifest against an
   explicit allowlist and fails the run on any extra path.

Rule 6 is the enforcement. The others are intent.

---

## 6. Sterile execution environment

`--pure` means "run without external plugins" and nothing more. It does not
ignore configuration, project rules, agents, skills, or MCP servers. Verified
against the installed binary: opencode 1.18.23 exposes 58 `OPENCODE_*` variables,
and the isolation levers are all separate switches.

The existence of `OPENCODE_DISABLE_PROJECT_CONFIG` is itself proof that project
configuration is loaded by default: a fixture repo containing `AGENTS.md`,
`CLAUDE.md`, or `opencode.json` would otherwise become part of the treatment
without appearing anywhere in the record.

**Every run sets, at minimum:**

| Variable | Purpose |
|---|---|
| `OPENCODE_DISABLE_PROJECT_CONFIG` | Fixture repo config cannot leak into the treatment |
| `OPENCODE_DISABLE_CLAUDE_CODE` | No Claude Code compatibility layer |
| `OPENCODE_DISABLE_CLAUDE_CODE_PROMPT` | No inherited prompt |
| `OPENCODE_DISABLE_CLAUDE_CODE_SKILLS` | No skill injection |
| `OPENCODE_DISABLE_EXTERNAL_SKILLS` | No skill injection |
| `OPENCODE_DISABLE_DEFAULT_PLUGINS` | `--pure` covers external plugins only |
| `OPENCODE_DISABLE_AUTOCOMPACT` | **Critical.** Divergent compaction between arms is an invisible confound |
| `OPENCODE_DISABLE_MODELS_FETCH` | No remote model-list mutation mid-suite |
| `OPENCODE_DISABLE_AUTOUPDATE` | Binary cannot change under the suite |
| `OPENCODE_DISABLE_SHARE` | No session egress |
| `OPENCODE_CONFIG_CONTENT` | Canonical config injected, no file on disk |
| `OPENCODE_AUTH_CONTENT` | Arm credential injected, no `auth.json` |

### 6.0 Verified: containerisation is the sterility mechanism, not just containment

Revision 2 assumed `OPENCODE_CONFIG_CONTENT` would supply "a canonical config,
no file on disk". **That is wrong**, established empirically against opencode
1.18.23 on 2026-08-27 by A/B-ing `opencode debug config`:

| Test | Result |
|---|---|
| `--pure` plus the disable switches | **Works** for plugins and skills: superpowers' `skills.paths` and the plugin-injected agents disappear |
| `OPENCODE_DISABLE_PROJECT_CONFIG` | Disables *project* config only. The entire global `~/.config/opencode/opencode.jsonc` survives - providers, model pins, plugin list |
| `OPENCODE_CONFIG_CONTENT` | **Merges, does not replace.** An injected minimal config set `model` and `enabled_providers`, but the host's `provider.anthropic` block and plugin array came through anyway |
| Throwaway `HOME` + `XDG_CONFIG_HOME` | **Clean slate:** `model: null`, `enabled_providers: null`, `plugin: []` |

The consequence is architectural. **A sterile run is not achievable by
environment variables on the host at all.** The only mechanism that produces a
clean configuration is an isolated `HOME`, which is precisely what a container
supplies. Running the agent as a host subprocess would silently execute *both
arms* against the operator's personal global config - their providers, their
model pins - and produce numbers that look entirely normal.

Containerisation therefore serves two independent purposes: containment
(section 12) and configuration sterility. Neither is optional, and the second is
the one that silently corrupts results rather than announcing itself.

**The verified recipe, all inside the agent container:**

1. Isolated `HOME` and `XDG_CONFIG_HOME` on tmpfs, outside `/workspace`.
2. `OPENCODE_CONFIG_CONTENT` carrying the canonical config - now correct, because
   with a clean `HOME` there is nothing left to merge with.
3. `OPENCODE_AUTH_CONTENT` carrying only the arm's credential.
4. The disable switches above.
5. Verification is **deterministic, not behavioural**: assert against
   `opencode debug config`, `debug skill`, and `debug agent <name>` that no host
   configuration, skill path, or agent survived. Positive controls with isolation
   off prove each canary is observable. A stochastic canary prompt is not a valid
   isolation test and is not used.

Note that the resolved `plugin` array still *lists* declared plugins even when
they are not loaded. Isolation must be verified by what actually loaded - agents
and `skills.paths` - never by that key.

Additionally pinned per run: an immutable OCI image digest, the opencode binary
digest, `--agent` explicitly named, an allowlisted environment rather than
inherited host variables, and an exact model id rather than a moving alias.

**Model identity is enforced, not merely recorded.** Every relevant API response
is checked against the requested model id and the run **fails** on mismatch.
Provider prefix is a billing address; model id is the thing that thinks.

**Recorded per run:** hashes of the effective configuration, assembled
instructions, agent definition, and tool schema.

### 6.1 Budget enforcement

`opencode run` exposes no token-cap flag. Revision 1 specified one anyway.

Phase 1 caps on **wall-clock and turn count**, which the runner can enforce
directly. A budgeted API proxy is the correct long-term answer and is deferred
to phase 2, gated on whether phase 1 shows runaway cost is a real problem.

A run that hits a cap is a **distinct observation**, recorded as such, never
silently dropped and never counted as a hazard failure.

---

## 7. Fixtures

**v1 ships 12 fixtures: 6 Python (Django/DRF), 6 TypeScript (React/Node).**

A fixture is a small but real repo: existing conventions, more than one module,
and a believable-but-incomplete test suite, with 3-6 planted hazards. The task
brief reads like an ordinary ticket and never mentions the hazards.

The fixture's own suite is deliberately incomplete, the way a real repo is. That
makes "did the model notice the coverage gap" measurable rather than a judgement
call.

### 7.1 Hazards must be observed, not invented

A hazard drawn from a real incident in Andrea's repos outranks one derived from
first principles. Where a hazard is invented, it is marked as such in
`hazards.yaml`, and inventions are the first cut when the list must shrink.

### 7.2 Grader validation gates everything

Each grader is validated before any model run is trusted:

- Every `known_bad/` solution MUST fail the hazard it embodies.
- Every `known_good/` solution MUST pass every hazard in the fixture.
- **`known_good/` is plural.** One reference solution does not prove the grader
  accepts the valid solution space; at least three structurally different
  correct implementations are required per fixture.

A grader that does not discriminate is a finding factory. This runs in CI and
gates publication: **if grader validation fails, no results are published.**

### 7.3 Hazard taxonomy

Every hazard needs an id, a planting recipe, and a mechanical grader. Without a
grader it does not exist. The `Repl.` column follows section 9.3: **agnostic**
hazards may replicate across languages and are the premium case; **py** and **ts**
hazards must replicate within their own language.

#### Language-agnostic

| id | Planted hazard | Grader | Repl. |
|---|---|---|---|
| `H-CALLSITE` | Signature change with 3 call sites, one non-obvious (a management command, a script, a template) | Hidden tests exercise all 3 paths | agnostic |
| `H-CONTRACT` | A helper tempted into enforcing a stricter contract than the endpoint it serves | Hidden test sends input the endpoint permits | agnostic |
| `H-IDOR` | Read path must be scoped to the requesting tenant | User B fetches user A's object, expects 404 | agnostic |
| `H-SECRET` | New config value must come from env/settings | AST plus grep for literals | agnostic |
| `H-TXN` | Multi-write operation needs atomicity | Forced mid-operation failure, assert rollback | agnostic |
| `H-COVGAP` | The hazard sits in an uncovered region of the existing suite | Mutation: does an added test catch it? | agnostic |
| `H-HOLLOW` | Do added tests assert anything at all? | Mutation score (section 8.1) | agnostic |
| `H-GREEN` | A test is already failing when the agent arrives | Trace plus final state: noticed and reported, or claimed done? | agnostic |

#### Python (Django/DRF)

| id | Planted hazard | Grader | Repl. |
|---|---|---|---|
| `H-MIGRATION` | Model change requires a migration | `makemigrations --check` | py |
| `H-NPLUSONE` | List endpoint over relations | `assertNumQueries` | py |
| `H-MASSASSIGN` | Serializer temptation exposing a privileged field | POST the field, assert ignored | py |
| `H-LAYERING` | Repo separates services from views | Import-graph assertion | py |
| `H-INJECT` | A raw-SQL helper exists and the task tempts using it with user input | Payload test | py |

#### TypeScript (React/Node)

| id | Planted hazard | Grader | Repl. |
|---|---|---|---|
| `H-TSANY` | Type friction that tempts `any` or `as unknown as` | AST: no new escape hatches on the changed path | ts |
| `H-BOUNDARY` | External input crosses into typed code without parsing | Hidden test posts a shape the types claim is impossible | ts |
| `H-EFFECTDEP` | Effect with a stale-closure trap in its dependency array | Hidden test asserts the stale render is not produced | ts |
| `H-WATERFALL` | Sequential awaits in a loop where batching is available | Instrumented call counter or timing assertion | ts |
| `H-XSS` | Untrusted string rendered where escaping is bypassable | Hidden test renders a payload, asserts escaped | ts |

The two language tables deliberately mirror each other in *kind* rather than in
detail: `H-MASSASSIGN` and `H-BOUNDARY` are both "trusting the shape of external
input", `H-NPLUSONE` and `H-WATERFALL` are both "correct but quadratic". Where a
pair turns out to behave identically across both arms, that is evidence the
underlying hazard is agnostic and should be promoted to the first table.

This list is the v1 seed and is expected to shrink. Per section 7.1, hazards
Andrea has actually observed outrank invented ones, and inventions are cut first.

---

## 8. Grading

Three channels, all executed in a **second sandbox with no network and no
provider credential**, because graders run model-authored code. Revision 1 never
said where grading happened, which left the containment boundary ending exactly
before the untrusted code ran.

**Hidden functional suite** - primary signal, pass/fail per hazard, applied to a
copy of the post-run repo from outside.

**Static assertions** - AST and import-graph checks for what tests cannot see
(business logic in a view, hardcoded secret, layering violation).

**Trace assertions** - from the session JSON, these catch the expensive failures
that are invisible in the final diff:

- `T-RANTESTS` - did it ever invoke the test command?
- `T-READCALLSITES` - did it open the other call sites before editing?
- `T-CLAIMDONE` - did it report success while the hidden suite fails?
- `T-SCOPE` - did it modify files outside the task scope?

### 8.1 Test quality is graded by mutation, correctly

Revision 1 asked one binary question about one mutant and generalised it to test
quality. That is high-variance and trivially gamed.

The corrected procedure:

1. The model's tests MUST first pass against the unmutated post-run
   implementation. A failing suite is a different finding, not a mutation result.
2. Apply **several** independent, behaviourally meaningful mutants.
3. Each mutant is pre-validated: it compiles, it reaches the target behaviour,
   and it is **not already killed by the fixture's pre-existing suite**.
4. Attribute the kill to tests the model added or changed, not to inherited ones.
5. Reject kills caused by unrelated failures (import errors, fixture breakage).
6. Report a mutation score and fault matrix, never one bit.

---

## 9. Statistical method

### 9.1 Two stages

- **Exploration:** n=3 per (fixture, arm). Cheap. Produces candidates.
- **Confirmation:** entirely **fresh** runs at n=10 on that fixture, both arms.
  Fresh runs matter: reusing exploration counts would let the screen bias the
  confirmation.

### 9.2 The promotion rule

Revision 1 used `D>=6 AND O<=2`. Verified computationally, that rule's
per-hazard false-positive rate under the null peaks at **0.0278** (at p=0.406),
giving roughly **1.1 to 1.95 expected false promotions** across 40-70 hazards
and a **68-86%** chance of at least one. That is not acceptable for a published
artifact.

**Revision 2 rule: `D>=8 AND O<=1` at n=10.** Verified peak per-hazard
false-positive rate **0.00064**, giving a **4.4%** chance of at least one false
promotion across 70 hazards.

Anything between the lines is recorded as inconclusive and explicitly NOT put in
the skill. The threshold lives in one config constant so it is revised
deliberately rather than drifting per finding.

### 9.3 Cross-fixture replication is the real control

A stricter threshold controls sampling noise. It does not control **fixture
artifacts** - ten repetitions of one fixture measure repeatability on that
prompt, not generality. This is the more important rule:

> **A hazard may generate an instruction only if it replicates across two
> independently authored fixtures.**

- **Language-agnostic hazards** (call sites, hollow tests, claiming done without
  running anything) may replicate *across* languages. Python-plus-TypeScript
  replication is the **premium** case: a failure independent of language cannot
  be a framework artifact.
- **Language-specific hazards** (Django migrations, ORM N+1) must replicate
  within their language, and are correspondingly more expensive.

This is what gives Andrea's "don't degrade Python and TypeScript" constraint a
precise meaning: a third language may be added only if it brings its own
replication pairs rather than borrowing them.

### 9.4 Pre-registration

The candidate rule, thresholds, hazard list, and all graders are committed
**before** the confirmation runs execute. Reported alongside: raw counts, effect
size with confidence bounds, and a Holm correction across the confirmed family.
No p-value is presented as a headline; the sample is too small and dressing it up
would be dishonest.

---

## 10. Skill generation and validation

`./eval generate-skill` emits **candidate** instruction blocks with provenance:
hazard id, observed counts, model versions, config hash, run date.

Per section 1, the shipped skill is editorially maintained, not raw build output.
The binding constraint is that **every claim must cite currently valid
evidence**; a rerun that invalidates the evidence expires the instruction.

### 10.0 Form factor: a plugin containing a model-pinned agent

Verified against opencode 1.18.23: agent definitions carry `model`, `tools`,
`permission` and `prompt`. A `SKILL.md` carries none of those - it is
instructions only.

**This rules out shipping as a bare skill.** A skill loads into whatever model
currently drives the session, so invoking it from a DeepSeek session has DeepSeek
review its own output - exactly the blind-spot failure section 4 bucket 2 names.
The failure is silent: no error, just a weaker review. Packaging the reviewer as
a skill would make its single most important property depend on the user
remembering to switch models first.

Three layers, each load-bearing:

| Layer | Carries | Why it is needed |
|---|---|---|
| **Agent** | `model: anthropic/claude-opus-5`, read-only `tools`/`permission` | Makes the model pin structural rather than conventional. A reviewer also has no business editing |
| **Skill** | Hazard instructions plus provenance | The long, frequently regenerated part; isolating it keeps regeneration diffs clean, and `SKILL.md` is the portable format if section 16.1 is ever revisited |
| **Plugin** | Agent, skill, and executable checks | The only layer that can register real tools |

The plugin layer is what gives **bucket 2 somewhere to go.** Section 4 routes
findings where both arms fail to a mechanical check rather than a model
instruction. Markdown cannot express an AST check; a plugin can register one as a
tool. Without this layer those findings are simply discarded.

The plugin also gives the published artifact a one-line install rather than
instructions to copy files into directories.

**Cost:** a plugin is JavaScript and carries maintenance that markdown does not.
Accepted, because the alternative has a silent correctness failure.

**Degrades gracefully:** if bucket 2 is empty after phase 1, the plugin reduces
to an agent-plus-skill installer - thinner, still correct. A `/deepseek-review`
command is sugar over `@deepseek-review` and is cut if it does not earn itself.

**If the differential is thin, the skill is thin.** We publish the null result
and do not pad it with generic advice.

### 10.1 Skill validation, and its honest limits

A skill derived from evidence can still fail to work. Longer instructions are not
better instructions.

**The measurement.** On fixtures never used to derive findings: take DeepSeek
runs that failed a hazard, give Opus each diff to review under three conditions -
bare, with the generated skill, and with an **equal-length neutral checklist
placebo** - then grade mechanically on whether the review named the hazard at its
actual location. Conditions are randomised and hidden from the grading step, and
the stochastic Opus review is itself replicated.

The placebo is load-bearing. Without it, a with/without comparison cannot
distinguish hazard-specific content from the generic effect of more words.

**Reported:** precision and false-positive rate, not catch rate alone. A reviewer
that flags everything catches everything.

**Power, stated honestly.** Phase 1 has 3 holdout fixtures. Three paired
outcomes give 1/8 one-sided under a symmetric null even if all three improve.
**That is a smoke test, not a ship gate, and phase 1 does not ship a skill on
it.** The ship gate requires the phase 2 fixture expansion (section 11).

**Holdout hygiene.** Repeatedly consulting one holdout while rejecting revisions
that score lower turns it into a tuning set. Phase 2 therefore uses three
separate sets: development, validation (consulted during iteration), and a
**locked final test set consulted exactly once**.

---

## 11. Staged delivery

**Phase 1 - build and probe.** 12 fixtures, full pipeline, exploration at n=3,
confirmation at n=10 for candidates. Output: a report with raw differentials, and
candidate instruction blocks. **No skill ships.**

**Phase 1 gate.** Is there a real differential? Concretely: does at least one
hazard clear `D>=8 AND O<=1` *and* replicate across two independently authored
fixtures?

- **Yes** -> phase 2: expand to roughly 24 fixtures with development /
  validation / locked-test split, add the placebo arm, and ship the skill behind
  a real gate.
- **No** -> publish the null result and stop. Half the cost, and a genuinely
  useful finding.

This sequencing exists because "the differential may be thin" is a live,
pre-agreed risk. Doubling the dominant cost line before knowing whether any
signal exists is bad sequencing.

---

## 12. Containment

Two sandboxes, both rootless podman, fresh per run, destroyed after.

**Agent sandbox:** network restricted to the model API via an **egress proxy
with destination allowlisting**. Egress restriction is a policy that must be
enforced outside the container; rootless podman does not supply it. Host-local,
link-local, and metadata routes blocked. An ephemeral, narrowly scoped credential
with a spend ceiling, never a long-lived key. CPU, memory, PID, disk and output
limits via cgroups. `no-new-privileges`, dropped capabilities, seccomp, read-only
root filesystem with an isolated writable work volume, no host sockets.

**Grading sandbox:** no network at all, no provider credential, same hardening.
This is where untrusted model-authored code executes. Host-side preparation of a
post-run tree must never follow model-authored symlinks: a model-created link to
a host path would be dereferenced by the host before the sandbox ever starts.

**The agent sandbox is also the sterility mechanism** - see section 6.0. It is
not an optional hardening layer that a host subprocess could substitute for.

### 12.1 Slice-scoped egress exception (expires before phase 1)

The egress proxy is **not** implemented for the vertical slice. This is a
recorded exception, approved 2026-08-27, not a silent violation.

**What is deferred:** destination allowlisting. The agent container has general
network access while a provider credential is present, and it runs
model-authored shell commands.

**Mandatory compensating controls while the exception stands:**

1. ~~Credentials are **fresh, eval-only, and spend-capped**. Never the operator's
   primary keys.~~ **DEVIATION, 2026-08-27:** the slice runs on the operator's
   existing opencode credentials by explicit decision. Consequences accepted: a
   leak requires rotating the credential daily opencode work depends on, there is
   no spend ceiling, and eval spend is not separable from normal usage (which
   leaves §16.3 open rather than answered). Controls 2-4 below still apply and
   carry the safety argument on their own. Revisit before any unattended run.
2. Link-local, metadata, and host-local routes are blocked at the container.
3. Runs are **attended**. No unattended multi-run session under this exception.
4. The fixture task is a benign refactor; no fixture may contain content
   designed to induce network activity.

**Expiry:** the exception covers the vertical slice only. The proxy must exist
before phase 1's 12-fixture run, and before any unattended session, whichever
comes first. Residual risk accepted: a model-authored command could reach an
arbitrary destination during an attended slice run.

**What this covers:** shell damage outside the copied worktree, run-to-run
persistence, container-root to host-root escalation by normal means, runaway
resource use, unbounded provider spend.

**What it does not cover:** kernel or runtime escape, exfiltration through the
permitted model-API path itself, and supply-chain code fetched during package
installation inside a fixture. These are accepted, and named here so they are
accepted knowingly.

---

## 13. Changes from revision 1

| # | Codex finding | Disposition |
|---|---|---|
| 1 | Answer-key leakage | **Applied.** Section 5 is now a normative invariant with a manifest test |
| 2 | Causal claim exceeds the experiment | **Applied as language, not arms.** Section 2 names the estimand; decomposition arms declined as unnecessary for the stated goal |
| 3 | Family-wise false positives | **Applied, math verified.** Threshold to `D>=8 AND O<=1`; cross-fixture replication added as the stronger control |
| 4 | `--pure` is not sterile | **Applied.** Section 6, verified against the installed binary |
| 5 | Holdout underpowered and reused | **Applied via staging.** Phase 1 demotes it to a smoke test and ships nothing; phase 2 adds the three-way split and placebo |
| 6 | One mutant is not test quality | **Applied.** Section 8.1 |
| 7 | Containment incomplete | **Applied.** Section 12, two sandboxes |
| 8 | "Skill as build output" oversold | **Applied with modification.** Section 1 states the weaker true claim; skill is editorially maintained against generated evidence |

Also corrected: `opencode run` has no token-cap flag (verified), so section 6.1
caps on wall-clock and turns instead of specifying something unimplementable.
Reproducibility language softened from "anyone can reproduce every claim" to
rerunnable and auditable, since the APIs are proprietary and stochastic.

---

## 14. Testing the harness

TDD, before the first real eval run:

- Container-visible manifest matches the allowlist; a planted answer-key file
  makes the test fail.
- Fixture reset is byte-identical across runs.
- Trace parser extracts tool calls from a recorded session JSON.
- Every grader discriminates `known_bad` from all three `known_good` variants.
- Model-id mismatch fails the run.
- Cap-hit runs are recorded distinctly from completed runs.
- Bucketing assigns the three outcome classes correctly.
- Skill generator refuses unconfirmed or unreplicated findings.

---

## 15. Risks

| Risk | Mitigation |
|---|---|
| Thin or absent differential | Pre-agreed. Phase 1 gate publishes the null result at half cost |
| Grader manufactures findings | Multi-variant `known_good` validation gates publication |
| Answer-key leakage | Section 5 invariant plus manifest test |
| Contaminated configuration | Section 6 sterile environment, hashes recorded |
| Family-wise false positives | Stricter threshold plus cross-fixture replication |
| Fixture artifacts read as model properties | Cross-fixture, cross-language replication requirement |
| Skill well-evidenced but ineffective | Placebo-controlled validation; phase 1 ships nothing |
| Holdout becomes a tuning set | Phase 2 three-way split, locked test set consulted once |
| Findings go stale | Instructions expire when evidence is invalidated on rerun |
| Untrusted code in the grader | Separate networkless, credential-free grading sandbox |
| Reviewer-neutrality | The control arm exists precisely because Maya cannot judge a competing model by taste |

---

## 16. Publishing

**The published product is the skill, not the harness.** The evaluation is the
method by which the skill is justified, not the deliverable.

- **Licence:** MIT.
- **Repo name:** `opencode-deepseek-review`. The harness code lives here during
  development; the published surface is the skill plus its evidence.
- **Scope in the name is deliberate.** It matches the ecosystem convention
  (`opencode-claude-memory`) and makes the narrow claim visible before anyone
  reads the README.

### 16.1 Harness support is opencode-only, by construction

Section 2 commits to an operational estimand: DeepSeek v4-pro *as driven by
opencode 1.18.23* under a pinned configuration. Publishing the skill as
harness-agnostic would assert the findings hold under Cline, Roo, or Aider,
having measured none of them - the same overreach as a vendor-level claim, moved
to a different axis.

Therefore:

- **Claims are scoped to opencode.** The README states findings were measured
  under opencode and may not transfer.
- **Format stays portable.** opencode loads Claude-Code-format skills, so
  portability is close to free. We do not advertise it.
- **Harness portability is a future evidence question, not a promise.** Rerun the
  existing fixtures under a second harness and report which hazards replicate.
  Deferred to a possible phase 3; the fixtures would already exist.

### 16.2 Evidence ships with the skill

Even though the harness is not the product, the **evidence reports are published
alongside the skill**. An instruction reading "DeepSeek frequently skips
non-obvious call sites" is an opinion; the same instruction carrying `8/10 vs
1/10, opencode 1.18.23, config hash abc123, 2026-09-14, 2 independent fixtures`
is a finding.

This is what makes the expiry mechanism in section 10 legible to a reader who is
not the author. Publishing generated instructions with the numbers stripped off
would forfeit the property the whole method exists to buy.

The README documents the method in enough detail for a reader to replicate it.
Publishing the harness source is optional and may follow later.

### 16.3 Still open

1. Whether eval spend goes on a separate DeepSeek billing account to keep it
   legible against normal usage.

Resolved since revision 1: languages are Python (Django/DRF) and TypeScript
(React/Node), 6 fixtures each, a third language only if it brings its own
replication pairs (section 9.3); licence MIT; repo name
`opencode-deepseek-review`; opencode-only scope.
