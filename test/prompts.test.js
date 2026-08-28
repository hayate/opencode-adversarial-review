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

test("both prompts contain the exact read-only sentence, verbatim, once", () => {
  // Round 2 finding: a substring-and-negation check ("read-only" present,
  // "not read-only" absent) has no notion of WHERE the clause sits or what
  // governs it. It passes on "read-only in principle, but you may edit when
  // necessary", on "read-only. Recommend changes; write them." (the "do not"
  // quietly dropped), and on the clause being deleted outright while an
  // unrelated decoy phrase containing "read-only" sits elsewhere in the file.
  // Matching the whole operative sentence, verbatim, closes all three: any
  // edit to it - weakening, softening, or deleting - changes this exact
  // string. This is deliberately brittle: these prompts are copied verbatim
  // from the spec, so a real rewording must touch the spec too, and a test
  // that survives silent edits to a safety instruction is worse than none.
  assert.ok(CODE_REVIEW_PROMPT.includes(
    "You are read-only. Recommend changes; do not write them."))
  assert.ok(DESIGN_REVIEW_PROMPT.includes(
    "You are read-only; recommend changes, do not make them."))
})

test("all six verification-before-reporting items survive in the code prompt", () => {
  // Fixed ALL-CAPS tags, pinned individually rather than as a pair, because
  // the earlier partial pin (2 shared + 1 unique per file) left 3 of 6 items
  // per file free to delete with the suite still green. The length floor
  // above catches nothing either - each item is ~100-150 chars against files
  // of 10000+. Case-sensitive on purpose: the code prompt's WIRING section
  // separately says lowercase "unreachable code", and a case-insensitive
  // match on UNREACHABLE would count that unrelated sentence as coverage.
  const tags = [
    "UNREACHABLE",
    "EXCLUDED BY THIS DOMAIN",
    "RIGHT DIAGNOSIS, WRONG FIX",
    "\"MAKE IT CONSISTENT\" WHERE BOTH OPTIONS ARE WORSE",
    "EQUIVALENT OR DELIBERATE",
    "THE PREMISE DOES NOT HOLD",
  ]
  for (const tag of tags) {
    assert.ok(CODE_REVIEW_PROMPT.includes(tag), `missing taxonomy item: ${tag}`)
  }
})

test("all six verification-before-reporting items survive in the design prompt", () => {
  const tags = [
    "THE DOCUMENT ALREADY SAYS IT",
    "OUT OF SCOPE BY DECLARATION",
    "A DIFFERENT DESIGN, NOT A DEFECT",
    "RIGHT DIAGNOSIS, WRONG FIX",
    "THE PREMISE DOES NOT HOLD",
    "UNVERIFIED ASSERTION OF YOUR OWN",
  ]
  for (const tag of tags) {
    assert.ok(DESIGN_REVIEW_PROMPT.includes(tag), `missing taxonomy item: ${tag}`)
  }
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
  // making isComplete stricter without discussing the tradeoff first. This
  // test and the bare-marker test below are a PAIR - see the comment above
  // isComplete for why both must be revisited together.
  const echoedThenCutOff = "I'll close with the required marker on its own line:\n\nREVIEW-COMPLETE"
  assert.equal(isComplete(echoedThenCutOff), true,
    "known limitation: an early echo of the marker immediately followed by truncation reads as complete")
})

test("a bare marker with no preamble at all is NOT detected - known limitation", () => {
  // The worst-case shape of the same hole, and the one a naive strengthening
  // is most likely to "fix" without closing anything: a provider call cut
  // off so early that only the marker itself made it through - no verdict,
  // no findings, nothing. isComplete cannot distinguish that from a genuine
  // "sound, nothing to report" completion, since both are exactly one
  // non-empty line consisting of the marker. If isComplete is ever
  // strengthened (for example, to require more than a bare marker), that
  // change would make THIS test fail while leaving the "echoes the marker
  // early" test above passing unchanged - so a fix must be checked against
  // both, and a change that leaves both still passing has not addressed the
  // general hole, only moved it.
  assert.equal(isComplete(COMPLETION_MARKER), true,
    "known limitation: a bare marker with no preceding content reads as complete")
})
