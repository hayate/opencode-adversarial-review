#!/usr/bin/env node
import fs from "node:fs"
import path from "node:path"
import process from "node:process"

const root = process.argv[2] ?? process.cwd()

const pkg = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"))
const lock = JSON.parse(fs.readFileSync(path.join(root, "package-lock.json"), "utf8"))
const lockRoot = lock.packages?.[""]

const mismatches = []
if (lock.name !== pkg.name) {
  mismatches.push(`package-lock.json name: expected ${pkg.name}, found ${lock.name}`)
}
if (lock.version !== pkg.version) {
  mismatches.push(`package-lock.json version: expected ${pkg.version}, found ${lock.version}`)
}
if (lockRoot?.version !== pkg.version) {
  mismatches.push(`package-lock.json packages[""].version: expected ${pkg.version}, found ${lockRoot?.version ?? "<missing>"}`)
}

if (mismatches.length > 0) {
  console.error(`Version metadata is out of sync:\n${mismatches.join("\n")}`)
  process.exitCode = 1
} else {
  console.log(`All version metadata matches ${pkg.version}.`)
}
