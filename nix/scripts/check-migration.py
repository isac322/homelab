#!/usr/bin/env python3
from pathlib import Path
import os
import re
import subprocess

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


def check_shell_syntax() -> None:
    scripts = [
        "nix/scripts/adopt-host",
        "nix/scripts/decommission-host",
        "nix/scripts/homelab-host",
        "nix/scripts/k3s-handoff",
        "nix/scripts/issue-kubeconfig",
        "nix/scripts/provision-host",
        "nix/scripts/render-macbook-wireguard",
        "nix/scripts/rollout-peers",
        "nix/scripts/sync-bootstrap-secret",
        "nix/scripts/verify-cluster",
        "nix/scripts/wireguard-secrets",
    ]
    for relative in scripts:
        result = subprocess.run(
            ["bash", "-n", str(root / relative)],
            text=True,
            capture_output=True,
        )
        if result.returncode:
            raise SystemExit(
                f"{relative}: bash -n failed\n{result.stderr.strip()}"
            )

        text = source(relative)
        for marker, body in re.findall(
            r"<<'([A-Za-z_][A-Za-z0-9_]*)'\n(.*?)\n\1",
            text,
            re.DOTALL,
        ):
            if marker == "EOF":
                continue
            result = subprocess.run(
                ["sh", "-n"],
                input=body,
                text=True,
                capture_output=True,
            )
            if result.returncode:
                raise SystemExit(
                    f"{relative}: embedded {marker} sh -n failed\n"
                    f"{result.stderr.strip()}"
                )


require(
    "nix/modules/linux/base.nix",
    "10-homelab-lan.network",
    "DNSSEC=no",
    "DNSOverTLS=opportunistic",
    "MulticastDNS=yes",
    "LLMNR=no",
    "lib.mkIf k8sMember",
    "systemd/zram-generator.conf",
    "tmpfiles.d/60-homelab-runtime-tuning.conf",
    "tmpfiles.d/20-homelab-resolv.conf",
    'source = "${pkgs.tzdata}/share/zoneinfo/Asia/Seoul"',
    "AuthorizedKeysFile ${authorizedKeysFile}",
    "../../../ssh_pub_keys/laptop.pub",
    'lib.concatStringsSep "\\n" adminKeys + "\\n"',
    "authorizedKeysFile =",
    "if cfg.allowDestructiveCommit then",
    '".ssh/authorized_keys /etc/ssh/authorized_keys.d/%u"',
    '"/etc/ssh/authorized_keys.d/%u"',
    "ssh/authorized_keys.d/democratic-csi",
    "PermitRootLogin no",
    '"sudoers.d/homelab-admin"',
    'root.shell = "/bin/bash";',
    "DNS=1.1.1.1#cloudflare-dns.com",
)
forbid(
    "nix/modules/linux/base.nix",
    "homelab-host-settings =",
    "homelab-runtime-tuning =",
    "homelab-legacy-tuning-cleanup =",
    "mkswap /dev/zram0",
    "diffie-hellman-group-exchange-sha256",
    "PermitRootLogin ${",
    'name != "n2p1"',
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
    "--dport 445",
    "--dport 137:138",
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
    "nix/scripts/adopt-host",
    "/root/.ssh",
    "/home/*/.ssh",
    "/var/spool/cron",
    "/usr/local/bin/kubectl",
    "/usr/local/bin/crictl",
    "/usr/local/bin/ctr",
    "/usr/local/bin/k3s-v*",
    "etcd-snapshot save",
    "pre-Nix state",
    "iptables-backend=",
)
require(
    "nix/scripts/homelab-host",
    "bootstrap-host",
    r"user=\$(id -un)",
    r'trap \"rm -f -- \$tmp\"',
    "secretGeneration",
    "different Git revision",
    "--baseline",
    "restore-host",
    "rollback_armed_host",
    "apply_native_runtime",
    "systemd-tmpfiles --create",
    "iptables-restore --noflush --wait",
    "cleanup_legacy_files",
    "! systemctl cat",
    "reconcile_distro_packages",
    "--version 1.20.0",
    "etc-state.tar",
    "policy-rc.d",
    "FIREWALL_SERVICE",
    "locale -a",
    "verify_legacy_cleanup",
    '"(nf_tables)"',
    "reconcile)",
    "lifecycle",
)
forbid(
    "nix/scripts/homelab-host",
    "trap 'rm -f",
)
for relative in (
    "README.md",
    "nix/scripts/homelab-host",
    "nix/scripts/issue-kubeconfig",
    "nix/scripts/verify-cluster",
):
    forbid(relative, "private-backbone")
