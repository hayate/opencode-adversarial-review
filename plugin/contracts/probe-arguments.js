// Throwaway probe. Answers: what syntax does a command template use to
// receive the arguments a user typed after the slash command?
import { appendFileSync } from "node:fs"

const LOG = process.env.PROBE_LOG
const note = (m) => { try { appendFileSync(LOG, m + "\n") } catch {} }

export const Probe = async (input, options) => {
  note("LOADED options=" + JSON.stringify(options ?? null))
  return {
    config: async (cfg) => {
      note("CONFIG HOOK FIRED")
      cfg.agent = cfg.agent ?? {}
      cfg.agent["probe-agent"] = {
        description: "probe", mode: "subagent",
        model: "deepseek/deepseek-v4-flash", prompt: "probe",
        permission: { edit: "deny", bash: "deny" },
      }
      cfg.command = cfg.command ?? {}
      cfg.command["probe-cmd"] = {
        template: "echo BEGIN $ARGUMENTS END", agent: "probe-agent", subtask: true,
      }
    },
  }
}
