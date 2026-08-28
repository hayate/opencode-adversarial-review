import test from "node:test"
import assert from "node:assert/strict"
import { mkdtemp, writeFile, chmod } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { makeReviewContextTool, safelyToText } from "../src/tool.js"

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

test("git-error with partial stdout puts the incompleteness notice at the head too", async () => {
  // Finding 2, fix round 2: the head notice was verified present on the
  // success path but nothing pinned it on the git-error-with-partial-stdout
  // path - a guard nothing tests is a guard a future change can silently
  // drop. Same fake-git-on-PATH technique as the test above, but this
  // script emits enough stdout that a regression to tail-only placement
  // would push the notice past the first 200 characters, the same way the
  // success-path test catches it.
  const binDir = await mkdtemp(join(tmpdir(), "arv-tool-fakegit-head-"))
  const fakeGit = join(binDir, "git")
  await writeFile(
    fakeGit,
    "#!/bin/sh\n" +
      "printf 'partial-output-before-kill\\n'\n" +
      "i=0\n" +
      'while [ "$i" -lt 30 ]; do\n' +
      "  printf 'padding-line-to-push-total-length-past-two-hundred-characters-%d\\n' \"$i\"\n" +
      "  i=$((i + 1))\n" +
      "done\n" +
      "exit 1\n",
  )
  await chmod(fakeGit, 0o755)

  const originalPath = process.env.PATH
  process.env.PATH = `${binDir}:${originalPath}`
  try {
    const tool = makeReviewContextTool(tmpdir())
    const output = await tool.execute({ mode: "status" }, {})
    const text = String(output)
    assert.match(text.slice(0, 200), /incomplete/i)
    assert.match(text, /partial-output-before-kill/)
  } finally {
    process.env.PATH = originalPath
  }
})

test("a successful but truncated read puts the incompleteness notice at the head, not just the tail", async () => {
  const dir = await fixtureRepo()
  await writeFile(join(dir, "big.txt"), "x".repeat(300000) + "\n")
  await exec("git", ["add", "."], { cwd: dir })
  const tool = makeReviewContextTool(dir)
  const output = await tool.execute({ mode: "diff", ref: "HEAD" }, {})
  const text = String(output)
  // A trailing-only marker is the first thing lost under a head-preserving
  // truncation somewhere downstream (a UI cap, a context-window trim). A
  // test that only checks presence anywhere in `text` would pass even with
  // the notice stuck 200000 characters in, behind the whole diff - so this
  // asserts it is within the first slice of the response, not merely
  // somewhere in it.
  assert.match(text.slice(0, 200), /incomplete/i)
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

// --- Fix round 1: a non-iterable paths must never escape as a raw throw ---

test("a non-iterable paths value returns an explanatory message, not a throw", async () => {
  const dir = await fixtureRepo()
  const tool = makeReviewContextTool(dir)
  for (const bad of [5, true, {}]) {
    const output = await tool.execute({ mode: "diff", paths: bad }, {})
    assert.match(String(output), /paths must be an array/i)
  }
})

// --- Fix round 2: the "runGit throws something unexpected" guarantee is
// reachable through the real production path - execute() -> runGit() ->
// buildGitArgs() - without any test-only injection seam. A getter that
// throws on access, and a Proxy that throws on any property access, both
// make buildGitArgs's plain property reads (`request?.mode`, `request.paths
// ?? []`) raise a non-GitRequestError synchronously, which is exactly the
// shape safelyToText exists to catch. These exercise the real call chain
// end to end. ---

test("execute never throws when args.paths is a throwing getter", async () => {
  const dir = await fixtureRepo()
  const tool = makeReviewContextTool(dir)
  const args = { mode: "diff" }
  Object.defineProperty(args, "paths", {
    enumerable: true,
    get() {
      throw new TypeError("boom from a throwing paths getter")
    },
  })
  const output = await tool.execute(args, {})
  assert.match(String(output), /unexpected/i)
  assert.match(String(output), /boom from a throwing paths getter/)
})

test("execute never throws when args itself is a proxy that throws on property access", async () => {
  const dir = await fixtureRepo()
  const tool = makeReviewContextTool(dir)
  const args = new Proxy(
    {},
    {
      get() {
        throw new TypeError("boom from a proxy trap")
      },
    },
  )
  const output = await tool.execute(args, {})
  assert.match(String(output), /unexpected/i)
  assert.match(String(output), /boom from a proxy trap/)
})

// --- Fix round 2: safelyToText is tested directly against a thunk that
// throws and one that rejects, replacing the round-1 tests that reached the
// same code through an injected runGit. makeReviewContextTool takes only
// `directory` again - the seam added no coverage that these two, plus the
// two behavioural tests above, do not already provide. ---

test("safelyToText returns an explanatory message when the operation throws synchronously", async () => {
  const output = await safelyToText(() => {
    throw new TypeError("boom from a thunk that throws")
  })
  assert.match(String(output), /unexpected/i)
  assert.match(String(output), /boom from a thunk that throws/)
})

test("safelyToText returns an explanatory message when the operation's promise rejects", async () => {
  const output = await safelyToText(() => Promise.reject(new Error("rejected, not thrown")))
  assert.match(String(output), /unexpected/i)
  assert.match(String(output), /rejected, not thrown/)
})
