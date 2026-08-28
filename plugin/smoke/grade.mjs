// Grading for the fixture smoke test. Deliberately mechanical and deliberately
// crude: every rule here is a keyword rule over the reviewer's prose, because
// the three conditions produce three different output shapes and anything
// tuned to the doctrine prompt's own output contract would score the doctrine
// condition on a home advantage.
//
// Read plugin/smoke/README.md before using any number this produces.

// The planted defect in each known_bad tree is a call site that should have
// been updated and was not. It is therefore ABSENT from the diff, and a
// reviewer only finds it by reading the tree.
export const DEFECT_FILE = {
  "py-callsite-01": "send_digest.py",
  "py-callsite-02": "recovery.py",
}

// A file mention alone is not a finding: every condition lists files it read.
// Requiring one of these alongside it is what separates "mentioned the file"
// from "said something is wrong with it".
const DEFECT_TERMS = [
  "call site", "callsite", "call-site", "caller",
  "signature", "argument", "parameter", "positional",
  "not updated", "was not updated", "never updated", "missed", "missing",
  "stale", "out of date", "outdated", "inconsistent",
  "typeerror", "will fail", "would fail", "breaks", "broken",
]

const has = (text, needle) => text.toLowerCase().includes(needle.toLowerCase())

// The SAME detector runs on every tree. On a known_bad tree firing is a catch;
// on a known_good tree firing is a false positive, because the tree does not
// contain the defect it is describing. Symmetry is the point: a detector with
// one definition and two populations is a measurement, whereas separate rules
// per population would be two unrelated heuristics wearing one table.
export function namesDefect(text, defectFile) {
  if (typeof text !== "string" || !text.trim()) return false
  if (!has(text, defectFile)) return false
  return DEFECT_TERMS.some((term) => has(text, term))
}

// Spec 5.1's own question - "on a known_good tree, did it report any finding at
// all?" - kept because the spec asks for it, and reported separately because it
// is the weaker of the two. Spec 5.1 says so itself: passing the planted grader
// does not prove a tree is otherwise defect-free, so a genuine unrelated
// finding is counted here as a false positive when it is nothing of the kind.
const FINDING_ITEM = /^[ \t]*(?:\d+[.)]|[-*+•])[ \t]+\S/m

export function reportsAnyFinding(text) {
  if (typeof text !== "string" || !text.trim()) return false
  if (/\bDO[- ]?NOT[- ]?SHIP\b/i.test(text)) return true
  if (/\bno (?:material )?(?:findings|issues)\b/i.test(text)) return false
  return FINDING_ITEM.test(text)
}

export function gradeRun({ kind, fixture, text }) {
  const defectFile = DEFECT_FILE[fixture]
  if (!defectFile) throw new Error(`no defect file recorded for fixture ${fixture}`)
  const fired = namesDefect(text, defectFile)
  return {
    fired,
    caught: kind === "bad" ? fired : null,
    defectFalsePositive: kind === "good" ? fired : null,
    anyFindingFalsePositive: kind === "good" ? reportsAnyFinding(text) : null,
    empty: typeof text !== "string" || !text.trim(),
  }
}
