# Adversarial Review Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an opencode plugin that runs adversarial code review and adversarial design review using a reviewer model the user configures, independent of the model driving their session.

**Architecture:** A single ESM JavaScript plugin module registers one tool (`review_context`, a sandboxed git reader that is the security boundary) and, through opencode's undocumented `config` hook, injects two read-only subagents and two commands. The reviewer model comes from plugin options in `opencode.jsonc`, defaulting to `anthropic/claude-opus-5`.

**Tech Stack:** Plain ESM JavaScript (no build step, no TypeScript compile), Node >= 18.18, `node:test` + `node:assert/strict` for tests, `node:child_process.execFile` for git. Zero runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-08-28-adversarial-review-plugin-design.md`

## Global Constraints

- **Zero runtime dependencies.** The plugin ships no `dependencies` in `package.json`.
- **Plain ESM JavaScript only.** No TypeScript compile step. `"type": "module"`.
- **Node >= 18.18**, declared in `engines`.
- **Reviewer default is `anthropic/claude-opus-5`**, overridable via plugin options.
- **The reviewer never writes.** No `edit`, `write`, `patch`, or `bash` tool, and `permission: { edit: "deny", bash: "deny", webfetch: "deny" }`.
- **The model supplies no git flags.** `review_context` accepts semantic parameters only and builds the argv itself.
- **Every review output ends with a line containing only `REVIEW-COMPLETE`.**
- **API-key authentication only.** No `claude` CLI path, ever.
- **Package name:** `opencode-adversarial-review`. Plugin source lives in `plugin/`.
- **No em dashes in any prose this project emits.** Use a plain dash.
- **Tests run with `node --test plugin/test/`** and must pass before every commit.

---

## Task 0: Land the base

**Files:**
- Modify: none (git operations only)

**Interfaces:**
- Consumes: nothing
- Produces: a `main` containing the harness, fixtures and reports, and a working branch cut from it

Spec section 6 requires PRs #1 and #2 merged before building. This branch (`design/adversarial-review-plugin`) was cut from `main`, which has only the scaffold, so the plugin branch must be re-cut after the merge or it will not see `fixtures/` for Task 11.

- [ ] **Step 1: Confirm both PRs are green and merge them**

```bash
cd ~/srv/opencode-deepseek-review
gh pr view 1 --json mergeable,mergeStateStatus --jq '.mergeable, .mergeStateStatus'
gh pr view 2 --json mergeable,mergeStateStatus --jq '.mergeable, .mergeStateStatus'
gh pr merge 1 --merge
gh pr merge 2 --merge
```

Merge #1 first; it is the base of the stack.

- [ ] **Step 2: Open a PR for the spec branch and merge it**

```bash
git push -u origin design/adversarial-review-plugin
gh pr create --title "Spec: adversarial review plugin for opencode" --body "See docs/superpowers/specs/2026-08-28-adversarial-review-plugin-design.md. Codex spec review folded in; disposition table in section 9."
```

- [ ] **Step 3: Cut the implementation branch from the merged main**

```bash
git checkout main && git pull
git checkout -b feat/adversarial-review-plugin
```

- [ ] **Step 4: Verify the harness still passes on the merged main**

Run: `.venv/bin/python -m pytest -q`
Expected: all tests pass (233 at time of writing).

- [ ] **Step 5: Rename the repository**

```bash
gh repo rename opencode-adversarial-review
git remote set-url origin "$(gh repo view --json url --jq .url).git"
git remote -v
```

---

## Task 1: Probe opencode's real behaviour and pin it as a contract

**Files:**
- Create: `plugin/contracts/README.md`
- Create: `plugin/contracts/probe-injection.js`
- Create: `plugin/contracts/probe-arguments.js`
- Create: `plugin/contracts/probe-interrupt.md`

**Interfaces:**
- Consumes: nothing
- Produces: documented answers to three questions that later tasks depend on. Nothing imports these files; they are evidence.

The repo already treats this as a first-class practice: `contracts/README.md` for the harness exists because "plan revision 1 wrote parsers against an imagined schema and half the bugs came from that." The published opencode plugin docs are wrong for 1.18.23 on three counts, so the same discipline applies here.

- [ ] **Step 1: Write the injection probe**

Create `plugin/contracts/probe-injection.js`:

```js
// Throwaway probe. Answers: does the config hook fire, do agent and command
// injection land in the resolved config, and do plugin options arrive?
import { appendFileSync } from "node:fs"

const LOG = process.env.PROBE_LOG
const note = (m) => { try { appendFileSync(LOG, m + "\n") } catch {} }

export const Probe = async (input, options) => {
  note("LOADED options=" + JSON.stringify(options ?? null))
  return {
    config: async (cfg) => {
      note("CONFIG HOOK FIRED")
      note("EXISTING agent keys=" + Object.keys(cfg.agent ?? {}).join(","))
      note("EXISTING command keys=" + Object.keys(cfg.command ?? {}).join(","))
      cfg.agent = cfg.agent ?? {}
      cfg.agent["probe-agent"] = {
        description: "probe", mode: "subagent",
        model: "anthropic/claude-opus-5", prompt: "probe",
        permission: { edit: "deny", bash: "deny" },
      }
      cfg.command = cfg.command ?? {}
      cfg.command["probe-cmd"] = {
        template: "probe $ARGUMENTS", agent: "probe-agent", subtask: true,
      }
    },
  }
}
```

- [ ] **Step 2: Run the injection probe and record what happened**

```bash
P=$(mktemp -d); mkdir -p "$P/.opencode/plugin"
cp plugin/contracts/probe-injection.js "$P/.opencode/plugin/"
echo '{"$schema":"https://opencode.ai/config.json"}' > "$P/opencode.json"
cd "$P" && PROBE_LOG=$P/probe.log ~/.opencode/bin/opencode debug config > cfg.json 2>err.txt
cat "$P/probe.log"
grep -o '"probe-agent"' cfg.json | head -1
grep -o '"probe-cmd"' cfg.json | head -1
```

Expected, from the earlier throwaway run: hook fires, both keys present in `cfg.json`, `options=null` for a directory-loaded plugin. Record the actual output verbatim in `plugin/contracts/README.md`.

- [ ] **Step 3: Probe the options tuple**

```bash
P=$(mktemp -d); mkdir -p "$P/ext"
cp plugin/contracts/probe-injection.js "$P/ext/"
cat > "$P/opencode.json" <<'JSON'
{"$schema":"https://opencode.ai/config.json",
 "plugin":[["./ext/probe-injection.js",{"model":"anthropic/claude-opus-5"}]]}
