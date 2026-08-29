import { CODE_REVIEW_PROMPT, DESIGN_REVIEW_PROMPT, COMPLETION_MARKER } from "./prompts.js"

export class CollisionError extends Error {}

// Distinct from CollisionError: this is not a name clash, it is config.agent
// or config.command being some non-object shape (an array, a string, a
// number) that the rest of this module's optional-chaining and object-spread
// code would otherwise mishandle silently rather than loudly. Kept as its
// own type, not a CollisionError, so a caller can tell "a real name collided"
// from "the config itself is malformed" without parsing the message.
export class InvalidConfigError extends Error {}

const CODE = "floor-review"
const DESIGN = "floor-review-design"
export const AGENTS = [CODE, DESIGN]
export const COMMANDS = [CODE, DESIGN]

// Confirmed by contracts/: opencode expands $ARGUMENTS in a command
// template. If that ever changes, this constant and its test move together.
const ARG_PLACEHOLDER = "$ARGUMENTS"

// A marker on the injected objects, so a second pass can tell its own work from
// a user's agent that happens to share the name.
const OURS = "x-opencode-floor-review"

// external_directory is denied too: a code reviewer has no business reading
// outside the repository it was pointed at. doom_loop is deliberately left
// unset - it is not security relevant, and setting it would be cargo cult.
const READ_ONLY_PERMISSION = { edit: "deny", bash: "deny", webfetch: "deny", external_directory: "deny" }

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
    `Finally, strip the ${COMPLETION_MARKER} line before showing the review, and do NOT`,
    `mention the marker to the user at all - it is an internal signal, not part of the`,
    `review. Show the review, or say it is incomplete. Never narrate the check itself.`,
  ].join("\n")
}

// config.agent = [] is not nullish, so `config.agent ?? {}` would leave the
// array in place; the collision check's optional chaining then finds nothing
// on it, and injection proceeds to attach both agents as string-keyed
// properties on the array - which JSON.stringify then serialises back to
// "[]", silently dropping both read-only security agents with no error at
// all. config.agent = "oops" would instead crash later with a raw, unhelpful
// TypeError ("Cannot create property ... on string") that names neither this
// plugin nor the actual cause. Reject both shapes here, before any mutation,
// naming the key and what was actually found. null/undefined are left alone -
// those already coerce correctly via `?? {}` below and are not the bug.
function assertValidContainer(config, key) {
  const value = config[key]
  if (value === undefined || value === null) return
  if (Array.isArray(value)) {
    throw new InvalidConfigError(
      `opencode-floor-review: config.${key} must be a plain object, got an array. ` +
      `Refusing to inject into a config shaped like that.`,
    )
  }
  if (typeof value !== "object") {
    throw new InvalidConfigError(
      `opencode-floor-review: config.${key} must be a plain object, got ${typeof value}. ` +
      `Refusing to inject into a config shaped like that.`,
    )
  }
}

// The same failure one level up, and the worst-behaved of the three: if
// `config` ITSELF is an array, both assertValidContainer calls read
// config.agent / config.command as undefined and wave it through, the two
// assignments below attach string-keyed properties to the array, and
// JSON.stringify serialises it straight back to "[]" - both read-only
// security agents gone, no error raised anywhere. Not reachable through
// opencode's own contract, which always passes a plain object, but injectInto
// is an exported entry point and this is the one shape whose failure is
// completely silent. null and undefined are rejected here rather than
// tolerated: unlike config.agent, there is no `?? {}` that could rescue them,
// and mutating them is impossible.
function assertValidRoot(config) {
  if (config === null || config === undefined || typeof config !== "object" || Array.isArray(config)) {
    throw new InvalidConfigError(
      `opencode-floor-review: config must be a plain object, got ${Array.isArray(config) ? "an array" : typeof config === "object" ? String(config) : typeof config}. ` +
      `Refusing to inject into a config shaped like that.`,
    )
  }
}

function assertNoCollision(config) {
  for (const name of AGENTS) {
    const existing = config.agent?.[name]
    if (existing && !existing[OURS]) {
      throw new CollisionError(
        `opencode-floor-review: an agent named "${name}" already exists and is not ours. ` +
        `Refusing to overwrite it. Rename your agent, or remove this plugin.`,
      )
    }
  }
  for (const name of COMMANDS) {
    const existing = config.command?.[name]
    if (existing && !existing[OURS]) {
      throw new CollisionError(
        `opencode-floor-review: a command named "${name}" already exists and is not ours. ` +
        `Refusing to overwrite it. Rename your command, or remove this plugin.`,
      )
    }
  }
}

export function injectInto(config, options) {
  assertValidRoot(config)
  assertValidContainer(config, "agent")
  assertValidContainer(config, "command")
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
