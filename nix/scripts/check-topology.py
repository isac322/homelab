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
    'network = "10.223.0.0/24"',
    'listenPort = 51903',
):
    if required not in text:
        raise SystemExit(f"missing topology contract: {required}")
if not re.search(r'bhyoo-macbook-pro\s*=\s*\{\s*address\s*=\s*"10\.222\.0\.7/24";\s*publicKey\s*=\s*"5gchbvge1BmPYynDnRd2FMDRZTxorFFmCv9Ktl6amRI=";', text, re.S):
    raise SystemExit("MacBook live mesh identity changed")
if "10.222.0.134/32" in text:
    raise SystemExit("retired MacBook edge identity remains")
wg0_nodes = re.search(r"wg0Nodes = \{(.*?)\n  \};\n  wg0Edges", text, re.S).group(1)
node_count = len(re.findall(r"^    [a-z0-9-]+ = \{", wg0_nodes, re.M))
wg0_edges = re.search(r"wg0Edges = \{(.*?)\n  \};\n  wg1Nodes", text, re.S).group(1)
edge_count = len(re.findall(r"^    [a-z0-9-]+ = \{", wg0_edges, re.M))
expected_links = node_count * (node_count - 1) // 2 + edge_count
if (node_count, edge_count, expected_links) != (7, 14, 35):
    raise SystemExit(f"wg0 required link count changed: nodes={node_count} edges={edge_count} links={expected_links}")
for required in (
    'address = "10.223.0.65/24"',
    'address = "10.223.0.66/24"',
    'address = "10.223.0.67/24"',
    'address = "10.223.0.68/24"',
    'address = "10.223.0.69/24"',
    'groups.backbone = {',
):
    if required not in text:
        raise SystemExit(f"wg1 backbone contract missing: {required}")
wg1_nodes = re.search(r"wg1Nodes = \{(.*?)\n  \};\n  wg1Edges", text, re.S).group(1)
wg1_node_count = len(re.findall(r"^    [a-z0-9-]+ = \{", wg1_nodes, re.M))
wg1_links = wg1_node_count * (wg1_node_count - 1) // 2
if (wg1_node_count, wg1_links) != (5, 10):
    raise SystemExit(f"wg1 backbone link count changed: nodes={wg1_node_count} links={wg1_links}")
if text.count('fullMeshLinks "wg1"') != 1:
    raise SystemExit("wg1 backbone full-mesh construction changed")
if "PrivateKey = " in text or "PresharedKey = " in text:
    raise SystemExit("topology contains plaintext secret")
if "REPLACE_WITH_OFFLINE_OPERATOR_AGE_RECIPIENT" not in text:
    raise SystemExit("operator recovery recipient hard gate missing")
if text.count("iscsiClient = true;") != 5:
    raise SystemExit("live backbone iSCSI client scope must remain exactly five hosts")
if not re.search(r'rpi4\s*=\s*mkNode.*?"eth0"\s+4096\s+\{', text, re.S):
    raise SystemExit("rpi4 memory topology must match the live ~4 GiB host")
if not re.search(r'rock5bp\s*=\s*mkNode.*?"eth0"\s+32768\s+\{', text, re.S):
    raise SystemExit("rock5bp memory topology must match the live ~32 GiB host")
if 'managed = pair.a != "bhyoo-macbook-pro" && pair.b != "bhyoo-macbook-pro";' not in text:
    raise SystemExit("MacBook links must remain outside repository-owned PSK rotation")
print("topology: ok")
