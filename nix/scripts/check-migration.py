#!/usr/bin/env python3
from pathlib import Path
import os

root = Path(os.environ.get("HOMELAB_SOURCE_ROOT", Path(__file__).resolve().parents[2]))
required = {
    "nix/modules/linux/base.nix": ["users.mutableUsers = true", "services.userborn.enable = true", "99-kubernetes-network.conf", "99-memory.conf", "60-io-scheduler.rules", "usb-autosuspend.conf", "homelab-zram", "PasswordAuthentication no"],
    "nix/modules/linux/packages.nix": ["homelab.distroPackages", "dpkg-query", "pacman -Q", "allowDestructiveCommit", "apt-get purge", "pacman --noconfirm -Rns"],
    "nix/modules/linux/firewall.nix": ["DefaultDependencies = false", "network-pre.target", "iptables-restore --noflush --wait", "iptables -P INPUT DROP", "CILIUM_INPUT", "CILIUM_FORWARD", "-s ${topology.wg0.edgeNetwork} -d ${topology.wg0.edgeNetwork} -j DROP"],
    "nix/modules/linux/wireguard.nix": ["PresharedKey =", "PersistentKeepalive = 25", "wg syncconf", "expectedPeerKeys", "wg show", "/run/homelab-secrets/generations/"],
    "nix/modules/linux/k3s-host.nix": ["secrets-encryption: true", "disable-kube-proxy: true", "token-file:", "/run/rancher/k3s-managed/config.yaml", "legacy K3s unit before activation", "ExecStartPre", "modprobe br_netfilter", "modprobe overlay", "homelab-k3s-legacy-cleanup", "/usr/local/bin/k3s-agent-uninstall.sh"],
    "nix/modules/darwin/base.nix": ["wireguard-go", "wg-quick strip", "wg setconf", "launchd.daemons.homelab-wireguard", "generations/*"],
    "nix/scripts/wireguard-secrets": ["bootstrap-age-identity", "import-host", "copy-k3s-token", "/var/lib/rancher/k3s/server/token", ".k3s.serverTokenBase64", "base64 --decode", "plaintext_workdir", "k3s/server-token", "gen-psk", "rekey-secrets", "stage-secrets", "rotate-psk", "atomic_encrypt", "active.new", "stale inactive secret generation", ".aName and .bName"],
    "nix/scripts/k3s-handoff": ["preflight", "systemd-run", "--on-active=15m", "reset-failed homelab-k3s-handoff-rollback.service", "systemctl enable --now $legacy", "homelab-k3s-handoff-rollback", "restore"],
    "nix/scripts/homelab-host": ["adopt-host", "etcd-snapshot save", "prepare", "activate", "reboot-verify", "commit", "upgrade-k3s", "$host-commit", "systemctl cat homelab-k3s.service", "k3s-handoff", "k3s-cold-state.tar", "onboard-k3s-node"],
    "nix/scripts/register-cluster": ["plaintext_workdir", "--rawfile token", "argocd-manager", "gitops.bhyoo.com/profile", "BACKBONE_CONTEXT"],
    "nix/scripts/issue-kubeconfig": ["CertificateSigningRequest", "ED25519", "0600", "already exists"],
    "nix/scripts/sync-bootstrap-secret": ["plaintext_workdir", "terraform -chdir", "--input-type yaml", "SOPS_AGE_RECIPIENTS", "external-secrets-cluster-store-aws"],
    "nix/packages.nix": ["bootstrap-age-identity", "import-wireguard-host", "copy-k3s-token", "k3s-handoff", "onboard-k3s-node", "adopt-host", "reconcile-distro-packages", "gen-psk", "rekey-secrets", "rotate-psk", "sync-bootstrap-secret", "upgrade-k3s", "verify-cluster"],
    "flake.nix": ["mkLinuxHost false", "mkLinuxHost true", '"${name}-commit"', "HOMELAB_SOURCE_ROOT"],
}
for relative, needles in required.items():
    text = (root / relative).read_text()
    for needle in needles:
        if needle not in text:
            raise SystemExit(f"{relative}: missing contract {needle!r}")
for forbidden in ("apt-get upgrade", "apt upgrade", "pacman -Syu", "PrivateKey = ", "PresharedKey = "):
    for relative in ("nix/modules/linux/packages.nix", "nix/lib/topology.nix"):
        if forbidden in (root / relative).read_text():
            raise SystemExit(f"{relative}: forbidden contract {forbidden!r}")
if "/var/lib/rancher/k3s/agent/token" in (root / "nix/scripts/wireguard-secrets").read_text():
    raise SystemExit("wireguard-secrets: local agent token must not be treated as canonical")
for forbidden in ('strenv(PSK)', 'strenv(PRIVATE)', "--arg token", "secret=$(jq"):
    for relative in ("nix/scripts/wireguard-secrets", "nix/scripts/register-cluster", "nix/scripts/sync-bootstrap-secret"):
        if forbidden in (root / relative).read_text():
            raise SystemExit(f"{relative}: secret exposure contract {forbidden!r}")
host_script = (root / "nix/scripts/homelab-host").read_text()
system_manager_profile = "/nix/var/nix/profiles/system-manager-profiles/system-manager"
if host_script.count(system_manager_profile) != 4:
    raise SystemExit("homelab-host: system-manager profile contract changed")
if f"{system_manager_profile}/bin/activate" not in host_script:
    raise SystemExit("homelab-host: system-manager activation path changed")
for forbidden in (
    "--profile /nix/var/nix/profiles/system-manager ",
    "/nix/var/nix/profiles/system-manager/activate",
):
    if forbidden in host_script:
        raise SystemExit(f"homelab-host: obsolete system-manager profile {forbidden!r}")
print("migration-contracts: ok")
