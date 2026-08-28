import { createHash } from "node:crypto"
import { AGENTS, COMMANDS, injectInto } from "./inject.js"
import { CODE_REVIEW_PROMPT, DESIGN_REVIEW_PROMPT } from "./prompts.js"

const hash = (text) => createHash("sha256").update(text).digest("hex").slice(0, 16)

// EXPECTED_PROMPT and EXPECTED_TOOLS below are keyed by agent name while the
// loop iterates AGENTS from inject.js, so a third agent added there without a
// key here throws instead of reporting. That is deliberate and needs no runtime
// guard: AGENTS is a module constant, never user input, so no runtime path can
// reach an unknown name. The mismatch is a development-time error, and the
// parameterised test matrix runs every case over every name in AGENTS, so it
// surfaces as a red suite before it can ship.
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

const REQUIRED_PERMISSION = { edit: "deny", bash: "deny", webfetch: "deny", external_directory: "deny" }

// Restated as literals rather than read back out of injectInto, deliberately.
// The template hash has to be derived from injectInto because its closure is
// not exported, but everything here can be written down independently, and an
// expectation derived from the thing it checks would mirror a change to
// inject.js instead of catching it.
//
// Three of these were previously unchecked, all of them load-bearing:
//   webfetch       permission.webfetch is checked too, but the resolved
//                  permission is a MERGE with the operator's wider opencode
//                  config and precedence is not pinned down, so this flag may
//                  be the one that actually holds. Flipped true, a reviewer
//                  that has just read the whole repository gets a route back
//                  out to the network.
//   read/grep/glob/list
//                  flipped false, the reviewer cannot read what it was asked
//                  to review and returns "no findings" from having seen
//                  nothing. A blind pass reads as a clean pass, which is the
//                  same hazard the completion marker exists to prevent.
//   review_context the code reviewer's only route to git, and deliberately
//                  withheld from the design reviewer, which reads a document
//                  the caller supplies and has no repository to inspect. The
//                  only per-agent value here, which is why this is a map of
//                  agents rather than one shared list.
const READABLE = { read: true, grep: true, glob: true, list: true }
const DENIED = { write: false, edit: false, patch: false, bash: false, webfetch: false }
const EXPECTED_TOOLS = {
  "adversarial-review": { ...READABLE, ...DENIED, review_context: true },
  "adversarial-review-design": { ...READABLE, ...DENIED, review_context: false },
}

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
    // Iterating the EXPECTED keys, never the agent's own: opencode's resolution
    // adds task/todowrite/skill/memory_* and a check that rejected unknown keys
    // would cry wolf on a healthy config. A control that does that gets
    // switched off.
    for (const [tool, want] of Object.entries(EXPECTED_TOOLS[name])) {
      if (agent.tools?.[tool] !== want) {
        problems.push(`agent "${name}" tools.${tool} is ${JSON.stringify(agent.tools?.[tool])}, expected ${JSON.stringify(want)}`)
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
