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

// Appended whenever `truncated` is true, on top of whatever text git-run.js
// already wrote into stdout itself. It is deliberately independent of that
// inline text: a reviewer reading a silently-cut diff reasons about code it
// cannot see, so this boundary carries its own explicit signal tied to the
// structured `truncated` field, rather than leaning on a string another
// module happens to embed.
const TRUNCATION_NOTICE =
  "\n\n[NOTE: this output is incomplete - git produced more than is shown above. " +
  "Narrow the request (fewer paths, a smaller limit, or a narrower range) rather than reasoning about what is missing.]"

function successText(result) {
  const body = result.stdout || "(no output)"
  return result.truncated ? `${body}${TRUNCATION_NOTICE}` : body
}

// `cause` is a closed set (see git-run.js): "refused", "git-error",
// "harness-error", or null on success. Collapsing all three failure causes
// into one generic "refused or failed" message - as a naive `!result.ok`
// check would - hides exactly the distinction that matters to the calling
// model: a "refused" request is a request problem worth retrying with
// different arguments; a "harness-error" is an environment problem that no
// argument will fix; and a "git-error" is git's own verdict, which may still
// carry real partial output worth reading rather than discarding.
function failureText(result) {
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
  // than discarding. runGit's own `truncated` is always true here whenever
  // stdout is non-empty, because a failed or killed run gives no guarantee
  // the rest would have matched a clean success - so this is never
  // presented as the complete output.
  const partial = result.stdout
    ? `\n\nPartial output produced before the failure (incomplete, not the full answer):\n${result.stdout}`
    : ""
  return `git failed: ${result.stderr}${partial}`
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
      const result = await runGit(args, directory)
      return result.ok ? successText(result) : failureText(result)
    },
  })
}
