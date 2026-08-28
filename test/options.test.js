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

// openrouter routes to other providers' models using a model id that itself
// contains a slash: provider "openrouter", model id "anthropic/claude-3.5-sonnet".
// This is a legitimate, working opencode model reference and MUST stay
// accepted. Do not tighten validation to require exactly two components -
// that would reject this working setup while claiming the config is wrong.
test("accepts a multi-slash reference whose model id itself contains a slash", () => {
  assert.equal(
    resolveOptions({ model: "openrouter/anthropic/claude-3.5-sonnet" }).model,
    "openrouter/anthropic/claude-3.5-sonnet",
  )
})

// "a/b/c" has the exact same shape as the openrouter case above: three
// non-empty slash-separated components, no whitespace, no leading or
// trailing slash. There is no character-level property that distinguishes
// "an implausible provider name" from "a real one" - only a provider
// registry could do that, which is out of scope here. So this is accepted
// for the same structural reason the openrouter case is, not rejected.
test("accepts other multi-component references for the same structural reason", () => {
  assert.equal(resolveOptions({ model: "a/b/c" }).model, "a/b/c")
})

test("rejects a model reference without a provider", () => {
  assert.throws(() => resolveOptions({ model: "claude-opus-5" }), OptionsError)
})

test("rejects a non-string or empty model", () => {
  assert.throws(() => resolveOptions({ model: 5 }), OptionsError)
  assert.throws(() => resolveOptions({ model: "" }), OptionsError)
})

// Without the `typeof model !== "string"` guard, a value whose toString()
// returns a valid-looking reference would slip through any regex-based
// check (regex .test() coerces its argument to a string first), leaving a
// non-string `model` in the resolved result.
test("rejects a non-string model even when its toString looks valid", () => {
  const fakeModel = { toString: () => "anthropic/claude-opus-5" }
  assert.throws(() => resolveOptions({ model: fakeModel }), OptionsError)
})

// The old regex `/^[^/\s]+\/[^/\s]+/` had no trailing `$`, so it matched a
// valid provider/model PREFIX and silently ignored everything after it.
// Each of these is a plausible JSONC typo (trailing note, trailing
// whitespace, trailing slash) that must fail loudly here instead of
// reaching opencode.
for (const bad of [
  "anthropic/claude-opus-5 (recommended)",
  "anthropic/claude-opus-5\n",
  "anthropic/claude-opus-5\t",
  "anthropic/claude-opus-5/",
]) {
  test(`rejects an unanchored match: ${JSON.stringify(bad)}`, () => {
    assert.throws(() => resolveOptions({ model: bad }), OptionsError)
  })
}

test("rejects a value with an empty path component", () => {
  assert.throws(() => resolveOptions({ model: "a//b" }), OptionsError)
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

test("the non-string error also echoes what was given", () => {
  try {
    resolveOptions({ model: 5 })
    assert.fail("should have thrown")
  } catch (error) {
    assert.match(error.message, /provider\/model/)
    assert.match(error.message, /5/)
  }
})
