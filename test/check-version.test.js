import test from "node:test"
import assert from "node:assert/strict"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { spawnSync } from "node:child_process"
import { fileURLToPath } from "node:url"

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const SCRIPT = path.join(ROOT, "scripts", "check-version.mjs")

function fixture(version, lockVersion) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "oc-check-version-"))
  fs.writeFileSync(
    path.join(dir, "package.json"),
    `${JSON.stringify({ name: "x", version }, null, 2)}\n`
  )
  fs.writeFileSync(
    path.join(dir, "package-lock.json"),
    `${JSON.stringify({ name: "x", version: lockVersion, lockfileVersion: 3, packages: { "": { name: "x", version: lockVersion } } }, null, 2)}\n`
  )
  return dir
}

test("check-version passes when package.json and the lockfile agree", () => {
  const dir = fixture("1.0.0", "1.0.0")
  const result = spawnSync("node", [SCRIPT, dir], { encoding: "utf8" })
  assert.equal(result.status, 0, result.stderr)
  assert.match(result.stdout, /matches 1\.0\.0/)
})

test("check-version fails when the lockfile version differs", () => {
  const dir = fixture("1.0.0", "0.9.0")
  const result = spawnSync("node", [SCRIPT, dir], { encoding: "utf8" })
  assert.notEqual(result.status, 0, "must exit nonzero on mismatch")
  assert.match(result.stderr, /out of sync/)
})

test("check-version fails when the lockfile name differs", () => {
  const dir = fixture("1.0.0", "1.0.0")
  const lock = JSON.parse(fs.readFileSync(path.join(dir, "package-lock.json"), "utf8"))
  lock.name = "old-name"
  fs.writeFileSync(path.join(dir, "package-lock.json"), `${JSON.stringify(lock, null, 2)}\n`)
  const result = spawnSync("node", [SCRIPT, dir], { encoding: "utf8" })
  assert.notEqual(result.status, 0, "must exit nonzero on name mismatch")
})
