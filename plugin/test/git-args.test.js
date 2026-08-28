import test from "node:test"
import assert from "node:assert/strict"
import { buildGitArgs, GitRequestError } from "../src/git-args.js"

test("diff builds a safe argv with no-ext-diff and no-textconv", () => {
  assert.deepEqual(
    buildGitArgs({ mode: "diff", base: "main", head: "HEAD" }),
    ["diff", "--no-ext-diff", "--no-textconv", "main...HEAD", "--"],
  )
})

test("paths are placed after the -- separator", () => {
  assert.deepEqual(
    buildGitArgs({ mode: "diff", base: "main", paths: ["src/a.js", "src/b.js"] }),
    ["diff", "--no-ext-diff", "--no-textconv", "main", "--", "src/a.js", "src/b.js"],
  )
})

test("log applies the limit as a bounded integer", () => {
  assert.deepEqual(
    buildGitArgs({ mode: "log", limit: 5 }),
    ["log", "--no-ext-diff", "--no-textconv", "-n", "5", "--"],
  )
})

test("status and files take no diff options", () => {
  assert.deepEqual(buildGitArgs({ mode: "status" }), ["status", "--porcelain"])
  assert.deepEqual(buildGitArgs({ mode: "files" }), ["ls-files"])
})

for (const bad of [
  { mode: "diff", base: "--output=/tmp/pwned" },
  { mode: "diff", head: "--output=/tmp/pwned" },
  { mode: "diff", paths: ["--output=/tmp/pwned"] },
  { mode: "log", ref: "-c" },
  { mode: "show", ref: "--exec-path=/tmp" },
  { mode: "diff", base: "-p" },
  { mode: "diff", paths: ["-anything"] },
]) {
  test(`rejects a leading-dash value: ${JSON.stringify(bad)}`, () => {
    assert.throws(() => buildGitArgs(bad), GitRequestError)
  })
}

test("rejects an unknown mode", () => {
  assert.throws(() => buildGitArgs({ mode: "push" }), GitRequestError)
  assert.throws(() => buildGitArgs({ mode: "gc" }), GitRequestError)
})

test("rejects a non-integer or out-of-range limit", () => {
  assert.throws(() => buildGitArgs({ mode: "log", limit: "5; rm -rf /" }), GitRequestError)
  assert.throws(() => buildGitArgs({ mode: "log", limit: 0 }), GitRequestError)
  assert.throws(() => buildGitArgs({ mode: "log", limit: 100000 }), GitRequestError)
})

test("rejects a path escaping the repository", () => {
  assert.throws(() => buildGitArgs({ mode: "diff", paths: ["../../etc/passwd"] }), GitRequestError)
  assert.throws(() => buildGitArgs({ mode: "diff", paths: ["/etc/passwd"] }), GitRequestError)
})

test("rejects a NUL byte anywhere", () => {
  assert.throws(() => buildGitArgs({ mode: "diff", base: "main\u0000--output=x" }), GitRequestError)
})

test("head without base is rejected, not silently discarded", () => {
  assert.throws(
    () => buildGitArgs({ mode: "diff", head: "abc123" }),
    (err) => err instanceof GitRequestError && /head requires base/i.test(err.message),
  )
})

test("ref combined with head is rejected, not silently ignored", () => {
  assert.throws(
    () => buildGitArgs({ mode: "diff", head: "abc123", ref: "x" }),
    (err) => err instanceof GitRequestError && /ref.*(cannot|may not) be combined with base or head/i.test(err.message),
  )
})

test("ref combined with base is rejected", () => {
  assert.throws(
    () => buildGitArgs({ mode: "diff", base: "main", ref: "x" }),
    (err) => err instanceof GitRequestError && /ref.*(cannot|may not) be combined with base or head/i.test(err.message),
  )
})

test("base combined with a benign head produces a range", () => {
  assert.deepEqual(
    buildGitArgs({ mode: "diff", base: "main", head: "abc123" }),
    ["diff", "--no-ext-diff", "--no-textconv", "main...abc123", "--"],
  )
})

test("rejects when a later paths element is malicious", () => {
  assert.throws(
    () => buildGitArgs({ mode: "diff", paths: ["src/ok.js", "--output=/tmp/pwned"] }),
    GitRequestError,
  )
})

test("rejects mid-string upward traversal", () => {
  assert.throws(
    () => buildGitArgs({ mode: "diff", paths: ["src/../../etc/passwd"] }),
    GitRequestError,
  )
})

test("rejects a non-array paths value instead of throwing an unhandled TypeError", () => {
  for (const bad of [5, true, {}, "src/a.js"]) {
    assert.throws(
      () => buildGitArgs({ mode: "diff", paths: bad }),
      (err) => err instanceof GitRequestError && /paths must be an array/i.test(err.message),
      `paths: ${JSON.stringify(bad)} should be rejected as a GitRequestError`,
    )
  }
})

test("rejects a non-string element inside an otherwise valid paths array", () => {
  assert.throws(
    () => buildGitArgs({ mode: "diff", paths: ["src/ok.js", 5] }),
    GitRequestError,
  )
})
