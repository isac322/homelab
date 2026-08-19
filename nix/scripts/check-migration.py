#!/usr/bin/env python3
from pathlib import Path
import os
import re

root = Path(os.environ.get("HOMELAB_SOURCE_ROOT", Path(__file__).resolve().parents[2]))


def source(relative: str) -> str:
    return (root / relative).read_text()


def require(relative: str, *needles: str) -> None:
    text = source(relative)
    for needle in needles:
        if needle not in text:
            raise SystemExit(f"{relative}: missing contract {needle!r}")


def forbid(relative: str, *needles: str) -> None:
    text = source(relative)
    for needle in needles:
        if needle in text:
            raise SystemExit(f"{relative}: forbidden contract {needle!r}")


require(
    "nix/modules/linux/base.nix",
    "10-homelab-lan.network",
    "DNSOverTLS=yes",
    "MulticastDNS=yes",
    "LLMNR=no",
    "lib.mkIf k8sMember",
    "systemd/zram-generator.conf",
    "tmpfiles.d/60-homelab-runtime-tuning.conf",
    "tmpfiles.d/20-homelab-resolv.conf",
    'source = "${pkgs.tzdata}/share/zoneinfo/Asia/Seoul"',
    "AuthorizedKeysFile .ssh/authorized_keys /etc/ssh/authorized_keys.d/%u",
    "ssh/authorized_keys.d/democratic-csi",
)
forbid(
    "nix/modules/linux/base.nix",
    "homelab-host-settings =",
    "homelab-runtime-tuning =",
    "homelab-legacy-tuning-cleanup =",
    "mkswap /dev/zram0",
)
require(
    "nix/modules/linux/packages.nix",
    "system-manager.preActivationAssertions",
    "required distro packages are missing",
    '"iptables-persistent"',
    '"systemd-zram-generator"',
    '"zram-generator"',
    "default = true;",
)
forbid(
    "nix/modules/linux/packages.nix",
    '"acl"',
    "apt-get upgrade",
    "pacman -Syu",
    "homelab-distro-packages",
    "homelab-iscsi-client",
)
require(
    "nix/modules/linux/firewall.nix",
    "--dport 9962",
    "--dport 9965",
    '"iptables/rules.v4"',
    '"iptables/iptables.rules"',
    ":INPUT DROP [0:0]",
    "-A INPUT -j HOMELAB_INPUT",
    "-A FORWARD -j HOMELAB_FORWARD",
)
forbid(
    "nix/modules/linux/firewall.nix",
    '${topology.wg0.edgeNetwork} -d ${topology.wg0.edgeNetwork} -j ACCEPT',
    "systemd.services.homelab-firewall",
    "iptables-save > /run",
)
require(
    "nix/modules/linux/wireguard.nix",
    "wg1PeerNames",
    'Endpoint=${topology.nodes.${peer}.lanAddress}',
    "[WireGuardPeer]",
    "PrivateKeyFile=${credentialPath",
    "PresharedKeyFile=${credentialPath",
    "LoadCredentialEncrypted=",
    "/var/lib/homelab-secrets/active",
)
forbid(
    "nix/modules/linux/wireguard.nix",
    "systemd.services.homelab-wireguard",
    "wg syncconf",
    "/run/homelab-wireguard-",
)
require(
    "nix/scripts/homelab-host",
    "bootstrap-host",
    "secretGeneration",
    "different Git revision",
    "--baseline",
    "restore_recovery",
    "deactivate_system_manager",
    "/etc/shadow",
    "/root/.ssh/authorized_keys",
    "/home/*/.ssh/authorized_keys",
    "apply_native_runtime",
    "systemd-tmpfiles --create",
    "iptables-restore --noflush --wait",
    "cleanup_legacy_files",
    "! systemctl cat",
    "reconcile_distro_packages",
    "--version 1.20.0",
    "restore_runtime_firewall",
    "/etc/iptables",
    "policy-rc.d",
    "FIREWALL_SERVICE",
    "locale -a",
    "verify_legacy_cleanup",
    "assert_iptables_nft_backend",
    '"(nf_tables)"',
    "iptables-backend=",
)
require(
    "ssh_pub_keys/democratic-csi.pub",
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIE5qnSjgYu7YDfPDhESjZXQE+n9Jm/PUGfo8ROpjkI2T",
)
forbid("nix/scripts/homelab-host", "--version 1.19.6")
forbid(
    "nix/scripts/homelab-host",
    "update-alternatives",
    "iptables-legacy",
    "ip6tables-legacy",
)
host_migration = source("nix/scripts/homelab-host")
for description, pattern in (
    (
        "runtime firewall capture must assert nft before iptables-save",
        r"capture_runtime_firewall\(\).*?assert_iptables_nft_backend.*?iptables-save",
    ),
    (
        "runtime firewall restore must assert nft before iptables-restore",
        r"restore_runtime_firewall\(\).*?assert_iptables_nft_backend.*?iptables-restore",
    ),
    (
        "prepare must assert nft before secret staging",
        r"prepare\|deploy\).*?reconcile_distro_packages.*?assert_iptables_nft_backend.*?stage_result=",
    ),
    (
        "activate must assert nft before arming the legacy handoff",
        r"  activate\).*?assert_iptables_nft_backend.*?k3s-handoff.*?arm",
    ),
    (
        "verify-host must assert nft before runtime verification",
        r"verify-host\|verify\).*?assert_iptables_nft_backend.*?current_baseline=",
    ),
):
    if not re.search(pattern, host_migration, re.DOTALL):
        raise SystemExit(f"nix/scripts/homelab-host: {description}")
