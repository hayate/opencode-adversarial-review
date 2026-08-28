// Throwaway probe. Answers, for spec 3.4's third check:
//   1. Does `chat.params` fire for a plugin-INJECTED SUBAGENT, and does it
//      carry that agent's name and the model about to serve it?
//   2. Does throwing from it actually stop the review, and what does the
//      CALLING session then receive - a named error, or an empty result that
//      reads as a clean review?
//
// Set PROBE_THROW=1 to answer question 2; leave it unset for question 1.
import { appendFileSync } from "node:fs"

const LOG = process.env.PROBE_LOG
const note = (m) => { try { appendFileSync(LOG, m + "\n") } catch {} }

export const Probe = async (_input, options) => {
  note("LOADED options=" + JSON.stringify(options ?? null))
  return {
    config: async (cfg) => {
      note("CONFIG HOOK FIRED")
      cfg.agent = cfg.agent ?? {}
      cfg.command = cfg.command ?? {}
      cfg.agent["probe-reviewer"] = {
        description: "probe reviewer",
        mode: "subagent",
        model: "deepseek/deepseek-v4-flash",
        prompt: "You are a probe. Say OK and stop.",
        tools: { read: true, write: false, edit: false, patch: false, bash: false, webfetch: false },
        permission: { edit: "deny", bash: "deny", webfetch: "deny", external_directory: "deny" },
      }
      cfg.command["probe-reviewer"] = {
        description: "probe command",
        template: "Review this: $ARGUMENTS",
        agent: "probe-reviewer",
        subtask: true,
      }
    },
    "command.execute.before": async (input) => {
      note(`COMMAND.EXECUTE.BEFORE command=${JSON.stringify(input.command)} args=${JSON.stringify(input.arguments)}`)
      // Set PROBE_THROW_CMD=1 to answer: does throwing HERE abort the command,
      // and what does the user see? A guard that cannot abort is not a guard.
      if (process.env.PROBE_THROW_CMD && input.command === "probe-reviewer") {
        note("THROWING FROM command.execute.before")
        throw new Error("PROBE-CMD-GUARD-TRIPPED: refusing to run this command")
      }
    },
    "chat.message": async (input) => {
      note(`CHAT.MESSAGE agent=${JSON.stringify(input.agent)} model=${JSON.stringify(input.model)}`)
    },
    "chat.params": async (input) => {
      note(
        `CHAT.PARAMS agent=${JSON.stringify(input.agent)}` +
        ` model.providerID=${JSON.stringify(input.model?.providerID)}` +
        ` model.id=${JSON.stringify(input.model?.id)}` +
        ` provider=${JSON.stringify(input.provider?.id ?? null)}` +
        ` inputKeys=${JSON.stringify(Object.keys(input))}`,
      )
      if (process.env.PROBE_THROW && input.agent === "probe-reviewer") {
        note("THROWING NOW")
        throw new Error("PROBE-GUARD-TRIPPED: refusing this review")
      }
    },
  }
}
export default Probe
