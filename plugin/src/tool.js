import { tool } from "@opencode-ai/plugin/tool"
import { runGit } from "./git-run.js"

const DESCRIPTION = [
  "Read repository history and diffs for review.",
  "",
  "You cannot pass git flags. Choose a mode and supply values:",
  "  mode=diff   base/head/paths  the change under review",
  "  mode=log    limit/ref/paths  recent history",
  "  mode=show   ref/paths        one commit",
  "  mode=status                  what is modified",
  "  mode=files                   what is tracked",
  "",
  "This tool only reads. It cannot write, and it is the only way you can run git.",
].join("\n")

// A trailing-only marker is the first thing lost if anything downstream -
// the opencode host's own message cap, a UI showing the first N characters,
// the model's own context handling - trims the tail of a long response. A
// reviewer that never sees the marker reasons about code it never received
// and may report "no issues" for a region it was never shown. So this notice
// is applied at both ends: the head marker is the one that has to survive,
// the tail marker is a second signal for whenever the whole body does
// arrive intact. Both are deliberately independent of whatever text
// git-run.js already wrote into stdout itself - this boundary carries its
// own explicit signal tied to the structured `truncated` field, rather than
// leaning on a string another module happens to embed.
const TRUNCATION_HEAD =
  "[NOTE: this output is incomplete - you are not seeing everything git produced. " +
  "Do not draw any conclusion about the part that is missing.]\n\n"

const TRUNCATION_TAIL =
  "\n\n[NOTE: this output is incomplete - you are not seeing everything git produced. " +
  "Narrow the request (fewer paths, a smaller limit, or a narrower range) to see the rest.]"

function successBody(result) {
  return result.stdout || "(no output)"
}

// `cause` is a closed set (see git-run.js): "refused", "git-error",
// "harness-error", or null on success. Collapsing all three failure causes
// into one generic "refused or failed" message - as a naive `!result.ok`
// check would - hides exactly the distinction that matters to the calling
// model: a "refused" request is a request problem worth retrying with
// different arguments; a "harness-error" is an environment problem that no
// argument will fix; and a "git-error" is git's own verdict, which may still
// carry real partial output worth reading rather than discarding.
function failureBody(result) {
  if (result.cause === "refused") {
    return (
      `Request refused before git ran: ${result.stderr}\n` +
      "This was rejected by the tool itself, not by git. Adjust the arguments and try again."
    )
  }

  if (result.cause === "harness-error") {
    return (
      `git could not be run: ${result.stderr}\n` +
      "This is an environment problem, not a request problem - a different mode, ref, or path will not fix it."
    )
  }

  // cause === "git-error": git ran and either failed or was killed by the
  // timeout. Any stdout it produced first is real and worth showing rather
  // than discarding.
  const partial = result.stdout
    ? `\n\nPartial output produced before the failure:\n${result.stdout}`
    : ""
  return `git failed: ${result.stderr}${partial}`
}

// `truncated` means the caller is not seeing everything git would have
// produced (see git-run.js). It is only ever true alongside a successful
// read that hit the size cap, a max-buffer read, or a git-error that
// captured some real stdout before failing - never alongside "refused" or
// "harness-error", both of which always report `truncated: false`. Wrapping
// here, once, keyed only on that field, means every present and future
// branch above gets the notice for free instead of each branch having to
// remember to add its own.
function toText(result) {
  const body = result.ok ? successBody(result) : failureBody(result)
  return result.truncated ? `${TRUNCATION_HEAD}${body}${TRUNCATION_TAIL}` : body
}

// This tool's contract is that it always returns text to the model, never
// throws. Do not rely on git-args.js's validation being exhaustive to
// guarantee that on its own - guarantee it here, at the boundary the model
// actually sees, so a bug two modules down (or in some future mode this
// tool grows) degrades to an error message instead of an unhandled
// rejection.
//
// Exported as a standalone function taking a thunk - rather than widening
// makeReviewContextTool's signature with an injectable runGit - so this
// guarantee is directly testable without adding a parameter whose only
// production caller always passes the same value. The same move as
// git-run.js's execOptions(cwd): extract the pure piece, test it
// structurally, keep the public constructor to the one argument it needs.
export async function safelyToText(operation) {
  let result
  try {
    result = await operation()
  } catch (error) {
    return `Unexpected error while running git: ${error?.message ?? String(error)}`
  }
  return toText(result)
}

export function makeReviewContextTool(directory) {
  return tool({
    description: DESCRIPTION,
    args: {
      mode: tool.schema.string().describe("diff | log | show | status | files"),
      base: tool.schema.string().optional().describe("base revision, e.g. main"),
      head: tool.schema.string().optional().describe("head revision; with base, produces base...head"),
      ref: tool.schema.string().optional().describe("a single revision, for show and log"),
      paths: tool.schema.array(tool.schema.string()).optional().describe("repository-relative paths"),
      limit: tool.schema.number().optional().describe("max commits for log, 1 to 1000"),
    },
    // `directory` is the only source of the git cwd, bound once here at
    // tool-registration time - never per call. `context` (the framework's
    // second execute() argument) carries its own `directory` field for the
    // session, but is intentionally never read: model-supplied `args` has
    // no cwd-shaped field among the six declared above, and even if a call
    // carried extra keys, runGit's cwd argument below always comes from
    // this closure, never from args or context.
    async execute(args, _context) {
      return safelyToText(() => runGit(args, directory))
    },
  })
}
