import { createHash } from "node:crypto"
import { AGENTS, COMMANDS, injectInto } from "./inject.js"
import { CODE_REVIEW_PROMPT, DESIGN_REVIEW_PROMPT } from "./prompts.js"

const hash = (text) => createHash("sha256").update(text).digest("hex").slice(0, 16)

const EXPECTED_PROMPT = {
  "adversarial-review": () => hash(CODE_REVIEW_PROMPT),
  "adversarial-review-design": () => hash(DESIGN_REVIEW_PROMPT),
}

// The command template is not a static constant like the prompts - it is
// built by injectInto's own callerInstruction() closure, which is not
// exported. Rather than duplicate that construction here (and risk it
// drifting from the real thing), inject into a throwaway config with the
// caller's own options and hash whatever injectInto actually produced. That
// makes "matches what injectInto would produce" literally true rather than
// an approximation of it.
function expectedTemplateHashes(options) {
  const scratch = {}
  injectInto(scratch, options)
  const hashes = {}
  for (const name of COMMANDS) hashes[name] = hash(String(scratch.command[name].template))
  return hashes
}

const FORBIDDEN_TOOLS = ["write", "edit", "patch", "bash"]
const REQUIRED_PERMISSION = { edit: "deny", bash: "deny", webfetch: "deny", external_directory: "deny" }

// Returns problems rather than throwing, so a caller can report every fault at
// once. An existence check would pass on a user's same-named agent pointing at
// a different model - the silent wrong-model review this exists to catch.
export function fingerprint(config, options) {
  const problems = []
  const expectedTemplate = expectedTemplateHashes(options)

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
    if (hash(String(command.template ?? "")) !== expectedTemplate[name]) {
      problems.push(`command "${name}" has a template we did not write`)
    }
  }

  return problems
}
