import test from "node:test"
import assert from "node:assert/strict"
import { injectInto, CollisionError, AGENTS, COMMANDS } from "../src/inject.js"

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
  const agent = config.agent["adversarial-review"]
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
  const agent = config.agent["adversarial-review-design"]
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
  const config = { agent: { "adversarial-review": { prompt: "the user's own" } } }
  assert.throws(() => injectInto(config, opts), CollisionError)
  assert.deepEqual(config.agent["adversarial-review"], { prompt: "the user's own" },
    "the user's agent must survive untouched")
  assert.equal(config.command, undefined, "nothing may be injected after a collision")
})

test("a colliding command name aborts WITHOUT mutating", () => {
  const config = { command: { "adversarial-review": { template: "the user's own" } } }
  assert.throws(() => injectInto(config, opts), CollisionError)
  assert.deepEqual(config.command["adversarial-review"], { template: "the user's own" })
  assert.equal(config.agent, undefined)
})

test("the collision error names what collided and how to resolve it", () => {
  try {
    injectInto({ agent: { "adversarial-review": {} } }, opts)
    assert.fail("should have thrown")
  } catch (error) {
    assert.match(error.message, /adversarial-review/)
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
