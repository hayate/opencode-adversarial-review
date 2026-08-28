import test from "node:test"
import assert from "node:assert/strict"
import { mkdtemp, writeFile, readFile, access } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { runGit } from "../src/git-run.js"

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
