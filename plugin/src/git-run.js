import { execFile } from "node:child_process"
import { buildGitArgs, GitRequestError } from "./git-args.js"

export const MAX_OUTPUT = 200000
export const TIMEOUT_MS = 20000

// The execFile options as a small pure function, so the options object -
// most importantly killSignal and the pruned env - can be asserted on
// directly in tests without spawning a process. See the "structural, not
// behavioural" tests in git-run.test.js for why that split exists.
export function execOptions(cwd) {
  return {
    cwd,
    timeout: TIMEOUT_MS,
    // execFile's timeout sends SIGTERM by default, which a process can
    // trap or ignore, leaving the promise to hang well past TIMEOUT_MS.
    // These are read-only git commands, so there is nothing for a
    // graceful shutdown to protect - escalate straight to SIGKILL so the
    // timeout is an actual wall-clock bound.
    killSignal: "SIGKILL",
    maxBuffer: MAX_OUTPUT * 4,
    windowsHide: true,
    // A minimal environment. This blocks GIT_EXTERNAL_DIFF and the
    // GIT_CONFIG_* env-var mechanism from reaching what is meant to be a
    // read. It does NOT block file-based config reached through HOME
    // (for example a hostile core.fsmonitor in ~/.gitconfig) - that is
    // accepted because the model cannot influence HOME or its contents;
    // anyone who can write to it already owns the host.
    env: { PATH: process.env.PATH, HOME: process.env.HOME, GIT_TERMINAL_PROMPT: "0" },
  }
}

// execFile, never exec: no shell means no redirection, no substitution, no
// chaining. The argv is built by buildGitArgs, so the model contributes values
// and never options.
//
// `cause` names why a request failed, as a small closed set, so a caller
// never has to regex stderr to tell these apart:
//   "refused"       the request was rejected before it reached git
//   "git-error"     git ran and exited non-zero, or was killed (timeout)
//   "harness-error" git could not even be started (bad cwd, missing binary)
//   "max-buffer"    not a failure: a successful read that exceeded the
//                   node-level output buffer (see below); ok is true
// `cause` is null on an ordinary successful read, including one truncated
// only by our own MAX_OUTPUT cap.
export function runGit(request, cwd) {
  let args
  try {
    args = buildGitArgs(request)
  } catch (error) {
    if (error instanceof GitRequestError) {
      return Promise.resolve({ ok: false, stdout: "", stderr: error.message, truncated: false, cause: "refused" })
    }
    throw error
  }

  return new Promise((resolve) => {
    execFile(
      "git",
      args,
      execOptions(cwd),
      (error, stdout, stderr) => {
        if (!error) {
          const truncated = stdout.length > MAX_OUTPUT
          resolve({
            ok: true,
            stdout: truncated ? stdout.slice(0, MAX_OUTPUT) + "\n[output truncated]" : stdout,
            stderr,
            truncated,
            cause: null,
          })
          return
        }

        // Node kills the child once accumulated stdout exceeds `maxBuffer`.
        // git itself was reading fine; only our own buffer ran out. That is
        // a successful read that produced more than we can hold, not a git
        // failure - report it as such, in our own words rather than
        // Node's internal error string.
        if (error.code === "ERR_CHILD_PROCESS_STDIO_MAXBUFFER") {
          resolve({
            ok: true,
            stdout: stdout.slice(0, MAX_OUTPUT) + "\n[output truncated]",
            stderr: "output exceeded the buffer limit and was truncated",
            truncated: true,
            cause: "max-buffer",
          })
          return
        }

        // git could not even be started: missing binary, a cwd that does
        // not exist, or similar. This is our own environment breaking, not
        // a verdict git reached about the request.
        if (error.code === "ENOENT") {
          resolve({ ok: false, stdout: "", stderr: error.message, truncated: false, cause: "harness-error" })
          return
        }

        // git ran and either exited non-zero or was killed by the timeout.
        resolve({
          ok: false,
          stdout: "",
          stderr: stderr || error.message,
          truncated: false,
          cause: "git-error",
        })
      },
    )
  })
}
