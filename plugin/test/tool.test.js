import test from "node:test"
import assert from "node:assert/strict"
import { mkdtemp, writeFile, chmod } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { makeReviewContextTool } from "../src/tool.js"

const exec = promisify(execFile)

async function fixtureRepo() {
  const dir = await mkdtemp(join(tmpdir(), "arv-tool-"))
  await exec("git", ["init", "-q"], { cwd: dir })
  await exec("git", ["config", "user.email", "t@t"], { cwd: dir })
  await exec("git", ["config", "user.name", "t"], { cwd: dir })
  await writeFile(join(dir, "a.txt"), "one\n")
  await exec("git", ["add", "."], { cwd: dir })
  await exec("git", ["commit", "-qm", "first"], { cwd: dir })
  await writeFile(join(dir, "a.txt"), "two\n")
  return dir
}

test("the tool declares exactly the six semantic parameters", () => {
  const tool = makeReviewContextTool("/tmp")
  assert.ok(tool.description.length > 0)
  assert.deepEqual(
    Object.keys(tool.args).sort(),
    ["base", "head", "limit", "mode", "paths", "ref"],
  )
})

test("executing returns git output as text", async () => {
  const dir = await fixtureRepo()
  const tool = makeReviewContextTool(dir)
  const output = await tool.execute({ mode: "diff" }, {})
  assert.match(String(output), /\+two/)
})

test("a rejected request returns an explanatory message, not a throw", async () => {
  const dir = await fixtureRepo()
  const tool = makeReviewContextTool(dir)
  const output = await tool.execute({ mode: "diff", base: "--output=x" }, {})
  assert.match(String(output), /may not begin with a dash/)
})

test("the description tells the model it cannot pass git flags", () => {
  const tool = makeReviewContextTool("/tmp")
  assert.match(tool.description, /flag/i)
})

// --- Beyond the brief: cause and truncated must reach the model in the text ---

test("a refused request is marked as refused before git ran, not as a git failure", async () => {
  const dir = await fixtureRepo()
  const tool = makeReviewContextTool(dir)
  const output = await tool.execute({ mode: "diff", base: "--output=x" }, {})
  assert.match(String(output), /before git ran/i)
  assert.doesNotMatch(String(output), /git failed/i)
})

test("a broken environment is reported distinctly from a refusal and from a git failure", async () => {
  const tool = makeReviewContextTool("/no/such/directory/at/all")
  const output = await tool.execute({ mode: "status" }, {})
  assert.doesNotMatch(String(output), /before git ran/i)
  assert.doesNotMatch(String(output), /git failed/i)
  assert.match(String(output), /environment/i)
})

test("git's own failure preserves partial stdout produced before the failure", async () => {
  // Stand-in git binary that streams real output and then exits non-zero,
  // exactly like the one in git-run.test.js. It exercises the "git-error
  // with stdout" branch without depending on a real failure mode of git.
  const binDir = await mkdtemp(join(tmpdir(), "arv-tool-fakegit-"))
  const fakeGit = join(binDir, "git")
  await writeFile(fakeGit, "#!/bin/sh\nprintf 'partial-output-before-kill\\n'\nexit 1\n")
  await chmod(fakeGit, 0o755)

  const originalPath = process.env.PATH
  process.env.PATH = `${binDir}:${originalPath}`
  try {
    const tool = makeReviewContextTool(tmpdir())
    const output = await tool.execute({ mode: "status" }, {})
    assert.match(String(output), /partial-output-before-kill/)
    assert.match(String(output), /git failed/i)
  } finally {
    process.env.PATH = originalPath
  }
})

test("a successful but truncated read tells the model the output is incomplete", async () => {
  const dir = await fixtureRepo()
  await writeFile(join(dir, "big.txt"), "x".repeat(300000) + "\n")
  await exec("git", ["add", "."], { cwd: dir })
  const tool = makeReviewContextTool(dir)
  const output = await tool.execute({ mode: "diff", ref: "HEAD" }, {})
  assert.match(String(output), /incomplete/i)
})

test("an ordinary successful read carries no truncation notice", async () => {
  const dir = await fixtureRepo()
  const tool = makeReviewContextTool(dir)
  const output = await tool.execute({ mode: "diff" }, {})
  assert.doesNotMatch(String(output), /incomplete/i)
})

test("per-call args cannot influence which directory git runs in", async () => {
  const dir = await fixtureRepo()
  const elsewhere = await mkdtemp(join(tmpdir(), "arv-tool-elsewhere-"))
  const tool = makeReviewContextTool(dir)
  // Neither `directory` nor `cwd` is a declared parameter; a model that
  // supplies them anyway must not be able to redirect where git runs.
  const output = await tool.execute({ mode: "status", directory: elsewhere, cwd: elsewhere }, {})
  assert.match(String(output), /M a\.txt/)
})
