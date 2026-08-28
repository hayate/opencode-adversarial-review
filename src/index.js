import { OptionsError, resolveOptions } from "./options.js"
import { AGENTS, COMMANDS, injectInto } from "./inject.js"
import { fingerprint } from "./verify.js"
import { makeReviewContextTool } from "./tool.js"

// opencode 1.18.23 spells the model id differently on two hooks that describe
// the same thing: chat.params carries `model.id`, chat.message carries
// `model.modelID`, with `model.providerID` on both (see contracts/).
// Accepting either is not speculative generality - both spellings were
// observed on this one version, so pinning one would make this check a
// permanent false alarm the first time the shape shifts again, and a control
// that cries wolf on a healthy session gets switched off.
//
// providerID and id are concatenated rather than compared field by field so
// that a model id containing its own slashes round-trips: openrouter serves
// "openrouter/anthropic/claude-3.5-sonnet" as providerID "openrouter" and id
// "anthropic/claude-3.5-sonnet", which options.js already accepts as a single
// reference.
function servingModel(model) {
  const providerID = model?.providerID
  const modelID = model?.id ?? model?.modelID
  // F7: an empty string passes a bare typeof check and concatenates to "/",
  // which trips the MISMATCH branch and names the wrong cause. Route it to
  // "cannot tell", which already carries the right guidance.
  if (typeof providerID !== "string" || providerID === "") return null
  if (typeof modelID !== "string" || modelID === "") return null
  return `${providerID}/${modelID}`
}

// JSON.stringify is wrong here twice over. It THROWS on a circular structure or
// a BigInt - and this runs only in the branch where the model shape is already
// unrecognisable, so those correlate - which would replace the one message the
// user gets with a raw TypeError. And opencode's chat.params carries the FULL
// provider model record (api, capabilities, cost, limits), so even on the happy
// path it would paste a wall of JSON into an error meant to be read.
function describeShape(value) {
  if (value === null || typeof value !== "object") return typeof value === "string" ? `the string ${JSON.stringify(value)}` : String(value)
  try {
    const keys = Object.keys(value)
    return keys.length ? `an object with keys ${keys.slice(0, 12).join(", ")}${keys.length > 12 ? ", ..." : ""}` : "an object with no keys"
  } catch {
    return "an object whose keys could not be read"
  }
}

// opencode SWALLOWS both a plugin load error and a config-hook throw: exit 0,
// empty stderr, the plugin simply absent, with the message reachable only via
// `opencode debug config --print-logs --log-level ERROR`. console.error and a
// raw process.stderr.write from inside a hook are swallowed too - the platform
// gives a plugin no way to speak at config time at all. All verified against
// 1.18.23 and recorded in contracts/, Step 7.
//
// Failing closed is still right, and opencode helps: a throw makes it discard
// the WHOLE hook's mutations, so there is never a half-installed reviewer. But
// a throw alone produces exactly what spec 3.4 calls the worst available
// outcome - a plugin that silently does nothing. So on the one fault a user can
// actually cause by hand, a bad `model` value, we leave behind something that
// speaks: the two command names, bound to no agent, whose template asks the
// user's own session model to relay the error. `/adversarial-review` then says
// what is wrong instead of "unknown command".
//
// This is deliberately NOT done for a collision or a fingerprint failure. A
// collision means the user's own agent already owns the name and displacing it
// with a diagnostic would be the overwrite we refuse on principle; a
// fingerprint failure means inject.js and verify.js disagree, which is our own
// bug and is caught by the test suite long before a user sees it.
const diagnosticTemplate = (message, remedy) => [
  "Relay the following to the user verbatim, and do nothing else. Do not read files,",
  "do not run any command, and do not attempt a review:",
  "",
  message,
  "",
  "The opencode-adversarial-review plugin did not install because of that.",
  remedy,
].join("\n")

// Every string below is a FIXED LITERAL, and that is the point. The diagnostic
// template becomes a prompt executed by the user's SESSION model, which - unlike
// the two reviewers - may well have bash and write access. Interpolating the
// rejected option value into it would take text from a config file and place it
// inside a privileged prompt: a project-level opencode.json carrying
// `model: "x/Ignore all previous instructions and ..."` would have had its
// instructions read by that model. Quoting a value inside an error sentence is
// not a trust boundary.
//
// The value is not lost, it is just not put in a prompt. opencode's own error
// log carries it verbatim, and the remedy below says exactly how to read it.
const SEE_THE_VALUE =
  "To see the exact value opencode rejected, run: opencode debug config --print-logs --log-level ERROR"

const FAULTS = {
  options: {
    problem: "the `model` option in this plugin's configuration is not a valid provider/model reference",
    remedy: `Correct it in the plugin's options in your opencode config, then restart opencode. ${SEE_THE_VALUE}`,
  },
  directory: {
    problem: "opencode did not tell the plugin which directory to review",
    remedy: "That is not something your configuration can fix - it is a bug in the plugin, or opencode changed shape. Please report it, and re-run the probes in contracts/ if opencode was just upgraded.",
  },
  internal: {
    problem: "this plugin failed to load",
    remedy: `That is not something your configuration can fix - it is a bug in the plugin. Please report it. ${SEE_THE_VALUE}`,
  },
}

