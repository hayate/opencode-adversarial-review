import test from "node:test"
import assert from "node:assert/strict"
import { injectInto, CollisionError, InvalidConfigError, AGENTS, COMMANDS } from "../src/inject.js"
import { CODE_REVIEW_PROMPT, DESIGN_REVIEW_PROMPT } from "../src/prompts.js"

const opts = { model: "anthropic/claude-opus-5" }

test("injects two agents and two commands", () => {
  const config = {}
  injectInto(config, opts)
  assert.deepEqual(Object.keys(config.agent).sort(), [...AGENTS].sort())
  assert.deepEqual(Object.keys(config.command).sort(), [...COMMANDS].sort())
})

test("the code reviewer is read-only and pinned to the configured model", () => {
  const config = {}
  injectInto(config, opts)
  const agent = config.agent["floor-review"]
  assert.equal(agent.model, "anthropic/claude-opus-5")
  assert.equal(agent.mode, "subagent")
  assert.equal(agent.permission.edit, "deny")
  assert.equal(agent.permission.bash, "deny")
  assert.equal(agent.permission.webfetch, "deny")
  assert.equal(agent.tools.write, false)
  assert.equal(agent.tools.edit, false)
  assert.equal(agent.tools.patch, false)
  assert.equal(agent.tools.bash, false)
  assert.equal(agent.tools.review_context, true)
})

test("the design reviewer gets no git tool at all", () => {
  const config = {}
  injectInto(config, opts)
  const agent = config.agent["floor-review-design"]
  assert.equal(agent.tools.review_context, false)
  assert.equal(agent.tools.bash, false)
  assert.equal(agent.permission.edit, "deny")
})

test("existing unrelated agents and commands are preserved", () => {
  const config = { agent: { mine: { prompt: "x" } }, command: { mine: { template: "y" } } }
  injectInto(config, opts)
  assert.deepEqual(config.agent.mine, { prompt: "x" })
  assert.deepEqual(config.command.mine, { template: "y" })
})

test("a colliding agent name aborts WITHOUT mutating", () => {
  const config = { agent: { "floor-review": { prompt: "the user's own" } } }
  assert.throws(() => injectInto(config, opts), CollisionError)
  assert.deepEqual(config.agent["floor-review"], { prompt: "the user's own" },
    "the user's agent must survive untouched")
  assert.equal(config.command, undefined, "nothing may be injected after a collision")
})

test("a colliding command name aborts WITHOUT mutating", () => {
  const config = { command: { "floor-review": { template: "the user's own" } } }
  assert.throws(() => injectInto(config, opts), CollisionError)
  assert.deepEqual(config.command["floor-review"], { template: "the user's own" })
  assert.equal(config.agent, undefined)
})

test("the collision error names what collided and how to resolve it", () => {
  try {
    injectInto({ agent: { "floor-review": {} } }, opts)
    assert.fail("should have thrown")
  } catch (error) {
    assert.match(error.message, /floor-review/)
    assert.match(error.message, /rename/i)
  }
})

test("the command template tells the caller to check for the marker", () => {
  const config = {}
  injectInto(config, opts)
  for (const name of COMMANDS) {
    assert.match(config.command[name].template, /REVIEW-COMPLETE/)
    assert.equal(config.command[name].subtask, true)
  }
})

test("injection is idempotent for our own agents", () => {
  const config = {}
  injectInto(config, opts)
  const first = JSON.stringify(config)
  injectInto(config, opts)
  assert.equal(JSON.stringify(config), first)
})

test("the design agent also runs in subagent mode", () => {
  const config = {}
  injectInto(config, opts)
  assert.equal(config.agent["floor-review-design"].mode, "subagent")
})

test("the design agent is also pinned to the configured model", () => {
  const config = {}
  injectInto(config, opts)
  assert.equal(config.agent["floor-review-design"].model, "anthropic/claude-opus-5")
})

test("each agent carries its own prompt, not the other's", () => {
  const config = {}
  injectInto(config, opts)
  assert.equal(config.agent["floor-review"].prompt, CODE_REVIEW_PROMPT)
  assert.equal(config.agent["floor-review-design"].prompt, DESIGN_REVIEW_PROMPT)
})

test("each command binds to its own agent, not the other's", () => {
  const config = {}
  injectInto(config, opts)
  assert.equal(config.command["floor-review"].agent, "floor-review")
  assert.equal(config.command["floor-review-design"].agent, "floor-review-design")
})

test("an array config.agent throws instead of silently losing both security agents", () => {
  const config = { agent: [] }
  assert.throws(() => injectInto(config, opts), InvalidConfigError)
  assert.deepEqual(config.agent, [], "the array must be left untouched, not silently populated")
})

test("a string config.agent throws our own error type, not a raw TypeError", () => {
  const config = { agent: "oops" }
  assert.throws(() => injectInto(config, opts), InvalidConfigError)
})

test("an array config.command throws instead of silently losing both commands", () => {
  const config = { command: [] }
  assert.throws(() => injectInto(config, opts), InvalidConfigError)
  assert.deepEqual(config.command, [], "the array must be left untouched, not silently populated")
})

test("a string config.command throws our own error type, not a raw TypeError", () => {
  const config = { command: "oops" }
  assert.throws(() => injectInto(config, opts), InvalidConfigError)
})

test("a null config.agent and config.command are still coerced to empty objects, not rejected", () => {
  const config = { agent: null, command: null }
  injectInto(config, opts)
  assert.deepEqual(Object.keys(config.agent).sort(), [...AGENTS].sort())
  assert.deepEqual(Object.keys(config.command).sort(), [...COMMANDS].sort())
})

// The same silent-loss bug one level up. `config` itself being an array is not
// reachable through opencode's own contract, which always passes a plain
// object - but injectInto is an exported entry point, and the failure mode is
// the worst available one: the two assignments attach string-keyed properties
// to the array, JSON.stringify serialises it back to "[]", and both read-only
// security agents vanish with no error anywhere.
test("an array config throws instead of silently losing everything on serialisation", () => {
  const config = []
  assert.throws(() => injectInto(config, opts), InvalidConfigError)
  assert.equal(JSON.stringify(config), "[]")
  assert.equal(config.agent, undefined, "the array must be left untouched, not silently populated")
})

test("a string config throws our own error type, not a raw TypeError", () => {
  assert.throws(() => injectInto("oops", opts), InvalidConfigError)
})

test("a null config throws our own error type, not a raw TypeError", () => {
  assert.throws(() => injectInto(null, opts), InvalidConfigError)
})
