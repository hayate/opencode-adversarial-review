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