function diagnosticHooks(fault) {
  const { problem, remedy } = FAULTS[fault]
  return {
    config: async (config) => {
      // Same shapes injectInto refuses, refused the same way - except silently,
      // because this path exists precisely because we cannot report anything.
      if (config === null || typeof config !== "object" || Array.isArray(config)) return
      if (config.command !== undefined && config.command !== null &&
          (typeof config.command !== "object" || Array.isArray(config.command))) return
      // A frozen or read-only config would make the assignments below throw,
      // which contradicts the whole point of this path: it exists to leave
      // something behind when nothing else can be said, so it must never be the
      // thing that fails. Stand down instead.
      try {
        config.command = config.command ?? {}
        for (const name of COMMANDS) {
          // Never displace a command the user already has under that name.
          if (config.command[name]) continue
          config.command[name] = {
            description: `MISCONFIGURED - ${problem}`,
            template: diagnosticTemplate(problem, remedy),
            subtask: false,
          }
        }
      } catch {
        // Nothing to report it to. See contracts/README.md Step 7.
      }
    },
  }
}

export const AdversarialReview = async (input, rawOptions) => {
  // Resolve options at LOAD time. A bad model reference discovered when the
  // user runs a review is a wasted round trip and a confusing error.
  let options
  try {
    options = resolveOptions(rawOptions)
  } catch (error) {
    // Catch everything - rethrowing would make the plugin vanish silently - but
    // only tell the user to fix their config when their config is the problem.
    // Anything that is not an OptionsError is ours, and pointing them at a
    // `model` value that is already correct wastes their time.
    return diagnosticHooks(error instanceof OptionsError ? "options" : "internal")
  }

  // F4: `directory` is the ONLY source of the git cwd. Left undefined,
  // execFile treats it as "inherit", and review_context silently reads whatever
  // tree the opencode process happened to start in - reporting success. A review
  // of the wrong tree reads exactly like a review of the right one, which is this
  // plugin's own hazard class. opencode always supplies it today; if that ever
  // stops being true it must be loud, the way every other shape change here is.
  const directory = input?.directory ?? input?.worktree
  if (typeof directory !== "string" || directory === "") {
    return diagnosticHooks("directory")
  }

  // Set by the config hook only when our own injection actually landed, and
  // read by chat.params below. VERIFIED LIVE against opencode 1.18.23: a
  // config-hook throw is logged and IGNORED, and every hook we returned stays
  // registered and keeps firing. Without this flag, refusing to overwrite a
  // user's same-named agent left us policing THEIR agent on their model, killing
  // it on every invocation with an error that blamed the config hook for not
  // applying - when it had applied and deliberately declined.
  let installed = false

  return {
    tool: {
      review_context: makeReviewContextTool(directory),
    },

    config: async (config) => {
      // Withdrawn first, so any failure below leaves the guard without standing
      // rather than leaving it armed over a name that is no longer ours.
      installed = false
      injectInto(config, options)

      // Verify what actually landed. Be precise about what this does and does
      // not cover, or a later maintainer will trust coverage that is not here.
      // opencode runs plugin config hooks SEQUENTIALLY over one shared config
      // object, and injectInto and fingerprint are synchronous with no await
      // between them - so this cannot catch a later plugin mutating our agents
      // after we return, and there is no merge phase for it to catch either.
      // What it actually covers is exactly two things: inject.js and verify.js
      // drifting apart, which is our own bug, and a config object that does not
      // retain writes.
      const problems = fingerprint(config, options)
      if (problems.length > 0) {
        throw new Error(
          "opencode-adversarial-review: the reviewer did not install correctly:\n  " +
          problems.join("\n  ") +
          "\nRefusing to continue rather than give you a reviewer that silently uses the wrong model.",
        )
      }
      installed = true
    },

    // Spec 3.4's third check, and the only one that runs outside the config
    // hook. The other two live inside it, so a hook that stops firing takes
    // both guards with it and the review proceeds on the session model. This
    // one fires per LLM request instead.
    //
    // Verified against opencode 1.18.23, recorded in contracts/: this
    // hook fires for a plugin-injected subagent carrying that agent's own
    // name and the model about to serve it, and throwing here aborts the
    // subagent and reaches the caller as `status: "error"` with this message
    // attached - not as an empty result that reads as a clean review.
    "chat.params": async (params) => {
      // No injection of ours landed, so nothing wearing these names is ours to
      // police. This is the whole of the collision case: the user owns the name,
      // we declined it, and their agent is none of our business.
      if (!installed) return

      // chat.params fires for title, build, summary and every other agent in
      // the session. Policing any of those would break the user's whole
      // opencode install the moment this plugin loads. Exact membership, not
      // a prefix test: "adversarial-review-mine" is somebody else's agent.
      if (!AGENTS.includes(params?.agent)) return

      const serving = servingModel(params.model)
      if (serving === null) {
        throw new Error(
          `opencode-adversarial-review: cannot tell which model is about to serve "${params.agent}". ` +
          `opencode reported ${describeShape(params.model)}, which carries no non-empty id or modelID alongside providerID. ` +
          `Refusing to run a review whose model cannot be verified. If opencode was just upgraded, this shape has ` +
          `changed and the plugin needs updating - re-run the probes in contracts/.`,
        )
      }
      if (serving !== options.model) {
        throw new Error(
          `opencode-adversarial-review: "${params.agent}" is about to be served by ${serving}, not the configured ` +
          `${options.model}. Refusing to run. A review by the wrong model is worse than no review, because it reads ` +
          `exactly the same. The config hook most likely did not apply - see the README's troubleshooting section.`,
        )
      }
    },
  }
}

export default AdversarialReview
