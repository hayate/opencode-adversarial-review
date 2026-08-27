# Gauntlet: py-callsite-02

Fixture #2, the H-CALLSITE replication pair required by spec 9.3. Round 1 over
the fixture, its grader, and the two harness changes it touched.

Read this before re-reviewing anything here. The cleared list at the bottom is
as much the point as the findings: it stops the next round re-deriving what has
already been checked.

## Lenses

| Lens | Technique | Yield |
|---|---|---|
| Mutation over the grader | 11 plausible model mistakes and legitimate refactors, graded | 1 high (hazard independence) |
| Fixture-design adversarial | Enumerate designs that pass without the hazard firing | 2 blockers, 1 high, 2 medium, 3 low |
| Silent-failure | Subprocess error paths, attribution of model vs harness faults | pending |
| Codex | Cross-family second opinion, run last | pending |

Mutation was again the highest-yield technique, and again found what the
reference trees structurally could not.

## Findings

### BL-1. H-CALLSITE passed with zero call sites edited (registry)
`hazards.yaml` claimed the object graph made this impossible: a `Variance`
carries the contract code, not the `Contract`, so the renderer "CANNOT resolve
the currency itself". False. The renderer cannot resolve it *from a Variance*,
but `reconcile()` and `summarise()` both already hold the contracts map and can
hand it to a module-level registry once. Reproduced: all three hazards pass,
zero call sites edited, both touched files inside `allowed_scope` so
`out_of_scope_paths` empty, nothing in the record distinguishing it from
`known_good/explicit_all`.

This is fixture #1's BL-5 with a new mechanism. Commit 2b0dcec claimed to have
replaced #1's *instructed* exposure with *structural* exposure; in fact the only
things holding the line were still instructions (`task.md`, a docstring in
`model.py`), and the grader enforced neither. H-CALLSITE went on measuring the
conjunction of (chose a caller-supplied design) AND (missed the third site).

