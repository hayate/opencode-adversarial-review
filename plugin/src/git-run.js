import { execFile } from "node:child_process"
import { buildGitArgs, GitRequestError } from "./git-args.js"

const MAX_OUTPUT = 200000
const TIMEOUT_MS = 20000

// execFile, never exec: no shell means no redirection, no substitution, no
// chaining. The argv is built by buildGitArgs, so the model contributes values
// and never options.
export function runGit(request, cwd) {
  let args
  try {
    args = buildGitArgs(request)
  } catch (error) {
    if (error instanceof GitRequestError) {
      return Promise.resolve({ ok: false, stdout: "", stderr: error.message, truncated: false })
    }
    throw error
  }

  return new Promise((resolve) => {
    execFile(
      "git",
      args,
      {
        cwd,
        timeout: TIMEOUT_MS,
        maxBuffer: MAX_OUTPUT * 4,
        windowsHide: true,
        // A minimal environment. GIT_EXTERNAL_DIFF and GIT_CONFIG_* in the
        // ambient environment would otherwise reach a read.
        env: { PATH: process.env.PATH, HOME: process.env.HOME, GIT_TERMINAL_PROMPT: "0" },
      },
      (error, stdout, stderr) => {
        const truncated = stdout.length > MAX_OUTPUT
        resolve({
          ok: !error,
          stdout: truncated ? stdout.slice(0, MAX_OUTPUT) + "\n[output truncated]" : stdout,
          stderr: error ? (stderr || error.message) : stderr,
          truncated,
        })
      },
    )
  })
}
