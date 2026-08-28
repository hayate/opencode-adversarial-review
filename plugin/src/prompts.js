import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { dirname, join } from "node:path"

const here = dirname(fileURLToPath(import.meta.url))
const read = (name) => readFileSync(join(here, "prompts", name), "utf8")

export const COMPLETION_MARKER = "REVIEW-COMPLETE"
export const CODE_REVIEW_PROMPT = read("code-review.md")
export const DESIGN_REVIEW_PROMPT = read("design-review.md")

// The marker must be the final non-empty line. This detects TRUNCATION: a
// review cut off before it ever reaches the marker correctly reads as
// incomplete, and a reviewer that only MENTIONS the marker mid-prose (for
// example, describing the output format) does not pass either.
//
// KNOWN LIMITATION, stated plainly rather than papered over: this cannot
// detect a model that echoes or restates the marker early, in defiance of
// the prompt's own "Never emit it early" instruction, and is then cut off
// immediately after that echo, before writing any real findings or actually
// finishing. In that case the marker still ends up as the final non-empty
// line of the partial text, so this function reports completion for a
// review that did not in fact complete. The prompt's "Never emit it early"
// instruction is the PRIMARY control against that failure mode; this
// function is a secondary, best-effort check layered on top of it, not a
// substitute for it. No last-line text heuristic can close this hole from
// content alone; see the test suite for the documented case this misses.
export function isComplete(text) {
  if (typeof text !== "string") return false
  const lines = text.split("\n").map((line) => line.trim()).filter((line) => line.length > 0)
  return lines.length > 0 && lines[lines.length - 1] === COMPLETION_MARKER
}