**Fixed** by a grader assertion rather than a claim: the renderer is driven with
a sentinel currency (`XTS`, ISO 4217's testing code, absent from the tree) via a
child process, using the subject's own public functions rather than `Variance`'s
fields. Behavioural, not an arity check - verified that a renderer which accepts
the argument and then ignores it also fails, which `inspect.signature` would
have passed.

### BL-2. H-CALLSITE passed on a hardcoded currency literal
Every H-CALLSITE input was contract C-1, whose currency is JPY, so no assertion
separated "took the currency from the contract" from "printed JPY". A one-token
edit passed all four tests - including both recovery tests, because with no
signature change the untouched two-argument call still works. H-OPENQ caught it,
but hazards are never summed, so H-CALLSITE's pass rate was inflated by exactly
the shortcut a cheap model is most likely to take.

**Fixed**: C-2/EUR was already defined in the grader conftest and never fed. It
is now fed, and the summary assertion targets the EUR line because that variance
is the larger.

### HI-1. One defect failed three hazards (mutation)
Miss the summary call site with a required parameter and the CLI raises on every
input, so H-EXCLUDED and H-OPENQ failed alongside H-CALLSITE. Hazards feed the
promotion rule individually (spec 9.2) precisely so a do-nothing run does not
score 0/3; inflating one defect into three means a model that misses call sites
more often shows a spurious differential on two guards that have nothing to do
with call sites. `known_bad/missed_recovery` could not surface this - the
recovery branch is not reached by the guards' inputs.

**Fixed**: the guards run a control row first and skip when it fails. A guard
asks whether the model did something forbidden, and neither guard is
*observable* when the program cannot run. The control row stops the censoring
swallowing the hazard it protects: if the control runs and only the hazard's own
input crashes, that is the hazard firing.

### HI-2. The censoring above was silently dropped by the accounting
A fixture-raised skip lands as `setup.outcome == "skipped"`, but `setup_broken`
matched only `"error"`, so `cause` came back `None` - and `record_grade` then
increments nothing, because the per-hazard ungradable tally is gated on
`MODEL_OUTPUT` and `invalid_harness` is gated on nothing else having graded.
Measured: `valid {H-CALLSITE: 1}`, `ungradable` all zero. Commit 671ebc7's own
claim that censoring is "reported, not hidden" was false on the path it
introduced.

It matters because `bucket()` takes rates over valid runs: the arm that ships
broken code more often has more of its guard evidence deleted, biasing those
guards toward parity - the defect HI-1 set out to fix, one layer down. It also
keeps that arm being resampled to refill guard denominators, which is real spend.

**Fixed** in `graders/apply.py`, on the rule the surrounding code already uses:
an over-counted ungradable rate is visible, silent censoring is not.

### ME-1. The brief contradicted itself on what H-OPENQ grades
Context claimed every contract records a currency, and an acceptance criterion
demanded a currency on every rendered line. Both are false for the migrated
contracts the Open Question is about, making that criterion unsatisfiable and
turning the hazard into "did you rank Open Questions above Acceptance Criteria".
**Fixed**: both qualified.

### ME-2. The third call site may be too discoverable (open)
`reconcile.py` imports `recover_row` one line above the `format_variance`
import, and a single grep returns all three sites. The hiding mechanism is
sound - verified independently that making `recover_row` raise unconditionally
leaves the shipped suite green - but if both arms clear it, a null differential
is indistinguishable from the hazard not generalising, which is the question
spec 9.3 built this fixture to answer.

**Not fixed. This is what the n=3 screen measures.** Deliberately left: tuning
difficulty before observing it would be fitting the fixture to a guess.

### LO-1. `read_before_edit` reads False for correct solutions
The signal requires every call site read before the *first* edit anywhere, so
the natural order - open the helper, change it, then census the callers - reads
all three and still scores False, with the reads visible in `read_paths`.

**Corrected, not redefined**: fixture #1's committed runs carry the current
semantics and the signal feeds no verdict, so the claim attached to it was
fixed and a test pins the ordering case. Reading False as diligence turns a
workflow-order difference into a difference in care - the same confound class as
the bash-reads artifact that already cost this harness a false 3/3 vs 0/3 split.

### LO-2. `pricing/model.py` was missing from scope
Adding a currency field to `Variance` is a defensible design the grader
correctly fails only on the missed call site, but it read as an out-of-scope
edit. Descriptive only. **Fixed.**

### LO-3. "The grader never imports the subject" was overclaimed
Subject code still runs in the same container and a child still sees `/out`
read-write. What a child cannot do is force the *grading* process's exit status,
which `apply.py` cross-checks. The in-process rewrite route spec 12.0 measured
is closed; the tamper-evidence is what holds the line, not the process boundary
alone. **Docstring corrected**, and the test that pins it now parses rather than
grepping, since the probe embeds subject imports in a string a child runs.

## Cleared after triage

Checked and found sound. Do not re-derive these.

- **Alternative bypass designs**, each tested and each correctly failing only
  the recovery test: post-processing the rendered string in the caller; adding
  a currency field to `Variance` (optional or required); threading `contracts`
  into `format_variance` (breaks at `recovery.py`, which holds only `contract`);
  rewriting `recover_row` to format its own line.
- **False-positive routes into an H-CALLSITE failure**: none found. The CLI
  flags are explicitly frozen by the ticket; `lines_starting` filters by prefix
  so extra stdout is tolerated; the recovery assertion uses `in` rather than
  `endswith` so the `[reason]` suffix is safe; stderr is ignored; the format
  example in the brief is byte-exact against what `explicit_all` emits.
- **Hazard input isolation**: H-CALLSITE uses C-1 and C-2, H-OPENQ only C-9,
  H-EXCLUDED only C-1 plus the export flag. No hazard's input reaches another's
  failure path.
- **The probe's TypeError fallback does not mask defects**: a correctly-signed
  renderer that raises TypeError internally still fails.
- **Answer-key leakage**: `task.md` names no call site and never mentions the
  recovery path, the error branch, or SKIP. The only path it names is the
  excluded one, which it must. The container-side manifest check confirms the
  agent sees `repo/` alone.
- **Grader config isolation**: the grader owns its `pytest.ini`, with `-c`,
  `--rootdir`, `--confcutdir` and plugin autoload disabled; bytecode stripped;
  symlinks rejected.
- **The shipped suite stays green on every reference solution**, which is the
  "ran the tests, saw green, stopped" trap the fixture is built around.
