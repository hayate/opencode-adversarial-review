export class GitRequestError extends Error {}

const MODES = new Set(["diff", "log", "show", "status", "files"])
const MAX_LIMIT = 1000

function reject(why) {
  throw new GitRequestError(why)
}

// A value the model supplied. It may name a revision or a path; it may never
// begin with a dash, because every git write and exec primitive we care about
// arrives as an option - `--output=` creates or truncates a file, `-c` injects
// config, `--exec-path` relocates the binary directory.
function safeValue(value, label) {
  if (typeof value !== "string" || value.length === 0) reject(`${label} must be a non-empty string`)
  if (value.includes("\u0000")) reject(`${label} contains a NUL byte`)
  if (value.startsWith("-")) reject(`${label} may not begin with a dash: ${value}`)
  return value
}

function safePath(value) {
  const path = safeValue(value, "path")
  if (path.startsWith("/")) reject(`path must be repository-relative: ${path}`)
  if (path.split("/").includes("..")) reject(`path may not traverse upward: ${path}`)
  return path
}

function safeLimit(limit) {
  if (!Number.isInteger(limit)) reject("limit must be an integer")
  if (limit < 1 || limit > MAX_LIMIT) reject(`limit must be between 1 and ${MAX_LIMIT}`)
  return String(limit)
}

export function buildGitArgs(request) {
  const mode = request?.mode
  if (!MODES.has(mode)) reject(`unknown mode: ${String(mode)}`)

  if (mode === "status") return ["status", "--porcelain"]
  if (mode === "files") return ["ls-files"]

  // --no-ext-diff and --no-textconv stop a repository's own configuration from
  // executing a program during what is meant to be a read.
  const args = [mode, "--no-ext-diff", "--no-textconv"]

  if (mode === "log" && request.limit !== undefined) {
    args.push("-n", safeLimit(request.limit))
  }

  if (request.ref !== undefined && (request.base !== undefined || request.head !== undefined)) {
    reject("ref cannot be combined with base or head")
  }
  if (request.head !== undefined && request.base === undefined) {
    reject("head requires base")
  }

  if (request.base !== undefined) {
    const base = safeValue(request.base, "base")
    args.push(request.head !== undefined
      ? `${base}...${safeValue(request.head, "head")}`
      : base)
  } else if (request.ref !== undefined) {
    args.push(safeValue(request.ref, "ref"))
  }

  args.push("--")
  for (const path of request.paths ?? []) args.push(safePath(path))
  return args
}
