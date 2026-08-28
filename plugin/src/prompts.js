import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { dirname, join } from "node:path"

const here = dirname(fileURLToPath(import.meta.url))
const read = (name) => readFileSync(join(here, "prompts", name), "utf8")

export const COMPLETION_MARKER = "REVIEW-COMPLETE"
export const CODE_REVIEW_PROMPT = read("code-review.md")
export const DESIGN_REVIEW_PROMPT = read("design-review.md")

// The marker must be the final non-empty line. A reviewer that MENTIONS it
// mid-prose has not finished, and a truncated review that happens to contain
// the word must not read as complete.
export function isComplete(text) {
  if (typeof text !== "string") return false
  const lines = text.split("\n").map((line) => line.trim()).filter((line) => line.length > 0)
  return lines.length > 0 && lines[lines.length - 1] === COMPLETION_MARKER
}