require(
    "nix/scripts/wireguard-secrets",
    "unmanaged link has no repository-owned endpoint bundle",
    "/var/lib/rancher/k3s/server/token",
    "plaintext_workdir",
    "systemd-creds encrypt --with-key=host",
    "/var/lib/homelab-secrets",
)
forbid(
    "nix/scripts/wireguard-secrets",
    "/var/lib/rancher/k3s/agent/token",
    "base=/run/homelab-secrets",
)
require(
    "nix/scripts/issue-kubeconfig",
    "O=homelab:masters",
    "config view --raw --minify",
    "no certificate was issued",
)
require(
    "nix/scripts/sync-bootstrap-secret",
    ".external_secrets_access_key.value.id",
    ".external_secrets_access_key.value.secret",
)
forbid("nix/scripts/sync-bootstrap-secret", "external_secrets_cluster_store_aws")
require(
    "nix/modules/linux/k3s-host.nix",
    "LoadCredentialEncrypted",
    "/run/credentials/homelab-k3s.service/k3s-token",
    '"iptables.service"',
    '"netfilter-persistent.service"',
    '"dev-zram0.swap"',
)
forbid("nix/modules/linux/k3s-host.nix", "homelab-k3s-legacy-cleanup =")
require(
    "nix/scripts/k3s-handoff",
    "/var/lib/homelab-secrets/active/k3s-token.cred",
)
forbid("nix/scripts/k3s-handoff", "/run/homelab-secrets")
require("nix/secrets/README", "/var/lib/homelab-secrets/generations/<generation>")
forbid("nix/secrets/README", "/run/homelab-secrets")
require("values/cilium/backbone.yaml", "prependIptablesChains: true")
require("README.md", "iptables-nft backend invariant", "backend 전환은 이 migration의 범위가 아니다")
require(
    "nix/packages.nix",
    "kubernetes-helmPlugins.helm-diff",
    "findutils",
    "gnutar",
    "opentofu",
    "bootstrap-host",
)
for relative in (
    "nix/scripts/wireguard-secrets",
    "nix/scripts/sync-bootstrap-secret",
):
    forbid(relative, 'strenv(PSK)', 'strenv(PRIVATE)', "--arg token", "secret=$(jq")
forbid("Makefile", "register-cluster", "/tmp/backbone-cluster-secrets.yaml", "/tmp/public_ip_map.yaml")
forbid("nix/packages.nix", "register-cluster")
for relative in (
    "argocd/appsets/cert-manager.yaml",
    "argocd/appsets/external-dns.yaml",
    "argocd/appsets/external-secrets.yaml",
):
    require(relative, "- name: backbone")
    forbid(relative, "clusters: {}")
if not re.search(r"bootstrap-backbone:\s*##", source("Makefile")):
    raise SystemExit("Makefile: bootstrap target must not depend on a plaintext /tmp secret")
forbid("Makefile", "/tmp/backbone-cluster-secrets.yaml")
print("migration-contracts: ok")