JSON
cd "$P" && PROBE_LOG=$P/probe.log ~/.opencode/bin/opencode debug config > cfg.json 2>err.txt
cat "$P/probe.log"
```

Expected: `LOADED options={"model":"anthropic/claude-opus-5"}`.

- [ ] **Step 4: Probe the command template placeholder**

Create `plugin/contracts/probe-arguments.js` as a copy of the injection probe whose injected command template is `echo BEGIN $ARGUMENTS END`, bound to an agent using the cheapest available model. Run `opencode run "/probe-cmd hello world"` in a scratch project and record whether the expansion contains `hello world`, the literal `$ARGUMENTS`, or something else.

If `$ARGUMENTS` does not expand, try `{{ARGUMENTS}}` and `$1`, and record which works. **Task 7 depends on this answer.**

- [ ] **Step 5: Probe mid-stream provider failure**

This is the probe spec section 3.6 requires. Force a provider failure part-way through a subagent's response and record what the calling session receives.

Cheapest reliable method: configure the injected agent with a valid provider but an **invalid API key**, run it, and record the shape.

```bash
P=$(mktemp -d); mkdir -p "$P/.opencode/plugin"
cd "$P" && ANTHROPIC_API_KEY=sk-invalid ~/.opencode/bin/opencode run "/probe-cmd review this" 2>&1 | tee interrupt.txt
```

Record in `plugin/contracts/probe-interrupt.md`: does the calling session receive a raised error, a truncated assistant message, or silence? **If it receives partial text with no error, the `REVIEW-COMPLETE` marker in Task 6 is load-bearing rather than defence in depth, and the README troubleshooting section must say so.**

- [ ] **Step 6: Write the contracts README**

Create `plugin/contracts/README.md` recording, for opencode 1.18.23: each question, the exact command run, the observed output, and the date. Follow the tone of the existing `contracts/README.md` - a table of question and answer, then the files.

State plainly which behaviours are **undocumented** and therefore may change without deprecation.

- [ ] **Step 7: Commit**

```bash
git add plugin/contracts/
git commit -m "Pin opencode 1.18.23 plugin behaviour as a contract"
```

---

## Task 2: The git argument builder

**Files:**
- Create: `plugin/src/git-args.js`
- Create: `plugin/test/git-args.test.js`

**Interfaces:**
- Consumes: nothing
- Produces: `buildGitArgs(request) -> string[]`, throwing `GitRequestError` on rejection. `request` is `{ mode, base?, head?, ref?, paths?, limit? }` where `mode` is one of `"diff" | "log" | "show" | "status" | "files"`.

This is the security boundary. **The model supplies no git flags at all** - it supplies semantic parameters, and this function builds the argv. That removes the option-allowlist problem rather than solving it: there is nothing to allow.

- [ ] **Step 1: Write the failing tests**

Create `plugin/test/git-args.test.js`:

```js
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test plugin/test/git-args.test.js`
Expected: FAIL, cannot find module `../src/git-args.js`.

- [ ] **Step 3: Write the implementation**

Create `plugin/src/git-args.js`:

```js
export class GitRequestError extends Error {}

const MODES = new Set(["diff", "log", "show", "status", "files"])
const MAX_LIMIT = 1000

function reject(why) {
  throw new GitRequestError(why)
}

// A value the model supplied. It may name a revision or a path; it may never
// begin with a dash, because every git write and exec primitive we care about
// arrives as an option - `--output=` creates or truncates a file, `-c` injects
// config, `--exec-path` relocates the binary directory.
function safeValue(value, label) {
  if (typeof value !== "string" || value.length === 0) reject(`${label} must be a non-empty string`)
  if (value.includes("\u0000")) reject(`${label} contains a NUL byte`)
  if (value.startsWith("-")) reject(`${label} may not begin with a dash: ${value}`)
  return value
}

function safePath(value) {
  const path = safeValue(value, "path")
  if (path.startsWith("/")) reject(`path must be repository-relative: ${path}`)
  if (path.split("/").includes("..")) reject(`path may not traverse upward: ${path}`)
  return path
}

function safeLimit(limit) {
  if (!Number.isInteger(limit)) reject("limit must be an integer")
  if (limit < 1 || limit > MAX_LIMIT) reject(`limit must be between 1 and ${MAX_LIMIT}`)
  return String(limit)
}

