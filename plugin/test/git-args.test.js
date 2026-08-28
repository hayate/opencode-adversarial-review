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
