#!/usr/bin/env bash
# Build both sandbox images and record what was actually built.
# Later runs execute BY DIGEST, never by :latest.
set -euo pipefail
cd "$(dirname "$0")"

BASE_DIGEST="sha256:16f75ad0fbc6c4883a8afd63b2d700c3cf68ccffc1aaeca5304ca0a3a908451f"

for img in agent grading; do
  echo "==> building odr-$img"
  podman build -t "localhost/odr-$img:latest" -f "$img.Containerfile" .
done

AGENT_ID=$(podman image inspect localhost/odr-agent:latest --format '{{.Id}}')
GRADING_ID=$(podman image inspect localhost/odr-grading:latest --format '{{.Id}}')
OC_VERSION=$(podman run --rm localhost/odr-agent:latest opencode --version | tr -d '\r\n')

jq -n \
  --arg agent "sha256:$AGENT_ID" \
  --arg grading "sha256:$GRADING_ID" \
  --arg oc "$OC_VERSION" \
  --arg base "$BASE_DIGEST" \
  '{agent: $agent, grading: $grading, opencode_version: $oc, base_image: $base}' \
  > digests.json

echo "==> recorded:"
cat digests.json
