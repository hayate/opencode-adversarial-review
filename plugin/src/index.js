import { resolveOptions } from "./options.js"
import { AGENTS, injectInto } from "./inject.js"
import { fingerprint } from "./verify.js"
import { makeReviewContextTool } from "./tool.js"

// opencode 1.18.23 spells the model id differently on two hooks that describe
// the same thing: chat.params carries `model.id`, chat.message carries
// `model.modelID`, with `model.providerID` on both (see plugin/contracts).
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
  if (typeof providerID !== "string" || typeof modelID !== "string") return null
  return `${providerID}/${modelID}`
}

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
      // hook never firing at all - that is what chat.params below is for.
      const problems = fingerprint(config, options)
      if (problems.length > 0) {
        throw new Error(
          "opencode-adversarial-review: the reviewer did not install correctly:\n  " +
          problems.join("\n  ") +
          "\nRefusing to continue rather than give you a reviewer that silently uses the wrong model.",
        )
      }
    },

    // Spec 3.4's third check, and the only one that runs outside the config
    // hook. The other two live inside it, so a hook that stops firing takes
    // both guards with it and the review proceeds on the session model. This
    // one fires per LLM request instead.
    //
    // Verified against opencode 1.18.23, recorded in plugin/contracts: this
    // hook fires for a plugin-injected subagent carrying that agent's own
    // name and the model about to serve it, and throwing here aborts the
    // subagent and reaches the caller as `status: "error"` with this message
    // attached - not as an empty result that reads as a clean review.
    "chat.params": async (params) => {
      // chat.params fires for title, build, summary and every other agent in
      // the session. Policing any of those would break the user's whole
      // opencode install the moment this plugin loads. Exact membership, not
      // a prefix test: "adversarial-review-mine" is somebody else's agent.
      if (!AGENTS.includes(params?.agent)) return

      const serving = servingModel(params.model)
      if (serving === null) {
        throw new Error(
          `opencode-adversarial-review: cannot tell which model is about to serve "${params.agent}". ` +
          `opencode reported ${JSON.stringify(params.model)}, which carries neither id nor modelID alongside providerID. ` +
          `Refusing to run a review whose model cannot be verified. If opencode was just upgraded, this shape has ` +
          `changed and the plugin needs updating - re-run the probes in plugin/contracts.`,
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
