# DeepSeek Review Gauntlet - Design

**Date:** 2026-08-27
**Status:** Design approved in chat, pending Codex adversarial review
**Author:** Andrea + Maya

---

## 1. Purpose

Build a reviewer tuned to the specific failure modes of DeepSeek-authored code,
so that Opus 5 reviewing DeepSeek's output in opencode catches what DeepSeek
actually gets wrong - not what LLMs generically get wrong.

The reviewer is derived from evidence, not from opinion. Every claim it makes
must trace back to a reproducible, mechanically-graded run.

### The core inversion

**The deliverable is the harness. The skill is its build output.**

A hand-written skill decays: DeepSeek ships v5, Opus improves, and the skill
keeps asserting stale claims with no way to notice. By making the skill a
generated artifact of a reproducible eval, "keep it updated" becomes a script
run and a reviewed diff, rather than a fresh research project each time.

This also makes the repo publishable. A repo asserting "here are DeepSeek's
weaknesses" is an undefended public claim about a vendor. A repo where anyone
can run `./eval run` and reproduce every claim, version-pinned and dated, is a
reference.

---

## 2. Non-goals

- **Not a general model benchmark.** Task fixtures target the stacks Andrea
  ships (Python/Django/DRF, TypeScript/React). Findings are scoped to that and
  the published README says so plainly.
- **Not a leaderboard.** We report per-hazard pass rates on a small suite, not
  an aggregate score. No composite "DeepSeek scores 7.2/10".
- **Not single-shot evaluation.** We measure DeepSeek as an agent in opencode,
  because that is the only mode Andrea uses.
- **Not a replacement for the existing gauntlet.** This adds one evidence-based
  lens; `silent-failure-hunter`, `pr-test-analyzer` and Codex stay.

---

## 3. Decisions locked

| Decision | Choice | Rationale |
|---|---|---|
| Audience | Andrea's stack first, publish as byproduct | Findings grounded in code he can verify by eye; fastest to something usable |
| Elicitation | Agentic only, `opencode run --pure` | Matches real usage; `--pure` excludes superpowers so we measure DeepSeek, not DeepSeek+plugins |
| Control arm | `claude-opus-5`, single control | Directly answers "what does DeepSeek do that its reviewer does not" |
| Task shape | Instrumented realistic fixtures | Realistic *and* mechanically gradable |
| Repo shape | Single repo, harness-as-source, skill-as-output | Keeps claims welded to their evidence |
| Containment | Rootless podman | No container runtime existed; needed for both safety and reproducibility |

### Why a control arm at all

Findings sort into three buckets:

1. **DeepSeek fails, Opus passes** - prime skill material. The reviewer is
   demonstrably clean here, so an instruction to watch for it can actually fire.
2. **Both fail** - generic LLM failure. Do NOT put in the skill as a model
   instruction: you cannot reliably ask a model to catch its own blind spot.
   Route to a *mechanical* check (linter, test, CI gate) or drop it.
3. **Opus fails, DeepSeek passes** - published honestly. Costs nothing extra and
   is what stops the repo reading as vendor-bashing.

---

## 4. Architecture

```
deepseek-review-gauntlet/
  fixtures/<fixture-id>/
    repo/              # the seeded project the agent works in
    task.md            # the brief handed to the agent
    hazards.yaml       # which hazards are planted, and where
    grader/            # HIDDEN from the agent - applied post-run
      test_*.py        # hidden test suite
      static.py        # AST / import-graph assertions
      mutants/         # mutation-testing seeds for test-quality grading
    known_good/        # reference solution - validates the grader
    known_bad/         # deliberately hazardous solution - validates the grader
  harness/
    runner.py          # drives podman + `opencode run --pure`, per-run caps
    trace.py           # parses `opencode export` session JSON
    reset.py           # restores fixture to pristine state between runs
  graders/
    hidden_suite.py    # applies grader/ into a copy of the post-run repo
    mutation.py        # test-quality grading via mutants
    trace_assert.py    # trace-level assertions
  analysis/
    bucket.py          # 3-way bucketing across arms
    confirm.py         # high-n confirmation runs for promoted findings
  skill/               # GENERATED - do not hand-edit
  reports/<date>-<models>/
```

### 4.1 Fixture anatomy

**v1 ships 12 fixtures.** A fixture is a small but *real* repo: existing
conventions, a partial test suite, more than one module, and 3-6 deliberately
planted hazards. The task
brief reads like a normal ticket and never mentions the hazards.

**The grading tests are never in the fixture repo.** If they were, both models
would simply make them pass and we would have measured test-following. The
grader is applied to a copy of the post-run repo, from outside.

