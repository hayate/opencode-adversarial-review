#!/usr/bin/env bash
# Record real opencode outputs from INSIDE the pinned agent image.
#
# Why in-image: a host-captured contract describes a different runtime than
# the eval uses. Plan revision 2 got this wrong; Codex caught it.
# Why one container lifecycle: `opencode export` must run with the same HOME
# as the run, or it cannot find the session.
#
# The positive control uses a SYNTHETIC seeded config, never the operator's
# real one - that would publish provider settings to a public repo.
set -euo pipefail

OUT="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$OUT/.." && pwd)"
IMAGE="${ODR_AGENT_IMAGE:-localhost/odr-agent:latest}"
ENV_FILE="$HOME/.config/opencode-deepseek-review/env"

[ -f "$ENV_FILE" ] || { echo "ERROR: run bash ~/maya/odr-keys.sh first" >&2; exit 1; }
# shellcheck disable=SC1090
. "$ENV_FILE"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/repo" "$WORK/seed"
printf 'def add(a, b):\n    return a + b\n' > "$WORK/repo/calc.py"
printf '{"provider":{"canary-provider":{"options":{"baseURL":"https://canary.invalid"}}}}\n' \
  > "$WORK/seed/seeded-config.json"

echo "==> capturing from $IMAGE"
podman run --rm --network=bridge \
  --security-opt no-new-privileges --cap-drop ALL \
  --memory 2g --cpus 2 --pids-limit 512 \
  --read-only --tmpfs /tmp:rw,size=1g \
  -v "$WORK/repo:/workspace:rw,Z" \
  -v "$WORK/seed:/seed:ro,Z" \
  -v "$OUT:/out:rw,Z" \
  -w /workspace \
  -e "DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY" \
  -e HOME=/tmp/h -e XDG_CONFIG_HOME=/tmp/h/.config \
  -e XDG_DATA_HOME=/tmp/h/.local/share -e XDG_CACHE_HOME=/tmp/h/.cache \
  -e XDG_STATE_HOME=/tmp/h/.local/state \
  -e OPENCODE_DISABLE_PROJECT_CONFIG=1 -e OPENCODE_DISABLE_DEFAULT_PLUGINS=1 \
  -e OPENCODE_DISABLE_AUTOUPDATE=1 -e OPENCODE_DISABLE_MODELS_FETCH=1 \
  -e OPENCODE_DISABLE_SHARE=1 -e OPENCODE_DISABLE_AUTOCOMPACT=1 \
  "$IMAGE" bash -euo pipefail -c '
    mkdir -p /tmp/h/.config /tmp/h/.local/share /tmp/h/.cache /tmp/h/.local/state

    echo "--- debug config (sterile)"
    opencode debug config --pure > /out/debug-config-sterile.json 2>/out/debug-config-sterile.err || true

    echo "--- debug config (seeded: POSITIVE CONTROL)"
    OPENCODE_CONFIG_CONTENT="$(cat /seed/seeded-config.json)" \
      opencode debug config > /out/debug-config-seeded.json 2>/dev/null || true

    echo "--- debug skill / agent"
    opencode debug skill  > /out/debug-skill.txt 2>&1 || true
    opencode debug agent build > /out/debug-agent-build.txt 2>&1 || true

    echo "--- printing auth for the run"
    mkdir -p /tmp/h/.local/share/opencode
    printf "{\"deepseek\":{\"type\":\"api\",\"key\":\"%s\"}}" "$DEEPSEEK_API_KEY" \
      > /tmp/h/.local/share/opencode/auth.json

    echo "--- real run (deepseek-v4-flash, trivial task)"
    opencode run --pure --format json -m deepseek/deepseek-v4-flash \
      "Add a subtract(a, b) function to calc.py, then run: python -c \"import calc; print(calc.subtract(5,3))\"" \
      > /out/run-events.ndjson 2>/out/run-events.err || echo "run exited $?"

    echo "--- extracting session id (schema-aware, not a regex)"
    SESSION=$(python3 - <<PY
import json, sys
found = None
for line in open("/out/run-events.ndjson", errors="replace"):
    line = line.strip()
    if not line:
        continue
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        continue
    stack = [obj]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ("sessionID", "sessionId", "session_id") and isinstance(v, str):
                    found = v; break
                stack.append(v)
        elif isinstance(node, list):
            stack.extend(node)
        if found: break
    if found: break
print(found or "", end="")
PY
)
    if [ -n "$SESSION" ]; then
      echo "--- exporting session $SESSION"
      opencode export "$SESSION" > /out/session-export.json 2>/out/session-export.err || true
      echo "$SESSION" > /out/session-id.txt
    else
      echo "!! no session id found - inspect run-events.ndjson by hand" >&2
    fi
  ' 2>&1 | tail -20
echo "==> done"
