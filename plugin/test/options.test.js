import test from "node:test"
import assert from "node:assert/strict"
import { resolveOptions, OptionsError, DEFAULT_MODEL } from "../src/options.js"

test("defaults to claude-opus-5 when no options are given", () => {
  assert.equal(DEFAULT_MODEL, "anthropic/claude-opus-5")
  assert.equal(resolveOptions(undefined).model, DEFAULT_MODEL)
  assert.equal(resolveOptions({}).model, DEFAULT_MODEL)
})

test("accepts a provider/model reference", () => {
  assert.equal(resolveOptions({ model: "deepseek/deepseek-v4-pro" }).model, "deepseek/deepseek-v4-pro")
})

test("rejects a model reference without a provider", () => {
  assert.throws(() => resolveOptions({ model: "claude-opus-5" }), OptionsError)
})

test("rejects a non-string or empty model", () => {
  assert.throws(() => resolveOptions({ model: 5 }), OptionsError)
  assert.throws(() => resolveOptions({ model: "" }), OptionsError)
})

test("the error names the option and shows the expected shape", () => {
  try {
    resolveOptions({ model: "claude-opus-5" })
    assert.fail("should have thrown")
  } catch (error) {
    assert.match(error.message, /provider\/model/)
    assert.match(error.message, /claude-opus-5/)
  }
})
