import test from "node:test"
import assert from "node:assert/strict"
import {
  CODE_REVIEW_PROMPT, DESIGN_REVIEW_PROMPT, COMPLETION_MARKER, isComplete,
} from "../src/prompts.js"

test("both prompts are substantial and load from disk", () => {
  assert.ok(CODE_REVIEW_PROMPT.length > 2000)
  assert.ok(DESIGN_REVIEW_PROMPT.length > 2000)
})

test("both prompts require the completion marker as the last line", () => {
  for (const prompt of [CODE_REVIEW_PROMPT, DESIGN_REVIEW_PROMPT]) {
    assert.ok(prompt.includes(COMPLETION_MARKER), "prompt must name the marker")
    assert.match(prompt, /last line/i)
  }
})

test("the code prompt classifies the surface before ordering the search", () => {
  // The spec's own fenced block hard-wraps this phrase across a line break;
  // \s+ tolerates that without reflowing the verbatim copied prompt text.
  assert.match(CODE_REVIEW_PROMPT, /SECURITY IS FIRST\s+TIER/)
  assert.match(CODE_REVIEW_PROMPT, /TESTS THAT CANNOT FAIL/)
  assert.ok(!/rarely where the yield is/.test(CODE_REVIEW_PROMPT),
    "the globally-demoting appsec claim was removed for a reason")
})

test("the design prompt attacks documents, not diffs", () => {
  assert.match(DESIGN_REVIEW_PROMPT, /CLAIMS THAT EXCEED THEIR EVIDENCE/)
  assert.match(DESIGN_REVIEW_PROMPT, /DO-NOT-BUILD-AS-WRITTEN/)
})

test("both prompts tell the reviewer it is read-only", () => {
  for (const prompt of [CODE_REVIEW_PROMPT, DESIGN_REVIEW_PROMPT]) {
    assert.match(prompt, /read-only/i)
  }
})

test("isComplete requires the marker on its own final line", () => {
  assert.equal(isComplete("findings\n\nREVIEW-COMPLETE"), true)
  assert.equal(isComplete("findings\n\nREVIEW-COMPLETE\n"), true)
  assert.equal(isComplete("findings\n\nREVIEW-COMPLETE  \n"), true)
  assert.equal(isComplete("findings, cut off mid-sen"), false)
  assert.equal(isComplete(""), false)
  assert.equal(isComplete("I will end with REVIEW-COMPLETE when done"), false,
    "a mention inside prose is not a completion")
})
