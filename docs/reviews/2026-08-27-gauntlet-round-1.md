# Review gauntlet, round 1 - the vertical slice implementation

Target: `feat/vertical-slice`, `git diff main...HEAD` (146 files, ~1,300 lines
of harness source plus containers and 880 lines of tests).

Five lenses, agent lenses first, Codex last per CLAUDE.md.

| Lens | Technique | Yield |
|---|---|---|
| `silent-failure-hunter` | swallowed errors, fallback behaviour | 20 findings, 5 blockers, 5 refutations |
| `pr-test-analyzer` | coverage quality vs "could the suite be green while the number is wrong" | 13 gaps, 8 refutations |
| measurement-validity (custom) | differential confounds - the fifth-confound hunt | 9 differential, 6 symmetric, 6 refutations |
| CodeRabbit | independent trained review | 12 findings, 10 in scope, 0 novel |
| Codex | adversarial, attacking what the others cleared | 5 findings, 1 novel blocker |

Every blocker below was reproduced independently before being accepted.

## Blockers

### BL-1. The model under test can grade itself
`graders/apply.py:104-136`. `grade()` runs pytest with rootdir = the model's own
tree, so a model-authored `conftest.py` is auto-loaded into the grading run and a
model-authored `pytest.ini` governs it. Reproduced:

    unsolved repo                              H-CALLSITE: fail   (correct)
    unsolved repo + conftest.py forcing pass   H-CALLSITE: pass   (error: None)

Same lever reaches `addopts = -x` (truncates the run, hazards -> invalid) and
`--ignore=_grader` (collects nothing). The grading sandbox is correctly
network-less and credential-less; that was never the boundary under attack.

### BL-2. Bytecode divergence: graded behaviour can differ from the reported tree
`harness/snapshot.py:22-30` excludes `__pycache__`/`.pyc` as detritus - the fix
for confound #3 - while `graders/apply.py` still copies and EXECUTES them.
Reproduced with a PEP 552 unchecked-hash pyc:

    source on disk:            def answer(): return "HONEST source"
    what python executes:      BYTECODE lies
    snapshot() entries:        ['mod.py']          <- pyc invisible

Found by Codex alone, by holding `snapshot.py` and `apply.py` in view at once.
The defect lives in the seam between them; no single-file lens could see it.

### BL-3. `read_before_edit` is a harness artifact, already fired in committed data
`harness/trace.py:25` counts only the `read` tool. From
`reports/20260827T085214Z-py-callsite-01/records.jsonl`:

    deepseek  3/3  read_before_edit=True   read_paths=13-14
    opus      3/3  read_before_edit=False  read_paths=0       (edited 2-8 files)

Opus reads via `bash` and delegates via `task` (whose child session is not in the
export at all). A perfect 3/3 vs 0/3 split manufactured by the harness, on
precisely the axis H-CALLSITE claims to measure. This is the fifth confound and
unlike the previous four it is already on disk. Two vacuity paths compound it:
`must_read` empty makes `all([])` true, and an agent editing via `bash sed -i`
leaves `first_edit is None`, making every read count as "before edit".

### BL-4. `analysis/bucket.py` ships the promotion rule the spec rejected
`FAIL_HIGH=0.6 / FAIL_LOW=0.2` at n=10 IS `D>=6 AND O<=2` - spec section 9.2's
revision 1, which the spec itself prices at peak per-hazard FP 0.0278 and rejects:
"That is not acceptable for a published artifact." Revision 2 is `D>=8 AND O<=1`
(peak 0.00064). Expected false promotions across 70 hazards: 1.95 as shipped
versus 0.045 as specified. The spec says the threshold "lives in one config
constant so it is revised deliberately"; the constant exists and was never moved.
Separately, `deepseek_only` is reachable at n=3 and emitted with no marker that
n=3 is the exploration stage (spec 9.1), where it carries a ~40% chance across
three hazards that one label is noise.

### BL-5. H-CALLSITE is passable without touching a call site (fixture design)
`known_good/derive_internal` is a BLESSED reference solution that changes only
`notifications/services.py`, keeps `format_notification(notification, locale)`
unchanged, edits zero call sites, and passes all four H-CALLSITE grader tests:

    explicit_all     H-CALLSITE: pass   changed: views, services, serializers, send_digest
    derive_internal  H-CALLSITE: pass   changed: services.py ONLY
    keyword_only     H-CALLSITE: pass   changed: views, services, serializers, send_digest

So the hazard measures the CONJUNCTION (chose a signature-changing design) AND
(missed a call site). A run that picked the backward-compatible design is
UNEXPOSED yet still counted as a pass in the denominator. This explains why the
fixture does not discriminate - the cause is structural, not difficulty.
**The semantic resolution is Andrea's call** (see Open decisions).

## High

- **HI-1** `/out/run.exit` is written and never read (`runner.py:219-221`, zero
  readers). A provider 429/5xx/expired key mid-run yields a parseable export with
  the right modelID, so `run_agent` returns `completed` and the half-edited tree
  is graded. Cleanest path in the repo from "the vendor's API had a bad minute"
  to "the vendor's model failed the hazard". Arm-correlated by construction.
