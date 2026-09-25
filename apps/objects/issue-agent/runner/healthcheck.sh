#!/usr/bin/env bash
# Exec probe: the runner rewrites runner.state.json on each heartbeat (60s by default).
# `hapi runner status` always exits 0, so it cannot be used as a probe.
set -euo pipefail

state="${HAPI_HOME:?HAPI_HOME is required}/runner.state.json"
max_age="${1:-180}"

exec python3 - "$state" "$max_age" <<'PY'
import json, os, sys, time

path, max_age = sys.argv[1], float(sys.argv[2])
try:
    age = time.time() - os.stat(path).st_mtime
    pid = int(json.load(open(path))["pid"])
    os.kill(pid, 0)
except (OSError, ValueError, KeyError, TypeError) as exc:
    sys.exit(f"runner unhealthy: {exc}")
if age > max_age:
    sys.exit(f"runner unhealthy: heartbeat {age:.0f}s old")
PY
