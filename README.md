# opencode-deepseek-review

An [opencode](https://opencode.ai) plugin that reviews DeepSeek-written code
using Claude Opus 5.

> **Status: pre-release. No findings yet.**
> The evaluation described below has not been run. Nothing here is installable,
> and no claim about DeepSeek has been established. This README describes the
> method the project commits to, so it can be judged before any results exist.

## What makes this different

The checks are not somebody's opinion about how LLMs write code. Each one has to
survive a mechanically-graded differential evaluation before it may exist.

- **No model judges anything.** Grading is done by hidden test suites, static
  AST assertions, and mutation testing. A hazard either fails a test or it does
  not.
- **Opus 5 is a control arm, not a judge.** It runs identical fixtures under
  identical conditions. Its purpose is to establish what a *different* model
  does on the same task, so that "DeepSeek gets this wrong" can be distinguished
  from "LLMs get this wrong."
- **Findings where Opus is the weaker model are published too.** A one-directional
  report would be marketing.
- **A finding must replicate across two independently authored fixtures** before
  it may become an instruction. Ten repetitions of one fixture measure
  repeatability, not generality.
- **Every shipped instruction cites its evidence** - raw counts, model versions,
  configuration hash, date. A rerun that invalidates the evidence expires the
  instruction.

## Scope, stated narrowly on purpose

Findings are scoped to **DeepSeek v4-pro as driven by opencode**, under a pinned
configuration. That is an operational claim, not a claim about DeepSeek's
intrinsic code quality: a difference could come from tool-call reliability,
context compaction, or prompt sensitivity rather than from how the model writes
code. This project does not separate those and does not pretend to.

It has not been measured under any other harness, so it claims nothing about any
other harness.

## Requirements

- **opencode** - the plugin targets it specifically
- **A DeepSeek model** - what the plugin reviews
- **Anthropic API access** - the reviewer runs on Claude Opus 5, and this is a
  real cost you incur

## Method

The evaluation harness is the method, not the product. It is documented here in
enough detail to replicate, and its source may be published later.

See [the design specification](docs/superpowers/specs/2026-08-27-deepseek-review-gauntlet-design.md)
for the full design, including the visibility boundary that keeps the answer key
away from the model under test, the sterile-configuration requirements, and the
statistical rules governing what may be claimed.

## Licence

MIT
