#!/usr/bin/env bash
# Exercise the deployed ingress boundary without reading memory or credentials.
set -euo pipefail
context="${1:-homelab-backbone}"
k=(kubectl --context "$context" --request-timeout=15s)
curl --fail --silent --show-error --max-time 15 \
  https://hindsight-api.bhyoo.com/health >/dev/null
"${k[@]}" -n hindsight exec deploy/hindsight-control-plane -- node -e '
fetch("http://hindsight-api:8888/health", {signal: AbortSignal.timeout(5000)})
  .then(r => { if (r.status !== 200) process.exitCode = 1; })
  .catch(() => { process.exitCode = 1; });'
for pod in isacmes-0 isacmes-jay-0 yjyou-0; do
  "${k[@]}" -n hermes exec "$pod" -c hermes -- python -c \
    'import urllib.request; assert urllib.request.urlopen("http://hindsight-api.hindsight.svc:8888/health", timeout=5).status == 200'
done
"${k[@]}" -n immich exec deploy/immich-server -- node -e '
fetch("http://hindsight-api.hindsight.svc:8888/health", {signal: AbortSignal.timeout(5000)})
  .then(r => { console.error("Unrelated client reached Hindsight:", r.status); process.exitCode = 1; })
  .catch(e => { if (e.name !== "TimeoutError") { console.error(e.name); process.exitCode = 1; } });'
printf '%s\n' 'PASS: gateway, control plane and Hermes allowed; unrelated application blocked.'
