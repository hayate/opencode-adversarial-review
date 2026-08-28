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
