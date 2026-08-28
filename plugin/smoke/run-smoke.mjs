#!/usr/bin/env node
// The fixture smoke test. Read plugin/smoke/README.md first - it says what
// these numbers can and cannot support, and this runner prints those limits
// above its own table so they cannot be read without the caveat.
//
//   node plugin/smoke/run-smoke.mjs                    # dry run, free, no model calls
//   node plugin/smoke/run-smoke.mjs --live --replicates 3
//
// Dry run is the DEFAULT on purpose. A full live run is roughly $10-15, and
// nothing about staging, ordering, provenance stripping or grading needs a
// model to verify.
import { execFileSync } from "node:child_process"
import { cpSync, mkdtempSync, mkdirSync, writeFileSync, readFileSync, existsSync, readdirSync } from "node:fs"
import { tmpdir } from "node:os"
import { join, dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { CODE_REVIEW_PROMPT } from "../src/prompts.js"
import { DEFECT_FILE, gradeRun } from "./grade.mjs"

const HERE = dirname(fileURLToPath(import.meta.url))
const REPO = resolve(HERE, "..", "..")
const FIXTURES = join(REPO, "fixtures")
const OPENCODE = join(process.env.HOME, ".opencode", "bin", "opencode")

// ---------------------------------------------------------------------------
// Arguments
// ---------------------------------------------------------------------------

function parseArgs(argv) {
  const args = { replicates: 1, model: "anthropic/claude-opus-5", live: false, seed: 1, out: null }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a === "--live") args.live = true
    else if (a === "--replicates") args.replicates = Number(argv[++i])
    else if (a === "--model") args.model = argv[++i]
    else if (a === "--seed") args.seed = Number(argv[++i])
    else if (a === "--out") args.out = argv[++i]
    else throw new Error(`unknown argument: ${a}`)
  }
  if (!Number.isInteger(args.replicates) || args.replicates < 1) throw new Error("--replicates must be a positive integer")
  if (!Number.isInteger(args.seed)) throw new Error("--seed must be an integer")
  return args
}

// Seeded, so a run is reproducible from the seed it prints. Condition order is
// randomised per tree - spec 5.1 - and an unreproducible randomisation would
// make a surprising result impossible to re-examine.
function rng(seed) {
  let s = seed >>> 0
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0
    return s / 0x100000000
  }
}

function shuffle(items, next) {
  const out = [...items]
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(next() * (i + 1))
    ;[out[i], out[j]] = [out[j], out[i]]
  }
  return out
}

// ---------------------------------------------------------------------------
// Conditions
// ---------------------------------------------------------------------------

// A neutral checklist, then repeated to the doctrine prompt's exact character
// count. Equal length is what spec 5.1 asks for, so that a difference cannot be
// attributed to prompt size alone. The repetition is visible and is stated in
// the README rather than dressed up as a second real prompt.
export function placeboPrompt(targetLength) {
  const base = [
    "You are a code reviewer. Review the change you are given and report what you find.",
    "",
    "Work through this checklist:",
    "- Read the change.",
    "- Consider whether it does what it says.",
    "- Consider whether it is consistent with the surrounding code.",
    "- Consider whether the tests cover it.",
    "- Consider whether the naming is clear.",
    "- Consider whether the structure is reasonable.",
    "- Report anything that seems worth the author's attention.",
    "",
  ].join("\n")
  let text = base
  while (text.length < targetLength) text += base
  return text.slice(0, targetLength)
}

export const CONDITIONS = () => [
  { name: "bare", prompt: "You are a code reviewer. Review the change you are given and report what you find." },
  { name: "doctrine", prompt: CODE_REVIEW_PROMPT },
  { name: "placebo", prompt: placeboPrompt(CODE_REVIEW_PROMPT.length) },
]

// ---------------------------------------------------------------------------
// Discovery
// ---------------------------------------------------------------------------

export function discoverTrees() {
  const trees = []
  for (const fixture of readdirSync(FIXTURES).sort()) {
    const base = join(FIXTURES, fixture)
    if (!existsSync(join(base, "repo"))) continue
    for (const kind of ["good", "bad"]) {
      const dir = join(base, kind === "good" ? "known_good" : "known_bad")
      if (!existsSync(dir)) continue
      for (const variant of readdirSync(dir).sort()) {
        trees.push({ fixture, kind, variant, path: join(dir, variant), baseline: join(base, "repo") })
      }
    }
  }
  return trees
}

