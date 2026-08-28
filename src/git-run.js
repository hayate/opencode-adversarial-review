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
    // GIT_OPTIONAL_LOCKS=0 keeps git from taking locks or refreshing the index
    // for operations that only read. A reviewer must not write to the tree it
    // is reviewing. Stated honestly: a review claimed `git status` rewrites
    // .git/index, and it could NOT be reproduced here - the index was
    // byte-identical across runs. This is kept anyway because it is one env
    // entry, it is exactly the documented switch for the concern, and the
    // read-only guarantee is one we make publicly.
    env: { PATH: process.env.PATH, HOME: process.env.HOME, GIT_TERMINAL_PROMPT: "0", GIT_OPTIONAL_LOCKS: "0" },
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
//
// `truncated` means the caller is not seeing everything git would have
// produced - not merely "we hit MAX_OUTPUT". It is true when: our own
// MAX_OUTPUT cap sliced a successful read; Node's maxBuffer cut a read
// short (cause "max-buffer" - always true, by construction); or git
// produced some stdout before failing or being killed (cause "git-error"
// with any stdout at all - a failed or killed run gives no guarantee that
// what we captured is everything a clean run would have produced, so any
// prefix we did capture is flagged as partial rather than presented as
// complete). It is false only when stdout is genuinely everything there
// is to see: an under-the-cap successful read, a refusal, a harness-error,
// or a git-error that produced no output before failing. This must hold on
// every branch below - a truncated read must never be reported as
// complete, in either direction.
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
        // Any stdout the process emitted before that is real and worth
        // returning - "as much as we saw before this broke" is more useful
        // to a reviewer than nothing. It is never presented as complete:
        // a failing or killed run gives no guarantee the rest would ever
        // have matched a clean success, so any output we did capture is
        // flagged as truncated, and capped the same way a successful read
        // is.
        const truncated = stdout.length > 0
        resolve({
          ok: false,
          stdout: truncated ? stdout.slice(0, MAX_OUTPUT) + "\n[output truncated]" : stdout,
          stderr: stderr || error.message,
          truncated,
          cause: "git-error",
        })
      },
    )
  })
}