require(
    "nix/scripts/homelab-host",
    "BACKBONE_CONTEXT:-homelab-backbone",
    "BOOTSTRAP_CONTEXT:-homelab-backbone",
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
    (
        "commit must rearm persistent rollback before the destructive generation switch",
        r"  commit\).*?system_manager build.*?system_manager register.*?k3s-handoff.*?rearm"
        r".*?system_manager switch",
    ),
):
    if not re.search(pattern, host_migration, re.DOTALL):
        raise SystemExit(f"nix/scripts/homelab-host: {description}")
cleanup_block = host_migration.split("cleanup_legacy_files()", 1)[1].split(
    "verify_legacy_cleanup()", 1
)[0]
if "/usr/local/bin/k3s" in cleanup_block:
    raise SystemExit("nix/scripts/homelab-host: commit cleanup must retain the Rancher-managed K3s binary")
if 'test -x /usr/local/bin/k3s' not in host_migration:
    raise SystemExit("nix/scripts/homelab-host: K3s install layout retention is not verified")
require(
    "nix/scripts/wireguard-secrets",
    "unmanaged link has no repository-owned endpoint bundle",
    "/var/lib/rancher/k3s/server/token",
    "plaintext_workdir",
    "HOMELAB_OPERATOR_AGE_KEY_FILE",
    "SOPS_AGE_KEY_FILE",
    "${TMPDIR:-/tmp}",
    "systemd-creds encrypt --with-key=host",
    'systemd-creds decrypt --name=',
    "generation_committed",
    "/var/lib/homelab-secrets",
    "replace the online operator recipient before import",
    "replace the offline recovery recipient before import",
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
    "/usr/local/bin/k3s",
    'Restart = "always";',
)
forbid(
    "nix/modules/linux/k3s-host.nix",
    "k3sPackage",
    "../../k3s-package.nix",
)
forbid("nix/modules/linux/k3s-host.nix", "homelab-k3s-legacy-cleanup =")
require(
    "nix/scripts/k3s-handoff",
    "/var/lib/homelab-secrets/active/k3s-token.cred",
    "/var/lib/homelab-host-rollback/current",
    "homelab-host-rollback.timer",
    "ExecStart=/bin/sh /var/lib/homelab-host-rollback/current/rollback",
    "OnActiveSec=15min",
    "WantedBy=timers.target",
    "distro-packages.txt",
    "PACKAGE_BACKEND",
    "trap rollback_arm_failure EXIT HUP INT TERM",
    "/usr/bin/pacman --noconfirm --needed -S $packages",
    "/usr/bin/apt-get -o Dpkg::Options::=--force-confold install -y --no-install-recommends $packages",
)
forbid(
    "nix/scripts/k3s-handoff",
    "/run/homelab-secrets",
    "/run/homelab-k3s-handoff-rollback",
    "systemd-run --quiet",
)
handoff = source("nix/scripts/k3s-handoff")
if not re.search(
    r"systemctl is-active systemd-networkd\.service systemd-resolved\.service \"\$ssh_service\""
    r".*?systemctl disable homelab-host-rollback\.timer",
    handoff,
    re.DOTALL,
):
    raise SystemExit("nix/scripts/k3s-handoff: rollback timer must remain armed until restore verification")
restore_block = handoff.split("  restore)", 1)[1].split("  status)", 1)[0]
if "systemctl disable --now $rollback_unit.timer" in restore_block:
    raise SystemExit("nix/scripts/k3s-handoff: explicit restore must leave retry control to the rollback script")
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
for retained in (
    "argocd/appsets/k3s-upgrade.yaml",
    "argocd/appprojects/system-upgrade.yaml",
    "apps/objects/k3s-system-upgrade/k3s-upgrade-plan.yaml",
):
    if not (root / retained).exists():
        raise SystemExit(f"{retained}: Rancher K3s upgrade ownership must remain declared")
require(
    "apps/objects/k3s-system-upgrade/k3s-upgrade-plan.yaml",
    "name: server-plan",
    "name: agent-plan",
    "version: v1.36.3+k3s1",
    "image: rancher/k3s-upgrade",
)
if (root / "nix/k3s-package.nix").exists():
    raise SystemExit("nix/k3s-package.nix: Nix must not own the K3s binary version")
forbid(
    "nix/scripts/homelab-host",
    "upgrade-k3s",
    "assert_no_k3s_upgrade_manager",
    "K3s upgrade must not downgrade",
)
check_shell_syntax()
print("migration-contracts: ok")
