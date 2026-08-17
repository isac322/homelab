#!/usr/bin/env python3
from pathlib import Path
import os
import re

root = Path(os.environ.get("HOMELAB_SOURCE_ROOT", Path(__file__).resolve().parents[2]))
text = (root / "nix/lib/topology.nix").read_text()
required_hosts = {"n2p1", "n2p2", "rpi4", "rpi5", "rock5bp", "macmini", "bhyoo-macbook-pro"}
for host in required_hosts:
    if not re.search(rf"^\s+{re.escape(host)}\s*=", text, re.M):
        raise SystemExit(f"missing host: {host}")
node_ids = re.findall(r'mkNode\s+"([^"]+)"', text)
if len(node_ids) != len(set(node_ids)) or len(node_ids) != len(required_hosts):
    raise SystemExit("nodeId uniqueness changed")
addresses = re.findall(r'address\s*=\s*"([0-9.]+)/(?:24|32)"', text)
if len(addresses) != len(set(addresses)):
    raise SystemExit("duplicate WireGuard address")
for required in (
    'network = "10.222.0.0/24"',
    'trustedNetwork = "10.222.0.0/26"',
    'edgeNetwork = "10.222.0.128/25"',
    'gateway = "rpi5"',
    'listenPort = 51902',
):
    if required not in text:
        raise SystemExit(f"missing topology contract: {required}")
if not re.search(r'bhyoo-macbook-pro\s*=\s*\{\s*address\s*=\s*"10\.222\.0\.7/24";\s*publicKey\s*=\s*"5gchbvge1BmPYynDnRd2FMDRZTxorFFmCv9Ktl6amRI=";', text, re.S):
    raise SystemExit("MacBook live mesh identity changed")
if "10.222.0.134/32" in text:
    raise SystemExit("retired MacBook edge identity remains")
wg0_nodes = re.search(r"wg0Nodes = \{(.*?)\n  \};\n  wg0Edges", text, re.S).group(1)
node_count = len(re.findall(r"^    [a-z0-9-]+ = \{", wg0_nodes, re.M))
wg0_edges = re.search(r"wg0Edges = \{(.*?)\n  \};\n\n  combinations", text, re.S).group(1)
edge_count = len(re.findall(r"^    [a-z0-9-]+ = \{", wg0_edges, re.M))
expected_links = node_count * (node_count - 1) // 2 + edge_count
if (node_count, edge_count, expected_links) != (7, 14, 35):
    raise SystemExit(f"wg0 required link count changed: nodes={node_count} edges={edge_count} links={expected_links}")
for retired in ("oracle4", "wg1", "10.223.0."):
    if retired in text:
        raise SystemExit(f"retired topology remains: {retired}")
if "PrivateKey = " in text or "PresharedKey = " in text:
    raise SystemExit("topology contains plaintext secret")
if "REPLACE_WITH_OFFLINE_OPERATOR_AGE_RECIPIENT" not in text:
    raise SystemExit("operator recovery recipient hard gate missing")
print("topology: ok")
