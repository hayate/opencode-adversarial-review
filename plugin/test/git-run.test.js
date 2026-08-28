import test from "node:test"
import assert from "node:assert/strict"
import { mkdtemp, writeFile, readFile, access } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { runGit, execOptions, MAX_OUTPUT, TIMEOUT_MS } from "../src/git-run.js"

const exec = promisify(execFile)

async function fixtureRepo() {
  const dir = await mkdtemp(join(tmpdir(), "arv-git-"))
  await exec("git", ["init", "-q"], { cwd: dir })
  await exec("git", ["config", "user.email", "t@t"], { cwd: dir })
  await exec("git", ["config", "user.name", "t"], { cwd: dir })
  await writeFile(join(dir, "a.txt"), "one\n")
  await exec("git", ["add", "."], { cwd: dir })
  await exec("git", ["commit", "-qm", "first"], { cwd: dir })
  await writeFile(join(dir, "a.txt"), "two\n")
  return dir
}

test("returns the working-tree diff", async () => {
  const dir = await fixtureRepo()
  const result = await runGit({ mode: "diff" }, dir)
  assert.equal(result.ok, true)
  assert.match(result.stdout, /-one/)
  assert.match(result.stdout, /\+two/)
})

test("status uses porcelain", async () => {
  const dir = await fixtureRepo()
  const result = await runGit({ mode: "status" }, dir)
  assert.match(result.stdout, /^ M a\.txt$/m)
})

test("a rejected request never reaches git", async () => {
  const dir = await fixtureRepo()
  const result = await runGit({ mode: "diff", base: "--output=pwned.txt" }, dir)
  assert.equal(result.ok, false)
  assert.equal(result.cause, "refused")
  assert.match(result.stderr, /may not begin with a dash/)
  await assert.rejects(access(join(dir, "pwned.txt")), "the file must not exist")
})

test("a successful read leaves the tracked file untouched", async () => {
  const dir = await fixtureRepo()
  const result = await runGit({ mode: "diff", paths: ["a.txt"] }, dir)
  assert.equal(result.ok, true)
  assert.equal(result.cause, null)
  assert.match(result.stdout, /-one/)
  assert.match(result.stdout, /\+two/)
  assert.equal(await readFile(join(dir, "a.txt"), "utf8"), "two\n")
})

test("git's own failure is reported, not thrown", async () => {
  const dir = await fixtureRepo()
  const result = await runGit({ mode: "show", ref: "no-such-ref" }, dir)
  assert.equal(result.ok, false)
  assert.equal(result.cause, "git-error")
  assert.match(result.stderr, /no-such-ref/)
})

test("a broken environment is reported distinctly from a git failure", async () => {
  const result = await runGit({ mode: "status" }, "/no/such/directory/at/all")
  assert.equal(result.ok, false)
  assert.equal(result.cause, "harness-error")
  assert.match(result.stderr, /ENOENT/)
})

test("output beyond the cap is truncated and flagged", async () => {
  const dir = await fixtureRepo()
  await writeFile(join(dir, "big.txt"), "x".repeat(300000) + "\n")
  await exec("git", ["add", "."], { cwd: dir })
  const result = await runGit({ mode: "diff", ref: "HEAD" }, dir)
  assert.equal(result.ok, true)
  assert.equal(result.cause, null)
  assert.equal(result.truncated, true)
  assert.ok(result.stdout.length <= 200200)
})

test("output past the node maxBuffer is a successful truncated read, not a failure", async () => {
  const dir = await fixtureRepo()
  await writeFile(join(dir, "huge.txt"), "x".repeat(1000000) + "\n")
  await exec("git", ["add", "."], { cwd: dir })
  const result = await runGit({ mode: "diff", ref: "HEAD" }, dir)
  assert.equal(result.ok, true)
  assert.equal(result.cause, "max-buffer")
  assert.equal(result.truncated, true)
  assert.ok(result.stdout.length <= 200200)
  assert.match(result.stderr, /exceeded the buffer/)
  assert.doesNotMatch(result.stderr, /maxBuffer length exceeded/)
})

// The three tests below are structural, not behavioural: they assert that
// the right options reach execFile, not that a kill actually happens under
// process boundaries. A real behavioural test for the SIGKILL escalation
// would have to wait out the real TIMEOUT_MS to observe the bound, which we
// do not want in this suite. The realistic regression these guard against is
// deletion of a line (dropping killSignal, or spreading ...process.env back
// in), not a change to Node's own signal semantics - which is exactly what a
// structural check on the options object catches.
test("execOptions sets killSignal to SIGKILL, not the SIGTERM default", () => {
  const options = execOptions("/some/dir")
  assert.equal(options.killSignal, "SIGKILL")
})

test("execOptions passes only PATH, HOME and GIT_TERMINAL_PROMPT through", () => {
  const options = execOptions("/some/dir")
  assert.deepEqual(Object.keys(options.env).sort(), ["GIT_TERMINAL_PROMPT", "HOME", "PATH"])
})

test("execOptions pins timeout and maxBuffer to the module's own constants", () => {
  const options = execOptions("/some/dir")
  assert.equal(options.timeout, TIMEOUT_MS)
  assert.equal(options.maxBuffer, MAX_OUTPUT * 4)
})