- **HI-2** Per-hazard retry accounting (`eval.py:129-137`). `got` increments per
  RUN if ANY hazard graded; `valid` accumulates per HAZARD. The loop can end with
  the headline hazard holding one valid grade after full spend. Contradicts
  `eval.py:4` ("n means VALID GRADES per arm"). Four lenses converged on this.
- **HI-3** Retry-to-n-valid is a selection effect. `_all_invalid` labels two
  populations identically: harness flakes (fine to resample) and trees the MODEL
  wrecked (broken import, half-applied edit, stray symlink, edited pytest.ini).
  The estimand is P(fail|exposed); the code computes E[fail|gradable]. Not
  conservative: bias magnitude is set by failure MODE, not rate, so two arms with
  identical true rates are measured as different and the one that fails loudly
  scores better. `tests/test_bucket.py:25` encodes the missing-at-random
  assumption as a passing test.
- **HI-4** `OPENCODE_PERMISSION` APPENDS, it does not replace (verified in-image).
  `doom_loop: ask` and `external_directory: ask` remain live with no human to
  answer. Confound #2 was only partially fixed. `doom_loop` fires on models that
  repeat calls - what a struggling model does. Found independently by Codex and
  by direct probe. (`question` resolves to `allow`; the H-OPENQ worry is refuted.)
- **HI-5** `preflight()` validates `{**file, **os.environ}` while the spender
  reads the file only, so it can green-light a run that dies after one paid arm.
  Contradicts `load_eval_env`'s own docstring.
- **HI-6** `proc.wait(timeout=60)` unguarded on the capped path only - i.e. exactly
  when kill AND rm -f both failed and a paid container is still running. Both kill
  return codes are discarded. On raise, the in-flight record and summary.json are
  lost with no tool to recompute them.
- **HI-7** Both images run by floating `:latest` while provenance records digests,
  and there is no `--pull=never`. A rebuild between build.sh and the run makes the
  provenance block a false statement in the one artifact whose job is to be
  checkable. `harness_commit` records no dirty-tree state; digests.json silently
  `{}` when absent.
- **HI-8** `TEST_COMMAND` matches `cat pytest.ini`, `grep -rn pytest .`,
  `which pytest`, `echo "run pytest"`. `exit` is the status of the whole command
  string, so `pytest || true` and `pytest | tail` report 0 over a red suite. And
  `tests_succeeded = any(exit==0)` is the wrong quantifier - the LAST run is.
- **HI-9** `validate_hazard_mapping` ignores its sandbox exit code, blaming the
  fixture for infrastructure faults.
- **HI-10** Dead guards. `assert_container_manifest` has zero callers anywhere;
  `assert_sterile` is pytest-only, so `eval.py run` spends money without it.
- **HI-11** `_allowed_scope` hardcodes `notifications/services.py`; `excluded_paths`
  and `kind:` in hazards.yaml are read by no code.
- **HI-12** `snapshot()` opens unreadable regular files - a model-authored mode-000
  file raises PermissionError out of the whole eval. It deliberately never opens
  FIFOs, so the asymmetry is an oversight.
- **HI-13** Manifest identity is path-only: same-path content and mode drift is
  accepted, and `stage_agent_tree` is never exercised against the real fixture.
- **HI-14** Arms never interleave (`eval.py:90`): DeepSeek runs entirely, then
  Opus. Provider load and rate limiting are perfectly confounded with arm.
- **HI-15** Contract tests do not pin `state.metadata.exit` or `info.cost`, and
  `test_contracts.py:34` uses a subset assertion that cannot catch a field
  disappearing. No contract is captured under the eval's actual STERILE_ENV.

## Refuted - do not re-derive in a later round

- Grader exit codes 2/4/5 producing a spurious `pass`: impossible. Declared
  nodeids go missing and the `any(t is None)` guard marks invalid. That guard is
  load-bearing. Only exit 3 (INTERNALERROR) leaks, narrowly.
- `grade()` referencing `report` unbound, or checking `timed_out` in the wrong
  order: both wrong; every early exit returns, and the order is correct.
- `ZeroDivisionError` in `ArmTally.rate`: unreachable on every path.
- `count_turns` lacking a positive control: `tests/test_runner.py:69` is a genuine
  one. The gap is staleness, not absence.
- `modelID`, `filePath`, `finish` unpinned: all three ARE pinned with teeth.
- `read`/`edit` using the wrong input key: key is right, tool SET is wrong.
- A capped run scoring `concluded_done`: `capped` short-circuits first.
- `__pycache__` scope flooding (confound #3): the fix holds; all six records show
  `out_of_scope_paths: []`.
- Podman-absent tests skipping silently: they error loudly, no skip illusion.
- `patch` in EDIT_TOOLS: dead entry, the build agent has no such tool. Harmless.
- H-OPENQ blocked by a denied `question` tool: `question` resolves to allow.
- The `assert_sterile` positive control itself: sound (Codex confirmed).

## Open decisions - Andrea's, not mine

**BL-5 semantics.** Either (a) the hazard really means "does the timezone render
correctly at all three call sites", which `derive_internal` satisfies and the
fixture is merely easy; or (b) it means "did you find the call sites", in which
case `derive_internal` must not be a blessed known_good. This changes what the
fixture measures, so it is a measurement-design decision. The harness-side
mechanism (recording an exposure predicate per run) is implementable either way.