The fixture's *own* test suite is deliberately believable-but-incomplete - the
way a real repo is. That makes "did the model notice the coverage gap" a
measurable behaviour rather than a judgement call.

### 4.2 Runner

For each (fixture, arm, repetition):

1. Materialise a pristine fixture copy into a rootless podman container.
2. Inject only the API credential for that arm. Egress allowed (the agent needs
   to reach the model API); no host filesystem mount beyond the fixture.
3. Run `opencode run --pure -m <arm-model> "<task brief>"` under a wall-clock
   cap and a token cap.
4. Capture: final diff, `opencode export <sessionID>` JSON, `opencode stats`,
   exit status, and whether the cap was hit.
5. Destroy the container. Never reuse.

Caps are load-bearing, not hygiene. An agent that loops can burn real money
unattended, and a run that hit a cap is a *different observation* from a run
that finished - it gets recorded as such, never silently discarded.

### 4.3 Graders

Three independent grading channels:

**Hidden test suite** - the primary signal. Pass/fail per hazard.

**Static assertions** - AST and import-graph checks for things tests cannot see
(business logic placed in a view, a secret hardcoded, a layering violation).

**Trace assertions** - derived from the session JSON. These catch the expensive
failures that are invisible in the final diff:

- `T-RANTESTS` - did it ever invoke the test command?
- `T-READCALLSITES` - did it open the files containing the other call sites
  before editing the signature?
- `T-CLAIMDONE` - did it report success while the hidden suite fails?
- `T-SCOPE` - did it modify files outside the task's scope?

**Test-quality grading is by mutation, not by inspection.** To decide whether a
model's added tests are real, we apply a known mutant to the source and check
whether the model's tests go red. A test that passes against a broken
implementation is a hollow test, and this measures that mechanically instead of
asking a model to judge test quality.

### 4.4 Grader validation - mandatory

Every grader is validated against the fixture's `known_good/` and `known_bad/`
before any model run is trusted:

- `known_bad` MUST fail the hazard it embodies.
- `known_good` MUST pass every hazard in the fixture.

A grader that does not discriminate is a finding factory. This check runs in CI
and gates the whole eval: **if grader validation fails, no eval results are
published.**

---

## 5. Hazard taxonomy (initial)

Each hazard has an id, a planting recipe, and a mechanical grader.

### Contract and call sites
- `H-CALLSITE` - signature change with 3 call sites, one non-obvious (a
  management command or template). *Grader:* hidden tests exercise all 3.
- `H-CONTRACT` - a helper tempted into enforcing a stricter contract than the
  endpoint it serves. *Grader:* hidden test sends input the endpoint permits.

### Architecture and convention
- `H-AUTHCONV` - every existing view carries a permission convention; the new
  one must too. *Grader:* unauthenticated request expects 401/403.
- `H-LAYERING` - repo separates services from views. *Grader:* import-graph
  assertion.
- `H-MIGRATION` - model change requires a migration. *Grader:*
  `makemigrations --check`.

### Security
- `H-IDOR` - queryset must be scoped to the requesting tenant. *Grader:* user B
  fetches user A's object, expects 404.
- `H-MASSASSIGN` - serializer temptation exposing a privileged field.
  *Grader:* POST the privileged field, assert ignored.
- `H-INJECT` - a raw-SQL helper exists and the task tempts using it with user
  input. *Grader:* payload test.
- `H-SECRET` - new config value must come from settings/env. *Grader:* AST +
  grep.

### Correctness at scale
- `H-NPLUSONE` - list endpoint over relations. *Grader:* `assertNumQueries`.
- `H-TXN` - multi-write operation needs atomicity. *Grader:* forced mid-op
  failure, assert rollback.
- `H-PAGINATION` - unbounded list. *Grader:* 10k rows, assert bounded response.

### Testing discipline
- `H-COVGAP` - the hazard sits in an uncovered region of the existing suite.
  *Grader:* mutation - does the model's added test catch the mutant?
- `H-HOLLOW` - do added tests assert anything? *Grader:* mutation.
- `H-GREEN` - a test is already failing when the agent arrives. Does it notice
  and report, or claim done? *Grader:* trace + final state.

This list is the v1 seed, not a closed set. Fixtures may plant additional
hazards; every hazard needs an id and a mechanical grader or it does not exist.

---

## 6. Statistical method

LLM output is stochastic. A failure seen once is not a finding.

**Two-stage design:**

- **Exploration:** n=3 per (fixture, arm). Cheap. Produces candidate findings.
- **Confirmation:** any candidate promoted toward the skill gets a targeted
  re-run at n=10 on that fixture alone, both arms. Only confirmed findings enter
  the skill.

This spends tokens where they buy certainty and nowhere else.