export function buildGitArgs(request) {
  const mode = request?.mode
  if (!MODES.has(mode)) reject(`unknown mode: ${String(mode)}`)

  if (mode === "status") return ["status", "--porcelain"]
  if (mode === "files") return ["ls-files"]

  // --no-ext-diff and --no-textconv stop a repository's own configuration from
  // executing a program during what is meant to be a read.
  const args = [mode, "--no-ext-diff", "--no-textconv"]

  if (mode === "log" && request.limit !== undefined) {
    args.push("-n", safeLimit(request.limit))
  }

  if (request.base !== undefined) {
    const base = safeValue(request.base, "base")
    args.push(request.head !== undefined
      ? `${base}...${safeValue(request.head, "head")}`
      : base)
  } else if (request.ref !== undefined) {
    args.push(safeValue(request.ref, "ref"))
  }

  args.push("--")
  for (const path of request.paths ?? []) args.push(safePath(path))
  return args
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node --test plugin/test/git-args.test.js`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/src/git-args.js plugin/test/git-args.test.js
git commit -m "Build git argv from semantic parameters, never model flags

The reviewer supplies a mode and values, not options. That removes the
option-allowlist problem rather than solving it: git diff, log and show all
accept --output=<path>, which creates or truncates that file, and no allowlist
permissive enough for real revision arguments reliably excludes it."
```

---

## Task 3: The git runner

**Files:**
- Create: `plugin/src/git-run.js`
- Create: `plugin/test/git-run.test.js`

**Interfaces:**
- Consumes: `buildGitArgs`, `GitRequestError` from `plugin/src/git-args.js`
- Produces: `runGit(request, cwd) -> Promise<{ ok, stdout, stderr, truncated }>`

- [ ] **Step 1: Write the failing tests**

Create `plugin/test/git-run.test.js`:

```js
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test plugin/test/git-run.test.js`
Expected: FAIL, cannot find module `../src/git-run.js`.

- [ ] **Step 3: Write the implementation**

Create `plugin/src/git-run.js`:

```js
import { execFile } from "node:child_process"
import { buildGitArgs, GitRequestError } from "./git-args.js"

const MAX_OUTPUT = 200000
const TIMEOUT_MS = 20000

// execFile, never exec: no shell means no redirection, no substitution, no
// chaining. The argv is built by buildGitArgs, so the model contributes values
// and never options.
export function runGit(request, cwd) {
  let args
  try {
    args = buildGitArgs(request)
  } catch (error) {
    if (error instanceof GitRequestError) {
      return Promise.resolve({ ok: false, stdout: "", stderr: error.message, truncated: false })
    }
    throw error
  }

  return new Promise((resolve) => {
    execFile(
      "git",
      args,
      {
        cwd,
        timeout: TIMEOUT_MS,
        maxBuffer: MAX_OUTPUT * 4,
        windowsHide: true,
        // A minimal environment. GIT_EXTERNAL_DIFF and GIT_CONFIG_* in the
        // ambient environment would otherwise reach a read.
        env: { PATH: process.env.PATH, HOME: process.env.HOME, GIT_TERMINAL_PROMPT: "0" },
      },
      (error, stdout, stderr) => {
        const truncated = stdout.length > MAX_OUTPUT
        resolve({
          ok: !error,
          stdout: truncated ? stdout.slice(0, MAX_OUTPUT) + "\n[output truncated]" : stdout,
          stderr: error ? (stderr || error.message) : stderr,
          truncated,
        })
      },
    )
  })
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node --test plugin/test/git-run.test.js`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/src/git-run.js plugin/test/git-run.test.js
git commit -m "Run git through execFile with a minimal environment

No shell, so no redirection, substitution or chaining. A pruned environment,
because GIT_EXTERNAL_DIFF and GIT_CONFIG_* in the ambient environment would
otherwise reach what is meant to be a read."
```

---

## Task 4: Register `review_context` as an opencode tool

**Files:**
- Create: `plugin/src/tool.js`
- Create: `plugin/test/tool.test.js`

**Interfaces:**
- Consumes: `runGit` from `plugin/src/git-run.js`
- Produces: `makeReviewContextTool(directory) -> ToolDefinition` with `description`, `args`, and `async execute(args, context)`

- [ ] **Step 1: Write the failing tests**

Create `plugin/test/tool.test.js`:

```js
import test from "node:test"
import assert from "node:assert/strict"
import { mkdtemp, writeFile } from "node:fs/promises"
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test plugin/test/tool.test.js`
Expected: FAIL, cannot find module `../src/tool.js`.

- [ ] **Step 3: Write the implementation**

Create `plugin/src/tool.js`:

```js
import { tool } from "@opencode-ai/plugin/tool"
import { runGit } from "./git-run.js"

const DESCRIPTION = [
  "Read repository history and diffs for review.",
  "",
  "You cannot pass git flags. Choose a mode and supply values:",
  "  mode=diff   base/head/paths  the change under review",
  "  mode=log    limit/ref/paths  recent history",
  "  mode=show   ref/paths        one commit",
  "  mode=status                  what is modified",
  "  mode=files                   what is tracked",
  "",
  "This tool only reads. It cannot write, and it is the only way you can run git.",
].join("\n")

export function makeReviewContextTool(directory) {
  return tool({
    description: DESCRIPTION,
    args: {
      mode: tool.schema.string().describe("diff | log | show | status | files"),
      base: tool.schema.string().optional().describe("base revision, e.g. main"),
      head: tool.schema.string().optional().describe("head revision; with base, produces base...head"),
      ref: tool.schema.string().optional().describe("a single revision, for show and log"),
      paths: tool.schema.array(tool.schema.string()).optional().describe("repository-relative paths"),
      limit: tool.schema.number().optional().describe("max commits for log, 1 to 1000"),
    },
    async execute(args, _context) {
      const result = await runGit(args, directory)
      if (!result.ok) return `git request refused or failed:\n${result.stderr}`
      return result.stdout || "(no output)"
    },
  })
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node --test plugin/test/tool.test.js`
Expected: all PASS.

If `@opencode-ai/plugin/tool` cannot be imported in the test environment, add it as a **devDependency** only (`npm i -D @opencode-ai/plugin`). It must not appear in `dependencies`, because opencode provides it at runtime.

- [ ] **Step 5: Commit**

```bash
git add plugin/src/tool.js plugin/test/tool.test.js
git commit -m "Expose review_context, the reviewer's only route to git"
```

---

## Task 5: Plugin options

**Files:**
- Create: `plugin/src/options.js`
- Create: `plugin/test/options.test.js`

**Interfaces:**
- Consumes: nothing
- Produces: `resolveOptions(raw) -> { model }`, `OptionsError`, `DEFAULT_MODEL`

- [ ] **Step 1: Write the failing tests**

Create `plugin/test/options.test.js`:

```js
import test from "node:test"
import assert from "node:assert/strict"
import { resolveOptions, OptionsError, DEFAULT_MODEL } from "../src/options.js"

test("defaults to claude-opus-5 when no options are given", () => {
  assert.equal(DEFAULT_MODEL, "anthropic/claude-opus-5")
  assert.equal(resolveOptions(undefined).model, DEFAULT_MODEL)
  assert.equal(resolveOptions({}).model, DEFAULT_MODEL)
})

test("accepts a provider/model reference", () => {
  assert.equal(resolveOptions({ model: "deepseek/deepseek-v4-pro" }).model, "deepseek/deepseek-v4-pro")
})

test("rejects a model reference without a provider", () => {
  assert.throws(() => resolveOptions({ model: "claude-opus-5" }), OptionsError)
})

test("rejects a non-string or empty model", () => {
  assert.throws(() => resolveOptions({ model: 5 }), OptionsError)
  assert.throws(() => resolveOptions({ model: "" }), OptionsError)
})

test("the error names the option and shows the expected shape", () => {
  try {
    resolveOptions({ model: "claude-opus-5" })
    assert.fail("should have thrown")
  } catch (error) {
    assert.match(error.message, /provider\/model/)
    assert.match(error.message, /claude-opus-5/)
  }
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test plugin/test/options.test.js`
Expected: FAIL, cannot find module `../src/options.js`.

- [ ] **Step 3: Write the implementation**

Create `plugin/src/options.js`:

```js
export class OptionsError extends Error {}

export const DEFAULT_MODEL = "anthropic/claude-opus-5"

export function resolveOptions(raw) {
  const model = raw?.model ?? DEFAULT_MODEL
  if (typeof model !== "string" || model.length === 0) {
    throw new OptionsError("opencode-adversarial-review: `model` must be a string of the form provider/model")
  }
  if (!/^[^/\s]+\/[^/\s]+/.test(model)) {
    throw new OptionsError(
      `opencode-adversarial-review: \`model\` must be provider/model, got ${JSON.stringify(model)}. ` +
      `Example: "anthropic/claude-opus-5"`,
    )
  }
  return { model }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node --test plugin/test/options.test.js`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/src/options.js plugin/test/options.test.js
git commit -m "Resolve the reviewer model from plugin options"
```

---

## Task 6: The prompts, and the completion marker they must carry

**Files:**
- Create: `plugin/src/prompts/code-review.md`
- Create: `plugin/src/prompts/design-review.md`
- Create: `plugin/src/prompts.js`
- Create: `plugin/test/prompts.test.js`

**Interfaces:**
- Consumes: nothing
- Produces: `CODE_REVIEW_PROMPT`, `DESIGN_REVIEW_PROMPT`, `COMPLETION_MARKER` (the string `"REVIEW-COMPLETE"`), `isComplete(text) -> boolean`

The prompt bodies are **copied verbatim** from the spec's Appendix A and Appendix B. Do not paraphrase them; they are the design.

- [ ] **Step 1: Write the failing tests**

Create `plugin/test/prompts.test.js`:

```js
import test from "node:test"
import assert from "node:assert/strict"
import {
  CODE_REVIEW_PROMPT, DESIGN_REVIEW_PROMPT, COMPLETION_MARKER, isComplete,
} from "../src/prompts.js"

test("both prompts are substantial and load from disk", () => {
  assert.ok(CODE_REVIEW_PROMPT.length > 2000)
  assert.ok(DESIGN_REVIEW_PROMPT.length > 2000)
})

test("both prompts require the completion marker as the last line", () => {
  for (const prompt of [CODE_REVIEW_PROMPT, DESIGN_REVIEW_PROMPT]) {
    assert.ok(prompt.includes(COMPLETION_MARKER), "prompt must name the marker")
    assert.match(prompt, /last line/i)
  }
})

test("the code prompt classifies the surface before ordering the search", () => {
  assert.match(CODE_REVIEW_PROMPT, /SECURITY IS FIRST TIER/)
  assert.match(CODE_REVIEW_PROMPT, /TESTS THAT CANNOT FAIL/)
  assert.ok(!/rarely where the yield is/.test(CODE_REVIEW_PROMPT),
    "the globally-demoting appsec claim was removed for a reason")
})

test("the design prompt attacks documents, not diffs", () => {
  assert.match(DESIGN_REVIEW_PROMPT, /CLAIMS THAT EXCEED THEIR EVIDENCE/)
  assert.match(DESIGN_REVIEW_PROMPT, /DO-NOT-BUILD-AS-WRITTEN/)
})

test("both prompts tell the reviewer it is read-only", () => {
  for (const prompt of [CODE_REVIEW_PROMPT, DESIGN_REVIEW_PROMPT]) {
    assert.match(prompt, /read-only/i)
  }
})

test("isComplete requires the marker on its own final line", () => {
  assert.equal(isComplete("findings\n\nREVIEW-COMPLETE"), true)
  assert.equal(isComplete("findings\n\nREVIEW-COMPLETE\n"), true)
  assert.equal(isComplete("findings\n\nREVIEW-COMPLETE  \n"), true)
  assert.equal(isComplete("findings, cut off mid-sen"), false)
  assert.equal(isComplete(""), false)
  assert.equal(isComplete("I will end with REVIEW-COMPLETE when done"), false,
    "a mention inside prose is not a completion")
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test plugin/test/prompts.test.js`
Expected: FAIL, cannot find module `../src/prompts.js`.

- [ ] **Step 3: Copy the prompt bodies out of the spec**

Extract the fenced block under `## Appendix A - The reviewer prompt` into `plugin/src/prompts/code-review.md`, and the block under `## Appendix B - The design reviewer prompt` into `plugin/src/prompts/design-review.md`. Copy verbatim, without the surrounding triple backticks.

- [ ] **Step 4: Write the loader**

Create `plugin/src/prompts.js`:

```js
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { dirname, join } from "node:path"

const here = dirname(fileURLToPath(import.meta.url))
const read = (name) => readFileSync(join(here, "prompts", name), "utf8")

export const COMPLETION_MARKER = "REVIEW-COMPLETE"
export const CODE_REVIEW_PROMPT = read("code-review.md")
export const DESIGN_REVIEW_PROMPT = read("design-review.md")

// The marker must be the final non-empty line. A reviewer that MENTIONS it
// mid-prose has not finished, and a truncated review that happens to contain
// the word must not read as complete.
export function isComplete(text) {
  if (typeof text !== "string") return false
  const lines = text.split("\n").map((line) => line.trim()).filter((line) => line.length > 0)
  return lines.length > 0 && lines[lines.length - 1] === COMPLETION_MARKER
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `node --test plugin/test/prompts.test.js`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add plugin/src/prompts.js plugin/src/prompts/ plugin/test/prompts.test.js
git commit -m "Carry both reviewer prompts, and the marker that proves completion

isComplete requires the marker as the final non-empty line. A review cut off by
credit exhaustion must never read as a review that found nothing, and a mention
of the marker inside prose is not a completion."
```

---

## Task 7: Config injection, with collision refusal

**Files:**
- Create: `plugin/src/inject.js`
- Create: `plugin/test/inject.test.js`

**Interfaces:**
- Consumes: `CODE_REVIEW_PROMPT`, `DESIGN_REVIEW_PROMPT`, `COMPLETION_MARKER` from `plugin/src/prompts.js`
- Produces: `injectInto(config, options) -> { agents, commands }`, `CollisionError`, `AGENTS`, `COMMANDS`. Agent and command names are `adversarial-review` and `adversarial-review-design`.

**Use the placeholder syntax Task 1 Step 4 established.** The code below assumes `$ARGUMENTS`; if the probe found otherwise, change `ARG_PLACEHOLDER` and its test together.

- [ ] **Step 1: Write the failing tests**

Create `plugin/test/inject.test.js`:

```js
import test from "node:test"
import assert from "node:assert/strict"
import { injectInto, CollisionError, AGENTS, COMMANDS } from "../src/inject.js"

const opts = { model: "anthropic/claude-opus-5" }

test("injects two agents and two commands", () => {
  const config = {}
  injectInto(config, opts)
  assert.deepEqual(Object.keys(config.agent).sort(), [...AGENTS].sort())
  assert.deepEqual(Object.keys(config.command).sort(), [...COMMANDS].sort())
})

test("the code reviewer is read-only and pinned to the configured model", () => {
  const config = {}
  injectInto(config, opts)
  const agent = config.agent["adversarial-review"]
  assert.equal(agent.model, "anthropic/claude-opus-5")
  assert.equal(agent.mode, "subagent")
  assert.equal(agent.permission.edit, "deny")
  assert.equal(agent.permission.bash, "deny")
  assert.equal(agent.permission.webfetch, "deny")
  assert.equal(agent.tools.write, false)
  assert.equal(agent.tools.edit, false)
  assert.equal(agent.tools.patch, false)
  assert.equal(agent.tools.bash, false)
  assert.equal(agent.tools.review_context, true)
})

test("the design reviewer gets no git tool at all", () => {
  const config = {}
  injectInto(config, opts)
  const agent = config.agent["adversarial-review-design"]
  assert.equal(agent.tools.review_context, false)
  assert.equal(agent.tools.bash, false)
  assert.equal(agent.permission.edit, "deny")
})

test("existing unrelated agents and commands are preserved", () => {
  const config = { agent: { mine: { prompt: "x" } }, command: { mine: { template: "y" } } }
  injectInto(config, opts)
  assert.deepEqual(config.agent.mine, { prompt: "x" })
  assert.deepEqual(config.command.mine, { template: "y" })
})

test("a colliding agent name aborts WITHOUT mutating", () => {
  const config = { agent: { "adversarial-review": { prompt: "the user's own" } } }
  assert.throws(() => injectInto(config, opts), CollisionError)
  assert.deepEqual(config.agent["adversarial-review"], { prompt: "the user's own" },
    "the user's agent must survive untouched")
  assert.equal(config.command, undefined, "nothing may be injected after a collision")
})

test("a colliding command name aborts WITHOUT mutating", () => {
  const config = { command: { "adversarial-review": { template: "the user's own" } } }
  assert.throws(() => injectInto(config, opts), CollisionError)
  assert.deepEqual(config.command["adversarial-review"], { template: "the user's own" })
  assert.equal(config.agent, undefined)
})

test("the collision error names what collided and how to resolve it", () => {
  try {
    injectInto({ agent: { "adversarial-review": {} } }, opts)
    assert.fail("should have thrown")
  } catch (error) {
    assert.match(error.message, /adversarial-review/)
    assert.match(error.message, /rename/i)
  }
})

test("the command template tells the caller to check for the marker", () => {
  const config = {}
  injectInto(config, opts)
  for (const name of COMMANDS) {
    assert.match(config.command[name].template, /REVIEW-COMPLETE/)
    assert.equal(config.command[name].subtask, true)
  }
})

test("injection is idempotent for our own agents", () => {
  const config = {}
  injectInto(config, opts)
  const first = JSON.stringify(config)
  injectInto(config, opts)
  assert.equal(JSON.stringify(config), first)
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test plugin/test/inject.test.js`
Expected: FAIL, cannot find module `../src/inject.js`.

- [ ] **Step 3: Write the implementation**

Create `plugin/src/inject.js`:

```js
import { CODE_REVIEW_PROMPT, DESIGN_REVIEW_PROMPT, COMPLETION_MARKER } from "./prompts.js"

export class CollisionError extends Error {}

const CODE = "adversarial-review"
const DESIGN = "adversarial-review-design"
export const AGENTS = [CODE, DESIGN]
export const COMMANDS = [CODE, DESIGN]

// Confirmed by plugin/contracts: opencode expands $ARGUMENTS in a command
// template. If that ever changes, this constant and its test move together.
const ARG_PLACEHOLDER = "$ARGUMENTS"

// A marker on the injected objects, so a second pass can tell its own work from
// a user's agent that happens to share the name.
const OURS = "x-opencode-adversarial-review"

const READ_ONLY_PERMISSION = { edit: "deny", bash: "deny", webfetch: "deny" }

const BASE_TOOLS = {
  read: true, grep: true, glob: true, list: true,
  write: false, edit: false, patch: false, bash: false, webfetch: false,
}

function callerInstruction(what) {
  return [
    `Review ${what}: ${ARG_PLACEHOLDER}`,
    "",
    `When the reviewer returns, check that its output ends with a line containing only ${COMPLETION_MARKER}.`,
    `If that line is absent the review DID NOT FINISH - most likely the reviewer model ran out of credit or hit a rate limit.`,
    `In that case say so plainly, show whatever findings arrived and label them PARTIAL, and name what was not covered.`,
    `Never summarise an unfinished review as clean.`,
    `Finally, strip the ${COMPLETION_MARKER} line before showing the review.`,
  ].join("\n")
}

function assertNoCollision(config) {
  for (const name of AGENTS) {
    const existing = config.agent?.[name]
    if (existing && !existing[OURS]) {
      throw new CollisionError(
        `opencode-adversarial-review: an agent named "${name}" already exists and is not ours. ` +
        `Refusing to overwrite it. Rename your agent, or remove this plugin.`,
      )
    }
  }
  for (const name of COMMANDS) {
    const existing = config.command?.[name]
    if (existing && !existing[OURS]) {
      throw new CollisionError(
        `opencode-adversarial-review: a command named "${name}" already exists and is not ours. ` +
        `Refusing to overwrite it. Rename your command, or remove this plugin.`,
      )
    }
  }
}

export function injectInto(config, options) {
  assertNoCollision(config)

  config.agent = config.agent ?? {}
  config.command = config.command ?? {}

  config.agent[CODE] = {
    [OURS]: true,
    description: "Adversarial code review by a model you configure, independent of your session model. Read-only.",
    mode: "subagent",
    model: options.model,
    prompt: CODE_REVIEW_PROMPT,
    tools: { ...BASE_TOOLS, review_context: true },
    permission: { ...READ_ONLY_PERMISSION },
  }

  config.agent[DESIGN] = {
    [OURS]: true,
    description: "Adversarial review of a spec, plan or RFC by a model you configure. Read-only.",
    mode: "subagent",
    model: options.model,
    prompt: DESIGN_REVIEW_PROMPT,
    tools: { ...BASE_TOOLS, review_context: false },
    permission: { ...READ_ONLY_PERMISSION },
  }

  config.command[CODE] = {
    [OURS]: true,
    description: "Adversarially review code: a diff, a branch, or a path",
    template: callerInstruction("this code"),
    agent: CODE,
    subtask: true,
  }

  config.command[DESIGN] = {
    [OURS]: true,
    description: "Adversarially review a design document: a spec, plan or RFC",
    template: callerInstruction("this document"),
    agent: DESIGN,
    subtask: true,
  }

  return { agents: AGENTS, commands: COMMANDS }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node --test plugin/test/inject.test.js`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/src/inject.js plugin/test/inject.test.js
git commit -m "Inject two read-only reviewers, and refuse to clobber a user's agent

A same-named agent the user wrote is not ours to overwrite, so a collision
aborts before any mutation rather than after a partial one. The command template
carries the caller's half of the completion check."
```

---

## Task 8: Verification that checks a fingerprint, not a name

**Files:**
- Create: `plugin/src/verify.js`
- Create: `plugin/test/verify.test.js`

**Interfaces:**
- Consumes: `AGENTS`, `COMMANDS` from `plugin/src/inject.js`; the two prompts from `plugin/src/prompts.js`
- Produces: `fingerprint(config, options) -> string[]`, a list of problems where empty means healthy

Spec 3.4: an existence check cannot tell a wrong agent from a missing one.

- [ ] **Step 1: Write the failing tests**

Create `plugin/test/verify.test.js`:

```js
import test from "node:test"
import assert from "node:assert/strict"
import { injectInto } from "../src/inject.js"
import { fingerprint } from "../src/verify.js"

const opts = { model: "anthropic/claude-opus-5" }

function injected() {
  const config = {}
  injectInto(config, opts)
  return config
}

test("a freshly injected config is healthy", () => {
  assert.deepEqual(fingerprint(injected(), opts), [])
})

test("a MISSING agent is reported", () => {
  const config = injected()
  delete config.agent["adversarial-review"]
  const problems = fingerprint(config, opts)
  assert.equal(problems.length, 1)
  assert.match(problems[0], /missing/i)
  assert.match(problems[0], /adversarial-review/)
})

test("a WRONG MODEL is reported, which an existence check cannot see", () => {
  const config = injected()
  config.agent["adversarial-review"].model = "deepseek/deepseek-v4-flash"
  const problems = fingerprint(config, opts)
  assert.equal(problems.length, 1)
  assert.match(problems[0], /model/)
  assert.match(problems[0], /deepseek-v4-flash/)
})

test("a WEAKENED permission is reported", () => {
  const config = injected()
  config.agent["adversarial-review"].permission.edit = "allow"
  assert.match(fingerprint(config, opts).join(" "), /permission\.edit/)
})

test("a re-enabled write tool is reported", () => {
  const config = injected()
  config.agent["adversarial-review"].tools.write = true
  assert.match(fingerprint(config, opts).join(" "), /tools\.write/)
})

test("a replaced prompt is reported", () => {
  const config = injected()
  config.agent["adversarial-review"].prompt = "be nice about the code"
  assert.match(fingerprint(config, opts).join(" "), /prompt/)
})

test("a command unbound from its agent is reported", () => {
  const config = injected()
  config.command["adversarial-review"].agent = "build"
  assert.match(fingerprint(config, opts).join(" "), /agent binding/i)
})

test("a command that lost subtask is reported", () => {
  const config = injected()
  config.command["adversarial-review"].subtask = false
  assert.match(fingerprint(config, opts).join(" "), /subtask/)
})

test("several problems are all reported, not just the first", () => {
  const config = injected()
  delete config.agent["adversarial-review-design"]
  config.agent["adversarial-review"].model = "wrong/model"
  assert.equal(fingerprint(config, opts).length, 2)
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test plugin/test/verify.test.js`
Expected: FAIL, cannot find module `../src/verify.js`.

- [ ] **Step 3: Write the implementation**

Create `plugin/src/verify.js`:

```js
import { createHash } from "node:crypto"
import { AGENTS, COMMANDS } from "./inject.js"
import { CODE_REVIEW_PROMPT, DESIGN_REVIEW_PROMPT } from "./prompts.js"

const hash = (text) => createHash("sha256").update(text).digest("hex").slice(0, 16)

const EXPECTED_PROMPT = {
  "adversarial-review": () => hash(CODE_REVIEW_PROMPT),
  "adversarial-review-design": () => hash(DESIGN_REVIEW_PROMPT),
}

const FORBIDDEN_TOOLS = ["write", "edit", "patch", "bash"]
const REQUIRED_PERMISSION = { edit: "deny", bash: "deny", webfetch: "deny" }

// Returns problems rather than throwing, so a caller can report every fault at
// once. An existence check would pass on a user's same-named agent pointing at
// a different model - the silent wrong-model review this exists to catch.
export function fingerprint(config, options) {
  const problems = []

  for (const name of AGENTS) {
    const agent = config.agent?.[name]
    if (!agent) { problems.push(`agent "${name}" is missing from the resolved config`); continue }
    if (agent.model !== options.model) {
      problems.push(`agent "${name}" has model ${JSON.stringify(agent.model)}, expected ${JSON.stringify(options.model)}`)
    }
    if (agent.mode !== "subagent") {
      problems.push(`agent "${name}" has mode ${JSON.stringify(agent.mode)}, expected "subagent"`)
    }
    if (hash(String(agent.prompt ?? "")) !== EXPECTED_PROMPT[name]()) {
      problems.push(`agent "${name}" has a prompt we did not write`)
    }
    for (const [key, want] of Object.entries(REQUIRED_PERMISSION)) {
      if (agent.permission?.[key] !== want) {
        problems.push(`agent "${name}" permission.${key} is ${JSON.stringify(agent.permission?.[key])}, expected ${JSON.stringify(want)}`)
      }
    }
    for (const forbidden of FORBIDDEN_TOOLS) {
      if (agent.tools?.[forbidden] !== false) {
        problems.push(`agent "${name}" tools.${forbidden} is not disabled`)
      }
    }
  }

  for (const name of COMMANDS) {
    const command = config.command?.[name]
    if (!command) { problems.push(`command "${name}" is missing from the resolved config`); continue }
    if (command.agent !== name) {
      problems.push(`command "${name}" has agent binding ${JSON.stringify(command.agent)}, expected ${JSON.stringify(name)}`)
    }
    if (command.subtask !== true) {
      problems.push(`command "${name}" lost subtask: true`)
    }
  }

  return problems
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node --test plugin/test/verify.test.js`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/src/verify.js plugin/test/verify.test.js
git commit -m "Verify a fingerprint, not a name

An existence check passes on a user's same-named agent pointing at a different
model, which is the silent wrong-model review this plugin exists to prevent.
Model, mode, prompt hash, permissions, disabled tools, agent binding and subtask
are all checked, and every fault is reported rather than the first."
```

---

## Task 9: The plugin entry point

**Files:**
- Create: `plugin/src/index.js`
- Create: `plugin/test/index.test.js`

**Interfaces:**
- Consumes: `resolveOptions`, `injectInto`, `fingerprint`, `makeReviewContextTool`
- Produces: named export `AdversarialReview` matching opencode's `Plugin` type, plus a default export

- [ ] **Step 1: Write the failing tests**

Create `plugin/test/index.test.js`:

```js
import test from "node:test"
import assert from "node:assert/strict"
import { AdversarialReview } from "../src/index.js"

const input = { directory: "/tmp/repo", project: {}, client: {}, worktree: "/tmp/repo" }

test("returns hooks including config and the review_context tool", async () => {
  const hooks = await AdversarialReview(input, {})
  assert.equal(typeof hooks.config, "function")
  assert.ok(hooks.tool.review_context)
})

test("the config hook injects with the default model", async () => {
  const hooks = await AdversarialReview(input, undefined)
  const config = {}
  await hooks.config(config)
  assert.equal(config.agent["adversarial-review"].model, "anthropic/claude-opus-5")
})

test("the config hook honours a configured model for both agents", async () => {
  const hooks = await AdversarialReview(input, { model: "deepseek/deepseek-v4-pro" })
  const config = {}
  await hooks.config(config)
  assert.equal(config.agent["adversarial-review"].model, "deepseek/deepseek-v4-pro")
  assert.equal(config.agent["adversarial-review-design"].model, "deepseek/deepseek-v4-pro")
})

test("a bad model option fails loudly at load, not silently at review time", async () => {
  await assert.rejects(() => AdversarialReview(input, { model: "opus" }), /provider\/model/)
})

test("a collision surfaces as an error from the config hook", async () => {
  const hooks = await AdversarialReview(input, {})
  const config = { agent: { "adversarial-review": { prompt: "mine" } } }
  await assert.rejects(() => hooks.config(config), /Refusing to overwrite/)
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test plugin/test/index.test.js`
Expected: FAIL, cannot find module `../src/index.js`.

- [ ] **Step 3: Write the implementation**

Create `plugin/src/index.js`:

```js
import { resolveOptions } from "./options.js"
import { injectInto } from "./inject.js"
import { fingerprint } from "./verify.js"
import { makeReviewContextTool } from "./tool.js"

export const AdversarialReview = async (input, rawOptions) => {
  // Resolve options at LOAD time. A bad model reference discovered when the
  // user runs a review is a wasted round trip and a confusing error.
  const options = resolveOptions(rawOptions)

  return {
    tool: {
      review_context: makeReviewContextTool(input.directory ?? input.worktree),
    },

    config: async (config) => {
      injectInto(config, options)

      // Verify what actually landed. This runs after our own mutation, so it
      // catches a merge phase that overwrote our fields. It cannot catch the
      // hook never firing at all - the command template's marker check and the
      // README's troubleshooting section cover that.
      const problems = fingerprint(config, options)
      if (problems.length > 0) {
        throw new Error(
          "opencode-adversarial-review: the reviewer did not install correctly:\n  " +
          problems.join("\n  ") +
          "\nRefusing to continue rather than give you a reviewer that silently uses the wrong model.",
        )
      }
    },
  }
}

export default AdversarialReview
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node --test plugin/test/index.test.js`
Expected: all PASS.

- [ ] **Step 5: Run the whole suite**

Run: `node --test plugin/test/`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add plugin/src/index.js plugin/test/index.test.js
git commit -m "Wire the plugin entry point, failing loudly rather than quietly"
```

---

## Task 10: Package, install path, and README

**Files:**
- Create: `plugin/package.json`
- Modify: `README.md`

**Interfaces:**
- Consumes: `plugin/src/index.js`
- Produces: an installable npm package named `opencode-adversarial-review`

- [ ] **Step 1: Write the package manifest**

Create `plugin/package.json`:

```json
{
  "name": "opencode-adversarial-review",
  "version": "0.1.0",
  "description": "Adversarial code and design review for opencode, using a reviewer model you configure independently of your session model",
  "type": "module",
  "main": "src/index.js",
  "exports": { ".": "./src/index.js" },
  "files": ["src"],
  "engines": { "node": ">=18.18" },
  "license": "MIT",
  "keywords": ["opencode", "opencode-plugin", "code-review", "adversarial-review"],
  "scripts": { "test": "node --test test/" },
  "devDependencies": { "@opencode-ai/plugin": "1.18.21" }
}
```

`dependencies` is absent by design; opencode provides `@opencode-ai/plugin` at runtime.

- [ ] **Step 2: Verify the package contains only what it should**

Run: `cd plugin && npm pack --dry-run`
Expected: `src/**` and `package.json` only. No `test/`, no `contracts/`, no `smoke/`.

- [ ] **Step 3: Rewrite the repository README**

Lead with the plugin; the research is a link at the end.

````markdown
# opencode-adversarial-review

Adversarial code and design review for [opencode](https://opencode.ai), run by a
model you choose - independent of the model you are coding with.

You write code with DeepSeek, Qwen or a local model. This reviews it with Opus.
The reviewer is read-only and cannot touch your working tree.

## Install

```bash
opencode plugin opencode-adversarial-review
```

Then set your reviewer model in `opencode.jsonc`:

```jsonc
{
  "plugin": [
    ["opencode-adversarial-review", { "model": "anthropic/claude-opus-5" }]
  ]
}
```

## Use

```
/adversarial-review        review the current change
/adversarial-review src/   review a path
/adversarial-review-design docs/specs/my-spec.md
```

## Choosing a reviewer model

The reviewer should be a model you did NOT write the code with. Asking a model
to review its own output asks it to see its own blind spot.

The default is `anthropic/claude-opus-5`, which needs an **Anthropic API key**.
A Claude Pro or Max subscription does not cover third-party tools.

**No Anthropic API key?** Change one line. Any model your opencode config can
reach works:

```jsonc
["opencode-adversarial-review", { "model": "deepseek/deepseek-v4-pro" }]
["opencode-adversarial-review", { "model": "openai/gpt-5.4" }]
```

Your provider must be listed in `enabled_providers`, and the model must be
selectable under `provider.<name>.whitelist` if you use one.

## Cost

Reviews are priced per run by your provider. Switching the reviewer to a cheaper
model is a one-line change.

## What it looks for

Three axes: correctness of construction (code that looks right and cannot
work), architecture and fit, and operational risk. It classifies the changed
surface first, so security leads whenever the change touches untrusted input,
auth, secrets, network or the filesystem.

It is written to be useful on output from weaker models, which fails differently
from strong-model output: plausible shape, unsound wiring.

## If a review looks cut short

Every review ends with a completion marker. If your reviewer model runs out of
credit or hits a rate limit mid-review, you get an **incomplete** review with
partial findings labelled as partial, rather than a half-finished review
presented as a clean one.

## Running it last

It works standalone. If you prefer it as the final lens in a review gauntlet,
say so in your own `AGENTS.md` or `CLAUDE.md`; the plugin does not assume an
ordering.

## The research behind it

This repository also contains a differential evaluation harness. It set out to
derive review instructions by measuring where one model fails and another does
not, and stopped after two fixtures: see
[the design spec](docs/superpowers/specs/2026-08-28-adversarial-review-plugin-design.md)
for what it measured, what it did not, and why that is an economic stop rather
than a null result.
````

- [ ] **Step 4: Commit**

```bash
git add plugin/package.json README.md
git commit -m "Package the plugin, and lead the README with installing it

A repository holding both a research harness and a plugin will otherwise confuse
anyone who came for the plugin, so install is the second thing on the page and
the no-Anthropic-key path is the fourth."
```

---

## Task 11: The fixture smoke test, labelled as a smoke test

**Files:**
- Create: `plugin/smoke/README.md`
- Create: `plugin/smoke/run-smoke.mjs`

**Interfaces:**
- Consumes: `fixtures/py-callsite-01`, `fixtures/py-callsite-02` from the merged main
- Produces: a script printing catch rate and false-positive rate per condition

**This is not a ship gate.** Spec 5.1: six `known_good` variants differ by one to four one-line edits, there are two distinct planted defects, and these fixtures were used to develop the harness. Effective sample is 2, not 72.

- [ ] **Step 1: Write the smoke README first, so the limits travel with the tool**

Create `plugin/smoke/README.md` stating, in this order: what it measures; what it cannot measure; the effective sample size of 2; why the controls are near-clones; that the fixtures are development data rather than a held-out set; and that no claim stronger than "did not regress" may be published from it. Copy the bullet list from spec section 5.1 verbatim.

- [ ] **Step 2: Write the runner**

Create `plugin/smoke/run-smoke.mjs`. It must:

1. Copy each tree to a temp directory whose path contains **no** `known_good`, `known_bad` or fixture name. Spec 5.1 requires staging to strip provenance, or the reviewer can recognise the setup.
2. `git init` and commit the tree, so `review_context` has something to read.
3. For each of three conditions - `bare` (no prompt), `doctrine` (the shipped prompt), `placebo` (a neutral checklist of the same length) - run the reviewer and capture output. Randomise condition order; never put the condition name in the staged path.
4. Grade: on a `known_bad` tree, did the output name the defect's file and describe it? On a `known_good` tree, did it report any finding at all?
5. Print the limits from the README **above** the table, so a reader cannot see the number without the caveat.

- [ ] **Step 3: Run it and record the result**

```bash
node plugin/smoke/run-smoke.mjs --replicates 3
```

Expected cost roughly $10-15. Record the output in `plugin/smoke/results-2026-MM-DD.md`.

- [ ] **Step 4: Commit**

```bash
git add plugin/smoke/
git commit -m "Add the fixture smoke test, with its limits printed above its numbers

Effective sample is 2 distinct defects across near-clone controls, on fixtures
used to develop the harness. It catches a prompt that finds nothing and a prompt
that floods every tree. It cannot support a finer comparison, and the runner
says so."
```

---

## Task 12: Ship

**Files:**
- Modify: `plugin/package.json` (version only)

**Interfaces:**
- Consumes: every module from Tasks 2 to 10, exercised end to end against a real opencode session
- Produces: a published npm package and an open PR. Nothing imports this task.

- [ ] **Step 1: Run everything**

```bash
node --test plugin/test/
.venv/bin/python -m pytest -q
```
Expected: both suites green.

- [ ] **Step 2: Install locally from source and exercise both commands**

```bash
mkdir -p ~/.config/opencode/plugin
ln -sf "$PWD/plugin/src/index.js" ~/.config/opencode/plugin/adversarial-review.js
cd /tmp && mkdir -p arv-live && cd arv-live && git init -q
~/.opencode/bin/opencode run "/adversarial-review"
~/.opencode/bin/opencode run "/adversarial-review-design ../some-spec.md"
```

Confirm: the review runs on the configured model, findings appear, the marker is stripped, and `git status` shows nothing the reviewer wrote.

- [ ] **Step 3: Remove the symlink**

```bash
rm ~/.config/opencode/plugin/adversarial-review.js
```

- [ ] **Step 4: Open the PR**

```bash
git push -u origin feat/adversarial-review-plugin
gh pr create --title "The adversarial review plugin" --body "Implements docs/superpowers/specs/2026-08-28-adversarial-review-plugin-design.md"
```

- [ ] **Step 5: Run the review gauntlet on the branch**

Per the global workflow: the agent lenses, then Codex last, then fold in valid findings, then re-review only the delta. **`plugin/src/git-args.js` deserves its own dedicated pass** - it is the only thing between a reviewer and the user's working tree.

- [ ] **Step 6: Publish**

```bash
cd plugin && npm publish --access public
```

---

## Self-review notes

**Spec coverage.** Section 2.2 boundaries: Tasks 7, 8. Section 2.3 plugin justification: Tasks 2-4. Section 3.1 contracts: Task 1. Section 3.2 config: Task 5. Section 3.3 registration: Tasks 4, 7. Section 3.4 verification: Task 8. Section 3.5 compatibility: Task 1 Step 6 and Task 12 Step 2. Section 3.6 interrupted reviews: Tasks 6, 7. Section 4 prompts: Task 6. Section 5 validation: Task 11. Section 6 repo, distribution and README: Tasks 0, 10.

**Deliberate deviation from the spec.** Spec 3.3 describes `review_context` as taking an option **allowlist**. Task 2 takes semantic parameters instead, so the model supplies no flags at all. This is strictly stronger - there is no allowlist to get wrong - and the spec should be amended to match once this plan is approved.

**Dependencies on Task 1.** Task 7's `ARG_PLACEHOLDER` depends on the placeholder probe; if it found different syntax, change the constant and its test together. If the interrupt probe finds opencode swallows provider errors into partial text, record it in `plugin/contracts/probe-interrupt.md` and in the README troubleshooting section. The marker check in Task 7 handles it either way.

**Type consistency check.** `buildGitArgs` / `GitRequestError` (Task 2) are consumed by Task 3 under those exact names. `runGit` (Task 3) is consumed by Task 4. `makeReviewContextTool` (Task 4), `resolveOptions` (Task 5), `injectInto` / `AGENTS` / `COMMANDS` / `CollisionError` (Task 7), and `fingerprint` (Task 8) are all consumed by Task 9 under the names defined. `COMPLETION_MARKER` and `isComplete` (Task 6) are consumed by Task 7 and by the smoke runner.

**Known gap, deliberate.** `isComplete` is exported and tested but not called by plugin code, because the completion check happens in the calling session through the command template rather than in the plugin. It exists for the smoke runner in Task 11 and for a future move of the check into a tool layer, should Task 1's interrupt probe show that is necessary.