// ---------------------------------------------------------------------------
// Staging
// ---------------------------------------------------------------------------

const git = (cwd, ...args) =>
  execFileSync("git", args, {
    cwd,
    encoding: "utf8",
    env: { ...process.env, GIT_AUTHOR_NAME: "smoke", GIT_AUTHOR_EMAIL: "smoke@example.invalid",
           GIT_COMMITTER_NAME: "smoke", GIT_COMMITTER_EMAIL: "smoke@example.invalid" },
  })

// Spec 5.1: staging must strip fixture provenance, or the reviewer can
// recognise the setup and grade itself. Nothing identifying goes in the path -
// not the fixture, not the variant, not known_good/known_bad, and not the
// condition, which would be worse still since it is the independent variable.
const FORBIDDEN_IN_PATH = ["known_good", "known_bad", "py-callsite", "fixture", "bare", "doctrine", "placebo", "smoke"]

export function assertPathIsAnonymous(path) {
  const lower = path.toLowerCase()
  for (const marker of FORBIDDEN_IN_PATH) {
    if (lower.includes(marker)) throw new Error(`staged path leaks provenance (${marker}): ${path}`)
  }
}

// The baseline goes in as commit 1 and the variant as commit 2, so the change
// under review is a real diff rather than a whole tree presented as new. That
// matters for what is being measured: in a known_bad tree the planted defect is
// a call site that should have been updated and was NOT, so it is absent from
// the diff entirely. The reviewer only finds it by reading the tree around the
// change - which is the behaviour under test.
export function stage(tree) {
  const root = mkdtempSync(join(tmpdir(), "rv-"))
  const work = join(root, "workspace")
  assertPathIsAnonymous(work)
  mkdirSync(work)
  cpSync(tree.baseline, work, { recursive: true })
  git(work, "init", "-q", "-b", "main")
  git(work, "add", "-A")
  git(work, "commit", "-q", "-m", "Initial import")
  // Replace the tree wholesale: a variant may delete as well as change files.
  for (const entry of readdirSync(work)) {
    if (entry === ".git") continue
    execFileSync("rm", ["-rf", join(work, entry)])
  }
  cpSync(tree.path, work, { recursive: true })
  git(work, "add", "-A")
  git(work, "commit", "-q", "-m", "Show guests when a notification was created")
  return work
}

// ---------------------------------------------------------------------------
// Running one review
// ---------------------------------------------------------------------------

const ASK = "the change on this branch, which is the single most recent commit"

function writeConfig(work, condition, model) {
  writeFileSync(join(work, "opencode.json"), JSON.stringify({
    $schema: "https://opencode.ai/config.json",
    plugin: [[join(REPO, "plugin", "src", "index.js"), { model }]],
    agent: {
      "smoke-reviewer": {
        description: "smoke reviewer",
        mode: "subagent",
        model,
        prompt: condition.prompt,
        tools: { read: true, grep: true, glob: true, list: true, review_context: true,
                 write: false, edit: false, patch: false, bash: false, webfetch: false },
        permission: { edit: "deny", bash: "deny", webfetch: "deny" },
      },
    },
    command: {
      "smoke-review": {
        description: "smoke review",
        template: `Review ${ASK}: $ARGUMENTS`,
        agent: "smoke-reviewer",
        subtask: true,
      },
    },
  }, null, 2))
}

function extractText(stdout) {
  const parts = []
  for (const line of stdout.split("\n")) {
    if (!line.trim()) continue
    let event
    try { event = JSON.parse(line) } catch { continue }
    const part = event.part ?? {}
    if (part.type === "text" && typeof part.text === "string") parts.push(part.text)
    if (part.tool === "task" && part.state?.output) parts.push(String(part.state.output))
  }
  return parts.join("\n")
}

function runReview(work, condition, model) {
  const stdout = execFileSync(OPENCODE,
    ["run", "--command", "smoke-review", ASK, "--format", "json"],
    { cwd: work, encoding: "utf8", maxBuffer: 64 * 1024 * 1024, timeout: 15 * 60 * 1000 })
  return extractText(stdout)
}

