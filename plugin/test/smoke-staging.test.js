import test from "node:test"
import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import { existsSync } from "node:fs"
import { join } from "node:path"
import { discoverTrees, stage, assertPathIsAnonymous, placeboPrompt, CONDITIONS } from "../smoke/run-smoke.mjs"
import { DEFECT_FILE } from "../smoke/grade.mjs"
import { CODE_REVIEW_PROMPT } from "../src/prompts.js"

const git = (cwd, ...args) => execFileSync("git", args, { cwd, encoding: "utf8" }).trim()

test("discovery finds both fixtures, their known_good variants and their known_bad", () => {
  const trees = discoverTrees()
  assert.equal(trees.length, 8, "2 fixtures x (3 good + 1 bad)")
  assert.equal(trees.filter((t) => t.kind === "bad").length, 2)
  for (const t of trees) assert.ok(DEFECT_FILE[t.fixture], `fixture ${t.fixture} has no recorded defect file`)
})

test("provenance is refused in a staged path, including the condition name", () => {
  for (const name of CONDITIONS().map((c) => c.name)) {
    assert.throws(() => assertPathIsAnonymous(`/tmp/x/${name}/workspace`), /leaks provenance/)
  }
  for (const marker of ["known_good", "known_bad", "py-callsite-01", "fixture", "smoke"]) {
    assert.throws(() => assertPathIsAnonymous(`/tmp/${marker}/workspace`), /leaks provenance/)
  }
  assertPathIsAnonymous("/tmp/rv-abc123/workspace")
})

test("a staged tree is two commits, and the second one IS the change under review", () => {
  const tree = discoverTrees().find((t) => t.fixture === "py-callsite-01" && t.variant === "explicit_all")
  const work = stage(tree)
  assert.equal(git(work, "rev-list", "--count", "HEAD"), "2")
  const changed = git(work, "diff", "--name-only", "HEAD~1", "HEAD").split("\n").sort()
  assert.deepEqual(changed, [
    "notifications/management/commands/send_digest.py",
    "notifications/serializers.py",
    "notifications/services.py",
    "notifications/views.py",
  ])
})

// The whole point of the known_bad tree: the defect is a call site that should
// have been updated and was not, so it is ABSENT from the diff. A reviewer that
// only reads the diff cannot possibly find it. If this ever starts appearing in
// the diff, the fixture has stopped testing what it exists to test.
test("in a known_bad tree the defect file is NOT in the diff", () => {
  for (const tree of discoverTrees().filter((t) => t.kind === "bad")) {
    const work = stage(tree)
    const changed = git(work, "diff", "--name-only", "HEAD~1", "HEAD").split("\n")
    const defect = DEFECT_FILE[tree.fixture]
    assert.ok(
      !changed.some((f) => f.endsWith(defect)),
      `${tree.fixture}: ${defect} appears in the diff, so the defect is no longer hidden`,
    )
    assert.ok(existsSync(join(work, ...(tree.fixture === "py-callsite-01"
      ? ["notifications", "management", "commands", "send_digest.py"]
      : ["pricing", "recovery.py"]))), "the defect file must still exist in the tree, just unchanged")
  }
})

test("the known_bad tree differs from its known_good sibling in exactly the defect file", () => {
  const trees = discoverTrees()
  for (const bad of trees.filter((t) => t.kind === "bad")) {
    const good = trees.find((t) => t.fixture === bad.fixture && t.variant === "explicit_all")
    // diff exits 1 when trees differ, which is the expected case here.
    let raw
    try {
      raw = execFileSync("diff", ["-rq", good.path, bad.path], { encoding: "utf8" })
    } catch (error) {
      if (error.status !== 1) throw error
      raw = error.stdout
    }
    const changed = raw.trim().split("\n").filter(Boolean)
    assert.equal(changed.length, 1, `${bad.fixture}: expected one differing file, got ${changed.length}`)
    assert.match(changed[0], new RegExp(DEFECT_FILE[bad.fixture]))
  }
})

test("the placebo is exactly the doctrine prompt's length, so size cannot explain a difference", () => {
  const conditions = CONDITIONS()
  const doctrine = conditions.find((c) => c.name === "doctrine")
  const placebo = conditions.find((c) => c.name === "placebo")
  assert.equal(doctrine.prompt, CODE_REVIEW_PROMPT)
  assert.equal(placebo.prompt.length, CODE_REVIEW_PROMPT.length)
  assert.notEqual(placebo.prompt, CODE_REVIEW_PROMPT)
  assert.equal(placeboPrompt(50).length, 50)
})

test("the placebo carries none of the doctrine's substance", () => {
  const placebo = CONDITIONS().find((c) => c.name === "placebo").prompt
  for (const term of ["call site", "REVIEW-COMPLETE", "DO-NOT-SHIP", "attack", "failure scenario"]) {
    assert.ok(!placebo.toLowerCase().includes(term.toLowerCase()), `placebo leaks doctrine content: ${term}`)
  }
})
