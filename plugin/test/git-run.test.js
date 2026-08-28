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
  assert.match(result.stderr, /may not begin with a dash/)
  await assert.rejects(access(join(dir, "pwned.txt")), "the file must not exist")
})

test("a tracked file is never truncated by a read", async () => {
  const dir = await fixtureRepo()
  await runGit({ mode: "diff", base: "a.txt" }, dir).catch(() => {})
  assert.equal(await readFile(join(dir, "a.txt"), "utf8"), "two\n")
})

test("git's own failure is reported, not thrown", async () => {
  const dir = await fixtureRepo()
  const result = await runGit({ mode: "show", ref: "no-such-ref" }, dir)
  assert.equal(result.ok, false)
  assert.match(result.stderr, /no-such-ref/)
})

test("output beyond the cap is truncated and flagged", async () => {
  const dir = await fixtureRepo()
  await writeFile(join(dir, "big.txt"), "x".repeat(300000) + "\n")
  await exec("git", ["add", "."], { cwd: dir })
  const result = await runGit({ mode: "diff", ref: "HEAD" }, dir)
  assert.equal(result.truncated, true)
  assert.ok(result.stdout.length <= 200200)
})
