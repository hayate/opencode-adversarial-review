# The fixture smoke test

## This is not a ship gate, and cannot become one

<!-- LIMITS -->
> **Read this before quoting any number below it.** This is a smoke test. It is
> not a ship gate and it cannot become one. From spec 5.1, verbatim:
>
> - The `known_good` variants differ by one to four one-line edits and were
>   authored together. They are near-clones, not independent controls.
> - There are **two distinct planted defects** across the whole corpus. Catch
>   rate therefore moves in 16.7-point increments; the effective sample is 2,
>   not 72.
> - Even 0 false positives in 18 calls has a Wilson 95% upper bound near 17.6%.
> - The defects are synthetic and exposed through tiny curated repositories.
>   They do not represent the distribution of weak-model output.
> - **These fixtures were used to develop and repeatedly repair the harness.**
>   They are development data, not a held-out evaluation set.
> - Passing the planted grader does not prove a tree is otherwise defect-free,
>   so a genuine unrelated finding would be miscounted as a false positive.
>
> What it is good for: catching gross regressions - a prompt that finds nothing,
> or one that floods every tree with findings. Nothing finer. No claim stronger
> than "did not regress" may be published from it.
<!-- LIMITS -->

The runner reads that block out of this file and prints it above its own table,
so the numbers cannot be read without it.

## What it measures

Three conditions against every fixture tree:

| condition | prompt |
|---|---|
| `bare` | one sentence: review this and report what you find |
| `doctrine` | the shipped `plugin/src/prompts/code-review.md`, byte for byte |
| `placebo` | a neutral checklist repeated to the doctrine prompt's exact character count |

The placebo exists so that a difference cannot be attributed to prompt *size*
alone. Its repetition is mechanical and visible in `run-smoke.mjs`; it is not a
second seriously-authored prompt and is not presented as one.

## How a tree is staged

Each run gets a fresh temp directory containing two commits:

1. the fixture's `repo/` baseline
2. the variant tree

so the change under review is a real diff. This matters for what is being
measured: in a `known_bad` tree the planted defect is a call site that should
have been updated and **was not**, so it is absent from the diff entirely. The
reviewer only finds it by reading the code around the change.

Spec 5.1 requires staging to strip provenance. The staged path is
`<tmp>/rv-XXXX/workspace` and `assertPathIsAnonymous` refuses any path
containing `known_good`, `known_bad`, `py-callsite`, `fixture`, `smoke`, or a
condition name - the condition especially, since it is the independent variable.
Condition order is shuffled per tree from a printed seed, so a surprising result
can be re-run exactly.

## How it is graded

Grading is **keyword matching over prose**, in `grade.mjs`, and is unit-tested
in `plugin/test/smoke-grade.test.js`. It has to be crude: the three conditions
produce three different output shapes, and a grader tuned to the doctrine
prompt's own output contract would be scoring the doctrine condition on a home
advantage.

One detector, two populations. It fires when the review names the defect file
**and** says something is wrong near it - naming the file alone is not enough,
because every condition lists the files it read.

- on a `known_bad` tree, firing is a **catch**
- on a `known_good` tree, firing is a **defect false positive**: it is claiming
  the planted defect in a tree that does not have it

A second, weaker column reports spec 5.1's own question - did the review report
any finding at all on a `known_good` tree. It is reported separately and second
because spec 5.1 already says why it is weak: a genuine unrelated finding is
counted as a false positive when it is nothing of the kind.

Empty reviews are counted in their own column rather than folded into "no
finding", so a run of provider failures cannot read as a quiet, well-behaved
prompt.

## Running it

```bash
node plugin/smoke/run-smoke.mjs                        # DRY: free, no model called
node plugin/smoke/run-smoke.mjs --live --replicates 3  # roughly $10-15
```

Dry run is the default deliberately. Staging, provenance stripping, condition
shuffling, discovery and grading are all verifiable without spending anything,
and in a dry run every review body is empty by construction - so a dry table
should show zero catches and zero false positives everywhere. **A dry run
showing a catch means the grader is matching something other than review
prose**, and is a bug.

Options: `--replicates N`, `--model provider/model`, `--seed N`, `--out FILE`.

Record a live run's output as `plugin/smoke/results-YYYY-MM-DD.md`.
