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
if len(node_ids) != len(set(node_ids)):
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
if "readPublicKey ./../identities/wireguard/node-bhyoo-macbook-pro.pub" not in text:
    raise SystemExit("MacBook live mesh identity must come from an identity file")
if "10.222.0.134/32" in text:
    raise SystemExit("retired MacBook edge identity remains")
wg0_nodes = re.search(r"wg0Nodes = \{(.*?)\n  \};\n  wg0Edges", text, re.S).group(1)
node_count = len(re.findall(r"^    [a-z0-9-]+ = \{", wg0_nodes, re.M))
wg0_edges = re.search(r"wg0Edges = \{(.*?)\n  \};\n  wg1Nodes", text, re.S).group(1)
edge_count = len(re.findall(r"^    [a-z0-9-]+ = \{", wg0_edges, re.M))
if "wg0PeerNodes" not in text or "fullMeshLinks \"wg0\"" not in text:
    raise SystemExit("wg0 lifecycle-aware full-mesh construction changed")
if node_count < 2 or edge_count < 0:
    raise SystemExit("wg0 topology must contain at least two nodes")
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
if "wg1PeerNodes" not in text or 'fullMeshLinks "wg1"' not in text:
    raise SystemExit("wg1 lifecycle-aware full-mesh construction changed")
if wg1_node_count < 2:
    raise SystemExit("wg1 topology must contain at least two nodes")
if text.count('fullMeshLinks "wg1"') != 1:
    raise SystemExit("wg1 backbone full-mesh construction changed")
if "PrivateKey = " in text or "PresharedKey = " in text:
    raise SystemExit("topology contains plaintext secret")
if not re.search(r"secretRecipients\s*=\s*\{.*?recovery\s*=", text, re.S):
    raise SystemExit("operator recovery recipient contract missing")
if text.count("iscsiClient = true;") < 5:
    raise SystemExit("live backbone iSCSI client scope must retain the existing five hosts")
if 'lifecycle = extra.lifecycle or "active";' not in text:
    raise SystemExit("node lifecycle state is not declarative")
if '"provisioning"' not in text or '"decommissioning"' not in text:
    raise SystemExit("node lifecycle transitions are not declared")
if not re.search(r'activeNodes\s*=\s*lib\.filterAttrs.*lifecycle\s*==\s*"active"', text):
    raise SystemExit("active lifecycle partition is not declared")
if not re.search(r'provisioningNodes\s*=\s*lib\.filterAttrs.*lifecycle\s*==\s*"provisioning"', text):
    raise SystemExit("provisioning lifecycle partition is not declared")
if not re.search(r'decommissioningNodes\s*=\s*lib\.filterAttrs.*lifecycle\s*==\s*"decommissioning"', text):
    raise SystemExit("decommissioning lifecycle partition is not declared")
if not re.search(r'deployableNodes\s*=\s*lib\.filterAttrs.*lifecycle\s*!=\s*"decommissioning"', text):
    raise SystemExit("decommissioning nodes remain deployable")
if not re.search(r'rpi4\s*=\s*mkNode.*?"eth0"\s+4096\s+\{', text, re.S):
    raise SystemExit("rpi4 memory topology must match the live ~4 GiB host")
if not re.search(r'rock5bp\s*=\s*mkNode.*?"eth0"\s+32768\s+\{', text, re.S):
    raise SystemExit("rock5bp memory topology must match the live ~32 GiB host")
if 'managed = pair.a != "bhyoo-macbook-pro" && pair.b != "bhyoo-macbook-pro";' not in text:
    raise SystemExit("MacBook links must remain outside repository-owned PSK rotation")
if "k3sVersion" in text:
    raise SystemExit("Rancher system-upgrade-controller, not Nix topology, owns K3s versions")
if not re.search(
    r'rock5bp\s*=.*?firewall\s*=\s*\{\s*sambaClients\s*=\s*\[\s*"192\.168\.219\.139/32"\s*\];\s*netbios\s*=\s*true;',
    text,
    re.S,
):
    raise SystemExit("rock5bp Samba and NetBIOS firewall scope changed")
print("topology: ok")