// ---------------------------------------------------------------------------
// Report
// ---------------------------------------------------------------------------

const LIMITS = readFileSync(join(HERE, "README.md"), "utf8")
  .split("<!-- LIMITS -->")[1]?.trim() ?? "(limits section missing from plugin/smoke/README.md)"

function report(rows, args) {
  const out = []
  out.push("# Fixture smoke test")
  out.push("")
  out.push(LIMITS)
  out.push("")
  out.push(`Run: ${args.live ? "LIVE" : "DRY (no model was called; every review body is empty by construction)"}`)
  out.push(`Model: ${args.model}   replicates: ${args.replicates}   seed: ${args.seed}`)
  out.push("")
  out.push("| condition | trees | caught / known_bad | defect FP / known_good | any-finding FP / known_good | empty |")
  out.push("|---|---|---|---|---|---|")
  for (const condition of CONDITIONS().map((c) => c.name)) {
    const mine = rows.filter((r) => r.condition === condition)
    const bad = mine.filter((r) => r.kind === "bad")
    const good = mine.filter((r) => r.kind === "good")
    const caught = bad.filter((r) => r.grade.caught).length
    const dfp = good.filter((r) => r.grade.defectFalsePositive).length
    const afp = good.filter((r) => r.grade.anyFindingFalsePositive).length
    const empty = mine.filter((r) => r.grade.empty).length
    out.push(`| ${condition} | ${mine.length} | ${caught}/${bad.length} | ${dfp}/${good.length} | ${afp}/${good.length} | ${empty}/${mine.length} |`)
  }
  out.push("")
  out.push("Per run:")
  out.push("")
  out.push("| fixture | tree | condition | rep | fired | empty |")
  out.push("|---|---|---|---|---|---|")
  for (const r of rows) {
    out.push(`| ${r.fixture} | ${r.kind}/${r.variant} | ${r.condition} | ${r.replicate} | ${r.grade.fired ? "yes" : "no"} | ${r.grade.empty ? "yes" : "no"} |`)
  }
  return out.join("\n")
}

// ---------------------------------------------------------------------------

async function main() {
  const args = parseArgs(process.argv.slice(2))
  const trees = discoverTrees()
  const conditions = CONDITIONS()
  const total = trees.length * conditions.length * args.replicates

  if (trees.length === 0) throw new Error(`no fixtures found under ${FIXTURES}`)
  for (const tree of trees) {
    if (!DEFECT_FILE[tree.fixture]) throw new Error(`fixture ${tree.fixture} has no defect file in grade.mjs - refusing to run`)
  }

  console.error(`${trees.length} trees x ${conditions.length} conditions x ${args.replicates} replicates = ${total} reviews`)
  if (!args.live) console.error("DRY RUN - no model will be called. Pass --live to actually spend money (roughly $10-15 for --replicates 3).")

  const next = rng(args.seed)
  const rows = []
  for (let replicate = 1; replicate <= args.replicates; replicate++) {
    for (const tree of trees) {
      const work = stage(tree)
      // Order randomised per tree, so a systematic drift over the run cannot
      // land preferentially on one condition.
      for (const condition of shuffle(conditions, next)) {
        writeConfig(work, condition, args.model)
        let text = ""
        if (args.live) {
          try {
            text = runReview(work, condition, args.model)
          } catch (error) {
            console.error(`  run failed (${tree.fixture} ${tree.kind}/${tree.variant} ${condition}): ${error.message.split("\n")[0]}`)
          }
        }
        rows.push({ ...tree, condition: condition.name, replicate, text, grade: gradeRun({ ...tree, text }) })
        console.error(`  ${replicate} ${tree.fixture} ${tree.kind}/${tree.variant} ${condition.name} -> fired=${gradeRun({ ...tree, text }).fired}`)
      }
    }
  }

  const text = report(rows, args)
  if (args.out) {
    writeFileSync(args.out, text + "\n")
    console.error(`\nwrote ${args.out}`)
  }
  console.log(text)
}

// Only run when executed directly, so the tests can import stage() and
// discoverTrees() without kicking off a 24-review sweep on import.
if (process.argv[1] && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url))) {
  main().catch((error) => { console.error(error.message); process.exit(1) })
}
