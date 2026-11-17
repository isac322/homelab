#!/usr/bin/env python3
"""Probe both internal Gateways using synthetic credentials; never print raw log lines."""
import argparse
from datetime import datetime, timezone
import json
import secrets
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("--context", default="homelab-backbone")
args = parser.parse_args()
started = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
nonce = secrets.token_hex(8)
marker = "gateway-privacy-qa-" + nonce
credentials = ["fake-path-" + nonce, "fake-query-" + nonce,
               "fake-authorization-" + nonce, "fake-cookie-" + nonce]
for host, address in [("immich.bhyoo.com", "10.222.0.1"),
                      ("immich.bhyoo.com", "10.222.0.2"),
                      ("immich.bhyoo.com", "10.222.0.3"),
                      ("jellyfin.bhyoo.com", "10.222.0.4")]:
    subprocess.run(["curl", "--silent", "--show-error", "--max-time", "15",
                    "--resolve", f"{host}:443:{address}", "--output", "/dev/null",
                    "--header", "User-Agent: " + marker,
                    "--header", "Authorization: Bearer " + credentials[2],
                    "--header", "Cookie: session=" + credentials[3],
                    f"https://{host}/share/{credentials[0]}?token={credentials[1]}"],
                   check=True, capture_output=True)
log_command = ["kubectl", "--context", args.context, "--request-timeout=15s",
               "-n", "kube-system", "logs", "-l", "k8s-app=cilium-envoy",
               "--all-containers=true", "--max-log-requests=10", "--tail=-1",
               "--since-time=" + started, "--follow=true"]
try:
    logs = subprocess.run(log_command, text=True, capture_output=True, check=True, timeout=8).stdout
except subprocess.TimeoutExpired as error:
    # Envoy flushes access logs asynchronously. Observe one bounded stream
    # rather than assuming all records exist immediately after the response.
    logs = (error.stdout or b"").decode() if isinstance(error.stdout, bytes) else (error.stdout or "")
entries = []
for line in logs.splitlines():
    try:
        entry = json.loads(line)
    except json.JSONDecodeError:
        continue
    if entry.get("user_agent") == marker:
        entries.append(entry)
assert len(entries) == 4, f"Expected 4 probe records, found {len(entries)}; retry after xDS convergence."
for entry in entries:
    assert "path" not in entry, "Raw URL path logging is forbidden."
    assert entry.get("route"), "Static route identity is missing."
    assert entry.get("gateway") and entry.get("client_ip") and entry.get("response_code")
    encoded = json.dumps(entry)
    assert not any(value in encoded for value in credentials), "A synthetic credential leaked into a log field."
assert {entry["gateway"] for entry in entries} == {"ingress-ctrl/bhyoo-gateway", "ingress-ctrl/nas-gateway"}
print("PASS: four Gateway request records retain route/status/client metadata without URL, Authorization or Cookie credentials.")
