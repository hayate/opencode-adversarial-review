import test from "node:test"
import assert from "node:assert/strict"
import { AdversarialReview } from "../src/index.js"
import { AGENTS } from "../src/inject.js"

const input = { directory: "/tmp/repo", project: {}, client: {}, worktree: "/tmp/repo" }
const MODEL = "anthropic/claude-opus-5"

test("returns hooks including config and the review_context tool", async () => {
  const hooks = await AdversarialReview(input, {})
  assert.equal(typeof hooks.config, "function")
  assert.ok(hooks.tool.review_context)
})

test("the config hook injects with the default model", async () => {
  const hooks = await AdversarialReview(input, undefined)
  const config = {}
  await hooks.config(config)
  assert.equal(config.agent["adversarial-review"].model, MODEL)
})

test("the config hook honours a configured model for both agents", async () => {
  const hooks = await AdversarialReview(input, { model: "deepseek/deepseek-v4-pro" })
  const config = {}
  await hooks.config(config)
  assert.equal(config.agent["adversarial-review"].model, "deepseek/deepseek-v4-pro")
  assert.equal(config.agent["adversarial-review-design"].model, "deepseek/deepseek-v4-pro")
})

test("a bad model option fails loudly at load, not silently at review time", async () => {
  await assert.rejects(() => AdversarialReview(input, { model: "opus" }), /provider\/model/)
})

test("a collision surfaces as an error from the config hook", async () => {
  const hooks = await AdversarialReview(input, {})
  const config = { agent: { "adversarial-review": { prompt: "mine" } } }
  await assert.rejects(() => hooks.config(config), /Refusing to overwrite/)
})

// injectInto does full literal replacement, so re-injecting over a damaged
// copy of our own agent simply repairs it - the fingerprint inside the hook
// cannot be tripped that way. What it actually defends against is a config
// whose writes do not stick: a later merge phase, or a host that hands back a
// projection rather than the object it keeps. A getter returning a fresh copy
// on every read reproduces exactly that, and nothing else does.
test("a config that silently discards our writes is refused, not reported healthy", async () => {
  const hooks = await AdversarialReview(input, {})
  const config = { command: {} }
  let stored = {}
  Object.defineProperty(config, "agent", {
    configurable: true,
    enumerable: true,
    get: () => ({ ...stored }),
    set: (value) => { stored = value },
  })
  await assert.rejects(() => hooks.config(config), (e) => {
    assert.match(e.message, /did not install correctly/)
    assert.match(e.message, /"adversarial-review" is missing/)
    assert.match(e.message, /"adversarial-review-design" is missing/)
    assert.match(e.message, /Refusing to continue/)
    return true
  })
})

// ---------------------------------------------------------------------------
// Spec 3.4 check 3: the invocation-time check, the only one of the three that
// runs OUTSIDE the config hook. Verified against opencode 1.18.23 in
// plugin/contracts: chat.params fires per LLM request for a plugin-injected
// subagent, carries that agent's name and the model about to serve it, and a
// throw here aborts the subagent and reaches the caller as a named tool error.
// ---------------------------------------------------------------------------

const paramsInput = (agent, model) => ({
  sessionID: "ses_test", agent, model, provider: { id: "anthropic" }, message: {},
})

test("chat.params is registered at all, or check 3 does not exist", async () => {
  const hooks = await AdversarialReview(input, {})
  assert.equal(typeof hooks["chat.params"], "function")
})

for (const name of AGENTS) {
  test(`the correct serving model passes silently: ${name}`, async () => {
    const hooks = await AdversarialReview(input, {})
    await hooks["chat.params"](paramsInput(name, { providerID: "anthropic", id: "claude-opus-5" }), {})
  })

  test(`a WRONG serving model is refused at invocation: ${name}`, async () => {
    const hooks = await AdversarialReview(input, {})
    await assert.rejects(
      () => hooks["chat.params"](paramsInput(name, { providerID: "deepseek", id: "deepseek-v4-flash" }), {}),
      (e) => {
        assert.match(e.message, new RegExp(`"${name}"`))
        assert.match(e.message, /deepseek\/deepseek-v4-flash/)
        assert.match(e.message, /anthropic\/claude-opus-5/)
        return true
      },
    )
  })

  test(`an UNDETERMINABLE serving model is refused, not waved through: ${name}`, async () => {
    const hooks = await AdversarialReview(input, {})
    await assert.rejects(
      () => hooks["chat.params"](paramsInput(name, undefined), {}),
      /cannot tell which model/,
    )
  })

  // chat.params reports model.id; chat.message reports model.modelID, in the
  // same opencode version. Pinning only one turns the guard into a permanent
  // false alarm the first time the shape shifts.
  test(`the modelID spelling of the same model is accepted: ${name}`, async () => {
    const hooks = await AdversarialReview(input, {})
    await hooks["chat.params"](paramsInput(name, { providerID: "anthropic", modelID: "claude-opus-5" }), {})
  })
}

// chat.params fires for title, build, summary and every other agent in the
// session. A check that threw on those would break the user's whole opencode
// install the moment this plugin is loaded.
for (const other of ["title", "build", "general", "summary", "compaction"]) {
  test(`another agent's model is none of our business: ${other}`, async () => {
    const hooks = await AdversarialReview(input, {})
    await hooks["chat.params"](paramsInput(other, { providerID: "deepseek", id: "deepseek-v4-pro" }), {})
  })
}

test("an agent whose name merely starts with ours is not policed", async () => {
  const hooks = await AdversarialReview(input, {})
  await hooks["chat.params"](paramsInput("adversarial-review-mine", { providerID: "deepseek", id: "x" }), {})
})

test("a missing agent name is not policed, since we cannot know it is ours", async () => {
  const hooks = await AdversarialReview(input, {})
  await hooks["chat.params"](paramsInput(undefined, { providerID: "deepseek", id: "x" }), {})
})

test("a provider-qualified model with slashes in the id round-trips", async () => {
  const hooks = await AdversarialReview(input, { model: "openrouter/anthropic/claude-3.5-sonnet" })
  await hooks["chat.params"](
    paramsInput("adversarial-review", { providerID: "openrouter", id: "anthropic/claude-3.5-sonnet" }),
    {},
  )
  await assert.rejects(
    () => hooks["chat.params"](paramsInput("adversarial-review", { providerID: "openrouter", id: "anthropic/claude-3-opus" }), {}),
    /openrouter\/anthropic\/claude-3-opus/,
  )
})
