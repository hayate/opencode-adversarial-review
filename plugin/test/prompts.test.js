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

test("both prompts state, not merely mention, that the reviewer is read-only", () => {
  // A plain /read-only/i substring match passes on "You are NOT read-only."
  // just as happily as on the real instruction, so it cannot detect an
  // inversion of the property it exists to pin. Assert the actual clause,
  // and assert the negation is absent, so a flipped instruction fails loudly.
  for (const prompt of [CODE_REVIEW_PROMPT, DESIGN_REVIEW_PROMPT]) {
    assert.match(prompt, /you are read-only/i)
    assert.ok(!/not read-only/i.test(prompt),
      "an inverted read-only instruction must not pass a substring-only check")
  }
})

test("the verification-before-reporting taxonomy survives in both prompts", () => {
  // These are the least paraphrase-survivable part of the prompts: exact,
  // capitalized labels for specific ways a confident-sounding finding turns
  // out to be wrong. Deleting this taxonomy (or the calibration and probe
  // tests below) leaves both files comfortably over the 2000-character floor
  // asserted above, so that test alone would not catch the loss - these
  // pin the substance a length check cannot see.
  // RIGHT DIAGNOSIS, WRONG FIX and THE PREMISE DOES NOT HOLD are shared
  // verbatim between both prompts' six-item lists; the rest are specific to
  // one prompt's version of the taxonomy.
  for (const prompt of [CODE_REVIEW_PROMPT, DESIGN_REVIEW_PROMPT]) {
    assert.match(prompt, /RIGHT DIAGNOSIS, WRONG FIX/)
    assert.match(prompt, /THE PREMISE DOES NOT HOLD/)
  }
  assert.match(CODE_REVIEW_PROMPT, /UNREACHABLE/)
  assert.match(DESIGN_REVIEW_PROMPT, /THE DOCUMENT ALREADY SAYS IT/)
})

test("the calibration rule against manufacturing a finding per category survives", () => {
  // A reviewer padding output with one weak finding per axis defeats
  // adversarial review as surely as a reviewer that finds nothing. \s+
  // tolerates the spec's own line wrap of this phrase in one of the prompts.
  for (const prompt of [CODE_REVIEW_PROMPT, DESIGN_REVIEW_PROMPT]) {
    assert.match(prompt, /manufacture a finding\s+per\s+category/i)
  }
})

test("the code prompt legitimizes 'this needs a probe' as a real finding", () => {
  // Without this line, a model under pressure to look thorough will assert a
  // confident wrong answer instead of naming what it could not verify - the
  // exact failure mode <verification_before_reporting> exists to prevent.
  assert.match(CODE_REVIEW_PROMPT, /"This needs a probe"/)
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

test("a model that echoes the marker early and is then cut off is NOT detected - known limitation", () => {
  // The model is following the prompt's own output-contract instructions,
  // restates that it will close with the marker on its own line, and the
  // provider call is cut off immediately after that echoed marker - before
  // any real findings and before the review actually finished. The marker is
  // nonetheless the final non-empty line of the partial text, so isComplete
  // reports this as complete. That is a false positive, documented rather
  // than hidden: see the comment above isComplete for why this cannot be
  // cheaply closed from text content alone, and do not "fix" this test by
  // making isComplete stricter without discussing the tradeoff first.
  const echoedThenCutOff = "I'll close with the required marker on its own line:\n\nREVIEW-COMPLETE"
  assert.equal(isComplete(echoedThenCutOff), true,
    "known limitation: an early echo of the marker immediately followed by truncation reads as complete")
})
