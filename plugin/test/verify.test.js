import test from "node:test"
import assert from "node:assert/strict"
import { injectInto } from "../src/inject.js"
import { fingerprint } from "../src/verify.js"

const opts = { model: "anthropic/claude-opus-5" }

function injected() {
  const config = {}
  injectInto(config, opts)
  return config
}

test("a freshly injected config is healthy", () => {
  assert.deepEqual(fingerprint(injected(), opts), [])
})

test("a MISSING agent is reported", () => {
  const config = injected()
  delete config.agent["adversarial-review"]
  const problems = fingerprint(config, opts)
  assert.equal(problems.length, 1)
  assert.match(problems[0], /missing/i)
  assert.match(problems[0], /adversarial-review/)
})

test("a WRONG MODEL is reported, which an existence check cannot see", () => {
  const config = injected()
  config.agent["adversarial-review"].model = "deepseek/deepseek-v4-flash"
  const problems = fingerprint(config, opts)
  assert.equal(problems.length, 1)
  assert.match(problems[0], /model/)
  assert.match(problems[0], /deepseek-v4-flash/)
})

test("a WEAKENED permission is reported", () => {
  const config = injected()
  config.agent["adversarial-review"].permission.edit = "allow"
  assert.match(fingerprint(config, opts).join(" "), /permission\.edit/)
})

test("a re-enabled write tool is reported", () => {
  const config = injected()
  config.agent["adversarial-review"].tools.write = true
  assert.match(fingerprint(config, opts).join(" "), /tools\.write/)
})

test("a replaced prompt is reported", () => {
  const config = injected()
  config.agent["adversarial-review"].prompt = "be nice about the code"
  assert.match(fingerprint(config, opts).join(" "), /prompt/)
})

test("a command unbound from its agent is reported", () => {
  const config = injected()
  config.command["adversarial-review"].agent = "build"
  assert.match(fingerprint(config, opts).join(" "), /agent binding/i)
})

test("a command that lost subtask is reported", () => {
  const config = injected()
  config.command["adversarial-review"].subtask = false
  assert.match(fingerprint(config, opts).join(" "), /subtask/)
})

test("several problems are all reported, not just the first", () => {
  const config = injected()
  delete config.agent["adversarial-review-design"]
  config.agent["adversarial-review"].model = "wrong/model"
  assert.equal(fingerprint(config, opts).length, 2)
})