**Promotion criteria.** A hazard becomes skill material when, at confirmation
n=10: DeepSeek fails **>=6/10** AND Opus fails **<=2/10**. Anything between those
lines is recorded in the report as inconclusive and explicitly NOT put in the
skill.

This threshold is a declared heuristic, not a statistical test. We report raw
counts (`8/10 vs 1/10`) and never a p-value - the sample is too small for
inferential statistics and dressing it up would be dishonest. The threshold
lives in one config constant so it can be revised deliberately rather than
drifting per-finding.

**Settings are pinned and recorded.** Model ids, opencode version, temperature
where controllable, harness commit, and date go in every report. Per the
existing house rule: record the response's own model field per call. Provider
prefix is a billing address; model id is the thing that thinks.

---

## 7. Skill generation

`./eval generate-skill` emits `skill/` from confirmed findings. Each instruction
carries provenance: hazard id, observed rates, model versions, run date.

Generated, never hand-edited. If an instruction needs rewording, the generator
template changes and the skill is regenerated - otherwise the artifact drifts
from its evidence and we are back to unfalsifiable assertions.

**Form factor** is deferred until we know how many finding clusters exist -
whether that is one skill, several lenses, or an opencode plugin bundling them.
opencode already loads superpowers as a git plugin, so distribution is a solved
path either way.

**If the differential is thin,** the skill is thin. We publish the null result
honestly and do not pad it with generic advice to look substantial.

### 7.1 Skill validation - the holdout loop

A skill derived from evidence can still fail to work. Longer instructions are
not better instructions, and an instruction can be true and still not change
what the reviewer catches. The spec must be able to falsify its own output.

**Fixture split.** Of the 12 fixtures, 9 are development and 3 are holdout. The
holdout fixtures are never used to derive findings.

**The measurement.** Collect DeepSeek runs on holdout fixtures that failed a
hazard. Give Opus each resulting diff to review twice - once bare, once with the
generated skill loaded - and grade mechanically: did the review name the hazard
at its actual location? Order and identity of the two conditions are hidden from
the grading step.

**Success criterion.** The skill must raise the holdout catch rate. If it does
not, the skill is not shipped, regardless of how well-evidenced its individual
findings are. A finding can be true and useless.

**Regression guard.** The same loop runs on every regeneration. A skill revision
that lowers the catch rate is rejected. This makes the maintenance story
concrete: after a model bump, the harness tells you whether the new skill is
actually better, rather than asking anyone to eyeball a diff of instructions.

**Watch instruction count.** If catch rate peaks and then declines as findings
are added, the skill has hit an attention limit. Record the count at peak and
treat it as a budget - spend it on the highest-differential findings rather than
appending everything that passed promotion.

---

## 8. Containment

Rootless podman. Each run gets a fresh container, destroyed after. No host
mount beyond the fixture copy. Egress permitted for the model API only.

Serves two masters: safety (about 70 unattended agent runs with shell access)
and reproducibility (every run starts from a byte-identical state).

---

## 9. Testing the harness

The harness is developed TDD like any other code. Tests that must exist before
the first real eval run:

- Fixture reset produces a byte-identical tree across runs.
- Trace parser extracts tool calls from a recorded session JSON.
- Each grader discriminates `known_good` from `known_bad`.
- Runner records a cap-hit run distinctly from a completed run.
- Bucketing assigns the 3 outcome classes correctly from synthetic inputs.
- Skill generator refuses to emit unconfirmed findings.

---

## 10. Risks

| Risk | Mitigation |
|---|---|
| **Thin or absent differential** | Accepted and pre-agreed. Publish the null result; the harness remains the durable asset. |
| **Grader manufactures findings** | `known_good`/`known_bad` validation gates publication. |
| **Fixtures encode Maya's taste, not real hazards** | Every hazard must be mechanically checkable and drawn from a real pattern in Andrea's repos, not invented. |
| **Overfitting to 12 fixtures** | Report scope honestly; treat findings as hypotheses about DeepSeek, not laws. |
| **Findings go stale** | Regeneration is a script run; reports are version-pinned so staleness is visible. |
| **Skill is well-evidenced but ineffective** | Holdout validation loop (7.1); skill does not ship unless it raises catch rate. |
| **Reviewer-neutrality** | The control arm exists precisely because Maya cannot be trusted to judge a competing model by taste. |
| **Cost overrun from looping agents** | Per-run wall-clock and token caps, recorded. |

---

## 11. Open questions

1. Repo name before publishing (`deepseek-review-gauntlet` is a working title).
2. Language split across the 12 fixtures - all Python, or Python + TypeScript?
3. Licence.
4. Whether confirmation runs use a separate DeepSeek billing account to keep
   eval spend legible.
