import test from "node:test"
import assert from "node:assert/strict"
import { DEFECT_FILE, namesDefect, reportsAnyFinding, gradeRun } from "../smoke/grade.mjs"

const DEFECT = "send_digest.py"

test("naming the file without saying anything is wrong is not a catch", () => {
  assert.equal(namesDefect("I read notifications/management/commands/send_digest.py and views.py.", DEFECT), false)
})

test("saying something is wrong without naming the file is not a catch", () => {
  assert.equal(namesDefect("One call site was not updated and will raise TypeError.", DEFECT), false)
})

test("both together is a catch", () => {
  assert.equal(namesDefect("send_digest.py still calls the old signature - that call site was not updated.", DEFECT), true)
})

test("matching is case-insensitive, since prose capitalisation varies by condition", () => {
  assert.equal(namesDefect("SEND_DIGEST.PY: MISSED CALL SITE", DEFECT), true)
})

test("empty and non-string output is never a catch", () => {
  for (const bad of ["", "   ", null, undefined, 42]) assert.equal(namesDefect(bad, DEFECT), false)
})

test("every fixture the runner stages has a defect file recorded", () => {
  assert.deepEqual(Object.keys(DEFECT_FILE).sort(), ["py-callsite-01", "py-callsite-02"])
})

test("an unrecorded fixture throws rather than grading as a miss", () => {
  assert.throws(() => gradeRun({ kind: "bad", fixture: "py-callsite-99", text: "x" }), /no defect file/)
})

// The same detector on both populations, which is what makes the two numbers
// comparable at all.
test("the detector firing on a known_good tree is a false positive, not a catch", () => {
  const text = "send_digest.py was not updated for the new signature."
  const bad = gradeRun({ kind: "bad", fixture: "py-callsite-01", text })
  const good = gradeRun({ kind: "good", fixture: "py-callsite-01", text })
  assert.equal(bad.caught, true)
  assert.equal(bad.defectFalsePositive, null)
  assert.equal(good.caught, null)
  assert.equal(good.defectFalsePositive, true)
})

test("a clean review of a known_good tree is neither", () => {
  const g = gradeRun({ kind: "good", fixture: "py-callsite-01", text: "SHIP. No material findings." })
  assert.equal(g.defectFalsePositive, false)
  assert.equal(g.anyFindingFalsePositive, false)
})

test("an empty review is recorded as empty, not as a clean pass", () => {
  const g = gradeRun({ kind: "good", fixture: "py-callsite-01", text: "" })
  assert.equal(g.empty, true)
  assert.equal(g.anyFindingFalsePositive, false)
})

test("a bulleted item counts as a finding under the crude spec-5.1 measure", () => {
  assert.equal(reportsAnyFinding("Findings:\n- views.py leaks the server timezone"), true)
  assert.equal(reportsAnyFinding("1. serializers.py drops the parameter"), true)
})

test("an explicit no-findings statement is not a finding, even beside a list", () => {
  assert.equal(reportsAnyFinding("No material findings.\n- checked views.py\n- checked serializers.py"), false)
})

test("a DO-NOT-SHIP verdict is a finding even with no list", () => {
  assert.equal(reportsAnyFinding("DO-NOT-SHIP: the digest path is wrong."), true)
})

test("prose with no list and no verdict is not counted as a finding", () => {
  assert.equal(reportsAnyFinding("I reviewed the change and it looks consistent with the ticket."), false)
})
