#!/usr/bin/env python3
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import textwrap
try:
    from jinja2 import Environment, StrictUndefined
except ModuleNotFoundError:
    Environment = None
    StrictUndefined = None

root = Path(os.environ.get("HOMELAB_SOURCE_ROOT", Path(__file__).resolve().parents[2]))


def source(relative: str) -> str:
    return (root / relative).read_text()

def folded_yaml_scalar(relative: str, key: str) -> str:
    lines = source(relative).splitlines()
    marker = re.compile(rf"^(\s*){re.escape(key)}:\s*>-\s*$")
    for index, line in enumerate(lines):
        match = marker.match(line)
        if match is None:
            continue
        marker_indent = len(match.group(1))
        body: list[str] = []
        for candidate in lines[index + 1 :]:
            if candidate.strip():
                indent = len(candidate) - len(candidate.lstrip())
                if indent <= marker_indent:
                    break
            body.append(candidate)
        value = textwrap.dedent("\n".join(body)).strip()
        if not value:
            break
        return value
    raise SystemExit(f"{relative}: folded scalar {key!r} is missing")


def inventory_host_value(host: str, key: str) -> str:
    relative = f"cluster-setup/inventory/host_vars/{host}.yaml"
    match = re.search(
        rf"^{re.escape(key)}:\s*([^\s#]+)\s*(?:#.*)?$",
        source(relative),
        re.MULTILINE,
    )
    if match is None:
        raise SystemExit(f"{relative}: inventory value {key!r} is missing")
    return match.group(1)


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


def inventory_groups(relative: str) -> dict[str, set[str]]:
    groups: dict[str, set[str]] = {}
    current: str | None = None
    for raw_line in source(relative).splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            groups.setdefault(current, set())
            continue
        if current is not None:
            groups[current].add(line.split()[0])
    return groups


def check_ansible_cutover_partition() -> None:
    groups = inventory_groups("cluster-setup/inventory/hosts")
    nix_managed = groups.get("nix_managed", set())
    ansible_managed = groups.get("ansible_managed", set())
    migrated_backbone = {"n2p1", "n2p2", "rpi4", "rpi5", "rock5bp", "macmini"}
    migrated_hosts = migrated_backbone
    for host in sorted(migrated_hosts):
        if host not in nix_managed:
            raise SystemExit(
                f"cluster-setup/inventory/hosts: migrated host {host} is not nix_managed"
            )
        if host in ansible_managed:
            raise SystemExit(
                f"cluster-setup/inventory/hosts: migrated host {host} remains ansible_managed"
            )
    if nix_managed & ansible_managed:
        overlap = ", ".join(sorted(nix_managed & ansible_managed))
        raise SystemExit(
            f"cluster-setup/inventory/hosts: ownership groups overlap: {overlap}"
        )

    if groups.get("homelab:children") != {"ansible_managed", "nix_managed"}:
        raise SystemExit(
            "cluster-setup/inventory/hosts: homelab must contain both ownership groups"
        )
    if not migrated_backbone.issubset(groups.get("backbone", set())):
        raise SystemExit(
            "cluster-setup/inventory/hosts: migrated backbone topology was removed"
        )

    expected_play_hosts = {
        "cluster-setup/init-backbone-os.yaml": ["ansible_managed"] * 4,
        "cluster-setup/etc-hosts.yaml": ["ansible_managed"],
        "cluster-setup/ssh-hardening.yaml": ["ansible_managed"] * 3,
        "cluster-setup/firewall.yaml": ["ansible_managed"],
        "cluster-setup/wireguard.yaml": ["ansible_managed"],
        "cluster-setup/k3s.yaml": [
            "ansible_managed:&backbone",
            "ansible_managed:&backbone",
            "backbone_k8s_masters_for_cilium",
        ],
        "cluster-setup/argocd.yaml": [
            "ansible_managed:&backbone",
            "backbone_k8s_masters",
            "backbone_k8s_masters",
        ],
    }
    for relative, expected in expected_play_hosts.items():
        actual = re.findall(
            r'^\s*(?:-\s+)?hosts:\s*["\']?([^"\'\s]+)["\']?\s*$',
            source(relative),
            re.MULTILINE,
        )
        if actual != expected:
            raise SystemExit(
                f"{relative}: play host ownership differs: expected {expected}, got {actual}"
            )

    ssh_hardening = source("cluster-setup/ssh-hardening.yaml")
    expected_authorized_key_paths = [
        "./ssh_pub_keys/desktop.pub",
        "../ssh_pub_keys/laptop.pub",
        "./ssh_pub_keys/laptop.pub",
        "./ssh_pub_keys/mobile.pub",
        "./ssh_pub_keys/tablet.pub",
        "./ssh_pub_keys/office.pub",
    ]
    laptop_key_identities: dict[str, tuple[str, str]] = {}
    for relative, expected_comment in {
        "ssh_pub_keys/laptop.pub": "bhyoo@bhyoo-macbook-pro",
        "cluster-setup/ssh_pub_keys/laptop.pub": "bhyoo@latitude7490-manjaro",
    }.items():
        try:
            algorithm, material, comment = source(relative).strip().split(maxsplit=2)
        except ValueError as error:
            raise SystemExit(f"{relative}: malformed SSH public key") from error
        if algorithm != "ssh-ed25519" or comment != expected_comment:
            raise SystemExit(
                f"{relative}: expected ssh-ed25519 identity {expected_comment}, "
                f"got {algorithm} {comment}"
            )
        laptop_key_identities[relative] = (algorithm, material)
    if len(set(laptop_key_identities.values())) != len(laptop_key_identities):
        raise SystemExit(
            "legacy and current laptop SSH public keys must remain distinct"
        )

    for principal in ("root", '"{{ admin_user }}"'):
        match = re.search(
            rf"^        - name: {re.escape(principal)}\n"
            r"          authorized_keys:\n"
            r"(?P<body>(?:            - key: .*\n)+)",
            ssh_hardening,
            re.MULTILINE,
        )
        if match is None:
            raise SystemExit(
                f"cluster-setup/ssh-hardening.yaml: {principal} authorized keys are missing"
            )
        actual = re.findall(
            r"lookup\('file', '([^']+)'\)",
            match.group("body"),
        )
        if actual != expected_authorized_key_paths:
            raise SystemExit(
                "cluster-setup/ssh-hardening.yaml: "
                f"{principal} authorized keys differ: "
                f"expected {expected_authorized_key_paths}, got {actual}"
            )

    require(
        "cluster-setup/etc-hosts.yaml",
        "any_errors_fatal: true",
        "gather_facts: true",
        "(ansible_play_hosts_all | sort) == (groups['ansible_managed'] | sort)",
        "groups['nix_managed']",
        "map(attribute='ansible_host')",
        "zip(groups['nix_managed'])",
        "do not use --limit",
    )
    require(
        "cluster-setup/roles/etc_hosts/templates/etc/hosts.j2",
        "{% for host in ansible_play_batch %}",
        "{% for item in hosts_dns_hostname %}",
    )

    require(
        "cluster-setup/wireguard.yaml",
        "any_errors_fatal: true",
        "gather_facts: false",
        "groups['nix_managed']",
        "nix run .#rollout-peers -- <host>",
    )
    makefile = source("cluster-setup/Makefile")
    if not re.search(
        r"^wireguard:\s+ansible-install\s+wireguard\.yaml\s*$",
        makefile,
        re.MULTILINE,
    ):
        raise SystemExit(
            "cluster-setup/Makefile: WireGuard must fail before changing remote hosts"
        )
    k3s_target = re.search(r"^k3s:\s*(.*)$", makefile, re.MULTILINE)
    if k3s_target is None or "wireguard" in k3s_target.group(1).split():
        raise SystemExit(
            "cluster-setup/Makefile: K3s must not invoke disabled legacy WireGuard"
        )


def check_static_nix_hosts_render() -> None:
    if Environment is None or StrictUndefined is None:
        if os.environ.get("HOMELAB_REQUIRE_JINJA_RENDER") == "1":
            raise SystemExit(
                "check-migration.py: Jinja2 is required for the hosts render contract"
            )
        return
    expected = {
        host: inventory_host_value(host, "ansible_host")
        for host in sorted(
            inventory_groups("cluster-setup/inventory/hosts").get(
                "nix_managed", set()
            )
        )
    }
    environment = Environment(undefined=StrictUndefined)
    environment.filters["regex_search"] = lambda value, pattern: re.search(
        pattern, value
    )
    environment.filters["ansible.utils.ipaddr"] = lambda _value, _query: False
    template = environment.from_string(
        source("cluster-setup/roles/etc_hosts/templates/etc/hosts.j2")
    )
    rendered = template.render(
        ansible_managed="managed by Ansible",
        inventory_hostname="fixture",
        inventory_hostname_short="fixture",
        hosts_ipv4_address="192.0.2.1",
        ansible_lo={},
        hosts_ipv6=False,
        ansible_play_batch=[],
        hostvars={},
        hosts_excludes_interfaces=[],
        hosts_all_private=True,
        hosts_all_public=False,
        hosts_dns_hostname=[
            {"address": address, "hostname": host}
            for host, address in expected.items()
        ],
    )
    for host, address in expected.items():
        expected_line = f"{address} {host}"
        if rendered.splitlines().count(expected_line) != 1:
            raise SystemExit(
                "cluster-setup/etc-hosts.yaml: static Nix-managed host render "
                f"differs for {expected_line!r}"
            )

def check_static_nix_hosts_expression() -> None:
    ansible_playbook = shutil.which("ansible-playbook")
    if ansible_playbook is None:
        if os.environ.get("HOMELAB_REQUIRE_ANSIBLE_RENDER") == "1":
            raise SystemExit(
                "check-migration.py: ansible-playbook is required for the "
                "hosts expression contract"
            )
        return

    expression = folded_yaml_scalar(
        "cluster-setup/etc-hosts.yaml", "hosts_dns_hostname"
    )
    expected = {
        host: inventory_host_value(host, "ansible_host")
        for host in sorted(
            inventory_groups("cluster-setup/inventory/hosts").get(
                "nix_managed", set()
            )
        )
    }
    assertions = "\n".join(
        f'          - \'{{"address": "{address}", '
        f'"hostname": "{host}"}} in evaluated_hosts\''
        for host, address in expected.items()
    )
    playbook = f"""---
- hosts: localhost
  connection: local
  gather_facts: false
  vars:
    k8s_registration_address: k8s-registration.test
    evaluated_hosts: >-
{textwrap.indent(expression, "      ")}
  tasks:
    - name: Verify static Nix-managed host entries
      ansible.builtin.assert:
        that:
{assertions}
"""
    with tempfile.TemporaryDirectory() as temp_directory:
        fixture = Path(temp_directory) / "check-static-hosts.yaml"
        fixture.write_text(playbook)
        environment = os.environ.copy()
        environment.update(
            {
                "HOME": temp_directory,
                "ANSIBLE_LOCAL_TEMP": f"{temp_directory}/local",
                "ANSIBLE_REMOTE_TEMP": f"{temp_directory}/remote",
            }
        )
        result = subprocess.run(
            [
                ansible_playbook,
                "-i",
                str(root / "cluster-setup/inventory/hosts"),
                str(fixture),
            ],
            text=True,
            capture_output=True,
            env=environment,
        )
    if result.returncode != 0:
        raise SystemExit(
            "cluster-setup/etc-hosts.yaml: static inventory expression failed\n"
            f"{result.stdout}{result.stderr}"
        )

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
        "nix/scripts/sync-wireguard-runtime",
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


def check_receipt_round_trip() -> None:
    migration = source("nix/scripts/homelab-host")
    match = re.search(
        r"(render_receipt\(\) \{\n.*?^}\nwrite_receipt\(\) \{\n.*?^})",
        migration,
        re.DOTALL | re.MULTILINE,
    )
    if match is None:
        raise SystemExit("nix/scripts/homelab-host: write_receipt function missing")
    with tempfile.TemporaryDirectory() as state:
        script = f"""
set -euo pipefail
{match.group(1)}
receipt() {{ printf '%s/receipt.json' "$STATE"; }}
current_revision() {{ printf test-revision; }}
write_receipt test-host prepared "" legacy recovery secret store "" nas-baseline storage-inventory
jq -e '.previousGeneration == "" and .bootId == "" and .nasBaseline == "nas-baseline" and .storageInventory == "storage-inventory"' "$STATE/receipt.json" >/dev/null
write_receipt test-host rebooting "" legacy recovery secret store boot-1 nas-baseline storage-inventory
jq -e '.phase == "rebooting" and .bootId == "boot-1" and .nasBaseline == "nas-baseline" and .storageInventory == "storage-inventory"' "$STATE/receipt.json" >/dev/null
"""
        result = subprocess.run(
            ["bash"],
            input=script,
            text=True,
            capture_output=True,
            env={**os.environ, "STATE": state},
        )
        if result.returncode:
            raise SystemExit(
                "nix/scripts/homelab-host: empty previous generation receipt failed\n"
                f"{result.stderr.strip()}"
            )


def check_completed_rollback_receipt_sync() -> None:
    migration = source("nix/scripts/homelab-host")
    write_match = re.search(
        r"(render_receipt\(\) \{\n.*?^}\nwrite_receipt\(\) \{\n.*?^})",
        migration,
        re.DOTALL | re.MULTILINE,
    )
    sync_match = re.search(
        r"(sync_completed_rollback\(\) \{\n.*?^\})",
        migration,
        re.DOTALL | re.MULTILINE,
    )
    if write_match is None or sync_match is None:
        raise SystemExit("nix/scripts/homelab-host: rollback receipt synchronization missing")
    with tempfile.TemporaryDirectory() as directory:
        directory_path = Path(directory)
        handoff = directory_path / "nix/scripts/k3s-handoff"
        handoff.parent.mkdir(parents=True)
        handoff.write_text(
            "#!/bin/sh\n"
            'test "$1" = cleanup-restored\n'
            'printf "cleanup-restored\\n" >> "$ACCEPT_LOG"\n'
            'test "${ACCEPT_FAIL:-0}" != 1\n'
        )
        handoff.chmod(0o755)
        receipt_state = directory_path / "state"
        accepted = directory_path / "accepted"
        script = f"""
set -euo pipefail
root=$ROOT
state=$TEST_STATE
mkdir -p "$state/receipts"
receipt() {{ printf '%s/receipts/%s.json' "$state" "$1"; }}
current_revision() {{ printf test-revision; }}
rollback_state() {{ printf '%s\\n' "$ROLLBACK_STATUS"; }}
verify_receipt_nas_baseline() {{ printf 'baseline-verified\\n' >> "$BASELINE_LOG"; }}
{write_match.group(1)}
{sync_match.group(1)}
seed() {{
  write_receipt test-host activated "" k3s.service recovery secret store "" nas-baseline storage-inventory
}}
seed
ROLLBACK_STATUS=restored
export ROLLBACK_STATUS
sync_completed_rollback test-host
test "$(jq -r .phase "$(receipt test-host)")" = rolled-back
test "$(jq -r .nasBaseline "$(receipt test-host)")" = nas-baseline
test "$(jq -r .storageInventory "$(receipt test-host)")" = storage-inventory
test "$(cat "$ACCEPT_LOG")" = cleanup-restored

rm -f "$ACCEPT_LOG"
seed
ACCEPT_FAIL=1
export ACCEPT_FAIL
if sync_completed_rollback test-host; then
  echo "completed rollback cleanup failure was ignored" >&2
  exit 1
fi
test "$(jq -r .phase "$(receipt test-host)")" = rolled-back
test "$(cat "$ACCEPT_LOG")" = cleanup-restored
unset ACCEPT_FAIL
sync_completed_rollback test-host
test "$(jq -r .phase "$(receipt test-host)")" = rolled-back
test "$(wc -l < "$ACCEPT_LOG" | tr -d ' ')" = 2
ROLLBACK_STATUS=absent
export ROLLBACK_STATUS
sync_completed_rollback test-host
rm -f "$ACCEPT_LOG"
seed
ROLLBACK_STATUS=restoring
export ROLLBACK_STATUS
if sync_completed_rollback test-host; then
  echo "incomplete rollback was recorded as complete" >&2
  exit 1
fi
test "$(jq -r .phase "$(receipt test-host)")" = activated
test ! -e "$ACCEPT_LOG"

ROLLBACK_STATUS=armed
export ROLLBACK_STATUS
sync_completed_rollback test-host
test "$(jq -r .phase "$(receipt test-host)")" = activated

ROLLBACK_STATUS=absent
export ROLLBACK_STATUS
if sync_completed_rollback test-host; then
  echo "missing remote recovery was accepted" >&2
  exit 1
fi
test "$(jq -r .phase "$(receipt test-host)")" = activated

rm -f "$ACCEPT_LOG"
write_receipt test-host prepared "" k3s.service recovery secret store "" nas-baseline storage-inventory
ROLLBACK_STATUS=absent
export ROLLBACK_STATUS
sync_completed_rollback test-host
test "$(jq -r .phase "$(receipt test-host)")" = prepared
test ! -e "$ACCEPT_LOG"

ROLLBACK_STATUS=restored
export ROLLBACK_STATUS
sync_completed_rollback test-host
test "$(jq -r .phase "$(receipt test-host)")" = rolled-back
test "$(cat "$ACCEPT_LOG")" = cleanup-restored
"""
        result = subprocess.run(
            ["bash"],
            input=script,
            text=True,
            capture_output=True,
            env={
                **os.environ,
                "ROOT": directory,
                "TEST_STATE": str(receipt_state),
                "ACCEPT_LOG": str(accepted),
                "BASELINE_LOG": str(directory_path / "baseline"),
            },
        )
        if result.returncode:
            raise SystemExit(
                "nix/scripts/homelab-host: completed rollback receipt synchronization is unsafe\n"
                f"{result.stderr.strip()}"
            )


def check_record_rolled_back_order() -> None:
    migration = source("nix/scripts/homelab-host")
    write_match = re.search(
        r"(render_receipt\(\) \{\n.*?^}\nwrite_receipt\(\) \{\n.*?^})",
        migration,
        re.DOTALL | re.MULTILINE,
    )
    record_match = re.search(
        r"(record_rolled_back\(\) \{\n.*?^\})",
        migration,
        re.DOTALL | re.MULTILINE,
    )
    if write_match is None or record_match is None:
        raise SystemExit("nix/scripts/homelab-host: rolled-back receipt helper missing")
    with tempfile.TemporaryDirectory() as directory:
        directory_path = Path(directory)
        handoff = directory_path / "nix/scripts/k3s-handoff"
        handoff.parent.mkdir(parents=True)
        receipt_file = directory_path / "receipt.json"
        accepted = directory_path / "accepted"
        handoff.write_text(
            "#!/bin/sh\n"
            'test "$1" = cleanup-restored\n'
            'test "$(jq -r .phase "$TEST_RECEIPT")" = rolled-back\n'
            'printf "cleanup-restored\\n" >> "$ACCEPT_LOG"\n'
            'test "${ACCEPT_FAIL:-0}" != 1\n'
        )
        handoff.chmod(0o755)
        script = f"""
set -euo pipefail
root=$ROOT
receipt() {{ printf '%s' "$TEST_RECEIPT"; }}
current_revision() {{ printf test-revision; }}
verify_receipt_nas_baseline() {{ :; }}
{write_match.group(1)}
{record_match.group(1)}
write_receipt test-host activated "" k3s.service recovery secret store "" nas-baseline storage-inventory
ACCEPT_FAIL=1
export ACCEPT_FAIL
if record_rolled_back test-host "" k3s.service recovery secret; then
  echo "completed rollback cleanup failure was ignored" >&2
  exit 1
fi
test "$(jq -r .phase "$TEST_RECEIPT")" = rolled-back
test "$(jq -r .nasBaseline "$TEST_RECEIPT")" = nas-baseline
test "$(jq -r .storageInventory "$TEST_RECEIPT")" = storage-inventory
test "$(cat "$ACCEPT_LOG")" = cleanup-restored
unset ACCEPT_FAIL
record_rolled_back test-host "" k3s.service recovery secret
test "$(wc -l < "$ACCEPT_LOG" | tr -d ' ')" = 2
"""
        result = subprocess.run(
            ["bash"],
            input=script,
            text=True,
            capture_output=True,
            env={
                **os.environ,
                "ROOT": directory,
                "TEST_RECEIPT": str(receipt_file),
                "ACCEPT_LOG": str(accepted),
            },
        )
        if result.returncode:
            raise SystemExit(
                "nix/scripts/homelab-host: rolled-back receipt cleanup ordering is unsafe\n"
                f"{result.stderr.strip()}"
            )

def check_guarded_reboot() -> None:
    migration = source("nix/scripts/homelab-host")
    match = re.search(
        r"(reboot_host\(\) \{\n.*?^\})",
        migration,
        re.DOTALL | re.MULTILINE,
    )
    if match is None:
        raise SystemExit("nix/scripts/homelab-host: guarded reboot helper missing")
    with tempfile.TemporaryDirectory() as directory:
        directory_path = Path(directory)
        handoff = directory_path / "nix/scripts/k3s-handoff"
        handoff.parent.mkdir(parents=True)
        handoff.write_text(
            "#!/bin/sh\n"
            'test "$1" = rearm\n'
            'printf "rearm\\n" >> "$EVENTS"\n'
            'test "${REARM_FAIL:-0}" != 1\n'
        )
        handoff.chmod(0o755)
        receipt_path = directory_path / "receipt.json"
        events = directory_path / "events"
        script = f"""
set -euo pipefail
root=$ROOT
receipt() {{ printf '%s\\n' "$RECEIPT"; }}
seed() {{
  sync_count=0
  jq -n --arg phase "$1" --arg bootId "${{2:-}}" \
    '{{phase:$phase,previousGeneration:"",legacyK3sUnit:"k3s.service",recoveryDirectory:"recovery",secretGeneration:"secret",storePath:"store",bootId:$bootId}}' \
    > "$RECEIPT"
}}
sync_count=0
sync_completed_rollback() {{
  sync_count=$((sync_count + 1))
  printf 'sync\\n' >> "$EVENTS"
  if [ "${{ROLLBACK_COMPLETE_ON_SYNC:-0}}" = "$sync_count" ]; then
    jq '.phase = "rolled-back"' "$RECEIPT" > "$RECEIPT.new"
    mv "$RECEIPT.new" "$RECEIPT"
  fi
}}
verify_receipt_nas_baseline() {{
  printf 'baseline:%s\\n' "${{2:-no}}" >> "$EVENTS"
  test "${{BASELINE_FAIL:-0}}" != 1
}}
guard_count=0
require_receipt_phase() {{
  sync_completed_rollback "$1"
  guard_count=$((guard_count + 1))
  printf 'guard\\n' >> "$EVENTS"
  test "$(jq -r .phase "$RECEIPT")" = "$2"
  test "$guard_count" != "${{FAIL_GUARD:-0}}"
}}
write_receipt() {{
  printf 'receipt:%s\\n' "$2" >> "$EVENTS"
  jq --arg phase "$2" --arg bootId "${{8:-}}" \
    '.phase = $phase | .bootId = $bootId' "$RECEIPT" > "$RECEIPT.new"
  mv "$RECEIPT.new" "$RECEIPT"
}}
remote() {{
  host=$1
  shift
  test "$host" = test-host
  case "$*" in
    "cat /proc/sys/kernel/random/boot_id")
      printf 'boot-id\\n' >> "$EVENTS"
      printf '%s\\n' "${{CURRENT_BOOT_ID-boot-1}}"
      ;;
    "sudo -n systemctl --no-block reboot")
      printf 'reboot\\n' >> "$EVENTS"
      return "${{REBOOT_RC:-0}}"
      ;;
    *) return 2 ;;
  esac
}}
{match.group(1)}

seed activated
guard_count=0
: > "$EVENTS"
reboot_host test-host
printf '%s\\n' sync baseline:no rearm sync guard boot-id receipt:rebooting reboot > "$EXPECTED"
cmp "$EXPECTED" "$EVENTS"
test "$(jq -r .phase "$RECEIPT")" = rebooting
test "$(jq -r .bootId "$RECEIPT")" = boot-1

seed activated
guard_count=0
: > "$EVENTS"
REARM_FAIL=1
export REARM_FAIL
if reboot_host test-host; then
  echo "reboot continued after rearm failure" >&2
  exit 1
fi
printf '%s\\n' sync baseline:no rearm sync > "$EXPECTED"
cmp "$EXPECTED" "$EVENTS"
test "$(jq -r .phase "$RECEIPT")" = activated
unset REARM_FAIL

seed activated
: > "$EVENTS"
REARM_FAIL=1
ROLLBACK_COMPLETE_ON_SYNC=2
export REARM_FAIL ROLLBACK_COMPLETE_ON_SYNC
if reboot_host test-host; then
  echo "reboot continued after rollback completed during rearm" >&2
  exit 1
fi
printf '%s\\n' sync baseline:no rearm sync > "$EXPECTED"
cmp "$EXPECTED" "$EVENTS"
test "$(jq -r .phase "$RECEIPT")" = rolled-back
unset REARM_FAIL ROLLBACK_COMPLETE_ON_SYNC

seed rebooting boot-1
: > "$EVENTS"
ROLLBACK_COMPLETE_ON_SYNC=1
export ROLLBACK_COMPLETE_ON_SYNC
if reboot_host test-host; then
  echo "reboot continued after rollback completed before rearm" >&2
  exit 1
fi
printf '%s\\n' sync baseline:no > "$EXPECTED"
cmp "$EXPECTED" "$EVENTS"
test "$(jq -r .phase "$RECEIPT")" = rolled-back
unset ROLLBACK_COMPLETE_ON_SYNC

seed activated
guard_count=0
: > "$EVENTS"
FAIL_GUARD=1
export FAIL_GUARD
if reboot_host test-host; then
  echo "reboot continued after the command-entry state guard failed" >&2
  exit 1
fi
printf '%s\\n' sync baseline:no rearm sync guard > "$EXPECTED"
cmp "$EXPECTED" "$EVENTS"
test "$(jq -r .phase "$RECEIPT")" = activated
unset FAIL_GUARD

seed activated
guard_count=0
: > "$EVENTS"
BASELINE_FAIL=1
export BASELINE_FAIL
if reboot_host test-host; then
  echo "reboot continued after the NAS baseline guard failed" >&2
  exit 1
fi
printf '%s\\n' sync baseline:no > "$EXPECTED"
cmp "$EXPECTED" "$EVENTS"
test "$(jq -r .phase "$RECEIPT")" = activated
unset BASELINE_FAIL


seed activated
guard_count=0
: > "$EVENTS"
REBOOT_RC=1
export REBOOT_RC
if reboot_host test-host; then
  echo "failed reboot request reported success" >&2
  exit 1
fi
test "$(jq -r .phase "$RECEIPT")" = rebooting
test "$(jq -r .bootId "$RECEIPT")" = boot-1
unset REBOOT_RC
guard_count=0
: > "$EVENTS"
reboot_host test-host
printf '%s\\n' sync baseline:no rearm sync guard boot-id reboot > "$EXPECTED"
cmp "$EXPECTED" "$EVENTS"

seed rebooting boot-1
guard_count=0
: > "$EVENTS"
CURRENT_BOOT_ID=boot-2
export CURRENT_BOOT_ID
if reboot_host test-host; then
  echo "already rebooted host was rebooted again" >&2
  exit 1
fi
printf '%s\\n' sync baseline:no rearm sync guard boot-id > "$EXPECTED"
cmp "$EXPECTED" "$EVENTS"
unset CURRENT_BOOT_ID

seed rebooting boot-1
guard_count=0
: > "$EVENTS"
CURRENT_BOOT_ID=
export CURRENT_BOOT_ID
if reboot_host test-host; then
  echo "empty boot ID was accepted for reboot retry" >&2
  exit 1
fi
printf '%s\\n' sync baseline:no rearm sync guard boot-id > "$EXPECTED"
cmp "$EXPECTED" "$EVENTS"
unset CURRENT_BOOT_ID

seed activated
guard_count=0
: > "$EVENTS"
REBOOT_RC=255
export REBOOT_RC
reboot_host test-host
printf '%s\\n' sync baseline:no rearm sync guard boot-id receipt:rebooting reboot > "$EXPECTED"
cmp "$EXPECTED" "$EVENTS"
unset REBOOT_RC
"""
        result = subprocess.run(
            ["bash"],
            input=script,
            text=True,
            capture_output=True,
            env={
                **os.environ,
                "ROOT": directory,
                "RECEIPT": str(receipt_path),
                "EVENTS": str(events),
                "EXPECTED": str(directory_path / "expected"),
            },
        )
        if result.returncode:
            raise SystemExit(
                "nix/scripts/homelab-host: guarded reboot ordering is unsafe\n"
                f"{result.stderr.strip()}"
            )


def check_reboot_verify_phase_gate() -> None:
    migration = source("nix/scripts/homelab-host")
    match = re.search(
        r"  reboot-verify\)\n(.*?)\n    ;;",
        migration,
        re.DOTALL,
    )
    if match is None:
        raise SystemExit("nix/scripts/homelab-host: reboot-verify entrypoint missing")
    block = match.group(1)
    timeout_call = (
        'timeout --foreground --kill-after=30s 12m "$0" '
        'verify-host-while-armed "$host"'
    )
    if timeout_call not in block:
        raise SystemExit(
            "nix/scripts/homelab-host: reboot-verify armed verification call missing"
        )
    block = block.replace(timeout_call, 'verify_armed "$host"', 1)
    with tempfile.TemporaryDirectory() as directory:
        directory_path = Path(directory)
        handoff = directory_path / "nix/scripts/k3s-handoff"
        receipt_file = directory_path / "receipt.json"
        events = directory_path / "events"
        handoff.parent.mkdir(parents=True)
        handoff.write_text(
            "#!/bin/sh\n"
            'printf "%s\\n" "$1" >> "$EVENTS"\n'
            'test "$1" != rearm || test "${REARM_FAIL:-0}" != 1\n'
        )
        handoff.chmod(0o755)
        script = f"""
set -euo pipefail
root=$ROOT
receipt() {{ printf '%s\\n' "$RECEIPT"; }}
sync_count=0
sync_completed_rollback() {{
  sync_count=$((sync_count + 1))
  printf 'sync\\n' >> "$EVENTS"
  if [ "${{ROLLBACK_COMPLETE_ON_SYNC:-0}}" = "$sync_count" ]; then
    jq '.phase = "rolled-back"' "$RECEIPT" > "$RECEIPT.new"
    mv "$RECEIPT.new" "$RECEIPT"
  fi
}}
require_receipt_phase() {{
  sync_completed_rollback "$1"
  printf 'guard\\n' >> "$EVENTS"
  test "$(jq -r .phase "$RECEIPT")" = "$2"
}}
assert_host_rebooted() {{ printf 'boot\\n' >> "$EVENTS"; }}
verify_nas_baseline() {{ :; }}
verify_storage_recovery() {{ printf 'storage\\n' >> "$EVENTS"; }}
verify_armed() {{ printf 'verify\\n' >> "$EVENTS"; }}
rollback_armed_host() {{ printf 'rollback\\n' >> "$EVENTS"; return 1; }}
record_rolled_back() {{ printf 'rolled-back\\n' >> "$EVENTS"; }}
write_receipt() {{ printf 'receipt:%s\\n' "$2" >> "$EVENTS"; }}
set -- reboot-verify test-host
{block}
"""
        environment = {
            **os.environ,
            "ROOT": directory,
            "RECEIPT": str(receipt_file),
            "EVENTS": str(events),
        }

        def run_case(
            phase: str, **overrides: str
        ) -> subprocess.CompletedProcess[str]:
            events.unlink(missing_ok=True)
            receipt_file.write_text(
                json.dumps(
                    {
                        "phase": phase,
                        "previousGeneration": "4",
                        "legacyK3sUnit": "k3s.service",
                        "recoveryDirectory": "recovery",
                        "secretGeneration": "secret",
                        "storePath": "store",
                    }
                )
            )
            return subprocess.run(
                ["bash"],
                input=script,
                text=True,
                capture_output=True,
                env={**environment, **overrides},
            )

        result = run_case("rebooting")
        if (
            result.returncode
            or events.read_text()
            != "sync\nrearm\nsync\nguard\nboot\nverify\nstorage\ndisarm\nreceipt:reboot-verified\n"
        ):
            raise SystemExit(
                "nix/scripts/homelab-host: reboot-verify armed ordering is unsafe\n"
                f"{result.stderr.strip()}"
            )

        result = run_case("rebooting", REARM_FAIL="1")
        if (
            result.returncode == 0
            or events.read_text() != "sync\nrearm\nsync\n"
            or json.loads(receipt_file.read_text())["phase"] != "rebooting"
        ):
            raise SystemExit(
                "nix/scripts/homelab-host: reboot-verify mutated an ordinary rearm failure"
            )

        result = run_case("reboot-verified")
        if (
            result.returncode == 0
            or not events.exists()
            or events.read_text() != "sync\n"
            or "expected rebooting" not in result.stderr
        ):
            raise SystemExit(
                "nix/scripts/homelab-host: reboot-verify rearmed an invalid local phase"
            )

        result = run_case("rebooting", ROLLBACK_COMPLETE_ON_SYNC="1")
        if (
            result.returncode == 0
            or events.read_text() != "sync\n"
            or json.loads(receipt_file.read_text())["phase"] != "rolled-back"
            or "expected rebooting" not in result.stderr
        ):
            raise SystemExit(
                "nix/scripts/homelab-host: reboot-verify ignored a completed rollback"
            )

        result = run_case(
            "rebooting",
            REARM_FAIL="1",
            ROLLBACK_COMPLETE_ON_SYNC="2",
        )
        if (
            result.returncode == 0
            or events.read_text() != "sync\nrearm\nsync\n"
            or json.loads(receipt_file.read_text())["phase"] != "rolled-back"
        ):
            raise SystemExit(
                "nix/scripts/homelab-host: reboot-verify left a rearm race unsynchronized"
            )


def check_reboot_boot_id_proof() -> None:
    migration = source("nix/scripts/homelab-host")
    match = re.search(
        r"(assert_host_rebooted\(\) \{\n.*?^\})",
        migration,
        re.DOTALL | re.MULTILINE,
    )
    if match is None:
        raise SystemExit("nix/scripts/homelab-host: reboot boot ID proof missing")
    with tempfile.TemporaryDirectory() as directory:
        directory_path = Path(directory)
        receipt_file = directory_path / "receipt.json"
        script = f"""
set -euo pipefail
receipt() {{ printf '%s\\n' "$RECEIPT"; }}
remote() {{
  test "$1" = test-host
  test "$2" = "cat /proc/sys/kernel/random/boot_id"
  printf '%s\\n' "$ACTIVE_BOOT_ID"
}}
{match.group(1)}
jq -n --arg bootId boot-1 '{{bootId:$bootId}}' > "$RECEIPT"
ACTIVE_BOOT_ID=boot-2
export ACTIVE_BOOT_ID
assert_host_rebooted test-host
ACTIVE_BOOT_ID=boot-1
export ACTIVE_BOOT_ID
if assert_host_rebooted test-host; then
  echo "unchanged boot ID was accepted" >&2
  exit 1
fi
jq -n '{{}}' > "$RECEIPT"
if assert_host_rebooted test-host; then
  echo "missing pre-reboot boot ID was accepted" >&2
  exit 1
fi
"""
        result = subprocess.run(
            ["bash"],
            input=script,
            text=True,
            capture_output=True,
            env={**os.environ, "RECEIPT": str(receipt_file)},
        )
        if result.returncode:
            raise SystemExit(
                "nix/scripts/homelab-host: reboot boot ID proof is unsafe\n"
                f"{result.stderr.strip()}"
            )


def check_restore_host_guard() -> None:
    migration = source("nix/scripts/homelab-host")
    match = re.search(
        r"(restore_host\(\) \{\n.*?^\})",
        migration,
        re.DOTALL | re.MULTILINE,
    )
    if match is None:
        raise SystemExit("nix/scripts/homelab-host: restore_host function missing")
    with tempfile.TemporaryDirectory() as directory:
        directory_path = Path(directory)
        receipt_file = directory_path / "receipt.json"
        restore_log = directory_path / "restore"
        phase_log = directory_path / "phase"
        script = (
            "set -eu\n"
            "receipt() { printf '%s\\n' \"$TEST_RECEIPT\"; }\n"
            "rollback_state() { printf '%s\\n' \"$ROLLBACK_STATE\"; }\n"
            "rollback_armed_host() { printf 'restore\\n' > \"$RESTORE_LOG\"; }\n"
            "record_rolled_back() { printf '%s\\n' rolled-back > \"$PHASE_LOG\"; }\n"
            f"{match.group(1)}\n"
            "restore_host test-host\n"
        )
        environment = {
            **os.environ,
            "TEST_RECEIPT": str(receipt_file),
            "RESTORE_LOG": str(restore_log),
            "PHASE_LOG": str(phase_log),
        }

        def run_case(phase: str, rollback_status: str) -> subprocess.CompletedProcess[str]:
            restore_log.unlink(missing_ok=True)
            phase_log.unlink(missing_ok=True)
            receipt_file.write_text(
                json.dumps(
                    {
                        "phase": phase,
                        "previousGeneration": "4",
                        "legacyK3sUnit": "k3s.service",
                        "recoveryDirectory": "/recovery",
                        "secretGeneration": "generation",
                    }
                )
            )
            return subprocess.run(
                ["sh"],
                input=script,
                text=True,
                capture_output=True,
                env={**environment, "ROLLBACK_STATE": rollback_status},
            )

        result = run_case("prepared", "armed")
        if (
            result.returncode
            or not restore_log.exists()
            or phase_log.read_text().strip() != "rolled-back"
        ):
            raise SystemExit(
                "nix/scripts/homelab-host: prepared recovery cannot be restored safely\n"
                f"{result.stderr.strip()}"
            )

        for phase, rollback_status, expected_error in (
            ("rolled-back", "armed", "no migration recovery"),
            ("prepared", "absent", "no remote recovery state"),
            ("prepared", "unknown", "invalid rollback state"),
        ):
            result = run_case(phase, rollback_status)
            if (
                result.returncode == 0
                or expected_error not in result.stderr
                or restore_log.exists()
                or phase_log.exists()
            ):
                raise SystemExit(
                    "nix/scripts/homelab-host: restore-host phase/state guard is unsafe"
                )

def check_rollback_state_classification() -> None:
    handoff = source("nix/scripts/k3s-handoff")
    match = re.search(
        r'  state\).*?remote "\$host" "sudo -n sh -ceu \'\n(.*?)\n    \'"',
        handoff,
        re.DOTALL,
    )
    if match is None:
        raise SystemExit("nix/scripts/k3s-handoff: rollback state block missing")
    block = match.group(1).replace(r"\$", "$").replace(r"\"", '"')
    with tempfile.TemporaryDirectory() as directory:
        directory_path = Path(directory)
        rollback_root = directory_path / "rollback"
        current = rollback_root / "current"
        mock_bin = directory_path / "bin"
        mock_bin.mkdir()
        systemctl = mock_bin / "systemctl"
        systemctl.write_text(
            "#!/bin/sh\n"
            'test "$1" = is-active\n'
            'printf "%s\\n" "${SERVICE_STATE:-inactive}"\n'
        )
        systemctl.chmod(0o755)
        environment = {
            **os.environ,
            "PATH": f"{mock_bin}:{os.environ['PATH']}",
            "TEST_ROLLBACK_ROOT": str(rollback_root),
        }

        def classify(
            *,
            exists: bool,
            stages: bool = False,
            restored: bool = False,
            service_state: str = "inactive",
        ) -> str:
            shutil.rmtree(rollback_root, ignore_errors=True)
            if exists:
                current.mkdir(parents=True)
                if stages:
                    (current / "stages").mkdir()
                if restored:
                    (current / "restored").touch()
            result = subprocess.run(
                ["sh"],
                input=(
                    'set -eu\nrollback_root="$TEST_ROLLBACK_ROOT"\n'
                    "rollback_unit=homelab-host-rollback\n"
                    f"{block}\n"
                ),
                text=True,
                capture_output=True,
                env={**environment, "SERVICE_STATE": service_state},
            )
            if result.returncode:
                raise SystemExit(
                    "nix/scripts/k3s-handoff: rollback state fixture failed\n"
                    f"{result.stderr.strip()}"
                )
            return result.stdout.strip()

        cases = (
            ("absent", classify(exists=False)),
            ("armed", classify(exists=True)),
            ("restoring", classify(exists=True, stages=True)),
            ("restoring", classify(exists=True, service_state="active")),
            ("armed", classify(exists=True, service_state="failed")),
            (
                "restored",
                classify(exists=True, restored=True, service_state="active"),
            ),
        )
        for expected, actual in cases:
            if actual != expected:
                raise SystemExit(
                    "nix/scripts/k3s-handoff: rollback state misclassified "
                    f"{expected} fixture as {actual or 'empty'}"
                )


def check_rearm_guards() -> None:
    handoff = source("nix/scripts/k3s-handoff")
    match = re.search(
        r'  rearm\).*?remote "\$host" "sudo -n sh -ceu \'\n(.*?)\n    \'"',
        handoff,
        re.DOTALL,
    )
    if match is None:
        raise SystemExit("nix/scripts/k3s-handoff: rearm guard block missing")
    block = match.group(1).replace(r"\$", "$").replace(r"\"", '"')
    with tempfile.TemporaryDirectory() as directory:
        directory_path = Path(directory)
        rollback_root = directory_path / "rollback"
        current = rollback_root / "current"
        mock_bin = directory_path / "bin"
        events = directory_path / "events"
        restarted = directory_path / "restarted"
        current.mkdir(parents=True)
        mock_bin.mkdir()
        systemctl = mock_bin / "systemctl"
        systemctl.write_text(
            "#!/bin/sh\n"
            'case "$1" in\n'
            "  is-active)\n"
            '    if test "$2" = homelab-host-rollback.service; then\n'
            '      if test "${POST_RESTART_RACE:-0}" = 1 && test -e "$RESTARTED"; then\n'
            "        printf 'activating\\n'\n"
            "      else\n"
            "        printf '%s\\n' \"${SERVICE_STATE:-inactive}\"\n"
            "      fi\n"
            "    else\n"
            "      printf 'active\\n'\n"
            "    fi\n"
            "    ;;\n"
            "  reset-failed) ;;\n"
            "  enable) printf 'enable\\n' >> \"$EVENTS\" ;;\n"
            "  restart)\n"
            "    printf 'restart\\n' >> \"$EVENTS\"\n"
            '    : > "$RESTARTED"\n'
            "    ;;\n"
            "  *) exit 2 ;;\n"
            "esac\n"
        )
        systemctl.chmod(0o755)
        for name in (
            "etc-state.tar",
            "firewall-runtime.rules",
            "distro-packages.txt",
            "distro-packages-remove.txt",
        ):
            (current / name).write_text("fixture\n")
        environment = {
            **os.environ,
            "PATH": f"{mock_bin}:{os.environ['PATH']}",
            "TEST_ROLLBACK_ROOT": str(rollback_root),
            "EVENTS": str(events),
            "RESTARTED": str(restarted),
        }

        def run_case(**extra: str) -> subprocess.CompletedProcess[str]:
            events.unlink(missing_ok=True)
            restarted.unlink(missing_ok=True)
            return subprocess.run(
                ["sh"],
                input=(
                    'set -eu\nrollback_root="$TEST_ROLLBACK_ROOT"\n'
                    "rollback_unit=homelab-host-rollback\n"
                    f"{block}\n"
                ),
                text=True,
                capture_output=True,
                env={**environment, **extra},
            )

        (current / "restored").touch()
        result = run_case()
        if (
            result.returncode == 0
            or "rollback already completed" not in result.stderr
            or restarted.exists()
        ):
            raise SystemExit(
                "nix/scripts/k3s-handoff: completed rollback rearm guard is unsafe"
            )
        (current / "restored").unlink()

        (current / "stages").mkdir()
        result = run_case()
        if (
            result.returncode == 0
            or "rollback already started" not in result.stderr
            or restarted.exists()
        ):
            raise SystemExit(
                "nix/scripts/k3s-handoff: in-progress rollback rearm guard is unsafe"
            )
        (current / "stages").rmdir()

        result = run_case(SERVICE_STATE="active")
        if (
            result.returncode == 0
            or "rollback service is active" not in result.stderr
            or restarted.exists()
        ):
            raise SystemExit(
                "nix/scripts/k3s-handoff: active rollback service rearm guard is unsafe"
            )

        result = run_case(SERVICE_STATE="failed")
        if result.returncode or not restarted.exists():
            raise SystemExit(
                "nix/scripts/k3s-handoff: refused pre-mutation rollback cannot be rearmed\n"
                f"{result.stderr.strip()}"
            )
        result = run_case(POST_RESTART_RACE="1")
        if (
            result.returncode == 0
            or "rollback service is activating" not in result.stderr
            or not restarted.exists()
        ):
            raise SystemExit(
                "nix/scripts/k3s-handoff: post-restart rollback race was not rejected"
            )

        result = run_case()
        if result.returncode or not restarted.exists():
            raise SystemExit(
                "nix/scripts/k3s-handoff: safe rollback timer rearm failed\n"
                f"{result.stderr.strip()}"
            )

def check_accept_rearms_before_cleanup() -> None:
    handoff = root / "nix/scripts/k3s-handoff"
    with tempfile.TemporaryDirectory() as directory:
        directory_path = Path(directory)
        mock_bin = directory_path / "bin"
        events = directory_path / "events"
        expected = directory_path / "expected"
        mock_bin.mkdir()
        (mock_bin / "nix").write_text(
            "#!/bin/sh\n"
            'case "$*" in\n'
            "  *sshTarget*) printf 'test-target\\n' ;;\n"
            "  *) exit 97 ;;\n"
            "esac\n"
        )
        (mock_bin / "nix").chmod(0o755)
        (mock_bin / "ssh").write_text(
            "#!/bin/sh\n"
            "for argument in \"$@\"; do command=$argument; done\n"
            "case \"$command\" in\n"
            "  *assert_rearmable*)\n"
            "    printf 'rearm\\n' >> \"$EVENTS\"\n"
            "    test \"${REARM_FAIL:-0}\" != 1\n"
            "    ;;\n"
            "  *'test -d /var/lib/homelab-host-rollback/current'*)\n"
            "    printf 'accept\\n' >> \"$EVENTS\"\n"
            "    ;;\n"
            "  *'test -f /var/lib/homelab-host-rollback/current/restored'*)\n"
            "    printf 'cleanup-restored\\n' >> \"$EVENTS\"\n"
            "    ;;\n"
            "  *)\n"
            "    printf 'unexpected remote command: %s\\n' \"$command\" >&2\n"
            "    exit 2\n"
            "    ;;\n"
            "esac\n"
        )
        (mock_bin / "ssh").chmod(0o755)
        environment = {
            **os.environ,
            "PATH": f"{mock_bin}:{os.environ['PATH']}",
            "HOMELAB_REPO_ROOT": str(root),
            "EVENTS": str(events),
        }

        result = subprocess.run(
            ["bash", str(handoff), "accept", "test-host"],
            text=True,
            capture_output=True,
            env=environment,
        )
        expected.write_text("rearm\naccept\n")
        if result.returncode or events.read_text() != expected.read_text():
            raise SystemExit(
                "nix/scripts/k3s-handoff: accept did not rearm before cleanup\n"
                f"{result.stderr.strip()}"
            )

        events.unlink()
        result = subprocess.run(
            ["bash", str(handoff), "accept", "test-host"],
            text=True,
            capture_output=True,
            env={**environment, "REARM_FAIL": "1"},
        )
        if result.returncode == 0 or events.read_text() != "rearm\n":
            raise SystemExit(
                "nix/scripts/k3s-handoff: accept continued after command-entry rearm failed"
            )

        events.unlink()
        result = subprocess.run(
            ["bash", str(handoff), "cleanup-restored", "test-host"],
            text=True,
            capture_output=True,
            env=environment,
        )
        if result.returncode or events.read_text() != "cleanup-restored\n":
            raise SystemExit(
                "nix/scripts/k3s-handoff: restored rollback cleanup incorrectly rearmed"
            )


def check_armed_verify_entrypoint() -> None:
    migration = source("nix/scripts/homelab-host")
    usage_block = migration.split("Usage: homelab-host", 1)[1].split("\nEOF", 1)[0]
    if "verify-host-while-armed" in usage_block:
        raise SystemExit(
            "nix/scripts/homelab-host: armed verification must remain internal"
        )
    match = re.search(
        r"  verify-host-while-armed\)\n(.*?)\n    ;;",
        migration,
        re.DOTALL,
    )
    if match is None:
        raise SystemExit(
            "nix/scripts/homelab-host: verify-host-while-armed entrypoint missing"
        )
    block = match.group(1).replace(
        'exec "$0" verify-host "$@"',
        'exec "$VERIFY_TARGET" verify-host "$@"',
    )
    with tempfile.TemporaryDirectory() as directory:
        directory_path = Path(directory)
        handoff = directory_path / "nix/scripts/k3s-handoff"
        verify_target = directory_path / "verify"
        events = directory_path / "events"
        handoff.parent.mkdir(parents=True)
        handoff.write_text(
            "#!/bin/sh\n"
            'test "$1" = rearm\n'
            'printf "rearm:%s\\n" "$2" >> "$EVENTS"\n'
            'test "${REARM_FAIL:-0}" != 1\n'
        )
        handoff.chmod(0o755)
        verify_target.write_text(
            "#!/bin/sh\n"
            'printf "verify:%s\\n" "$*" >> "$EVENTS"\n'
        )
        verify_target.chmod(0o755)
        script = f"""
set -euo pipefail
root=$ROOT
verify_receipt_nas_baseline() {{ printf 'baseline:%s\\n' "$1" >> "$EVENTS"; }}
set -- verify-host-while-armed test-host --baseline baseline
{block}
"""
        environment = {
            **os.environ,
            "ROOT": directory,
            "VERIFY_TARGET": str(verify_target),
            "EVENTS": str(events),
        }
        result = subprocess.run(
            ["bash"],
            input=script,
            text=True,
            capture_output=True,
            env=environment,
        )
        if (
            result.returncode
            or events.read_text()
            != "baseline:test-host\nrearm:test-host\nverify:verify-host test-host --baseline baseline\n"
        ):
            raise SystemExit(
                "nix/scripts/homelab-host: armed verification did not validate the NAS baseline, rearm, and run checks\n"
                f"{result.stderr.strip()}"
            )

        events.unlink()
        result = subprocess.run(
            ["bash"],
            input=script,
            text=True,
            capture_output=True,
            env={**environment, "REARM_FAIL": "1"},
        )
        if result.returncode == 0 or events.read_text() != "baseline:test-host\nrearm:test-host\n":
            raise SystemExit(
                "nix/scripts/homelab-host: armed verification continued after rearm failed"
            )


def check_rollback_restore_failure() -> None:
    migration = source("nix/scripts/homelab-host")
    match = re.search(
        r"(rollback_armed_host\(\) \{\n.*?^\})",
        migration,
        re.DOTALL | re.MULTILINE,
    )
    if match is None:
        raise SystemExit("nix/scripts/homelab-host: rollback_armed_host function missing")
    with tempfile.TemporaryDirectory() as directory:
        directory_path = Path(directory)
        handoff = directory_path / "nix/scripts/k3s-handoff"
        handoff.parent.mkdir(parents=True)
        handoff.write_text(
            "#!/bin/sh\n"
            'test "$1" = restore\n'
            'count=$(cat "$ROLLBACK_COUNT" 2>/dev/null || printf 0)\n'
            "count=$((count + 1))\n"
            'printf "%s\\n" "$count" > "$ROLLBACK_COUNT"\n'
            'test "${RESTORE_SUCCEED_AFTER:-0}" -gt 0 '
            '&& test "$count" -ge "$RESTORE_SUCCEED_AFTER"\n'
        )
        handoff.chmod(0o755)
        count = directory_path / "restore-count"
        script = f"""
set -euo pipefail
{match.group(1)}
root=$ROOT
verify_receipt_nas_baseline() {{
  case "${{2:-before}}:${{BASELINE_FAIL_BEFORE:-0}}:${{BASELINE_FAIL_AFTER:-0}}" in
    before:1:*) return 1 ;;
    yes:*:1) return 1 ;;
  esac
}}
BASELINE_FAIL_BEFORE=1
export BASELINE_FAIL_BEFORE
if rollback_armed_host test-host; then
  echo "rollback ignored pre-restore NAS drift" >&2
  exit 1
fi
test ! -e "$ROLLBACK_COUNT"
unset BASELINE_FAIL_BEFORE

RESTORE_SUCCEED_AFTER=1
BASELINE_FAIL_AFTER=1
export RESTORE_SUCCEED_AFTER BASELINE_FAIL_AFTER
if rollback_armed_host test-host; then
  echo "rollback ignored post-restore NAS drift" >&2
  exit 1
fi
test "$(cat "$ROLLBACK_COUNT")" = 1
rm -f "$ROLLBACK_COUNT"
unset RESTORE_SUCCEED_AFTER BASELINE_FAIL_AFTER

if rollback_armed_host test-host; then
  echo "rollback accepted two failed restore attempts" >&2
  exit 1
fi
test "$(cat "$ROLLBACK_COUNT")" = 2
rm -f "$ROLLBACK_COUNT"
RESTORE_SUCCEED_AFTER=2
export RESTORE_SUCCEED_AFTER
rollback_armed_host test-host
test "$(cat "$ROLLBACK_COUNT")" = 2
rm -f "$ROLLBACK_COUNT"
RESTORE_SUCCEED_AFTER=1
export RESTORE_SUCCEED_AFTER
rollback_armed_host test-host
test "$(cat "$ROLLBACK_COUNT")" = 1
"""
        result = subprocess.run(
            ["bash"],
            input=script,
            text=True,
            capture_output=True,
            env={
                **os.environ,
                "ROOT": directory,
                "ROLLBACK_COUNT": str(count),
            },
        )
        if result.returncode:
            raise SystemExit(
                "nix/scripts/homelab-host: rollback restore failure handling is unsafe\n"
                f"{result.stderr.strip()}"
            )


def check_rollback_stage_resume() -> None:
    handoff = source("nix/scripts/k3s-handoff")
    delimiter = 'cat > "$dir/rollback" <<\'ROLLBACK\'\n'
    if delimiter not in handoff or "\nROLLBACK\n" not in handoff:
        raise SystemExit("nix/scripts/k3s-handoff: generated rollback script missing")
    rollback = handoff.split(delimiter, 1)[1].split("\nROLLBACK\n", 1)[0]
    rollback = rollback.split("systemctl daemon-reload", 1)[0]
    replacements = {
        'export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"': 'export PATH="$TEST_BIN:$PATH"',
        "dir=/var/lib/homelab-host-rollback/current": 'dir="$TEST_CURRENT"',
        "base=/var/lib/homelab-secrets": 'base="$TEST_SECRETS"',
        "profile=/nix/var/nix/profiles/system-manager-profiles/system-manager": 'profile="$TEST_PROFILE"',
        'tar -C / -xf "$dir/etc-state.tar"': 'tar -C "$TEST_ROOT" -xf "$dir/etc-state.tar"',
    }
    for original, replacement in replacements.items():
        if original not in rollback:
            raise SystemExit(
                f"nix/scripts/k3s-handoff: rollback resume fixture missing {original!r}"
            )
        rollback = rollback.replace(original, replacement, 1)
    rollback += '\nprintf "injected post-archive failure\\n" >&2\nexit 73\n'

    with tempfile.TemporaryDirectory() as directory:
        tar_binary = shutil.which("tar")
        if tar_binary is None:
            raise SystemExit("nix/scripts/check-migration.py: tar executable missing")
        directory_path = Path(directory)
        current = directory_path / "current"
        secrets = directory_path / "secrets"
        profile = directory_path / "profile"
        test_root = directory_path / "root"
        mock_bin = directory_path / "bin"
        for path in (current, secrets, profile / "bin", test_root, mock_bin):
            path.mkdir(parents=True, exist_ok=True)
        (current / "config").write_text(
            "\n\niptables.service\nsshd.service\neth0\n\nagent\napt\nfalse\ntrue\nfalse\nfalse\n"
        )
        payload = directory_path / "payload"
        payload.write_text("restored\n")
        with tarfile.open(current / "etc-state.tar", "w") as archive:
            archive.add(payload, arcname="etc/pr287-rollback-stage")

        deactivate_count = directory_path / "deactivate-count"
        tar_count = directory_path / "tar-count"
        (profile / "bin/deactivate").write_text(
            "#!/bin/sh\n"
            'count=$(cat "$DEACTIVATE_COUNT" 2>/dev/null || printf 0)\n'
            'printf "%s\\n" "$((count + 1))" > "$DEACTIVATE_COUNT"\n'
        )
        (profile / "bin/deactivate").chmod(0o755)
        (mock_bin / "systemctl").write_text(
            "#!/bin/sh\n"
            'test "${1:-}" != is-active\n'
        )
        (mock_bin / "tar").write_text(
            "#!/bin/sh\n"
            'count=$(cat "$TAR_COUNT" 2>/dev/null || printf 0)\n'
            'printf "%s\\n" "$((count + 1))" > "$TAR_COUNT"\n'
            f'exec "{tar_binary}" "$@"\n'
        )
        for command in ("systemctl", "tar"):
            (mock_bin / command).chmod(0o755)

        rollback_path = directory_path / "rollback"
        rollback_path.write_text(rollback)
        rollback_path.chmod(0o755)
        environment = {
            **os.environ,
            "PATH": f"{mock_bin}:{os.environ['PATH']}",
            "TEST_BIN": str(mock_bin),
            "TEST_CURRENT": str(current),
            "TEST_SECRETS": str(secrets),
            "TEST_PROFILE": str(profile),
            "TEST_ROOT": str(test_root),
            "DEACTIVATE_COUNT": str(deactivate_count),
            "TAR_COUNT": str(tar_count),
        }
        for _ in range(2):
            result = subprocess.run(
                ["/bin/sh", str(rollback_path)],
                text=True,
                capture_output=True,
                env=environment,
            )
            if result.returncode != 73:
                raise SystemExit(
                    "nix/scripts/k3s-handoff: rollback resume fixture did not reach the injected failure\n"
                    f"{result.stderr.strip()}"
                )
        if deactivate_count.read_text().strip() != "1":
            raise SystemExit(
                "nix/scripts/k3s-handoff: rollback retried completed system-manager restoration"
            )
        if tar_count.read_text().strip() != "1":
            raise SystemExit(
                "nix/scripts/k3s-handoff: rollback retried completed archive restoration"
            )
        for marker in (
            "secrets-restored",
            "system-manager-restored",
            "archive-restored",
        ):
            if not (current / "stages" / marker).is_file():
                raise SystemExit(
                    f"nix/scripts/k3s-handoff: rollback stage marker {marker!r} missing"
                )
        if (test_root / "etc/pr287-rollback-stage").read_text() != "restored\n":
            raise SystemExit(
                "nix/scripts/k3s-handoff: rollback archive fixture was not restored"
            )

def check_nas_manifest_runtime_index_normalization() -> None:
    manifests = {
        "baseline": """\
target-saveconfig-sha256=stable
target-saveconfig-json-begin
{"storage_objects":["pvc-a"]}
target-saveconfig-json-end
path=/sys/kernel/config/target/core/iblock_0|type=directory|mode=755|uid=0|gid=0|sha256=-
path=/sys/kernel/config/target/core/iblock_0/hba_info|type=regular file|mode=444|uid=0|gid=0|size=4096|sha256=old-hba
path=/sys/kernel/config/target/core/iblock_0/pvc-a|type=directory|mode=755|uid=0|gid=0|sha256=-
path=/sys/kernel/config/target/core/iblock_0/pvc-a/info|type=regular file|mode=444|uid=0|gid=0|size=4096|sha256=old-info
path=/sys/kernel/config/target/core/iblock_0/pvc-a/attrib/block_size|type=regular file|mode=644|uid=0|gid=0|size=4096|sha256=stable-attribute
path=/sys/kernel/config/target/core/alua/lu_gps/default_lu_gp/members|type=regular file|mode=444|uid=0|gid=0|size=4096|sha256=old-members
path=/sys/kernel/config/target/iscsi/iqn.example:pvc-a/tpgt_1/lun/lun_0/link|type=symbolic link|mode=777|uid=0|gid=0|sha256=old-link
path=/etc/samba/smb.conf|type=regular file|mode=644|uid=0|gid=0|size=20|sha256=stable-samba
listener=t|3260|present|endpoints=192.0.2.1:3260
""",
        "reordered": """\
target-saveconfig-sha256=stable
target-saveconfig-json-begin
{"storage_objects":["pvc-a"]}
target-saveconfig-json-end
path=/etc/samba/smb.conf|type=regular file|mode=644|uid=0|gid=0|size=20|sha256=stable-samba
path=/sys/kernel/config/target/iscsi/iqn.example:pvc-a/tpgt_1/lun/lun_0/link|type=symbolic link|mode=777|uid=0|gid=0|sha256=new-link
path=/sys/kernel/config/target/core/alua/lu_gps/default_lu_gp/members|type=regular file|mode=444|uid=0|gid=0|size=4096|sha256=new-members
path=/sys/kernel/config/target/core/iblock_11/pvc-a/attrib/block_size|type=regular file|mode=644|uid=0|gid=0|size=4096|sha256=stable-attribute
path=/sys/kernel/config/target/core/iblock_11/pvc-a/info|type=regular file|mode=444|uid=0|gid=0|size=4096|sha256=new-info
path=/sys/kernel/config/target/core/iblock_11/pvc-a|type=directory|mode=755|uid=0|gid=0|sha256=-
path=/sys/kernel/config/target/core/iblock_11/hba_info|type=regular file|mode=444|uid=0|gid=0|size=4096|sha256=new-hba
path=/sys/kernel/config/target/core/iblock_11|type=directory|mode=755|uid=0|gid=0|sha256=-
listener=t|3260|present|endpoints=192.0.2.1:3260
""",
        "drifted": """\
target-saveconfig-sha256=stable
target-saveconfig-json-begin
{"storage_objects":["pvc-a"]}
target-saveconfig-json-end
path=/etc/samba/smb.conf|type=regular file|mode=644|uid=0|gid=0|size=20|sha256=stable-samba
path=/sys/kernel/config/target/iscsi/iqn.example:pvc-a/tpgt_1/lun/lun_0/link|type=symbolic link|mode=777|uid=0|gid=0|sha256=new-link
path=/sys/kernel/config/target/core/alua/lu_gps/default_lu_gp/members|type=regular file|mode=444|uid=0|gid=0|size=4096|sha256=new-members
path=/sys/kernel/config/target/core/iblock_11/pvc-a/attrib/block_size|type=regular file|mode=644|uid=0|gid=0|size=4096|sha256=changed-attribute
path=/sys/kernel/config/target/core/iblock_11/pvc-a/info|type=regular file|mode=444|uid=0|gid=0|size=4096|sha256=new-info
path=/sys/kernel/config/target/core/iblock_11/pvc-a|type=directory|mode=755|uid=0|gid=0|sha256=-
path=/sys/kernel/config/target/core/iblock_11/hba_info|type=regular file|mode=444|uid=0|gid=0|size=4096|sha256=new-hba
path=/sys/kernel/config/target/core/iblock_11|type=directory|mode=755|uid=0|gid=0|sha256=-
listener=t|3260|present|endpoints=192.0.2.1:3260
""",
        "ambiguous": """\
path=/sys/kernel/config/target/core/iblock_0|type=directory|mode=755|uid=0|gid=0|sha256=-
path=/sys/kernel/config/target/core/iblock_0/pvc-a|type=directory|mode=755|uid=0|gid=0|sha256=-
path=/sys/kernel/config/target/core/iblock_0/pvc-b|type=directory|mode=755|uid=0|gid=0|sha256=-
""",
        "empty": """\
path=/sys/kernel/config/target/core/iblock_7|type=directory|mode=755|uid=0|gid=0|sha256=-
path=/sys/kernel/config/target/core/iblock_7/hba_info|type=regular file|mode=444|uid=0|gid=0|size=4096|sha256=empty-hba
""",
    }
    sources = {
        "nix/scripts/homelab-host": source("nix/scripts/homelab-host"),
        "nix/scripts/k3s-handoff rollback": source("nix/scripts/k3s-handoff").split(
            'cat > "$dir/rollback" <<\'ROLLBACK\'\n', 1
        )[1].split("\nROLLBACK\n", 1)[0],
    }
    with tempfile.TemporaryDirectory() as directory:
        directory_path = Path(directory)
        for name, content in manifests.items():
            (directory_path / name).write_text(content)
        failing_bin = directory_path / "failing-bin"
        failing_bin.mkdir()
        failing_sort = failing_bin / "sort"
        failing_sort.write_text("#!/bin/sh\nexit 43\n")
        failing_sort.chmod(0o700)
        for script_name, text in sources.items():
            match = re.search(
                r"(normalize_nas_manifest\(\) \{\n.*?^\})",
                text,
                re.MULTILINE | re.DOTALL,
            )
            if match is None:
                raise SystemExit(f"{script_name}: NAS manifest normalizer missing")
            environment = {
                **os.environ,
                "BASELINE": str(directory_path / "baseline"),
                "REORDERED": str(directory_path / "reordered"),
                "DRIFTED": str(directory_path / "drifted"),
                "AMBIGUOUS": str(directory_path / "ambiguous"),
                "EMPTY": str(directory_path / "empty"),
                "BASELINE_NORMALIZED": str(directory_path / "baseline.normalized"),
                "REORDERED_NORMALIZED": str(directory_path / "reordered.normalized"),
                "DRIFTED_NORMALIZED": str(directory_path / "drifted.normalized"),
                "AMBIGUOUS_NORMALIZED": str(directory_path / "ambiguous.normalized"),
                "EMPTY_NORMALIZED": str(directory_path / "empty.normalized"),
            }
            result = subprocess.run(
                ["bash", "--noprofile", "--norc", "-ceu", match.group(1) + """
normalize_nas_manifest "$BASELINE" "$BASELINE_NORMALIZED"
normalize_nas_manifest "$REORDERED" "$REORDERED_NORMALIZED"
cmp -s "$BASELINE_NORMALIZED" "$REORDERED_NORMALIZED"
normalize_nas_manifest "$DRIFTED" "$DRIFTED_NORMALIZED"
if cmp -s "$BASELINE_NORMALIZED" "$DRIFTED_NORMALIZED"; then
  exit 41
fi
if normalize_nas_manifest "$AMBIGUOUS" "$AMBIGUOUS_NORMALIZED"; then
  exit 42
fi
normalize_nas_manifest "$EMPTY" "$EMPTY_NORMALIZED"
grep -F 'path=/sys/kernel/config/target/core/iblock_7|' "$EMPTY_NORMALIZED" >/dev/null
grep -F 'path=/sys/kernel/config/target/core/iblock_7/hba_info|' "$EMPTY_NORMALIZED" >/dev/null
"""],
                capture_output=True,
                text=True,
                env=environment,
            )
            if result.returncode != 0:
                raise SystemExit(
                    f"{script_name}: NAS runtime-index normalization contract failed\n"
                    f"{result.stderr.strip()}"
                )
            failure_environment = {
                **environment,
                "PATH": f"{failing_bin}:{os.environ.get('PATH', '')}",
                "SORT_FAILURE_OUTPUT": str(directory_path / "sort-failure.normalized"),
            }
            failure_result = subprocess.run(
                [
                    "bash",
                    "--noprofile",
                    "--norc",
                    "-ceu",
                    match.group(1)
                    + """
if normalize_nas_manifest "$BASELINE" "$SORT_FAILURE_OUTPUT"; then
  exit 43
fi
""",
                ],
                capture_output=True,
                text=True,
                env=failure_environment,
            )
            if failure_result.returncode != 0:
                raise SystemExit(
                    f"{script_name}: NAS normalizer accepted a failed sort\n"
                    f"{failure_result.stdout}{failure_result.stderr}"
                )


def check_preserved_rollback_manifest_guard() -> None:
    handoff = source("nix/scripts/k3s-handoff")
    delimiter = 'cat > "$dir/rollback" <<\'ROLLBACK\'\n'
    if delimiter not in handoff or "\nROLLBACK\n" not in handoff:
        raise SystemExit("nix/scripts/k3s-handoff: generated rollback script missing")
    rollback = handoff.split(delimiter, 1)[1].split("\nROLLBACK\n", 1)[0]
    replacements = {
        'export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"': 'export PATH="$TEST_BIN:$PATH"',
        "dir=/var/lib/homelab-host-rollback/current": 'dir="$TEST_CURRENT"',
        'mkdir -p "$stages"': 'mkdir -p "$stages"\nexit 77',
    }
    for original, replacement in replacements.items():
        if original not in rollback:
            raise SystemExit(
                f"nix/scripts/k3s-handoff: preserved rollback fixture missing {original!r}"
            )
        rollback = rollback.replace(original, replacement, 1)

    with tempfile.TemporaryDirectory() as directory:
        directory_path = Path(directory)
        current = directory_path / "current"
        test_bin = directory_path / "bin"
        current.mkdir()
        test_bin.mkdir()
        (current / "config").write_text(
            "\n\niptables.service\nsshd.service\neth0\n\nagent\napt\ntrue\nfalse\ntrue\ntrue\n"
        )
        secret = "chap_password=must-not-enter-rollback-log"
        expected_manifest = f"expected\n{secret}\n"
        (current / "manifest.txt").write_text(expected_manifest)
        manifest_remote = current / "manifest-remote"
        manifest_remote.write_text(
            "set -eu\n"
            "printf '%s\\0' \"${MANIFEST_OUTPUT:-changed}\""
            " | while IFS= read -r -d '' item; do\n"
            "  printf '%s\\n' \"$item\"\n"
            "done\n"
        )
        manifest_remote.chmod(0o700)
        checksums = subprocess.check_output(
            ["sha256sum", "manifest.txt", "manifest-remote"],
            cwd=current,
            text=True,
        )
        (current / "manifest.sha256").write_text(checksums)
        rollback_path = directory_path / "rollback"
        rollback_path.write_text(rollback)
        rollback_path.chmod(0o755)
        environment = {
            **os.environ,
            "TEST_BIN": str(test_bin),
            "TEST_CURRENT": str(current),
        }

        result = subprocess.run(
            ["/bin/sh", str(rollback_path)],
            capture_output=True,
            text=True,
            env=environment,
        )
        if result.returncode == 0 or (current / "stages").exists():
            raise SystemExit(
                "nix/scripts/k3s-handoff: preserved rollback mutated state after NAS drift"
            )
        rollback_log = (current / "rollback.log").read_text()
        if "external NAS state changed; refusing rollback mutation" not in rollback_log:
            raise SystemExit(
                "nix/scripts/k3s-handoff: preserved rollback drift refusal was not recorded"
            )
        if secret in rollback_log:
            raise SystemExit(
                "nix/scripts/k3s-handoff: preserved rollback leaked secret manifest content"
            )

        result = subprocess.run(
            ["/bin/sh", str(rollback_path)],
            capture_output=True,
            text=True,
            env={**environment, "MANIFEST_OUTPUT": expected_manifest.rstrip("\n")},
        )
        if result.returncode != 77 or not (current / "stages").is_dir():
            raise SystemExit(
                "nix/scripts/k3s-handoff: matching NAS manifest did not pass the pre-mutation gate"
            )


def check_authorized_keys_verification() -> None:
    migration = source("nix/scripts/homelab-host")
    match = re.search(r"grep -Eqi '(\^authorizedkeysfile[^']+)'", migration)
    if match is None:
        raise SystemExit("nix/scripts/homelab-host: AuthorizedKeysFile verification pattern missing")
    pattern = match.group(1)
    allowed = (
        "authorizedkeysfile .ssh/authorized_keys /etc/ssh/authorized_keys.d/%u",
        "authorizedkeysfile /etc/ssh/authorized_keys.d/%u",
    )
    for value in allowed:
        result = subprocess.run(
            ["grep", "-Eqi", pattern],
            input=f"{value}\n",
            text=True,
        )
        if result.returncode:
            raise SystemExit(
                f"nix/scripts/homelab-host: rejected valid AuthorizedKeysFile value {value!r}"
            )
    invalid = subprocess.run(
        ["grep", "-Eqi", pattern],
        input="authorizedkeysfile .ssh/authorized_keys\n",
        text=True,
    )
    if invalid.returncode == 0:
        raise SystemExit("nix/scripts/homelab-host: accepted unmanaged-only AuthorizedKeysFile value")


def check_ssh_strict_modes_guard() -> None:
    require(
        "nix/modules/linux/base.nix",
        'systemd.tmpfiles.rules = [\n'
        '      "d /etc 0755 root root -"\n'
        '      "d /etc/ssh 0755 root root -"\n'
        '      "d /etc/ssh/authorized_keys.d 0755 root root -"\n'
        "    ];",
    )
    migration = source("nix/scripts/homelab-host")
    native_match = re.search(
        r"<<'REMOTE_NATIVE_RUNTIME'\n(.*?)\nREMOTE_NATIVE_RUNTIME",
        migration,
        re.DOTALL,
    )
    if native_match is None:
        raise SystemExit("nix/scripts/homelab-host: native runtime body missing")
    native = native_match.group(1)
    guard = """for path in /etc /etc/ssh /etc/ssh/authorized_keys.d; do
  test "$(stat -c '%a %u %g' "$path")" = "755 0 0"
done"""
    apply_tmpfiles = "systemd-tmpfiles --create --prefix=/etc\n"
    reload_ssh = 'systemctl reload "$SSH_SERVICE"'
    if apply_tmpfiles not in native:
        raise SystemExit("nix/scripts/homelab-host: /etc tmpfiles convergence missing")
    if guard not in native:
        raise SystemExit("nix/scripts/homelab-host: SSH StrictModes ancestor guard missing")
    if reload_ssh not in native:
        raise SystemExit("nix/scripts/homelab-host: SSH reload missing")
    if native.index(apply_tmpfiles) > native.index(guard):
        raise SystemExit("nix/scripts/homelab-host: StrictModes guard precedes tmpfiles convergence")
    if native.index(guard) > native.index(reload_ssh):
        raise SystemExit("nix/scripts/homelab-host: SSH reload precedes StrictModes ancestor guard")
    verify_match = re.search(
        r"<<'REMOTE_VERIFY'\n(.*?)\nREMOTE_VERIFY",
        migration,
        re.DOTALL,
    )
    if verify_match is None:
        raise SystemExit("nix/scripts/homelab-host: verify-host body missing")
    verify = verify_match.group(1)
    for expected in (
        guard,
        'test -s "/etc/ssh/authorized_keys.d/$ADMIN_USER"',
    ):
        if expected not in verify:
            raise SystemExit(
                f"nix/scripts/homelab-host: SSH StrictModes verification missing {expected!r}"
            )


def check_wireguard_handshake_probe() -> None:
    migration = source("nix/scripts/homelab-host")
    match = re.search(
        r"<<'REMOTE_WIREGUARD_HANDSHAKE'\n(.*?)\nREMOTE_WIREGUARD_HANDSHAKE",
        migration,
        re.DOTALL,
    )
    if match is None:
        raise SystemExit("nix/scripts/homelab-host: WireGuard handshake probe missing")
    with tempfile.TemporaryDirectory() as directory:
        directory_path = Path(directory)
        state = directory_path / "wg-count"
        for command, body in {
            "ping": "#!/bin/sh\nexit 0\n",
            "sleep": "#!/bin/sh\nexit 0\n",
            "wg": (
                "#!/bin/sh\n"
                'count=$(cat "$WG_TEST_STATE" 2>/dev/null || printf 0)\n'
                "count=$((count + 1))\n"
                'printf "%s\\n" "$count" > "$WG_TEST_STATE"\n'
                "handshake=0\n"
                'if [ "${WG_TEST_SUCCEED_AFTER:-0}" -gt 0 ] '
                '&& [ "$count" -ge "$WG_TEST_SUCCEED_AFTER" ]; then handshake=1; fi\n'
                'printf "%s\\t%s\\n" "$WG_PUBLIC" "$handshake"\n'
            ),
        }.items():
            path = directory_path / command
            path.write_text(body)
            path.chmod(0o755)
        environment = {
            **os.environ,
            "PATH": f"{directory}:{os.environ['PATH']}",
            "WG_INTERFACE": "wg0",
            "WG_PEER": "n2p2",
            "WG_PUBLIC": "test-public-key",
            "WG_ADDRESS": "10.222.0.2",
            "WG_TEST_STATE": str(state),
            "WG_TEST_SUCCEED_AFTER": "3",
        }
        result = subprocess.run(
            ["sh"],
            input=match.group(1),
            text=True,
            capture_output=True,
            env=environment,
        )
        if result.returncode or state.read_text().strip() != "3":
            raise SystemExit(
                "nix/scripts/homelab-host: WireGuard handshake probe did not retry to success\n"
                f"{result.stderr.strip()}"
            )
        state.unlink()
        environment["WG_TEST_SUCCEED_AFTER"] = "0"
        result = subprocess.run(
            ["sh"],
            input=match.group(1),
            text=True,
            capture_output=True,
            env=environment,
        )
        expected = "wg0 handshake with n2p2 (10.222.0.2) did not recover after 30 attempts"
        if result.returncode == 0 or expected not in result.stderr:
            raise SystemExit(
                "nix/scripts/homelab-host: WireGuard handshake probe failure is not actionable"
            )



def check_register_system_failure() -> None:
    migration = source("nix/scripts/homelab-host")
    match = re.search(
        r"(register_system\(\) \{\n.*?^\})",
        migration,
        re.DOTALL | re.MULTILINE,
    )
    if match is None:
        raise SystemExit("nix/scripts/homelab-host: register_system function missing")
    with tempfile.TemporaryDirectory() as directory:
        marker = Path(directory) / "remote-called"
        script = f"""
set -euo pipefail
{match.group(1)}
committed_flake() {{ printf 'git+https://example.invalid/homelab?rev=test#%s\\n' "$1"; }}
remote_system_manager() {{ return 73; }}
remote() {{ : > "$MARKER"; }}
if register_system test-host host-test; then
  echo "register_system accepted failed remote registration" >&2
  exit 1
fi
test ! -e "$MARKER"
"""
        result = subprocess.run(
            ["bash"],
            input=script,
            text=True,
            capture_output=True,
            env={**os.environ, "MARKER": str(marker)},
        )
        if result.returncode or "failed to register system-manager generation" not in result.stderr:
            raise SystemExit(
                "nix/scripts/homelab-host: failed remote registration did not stop preparation\n"
                f"{result.stderr.strip()}"
            )


def check_time_sync_waits() -> None:
    migration = source("nix/scripts/homelab-host")
    loops = re.findall(
        r'(attempt=0\nwhile test "\$\(timedatectl show -p NTPSynchronized --value\)" != yes; do'
        r'.*?^done)',
        migration,
        re.DOTALL | re.MULTILINE,
    )
    if len(loops) != 2:
        raise SystemExit("nix/scripts/homelab-host: activation and verification time-sync waits missing")
    with tempfile.TemporaryDirectory() as directory:
        directory_path = Path(directory)
        state = directory_path / "time-count"
        timedatectl = directory_path / "timedatectl"
        timedatectl.write_text(
            "#!/bin/sh\n"
            'count=$(cat "$TIME_TEST_STATE" 2>/dev/null || printf 0)\n'
            "count=$((count + 1))\n"
            'printf "%s\\n" "$count" > "$TIME_TEST_STATE"\n'
            'if test "$count" -ge 3; then printf "yes\\n"; else printf "no\\n"; fi\n'
        )
        timedatectl.chmod(0o755)
        sleep = directory_path / "sleep"
        sleep.write_text("#!/bin/sh\nexit 0\n")
        sleep.chmod(0o755)
        environment = {
            **os.environ,
            "PATH": f"{directory}:{os.environ['PATH']}",
            "TIME_TEST_STATE": str(state),
        }
        for loop in loops:
            state.unlink(missing_ok=True)
            result = subprocess.run(
                ["sh"],
                input=f"set -eu\n{loop}\n",
                text=True,
                capture_output=True,
                env=environment,
            )
            if result.returncode or state.read_text().strip() != "3":
                raise SystemExit(
                    "nix/scripts/homelab-host: time synchronization wait did not retry to success\n"
                    f"{result.stderr.strip()}"
                )

    handoff = source("nix/scripts/k3s-handoff")
    match = re.search(
        r"(systemctl restart systemd-timesyncd\.service\nattempt=0\n"
        r'while test .*?time_synchronized=true\nelse\n.*?^fi)\nif test -n "\$legacy_unit"',
        handoff,
        re.DOTALL | re.MULTILINE,
    )
    if match is None:
        raise SystemExit("nix/scripts/k3s-handoff: best-effort rollback time synchronization missing")
    with tempfile.TemporaryDirectory() as directory:
        directory_path = Path(directory)
        for command, body in {
            "systemctl": "#!/bin/sh\nexit 0\n",
            "timedatectl": "#!/bin/sh\nprintf 'no\\n'\n",
            "sleep": "#!/bin/sh\nexit 0\n",
        }.items():
            path = directory_path / command
            path.write_text(body)
            path.chmod(0o755)
        result = subprocess.run(
            ["sh"],
            input=f"set -eu\n{match.group(1)}\ntest \"$time_synchronized\" = false\n",
            text=True,
            capture_output=True,
            env={**os.environ, "PATH": f"{directory}:{os.environ['PATH']}"},
        )
        if result.returncode:
            raise SystemExit(
                "nix/scripts/k3s-handoff: NTP timeout aborted rollback before service recovery\n"
                f"{result.stderr.strip()}"
            )



def check_new_node_rollback_managed_k3s_state() -> None:
    handoff = source("nix/scripts/k3s-handoff")
    match = re.search(
        r'(if test -n "\$legacy_unit"; then\n.*?'
        r'elif test "\$role" = server \|\| test "\$role" = agent; then\n'
        r'.*?^fi)',
        handoff,
        re.DOTALL | re.MULTILINE,
    )
    if match is None:
        raise SystemExit(
            "nix/scripts/k3s-handoff: restored managed K3s service verification missing"
        )
    with tempfile.TemporaryDirectory() as directory:
        directory_path = Path(directory)
        unit = directory_path / "unit"
        state = directory_path / "state"
        systemctl = directory_path / "systemctl"
        systemctl.write_text(
            """#!/bin/sh
case "$1:$2" in
  cat:homelab-k3s.service)
    test "$(cat "$TEST_UNIT")" = present
    ;;
  is-active:homelab-k3s.service)
    state=$(cat "$TEST_STATE")
    printf '%s\n' "$state"
    test "$state" = active
    ;;
  *)
    exit 2
    ;;
esac
"""
        )
        systemctl.chmod(0o755)
        for unit_state, service_state, expected_success in (
            ("absent", "inactive", True),
            ("present", "active", True),
            ("present", "inactive", False),
        ):
            unit.write_text(f"{unit_state}\n")
            state.write_text(f"{service_state}\n")
            result = subprocess.run(
                ["sh"],
                input=(
                    "set -eu\n"
                    "legacy_unit=\n"
                    "role=agent\n"
                    f"{match.group(1)}\n"
                ),
                text=True,
                capture_output=True,
                env={
                    **os.environ,
                    "PATH": f"{directory}:{os.environ['PATH']}",
                    "TEST_UNIT": str(unit),
                    "TEST_STATE": str(state),
                },
            )
            if (result.returncode == 0) != expected_success:
                raise SystemExit(
                    "nix/scripts/k3s-handoff: restored managed K3s state was misclassified\n"
                    f"unit={unit_state} state={service_state}\n"
                    f"{result.stderr.strip()}"
                )


def check_new_node_rollback_cleanup() -> None:
    handoff = source("nix/scripts/k3s-handoff")
    host_migration = source("nix/scripts/homelab-host")
    for needle in (
        "K3S_BINARY_PRESENT=%q",
        'case "$K3S_BINARY_PRESENT" in true|false)',
        'printf \'%s\\n\' "$K3S_STATE_PRESENT"',
        'printf \'%s\\n\' "$K3S_BINARY_PRESENT"',
        "IFS= read -r k3s_state_present",
        "IFS= read -r k3s_binary_present",
    ):
        if needle not in handoff:
            raise SystemExit(
                f"nix/scripts/k3s-handoff: rollback state capture missing {needle!r}"
            )
    for needle in (
        "HOMELAB_K3S_BINARY_PRESENT",
        'printf \'%s\\n\' "$HOMELAB_K3S_BINARY_PRESENT" > "$recovery/k3s-binary-present"',
        "remote_k3s_binary_present",
        'binary_present=$(remote_k3s_binary_present "$host")',
    ):
        if needle not in host_migration:
            raise SystemExit(
                f"nix/scripts/homelab-host: K3s onboarding baseline capture missing {needle!r}"
            )
    link_guard = 'test "$(readlink "$path")" = k3s'
    if link_guard not in handoff or host_migration.count(link_guard) < 2:
        raise SystemExit(
            "K3s cleanup may remove preexisting kubectl, crictl, or ctr commands"
        )
    match = re.search(
        r'(if test "\$k3s_state_present" = false; then\n.*?^fi\n'
        r'if test "\$k3s_binary_present" = false; then\n.*?^fi)',
        handoff,
        re.DOTALL | re.MULTILINE,
    )
    if match is None:
        raise SystemExit(
            "nix/scripts/k3s-handoff: new-node K3s rollback cleanup missing"
        )
    with tempfile.TemporaryDirectory() as directory:
        directory_path = Path(directory)
        k3s_state = directory_path / "k3s"
        bin_directory = directory_path / "bin"
        mountinfo = directory_path / "mountinfo"
        systemctl = directory_path / "systemctl"
        systemctl.write_text(
            "#!/bin/sh\n"
            'test "$1" = is-active\n'
            "printf 'inactive\\n'\n"
            "exit 3\n"
        )
        systemctl.chmod(0o755)
        block = (
            match.group(1)
            .replace("/var/lib/rancher/k3s", str(k3s_state))
            .replace("/usr/local/bin", str(bin_directory))
            .replace("/proc/self/mountinfo", str(mountinfo))
        )
        k3s_state.mkdir()
        bin_directory.mkdir()
        command_names = ("kubectl", "crictl", "ctr")
        owned_names = (
            "k3s",
            "k3s-killall.sh",
            "k3s-uninstall.sh",
            "k3s-agent-uninstall.sh",
            "k3s-homelab-bootstrap-uninstall.sh",
        )
        binary_names = owned_names + command_names
        for name in owned_names:
            (bin_directory / name).write_text(name)
        for name in command_names:
            (bin_directory / name).symlink_to("k3s")
        mountinfo.write_text("")
        result = subprocess.run(
            ["sh"],
            input=(
                "set -eu\n"
                "k3s_state_present=false\n"
                "k3s_binary_present=false\n"
                f"{block}\n"
            ),
            text=True,
            capture_output=True,
            env={**os.environ, "PATH": f"{directory}:{os.environ['PATH']}"},
        )
        if (
            result.returncode
            or k3s_state.exists()
            or any(os.path.lexists(bin_directory / name) for name in binary_names)
        ):
            raise SystemExit(
                "nix/scripts/k3s-handoff: new-node rollback left K3s state or binaries\n"
                f"{result.stderr.strip()}"
            )

        k3s_state.mkdir()
        for name in owned_names:
            (bin_directory / name).write_text(name)
        for name in command_names:
            (bin_directory / name).write_text("admin")
        result = subprocess.run(
            ["sh"],
            input=(
                "set -eu\n"
                "k3s_state_present=false\n"
                "k3s_binary_present=false\n"
                f"{block}\n"
            ),
            text=True,
            capture_output=True,
            env={**os.environ, "PATH": f"{directory}:{os.environ['PATH']}"},
        )
        if (
            result.returncode
            or k3s_state.exists()
            or any((bin_directory / name).exists() for name in owned_names)
            or any((bin_directory / name).read_text() != "admin" for name in command_names)
        ):
            raise SystemExit(
                "nix/scripts/k3s-handoff: rollback removed preexisting admin commands\n"
                f"{result.stderr.strip()}"
            )

        k3s_state.mkdir()
        (k3s_state / "preexisting").write_text("keep")
        for name in owned_names:
            (bin_directory / name).write_text(name)
        result = subprocess.run(
            ["sh"],
            input=(
                "set -eu\n"
                "k3s_state_present=true\n"
                "k3s_binary_present=true\n"
                f"{block}\n"
            ),
            text=True,
            capture_output=True,
            env={**os.environ, "PATH": f"{directory}:{os.environ['PATH']}"},
        )
        if (
            result.returncode
            or not (k3s_state / "preexisting").exists()
            or any(not (bin_directory / name).exists() for name in binary_names)
        ):
            raise SystemExit(
                "nix/scripts/k3s-handoff: rollback removed preexisting K3s state or binaries\n"
                f"{result.stderr.strip()}"
            )
        shutil.rmtree(k3s_state)


        k3s_state.mkdir()
        (k3s_state / "agent").mkdir()
        mountinfo.write_text(
            f"1 0 0:1 / {k3s_state} rw - tmpfs tmpfs rw\n"
        )
        result = subprocess.run(
            ["sh"],
            input=(
                "set -eu\n"
                "k3s_state_present=false\n"
                "k3s_binary_present=true\n"
                f"{block}\n"
            ),
            text=True,
            capture_output=True,
            env={**os.environ, "PATH": f"{directory}:{os.environ['PATH']}"},
        )
        if (
            result.returncode == 0
            or not k3s_state.exists()
            or "K3s state remains mounted during rollback" not in result.stderr
        ):
            raise SystemExit(
                "nix/scripts/k3s-handoff: mounted K3s state cleanup was not blocked"
            )
        shutil.rmtree(k3s_state)



def check_wireguard_rollback_failure_continuation() -> None:
    handoff = source("nix/scripts/k3s-handoff")
    match = re.search(
        r'(wireguard_restore_failed=false\nfor interface in \$wg_interfaces; do\n.*?^done)',
        handoff,
        re.DOTALL | re.MULTILINE,
    )
    if match is None:
        raise SystemExit(
            "nix/scripts/k3s-handoff: best-effort WireGuard rollback restoration missing"
        )
    if not re.search(
        r'for unit in systemd-networkd\.service systemd-resolved\.service '
        r'systemd-timesyncd\.service "\$ssh_service"; do'
        r'.*?systemctl is-active "\$unit".*?verify_nas_manifest; fi'
        r'.*?if test "\$wireguard_restore_failed" = true; then'
        r'.*?rollback remains armed.*?exit 1.*?^fi'
        r'.*?systemctl disable --now homelab-host-rollback\.timer',
        handoff,
        re.DOTALL | re.MULTILINE,
    ):
        raise SystemExit(
            "nix/scripts/k3s-handoff: WireGuard restore failure must not block service recovery or disarm rollback"
        )
    with tempfile.TemporaryDirectory() as directory:
        directory_path = Path(directory)
        for command in ("ip", "networkctl"):
            path = directory_path / command
            path.write_text("#!/bin/sh\nexit 0\n")
            path.chmod(0o755)
        helper = directory_path / "sync-wireguard-runtime"
        helper.write_text("#!/bin/sh\nexit 1\n")
        helper.chmod(0o755)
        result = subprocess.run(
            ["sh"],
            input=(
                "set -eu\n"
                f'PATH="{directory}:{os.environ["PATH"]}"\n'
                f'dir="{directory}"\n'
                "wg_interfaces=wg0\n"
                f"{match.group(1)}\n"
                'test "$wireguard_restore_failed" = true\n'
                "printf 'service-recovery-continued\\n'\n"
            ),
            text=True,
            capture_output=True,
        )
        if (
            result.returncode
            or result.stdout.strip() != "service-recovery-continued"
            or "WireGuard runtime restoration failed" not in result.stderr
        ):
            raise SystemExit(
                "nix/scripts/k3s-handoff: WireGuard failure aborted rollback before service recovery\n"
                f"{result.stderr.strip()}"
            )


def check_firewall_restore_waits() -> None:
    handoff = source("nix/scripts/k3s-handoff")
    match = re.search(
        r'(  firewall_attempt=0\n  while ! iptables-restore --test --wait .*?'
        r"rollback failed while restoring the runtime firewall.*?^  \})",
        handoff,
        re.DOTALL | re.MULTILINE,
    )
    if match is None:
        raise SystemExit("nix/scripts/k3s-handoff: bounded runtime firewall restore wait missing")
    with tempfile.TemporaryDirectory() as directory:
        directory_path = Path(directory)
        state = directory_path / "firewall-count"
        applied = directory_path / "firewall-applied"
        rules = directory_path / "firewall-runtime.rules"
        rules.write_text("*filter\nCOMMIT\n")
        iptables_restore = directory_path / "iptables-restore"
        iptables_restore.write_text(
            "#!/bin/sh\n"
            'if test "$1" = --test; then\n'
            '  count=$(cat "$FIREWALL_TEST_STATE" 2>/dev/null || printf 0)\n'
            "  count=$((count + 1))\n"
            '  printf "%s\\n" "$count" > "$FIREWALL_TEST_STATE"\n'
            '  test "${FIREWALL_SUCCEED_AFTER:-0}" -gt 0 '
            '&& test "$count" -ge "$FIREWALL_SUCCEED_AFTER"\n'
            "  exit\n"
            "fi\n"
            ': > "$FIREWALL_APPLIED"\n'
        )
        iptables_restore.chmod(0o755)
        sleep = directory_path / "sleep"
        sleep.write_text("#!/bin/sh\nexit 0\n")
        sleep.chmod(0o755)
        environment = {
            **os.environ,
            "PATH": f"{directory}:{os.environ['PATH']}",
            "DIR": directory,
            "FIREWALL_TEST_STATE": str(state),
            "FIREWALL_APPLIED": str(applied),
            "FIREWALL_SUCCEED_AFTER": "3",
        }
        result = subprocess.run(
            ["sh"],
            input=f'set -eu\ndir="$DIR"\n{match.group(1)}\n',
            text=True,
            capture_output=True,
            env=environment,
        )
        if (
            result.returncode
            or state.read_text().strip() != "3"
            or not applied.exists()
        ):
            raise SystemExit(
                "nix/scripts/k3s-handoff: runtime firewall restore did not retry to success\n"
                f"{result.stderr.strip()}"
            )
        state.unlink()
        applied.unlink()
        environment["FIREWALL_SUCCEED_AFTER"] = "0"
        result = subprocess.run(
            ["sh"],
            input=f'set -eu\ndir="$DIR"\n{match.group(1)}\n',
            text=True,
            capture_output=True,
            env=environment,
        )
        if (
            result.returncode == 0
            or state.read_text().strip() != "60"
            or "did not become restorable within 120 seconds" not in result.stderr
            or applied.exists()
        ):
            raise SystemExit(
                "nix/scripts/k3s-handoff: runtime firewall restore timeout is unsafe"
            )


def check_cilium_restart_waits() -> None:
    handoff = source("nix/scripts/k3s-handoff")
    start = (
        'if test "$k3s_state_present" = true && '
        "grep -q 'CILIUM_' \"$dir/firewall-runtime.rules\"; then"
    )
    end = '\n  touch "$stages/firewall-restored"'
    if start not in handoff or end not in handoff:
        raise SystemExit("nix/scripts/k3s-handoff: cilium-agent restart wait missing")
    block = start + handoff.split(start, 1)[1].split(end, 1)[0]
    if block.endswith("\n  fi"):
        block = block[: -len("\n  fi")]
    block = block.replace(
        "crictl=/usr/local/bin/crictl", 'crictl="$TEST_CRICTL"', 1
    ).replace("/usr/bin/curl", '"$TEST_CURL"', 1)

    with tempfile.TemporaryDirectory() as directory:
        directory_path = Path(directory)
        rules = directory_path / "firewall-runtime.rules"
        rules.write_text("*filter\n:CILIUM_INPUT - [0:0]\nCOMMIT\n")
        state = directory_path / "crictl-count"
        stopped = directory_path / "stopped"
        healthy = directory_path / "healthy"
        crictl = directory_path / "crictl"
        crictl.write_text(
            "#!/bin/sh\n"
            'case " $* " in\n'
            '  *" ps "*)\n'
            '    count=$(cat "$CRICTL_STATE" 2>/dev/null || printf 0)\n'
            "    count=$((count + 1))\n"
            '    printf "%s\\n" "$count" > "$CRICTL_STATE"\n'
            '    if test ! -e "$CRICTL_STOPPED"; then\n'
            '      case "$count" in\n'
            "        1) exit 1 ;;\n"
            "        2) printf '%s\\n' old-cilium-id second-cilium-id ;;\n"
            "        *) printf '%s\\n' old-cilium-id ;;\n"
            "      esac\n"
            '    elif test "${CRICTL_RESTART:-0}" = 1 && test "$count" -ge 5; then\n'
            "      printf '%s\\n' new-cilium-id\n"
            "    else\n"
            "      printf '%s\\n' old-cilium-id\n"
            "    fi\n"
            "    ;;\n"
            '  *" stop "*)\n'
            '    for argument do previous=$argument; done\n'
            '    test "$previous" = old-cilium-id\n'
            '    : > "$CRICTL_STOPPED"\n'
            "    ;;\n"
            "  *) exit 1 ;;\n"
            "esac\n"
        )
        curl = directory_path / "curl"
        curl.write_text('#!/bin/sh\n: > "$CILIUM_HEALTHY"\n')
        sleep = directory_path / "sleep"
        sleep.write_text("#!/bin/sh\nexit 0\n")
        for command in (crictl, curl, sleep):
            command.chmod(0o755)
        environment = {
            **os.environ,
            "PATH": f"{directory}:{os.environ['PATH']}",
            "DIR": directory,
            "TEST_CRICTL": str(crictl),
            "TEST_CURL": str(curl),
            "CRICTL_STATE": str(state),
            "CRICTL_STOPPED": str(stopped),
            "CILIUM_HEALTHY": str(healthy),
            "CRICTL_RESTART": "1",
        }
        result = subprocess.run(
            ["sh"],
            input=f'set -eu\ndir="$DIR"\nk3s_state_present=true\n{block}\n',
            text=True,
            capture_output=True,
            env=environment,
        )
        if (
            result.returncode
            or state.read_text().strip() != "5"
            or not stopped.exists()
            or not healthy.exists()
        ):
            raise SystemExit(
                "nix/scripts/k3s-handoff: cilium-agent restart did not converge\n"
                f"{result.stderr.strip()}"
            )

        for path in (state, stopped, healthy):
            path.unlink(missing_ok=True)
        environment["CRICTL_RESTART"] = "0"
        result = subprocess.run(
            ["sh"],
            input=f'set -eu\ndir="$DIR"\nk3s_state_present=true\n{block}\n',
            text=True,
            capture_output=True,
            env=environment,
        )
        if (
            result.returncode == 0
            or state.read_text().strip() != "63"
            or "did not restart and become healthy within 120 seconds"
            not in result.stderr
            or healthy.exists()
        ):
            raise SystemExit(
                "nix/scripts/k3s-handoff: cilium-agent restart timeout is unsafe"
            )

        for path in (state, stopped, healthy):
            path.unlink(missing_ok=True)
        result = subprocess.run(
            ["sh"],
            input=f'set -eu\ndir="$DIR"\nk3s_state_present=false\n{block}\n',
            text=True,
            capture_output=True,
            env=environment,
        )
        if result.returncode or state.exists() or stopped.exists() or healthy.exists():
            raise SystemExit(
                "nix/scripts/k3s-handoff: rollback touched Cilium for a host without baseline K3s state\n"
                f"{result.stderr.strip()}"
            )

def check_onboard_k3s_install_guard() -> None:
    migration = source("nix/scripts/homelab-host")
    binary_probe_match = re.search(
        r"(remote_k3s_binary_present\(\) \{\n.*?^\})",
        migration,
        re.DOTALL | re.MULTILINE,
    )
    if binary_probe_match is None:
        raise SystemExit(
            "nix/scripts/homelab-host: fail-closed K3s binary detection is missing"
        )
    try:
        onboard = migration.split("  onboard-k3s-node)", 1)[1].split(
            "\n  reconcile-distro-packages)", 1
        )[0]
        preflight = onboard.split('    remote "$host" \'', 1)[1].split(
            "'\n    binary_present=", 1
        )[0]
        install = onboard.split("<<'REMOTE_K3S_INSTALL'\n", 1)[1].split(
            "\nREMOTE_K3S_INSTALL", 1
        )[0]
    except IndexError as error:
        raise SystemExit("nix/scripts/homelab-host: K3s onboarding installer is missing") from error

    for needle in (
        "test ! -e /var/lib/rancher/k3s",
        "systemctl is-active",
        "systemctl is-enabled",
        "install_complete=false",
        "INSTALL_K3S_SKIP_ENABLE=true",
        "INSTALL_K3S_SKIP_START=true",
        'INSTALL_K3S_SYSTEMD_DIR="$service_dir"',
        "INSTALL_K3S_NAME=homelab-bootstrap",
        'INSTALL_K3S_VERSION="$K3S_VERSION"',
        'INSTALL_K3S_EXEC="$K3S_ROLE"',
        'curl --proto \'=https\' --tlsv1.2 -fsSL -o "$installer" https://get.k3s.io',
        'rm -f -- /usr/local/bin/k3s-homelab-bootstrap-uninstall.sh',
        'test -s "$installer"',
        "test -x /usr/local/bin/k3s",
        "install_complete=true",
    ):
        if needle not in install:
            raise SystemExit(
                f"nix/scripts/homelab-host: K3s onboarding install contract missing {needle!r}"
            )
    if "| INSTALL_K3S_" in install:
        raise SystemExit("nix/scripts/homelab-host: K3s installer download failure may be masked by a pipe")
    if not (
        install.index("install_complete=false")
        < install.index('sh "$installer"')
        < install.index("install_complete=true")
    ):
        raise SystemExit(
            "nix/scripts/homelab-host: partial K3s installation cleanup is not armed"
        )

    token_check = (
        'if ! "$root/nix/scripts/wireguard-secrets" copy-k3s-token '
        '--from "$source_host" --to "$host" --check'
    )
    token_write = (
        '"$root/nix/scripts/wireguard-secrets" copy-k3s-token '
        '--from "$source_host" --to "$host" --write'
    )
    prepare = '"$0" prepare "$host"'
    if not (
        onboard.index("REMOTE_K3S_INSTALL")
        < onboard.index(token_check)
        < onboard.index(token_write)
        < onboard.index(prepare)
    ):
        raise SystemExit(
            "nix/scripts/homelab-host: install, token check/write, and guarded prepare order changed"
        )

    provision = source("nix/scripts/provision-host")
    if "INSTALL_K3S_" in provision or "https://get.k3s.io" in provision:
        raise SystemExit("nix/scripts/provision-host: K3s installation ownership is duplicated")
    if '"$host_app" onboard-k3s-node "$host" --token-source "$source_host"' not in provision:
        raise SystemExit("nix/scripts/provision-host: onboarding delegation is missing")
    binary_probe = binary_probe_match.group(1)
    for mode, expected_output, expected_success in (
        ("present", "true", True),
        ("absent", "false", True),
        ("transport", "", False),
        ("invalid", "", False),
    ):
        result = subprocess.run(
            ["bash"],
            input=(
                "set -euo pipefail\n"
                "remote() {\n"
                '  case "$TEST_BINARY_MODE" in\n'
                '    present) printf "true\\n" ;;\n'
                '    absent) printf "false\\n" ;;\n'
                "    transport) return 255 ;;\n"
                '    invalid) printf "unknown\\n" ;;\n'
                "  esac\n"
                "}\n"
                f"{binary_probe}\n"
                "remote_k3s_binary_present node\n"
            ),
            text=True,
            capture_output=True,
            env={**os.environ, "TEST_BINARY_MODE": mode},
        )
        if (result.returncode == 0) != expected_success or (
            expected_success and result.stdout.strip() != expected_output
        ):
            raise SystemExit(
                "nix/scripts/homelab-host: K3s binary detection did not fail closed\n"
                f"mode={mode} rc={result.returncode} output={result.stdout.strip()!r}"
            )

    with tempfile.TemporaryDirectory() as directory:
        directory_path = Path(directory)
        mock_bin = directory_path / "bin"
        mock_bin.mkdir()
        systemctl = mock_bin / "systemctl"
        systemctl.write_text(
            "#!/bin/sh\n"
            'case "${TEST_LEGACY_MODE:-}:$1:$2" in\n'
            '  active:is-active:k3s-agent.service) printf "active\\n" ;;\n'
            '  enabled:is-enabled:k3s.service) printf "enabled\\n" ;;\n'
            '  *:is-active:*) printf "inactive\\n"; exit 3 ;;\n'
            '  *:is-enabled:*) printf "disabled\\n"; exit 1 ;;\n'
            "  *) exit 2 ;;\n"
            "esac\n"
        )
        systemctl.chmod(0o755)
        environment = {
            **os.environ,
            "PATH": f"{mock_bin}:{os.environ['PATH']}",
        }
        preflight = preflight.replace(
            "/var/lib/rancher/k3s", f'"{directory_path / "k3s-state"}"'
        )
        for legacy_mode in ("active", "enabled"):
            result = subprocess.run(
                ["sh", "-c", preflight],
                text=True,
                capture_output=True,
                env={**environment, "TEST_LEGACY_MODE": legacy_mode},
            )
            if result.returncode == 0:
                raise SystemExit(
                    "nix/scripts/homelab-host: "
                    f"{legacy_mode} legacy K3s service was accepted before onboarding"
                )

        result = subprocess.run(
            ["sh", "-c", preflight],
            text=True,
            capture_output=True,
            env={**environment, "TEST_LEGACY_MODE": "absent"},
        )
        if result.returncode:
            raise SystemExit(
                "nix/scripts/homelab-host: clean K3s onboarding target was rejected\n"
                f"{result.stderr.strip()}"
            )

        result = subprocess.run(
            ["sh"],
            input=f"set -eu\nK3S_VERSION=v1.2.3 K3S_ROLE=agent\n{install}\n",
            text=True,
            capture_output=True,
            env={**environment, "TEST_LEGACY_MODE": "active"},
        )
        if result.returncode == 0:
            raise SystemExit(
                "nix/scripts/homelab-host: active legacy K3s service was accepted before installation"
            )

        installer_source = directory_path / "installer-source"
        installer_source.write_text(
            "#!/bin/sh\n"
            "set -eu\n"
            'mkdir -p "$INSTALL_K3S_SYSTEMD_DIR" "$TEST_BIN"\n'
            ': > "$INSTALL_K3S_SYSTEMD_DIR/k3s-homelab-bootstrap.service"\n'
            ': > "$INSTALL_K3S_SYSTEMD_DIR/k3s-homelab-bootstrap.service.env"\n'
            "for name in k3s k3s-killall.sh k3s-uninstall.sh "
            "k3s-agent-uninstall.sh k3s-homelab-bootstrap-uninstall.sh; do\n"
            '  : > "$TEST_BIN/$name"\n'
            "done\n"
            "for name in kubectl crictl ctr; do\n"
            '  test -e "$TEST_BIN/$name" || ln -s k3s "$TEST_BIN/$name"\n'
            "done\n"
            'chmod 0755 "$TEST_BIN/k3s"\n'
            'exit "${TEST_INSTALL_EXIT:-0}"\n'
        )
        installer_source.chmod(0o755)
        bin_directory = directory_path / "install-bin"
        state_path = directory_path / "install-state"
        sandboxed_install = (
            install.replace("/var/lib/rancher/k3s", str(state_path))
            .replace("/usr/local/bin", str(bin_directory))
            .replace("/tmp/k3s-install.XXXXXX", str(directory_path / "k3s-install.XXXXXX"))
            .replace("/tmp/k3s-systemd.XXXXXX", str(directory_path / "k3s-systemd.XXXXXX"))
            .replace(
                'curl --proto \'=https\' --tlsv1.2 -fsSL -o "$installer" https://get.k3s.io',
                'cp "$TEST_INSTALLER" "$installer"',
            )
        )
        install_environment = {
            **environment,
            "TEST_LEGACY_MODE": "absent",
            "TEST_INSTALLER": str(installer_source),
            "TEST_BIN": str(bin_directory),
        }
        result = subprocess.run(
            ["sh"],
            input=f"set -eu\nK3S_VERSION=v1.2.3 K3S_ROLE=agent\n{sandboxed_install}\n",
            text=True,
            capture_output=True,
            env=install_environment,
        )
        if (
            result.returncode
            or not (bin_directory / "k3s").exists()
            or (bin_directory / "k3s-homelab-bootstrap-uninstall.sh").exists()
            or list(directory_path.glob("k3s-systemd.*"))
        ):
            raise SystemExit(
                "nix/scripts/homelab-host: successful onboarding left bootstrap service artifacts\n"
                f"{result.stderr.strip()}"
            )
        shutil.rmtree(bin_directory)
        bin_directory.mkdir()
        admin_command = bin_directory / "kubectl"
        admin_command.write_text("admin")
        result = subprocess.run(
            ["sh"],
            input=f"set -eu\nK3S_VERSION=v1.2.3 K3S_ROLE=agent\n{sandboxed_install}\n",
            text=True,
            capture_output=True,
            env={**install_environment, "TEST_INSTALL_EXIT": "1"},
        )
        unexpected = [
            path.name for path in bin_directory.iterdir() if path.name != admin_command.name
        ]
        if (
            result.returncode == 0
            or admin_command.read_text() != "admin"
            or unexpected
            or list(directory_path.glob("k3s-systemd.*"))
        ):
            raise SystemExit(
                "nix/scripts/homelab-host: failed onboarding left installer artifacts\n"
                f"{result.stderr.strip()}"
            )

def check_iscsi_service_verification() -> None:
    migration = source("nix/scripts/homelab-host")
    try:
        section = migration.split("stage=iscsi-client", 1)[1].split(
            "stage=iscsi-server", 1
        )[0]
    except IndexError as error:
        raise SystemExit("nix/scripts/homelab-host: iSCSI service verification missing") from error
    match = re.search(
        r'(if test "\$ISCSI_CLIENT" = true; then\n.*?^fi)',
        section,
        re.DOTALL | re.MULTILINE,
    )
    if match is None:
        raise SystemExit("nix/scripts/homelab-host: iSCSI service verification missing")
    block = match.group(1).replace("/etc/iscsi/nodes", '"$TEST_NODES"')
    with tempfile.TemporaryDirectory() as directory:
        directory_path = Path(directory)
        mock_bin = directory_path / "bin"
        nodes = directory_path / "nodes"
        events = directory_path / "events"
        mock_bin.mkdir()
        nodes.mkdir()
        systemctl = mock_bin / "systemctl"
        systemctl.write_text(
            "#!/bin/sh\n"
            'printf "%s\\n" "$*" >> "$EVENTS"\n'
            'if test "$1:$2" = "is-active:iscsid.service"; then\n'
            '  test "$ISCSID_ACTIVE" = yes\n'
            'elif test "$1:$2" = "is-enabled:$LOGIN_SERVICE"; then\n'
            '  test "$LOGIN_ENABLED" = yes\n'
            'elif test "$1:$2" = "is-active:$LOGIN_SERVICE"; then\n'
            '  test "$LOGIN_ACTIVE" = yes\n'
            "else\n"
            "  exit 2\n"
            "fi\n"
        )
        systemctl.chmod(0o755)
        environment = {
            **os.environ,
            "PATH": f"{mock_bin}:{os.environ['PATH']}",
            "TEST_NODES": str(nodes),
            "EVENTS": str(events),
        }

        def run(
            login_service: str,
            *,
            has_nodes: bool,
            iscsid: str,
            enabled: str,
            active: str,
        ) -> subprocess.CompletedProcess[str]:
            shutil.rmtree(nodes)
            nodes.mkdir()
            if has_nodes:
                (nodes / "target").write_text("fixture\n")
            events.unlink(missing_ok=True)
            return subprocess.run(
                ["sh"],
                input=(
                    "set -eu\n"
                    "ISCSI_CLIENT=true\n"
                    f"ISCSI_LOGIN_SERVICE={login_service}\n"
                    f"{block}\n"
                ),
                text=True,
                capture_output=True,
                env={
                    **environment,
                    "LOGIN_SERVICE": login_service,
                    "ISCSID_ACTIVE": iscsid,
                    "LOGIN_ENABLED": enabled,
                    "LOGIN_ACTIVE": active,
                },
            )

        for login_service in ("open-iscsi.service", "iscsi.service"):
            result = run(
                login_service,
                has_nodes=False,
                iscsid="yes",
                enabled="yes",
                active="no",
            )
            if result.returncode != 0:
                raise SystemExit(
                    f"nix/scripts/homelab-host: target-free {login_service} client was rejected"
                )
            if f"is-active {login_service}" in events.read_text():
                raise SystemExit(
                    f"nix/scripts/homelab-host: target-free {login_service} was required active"
                )
            if (
                run(
                    login_service,
                    has_nodes=True,
                    iscsid="yes",
                    enabled="yes",
                    active="no",
                ).returncode
                == 0
            ):
                raise SystemExit(
                    f"nix/scripts/homelab-host: configured {login_service} target may be inactive"
                )
            if (
                run(
                    login_service,
                    has_nodes=True,
                    iscsid="yes",
                    enabled="yes",
                    active="yes",
                ).returncode
                != 0
            ):
                raise SystemExit(
                    f"nix/scripts/homelab-host: active configured {login_service} client was rejected"
                )
            if (
                run(
                    login_service,
                    has_nodes=False,
                    iscsid="no",
                    enabled="yes",
                    active="no",
                ).returncode
                == 0
            ):
                raise SystemExit("nix/scripts/homelab-host: inactive iscsid was accepted")
            if (
                run(
                    login_service,
                    has_nodes=False,
                    iscsid="yes",
                    enabled="no",
                    active="no",
                ).returncode
                == 0
            ):
                raise SystemExit(
                    f"nix/scripts/homelab-host: disabled {login_service} was accepted"
                )


def check_rollback_restored_services() -> None:
    handoff = source("nix/scripts/k3s-handoff")
    match = re.search(
        r'(for unit in systemd-networkd\.service systemd-resolved\.service '
        r'systemd-timesyncd\.service "\$ssh_service"; do\n'
        r'  systemctl is-active "\$unit"\n'
        r'done)',
        handoff,
    )
    if match is None:
        raise SystemExit("nix/scripts/k3s-handoff: restored service verification loop missing")
    with tempfile.TemporaryDirectory() as directory:
        systemctl = Path(directory) / "systemctl"
        systemctl.write_text(
            "#!/bin/sh\n"
            'test "$1" = is-active || exit 2\n'
            'test "$2" != "${INACTIVE_UNIT:-}"\n'
        )
        systemctl.chmod(0o755)
        environment = {**os.environ, "PATH": f"{directory}:{os.environ['PATH']}"}
        script = f'set -eu\nssh_service=ssh.service\n{match.group(1)}\n'
        result = subprocess.run(
            ["sh"],
            input=script,
            text=True,
            capture_output=True,
            env=environment,
        )
        if result.returncode != 0:
            raise SystemExit("nix/scripts/k3s-handoff: healthy restored services were rejected")
        result = subprocess.run(
            ["sh"],
            input=script,
            text=True,
            capture_output=True,
            env={**environment, "INACTIVE_UNIT": "systemd-resolved.service"},
        )
        if result.returncode == 0:
            raise SystemExit("nix/scripts/k3s-handoff: inactive restored service was accepted")


def check_legacy_cleanup_path_verification() -> None:
    migration = source("nix/scripts/homelab-host")
    cleanup_source = migration.split("cleanup_legacy_files()", 1)[1].split(
        "verify_legacy_cleanup()", 1
    )[0]
    cleanup_match = re.search(
        r'(    for unit in k3s\.service k3s-agent\.service zram-swap\.service '
        r'ksm\.service thp-madvise\.service; do\n'
        r'.*?'
        r'    done\n'
        r'    systemctl daemon-reload)',
        cleanup_source,
        re.DOTALL,
    )
    if cleanup_match is None:
        raise SystemExit("nix/scripts/homelab-host: legacy cleanup block missing")
    cleanup_block = cleanup_match.group(1).replace(
        "/etc/systemd/system", "${TEST_SYSTEMD}"
    )
    verify_match = re.search(
        r'(    if test "\$REQUIRE_K3S_BINARY" = true; then\n'
        r'      test -x /usr/local/bin/k3s\n'
        r'    fi\n'
        r'    assert_path_absent\(\) \{\n'
        r'      test ! -e "\$1"\n'
        r'      test ! -L "\$1"\n'
        r'    \}\n'
        r'    for unit in k3s\.service k3s-agent\.service zram-swap\.service '
        r'ksm\.service thp-madvise\.service; do\n'
        r'.*?'
        r'^    done)',
        migration,
        re.DOTALL | re.MULTILINE,
    )
    if verify_match is None:
        raise SystemExit("nix/scripts/homelab-host: legacy path verification block missing")
    verify_block = (
        verify_match.group(1)
        .replace("/etc/systemd/system", "${TEST_SYSTEMD}")
        .replace("/usr/local/bin/k3s", "${TEST_K3S}")
    )
    with tempfile.TemporaryDirectory() as directory:
        directory_path = Path(directory)
        mock_bin = directory_path / "bin"
        systemd = directory_path / "systemd"
        mock_bin.mkdir()
        systemctl = mock_bin / "systemctl"
        systemctl.write_text(
            "#!/bin/sh\n"
            'case "$1" in\n'
            "  disable) exit 1 ;;\n"
            "  show|daemon-reload) exit 0 ;;\n"
            "  *) exit 2 ;;\n"
            "esac\n"
        )
        systemctl.chmod(0o755)
        k3s_binary = directory_path / "k3s"
        environment = {
            **os.environ,
            "PATH": f"{mock_bin}:{os.environ['PATH']}",
            "TEST_SYSTEMD": str(systemd),
            "TEST_K3S": str(k3s_binary),
            "REQUIRE_K3S_BINARY": "false",
        }
        cleanup_script = f"set -eu\n{cleanup_block}\n"
        verify_script = f"set -eu\n{verify_block}\n"

        def reset() -> None:
            shutil.rmtree(systemd, ignore_errors=True)
            systemd.mkdir()

        reset()
        direct = systemd / "k3s.service"
        environment_file = systemd / "k3s.service.env"
        drop_in = systemd / "k3s.service.d"
        multi_user_wants = systemd / "multi-user.target.wants" / "k3s.service"
        graphical_wants = systemd / "graphical.target.wants" / "k3s.service"
        network_requires = systemd / "network-online.target.requires" / "k3s.service"
        direct.symlink_to("missing-unit")
        environment_file.write_text("fixture\n")
        drop_in.mkdir()
        (drop_in / "log.conf").write_text("fixture\n")
        for link in (multi_user_wants, graphical_wants, network_requires):
            link.parent.mkdir(parents=True)
            link.symlink_to("../k3s.service")
        result = subprocess.run(
            ["sh"],
            input=cleanup_script,
            text=True,
            capture_output=True,
            env=environment,
        )
        if result.returncode != 0:
            raise SystemExit("nix/scripts/homelab-host: legacy cleanup failed after disable error")
        for path in (
            direct,
            environment_file,
            drop_in,
            multi_user_wants,
            graphical_wants,
            network_requires,
        ):
            if path.exists() or path.is_symlink():
                raise SystemExit(
                    f"nix/scripts/homelab-host: legacy cleanup retained path: {path.relative_to(systemd)}"
                )

        reset()
        result = subprocess.run(
            ["sh"],
            input=verify_script,
            text=True,
            capture_output=True,
            env=environment,
        )
        if result.returncode != 0:
            raise SystemExit("nix/scripts/homelab-host: clean legacy paths were rejected")
        result = subprocess.run(
            ["sh"],
            input=verify_script,
            text=True,
            capture_output=True,
            env={**environment, "REQUIRE_K3S_BINARY": "true"},
        )
        if result.returncode == 0:
            raise SystemExit("nix/scripts/homelab-host: missing K3s binary was accepted for a K3s host")
        k3s_binary.write_text("#!/bin/sh\nexit 0\n")
        k3s_binary.chmod(0o755)
        result = subprocess.run(
            ["sh"],
            input=verify_script,
            text=True,
            capture_output=True,
            env={**environment, "REQUIRE_K3S_BINARY": "true"},
        )
        if result.returncode != 0:
            raise SystemExit("nix/scripts/homelab-host: retained K3s binary was rejected for a K3s host")

        regular = systemd / "k3s.service.env"
        regular.write_text("fixture\n")
        result = subprocess.run(
            ["sh"],
            input=verify_script,
            text=True,
            capture_output=True,
            env=environment,
        )
        if result.returncode == 0:
            raise SystemExit("nix/scripts/homelab-host: existing legacy path was accepted")

        for relative in (
            "k3s.service",
            "k3s.service.env",
            "k3s.service.d",
            "multi-user.target.wants/k3s.service",
            "graphical.target.wants/k3s.service",
            "network-online.target.requires/k3s.service",
        ):
            reset()
            path = systemd / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to("missing-target")
            result = subprocess.run(
                ["sh"],
                input=verify_script,
                text=True,
                capture_output=True,
                env=environment,
            )
            if result.returncode == 0:

                raise SystemExit(
                    f"nix/scripts/homelab-host: dangling legacy symlink was accepted: {relative}"
                )


def check_nas_preservation_contracts() -> None:
    adopt = source("nix/scripts/adopt-host")
    migration = source("nix/scripts/homelab-host")
    handoff = source("nix/scripts/k3s-handoff")

    for needle in (
        "zpool status -v | stable_zpool_status",
        "zpool get -H guid",
        "zfs list -Hp -t filesystem,volume -o name,type,mountpoint,volsize",
        "inventory_tree /sys/kernel/config/target target-configfs",
        'saveconfig=/etc/rtslib-fb-target/saveconfig.json',
        'sha256sum "$saveconfig"',
        'cat "$saveconfig"',
        "testparm -s",
        "/home/democratic-csi/.ssh/authorized_keys",
        "/etc/ssh/authorized_keys.d/democratic-csi",
        "/etc/sudoers.d/democratic-csi",
        "/etc/exports.d",
        "/etc/iptables/rules.v4",
        "/var/spool/cron",
        "/etc/nfs.conf",
        "/etc/zfs",
        "/etc/zfs/zpool.cache|/etc/zfs/zfs-list.cache",
        "cron.service",
        "iptables.service",
        "manifest-remote",
        "identity-passwd=",
        "listener_state t 3260",
        "listener_state t 445",
        "listener_state u 137",
        "listener_state u 138",
        "manifest.sha256",
        "$host-nas-$stamp",
    ):
        if needle not in adopt:
            raise SystemExit(f"nix/scripts/adopt-host: missing NAS preservation contract {needle!r}")
    filter_match = re.search(
        r"stable_zpool_status\(\) \{\n\s+awk '\n(?P<program>.*?)\n\s+'\n\}",
        adopt,
        re.DOTALL,
    )
    if filter_match is None:
        raise SystemExit("nix/scripts/adopt-host: stable zpool status filter is missing")
    awk_binary = shutil.which("awk")
    if awk_binary is None:
        raise SystemExit("nix/scripts/check-migration.py: awk is required for zpool filter test")
    status_a = """\
  pool: nas
 state: ONLINE
status: pool is healthy
action: no action is required
   see: https://openzfs.github.io/openzfs-docs/msg/ZFS-8000-4J
  scan: scrub in progress since Thu Aug 27 06:00:00 2026
        1.00G / 100G scanned at 100M/s, 512M / 100G issued
        0B repaired, 0.50% done, 00:03:00 to go
remove: device removal paused
checkpoint: checkpoint exists
config:

        NAME  STATE   READ WRITE CKSUM
        nas   ONLINE     0     0     0
errors: No known data errors
"""
    status_b = status_a.replace(
        "1.00G / 100G scanned at 100M/s, 512M / 100G issued\n"
        "        0B repaired, 0.50% done, 00:03:00 to go",
        "80.0G / 100G scanned at 800M/s, 79.0G / 100G issued\n"
        "        0B repaired, 79.0% done, 00:00:10 to go",
    )

    def filtered_zpool_status(text: str) -> str:
        result = subprocess.run(
            [awk_binary, filter_match.group("program")],
            input=text,
            text=True,
            capture_output=True,
        )
        if result.returncode:
            raise SystemExit(
                "nix/scripts/adopt-host: stable zpool status filter failed: "
                f"{result.stderr.strip()}"
            )
        return result.stdout

    filtered_a = filtered_zpool_status(status_a)
    filtered_b = filtered_zpool_status(status_b)
    if filtered_a != filtered_b or "scan:" in filtered_a or "to go" in filtered_a:
        raise SystemExit(
            "nix/scripts/adopt-host: zpool filter retains volatile scrub progress"
        )
    for stable_field in (
        "state: ONLINE",
        "status:",
        "action:",
        "remove:",
        "checkpoint:",
        "READ WRITE CKSUM",
        "errors:",
    ):
        if stable_field not in filtered_a:
            raise SystemExit(
                f"nix/scripts/adopt-host: zpool filter drops stable health field {stable_field!r}"
            )
    error_status = status_a.replace(
        "nas   ONLINE     0     0     0",
        "nas   ONLINE     1     0     0",
    )
    if filtered_zpool_status(error_status) == filtered_a:
        raise SystemExit(
            "nix/scripts/adopt-host: zpool filter hides device error counter changes"
        )
    if re.search(r"\btargetcli\b", adopt):
        raise SystemExit("nix/scripts/adopt-host: NAS baseline may not invoke targetcli")
    if re.search(
        r"(?:>|tee|install|cp|mv|truncate)[^\n]*(?:/etc/rtslib-fb-target/saveconfig\.json|\"\$saveconfig\")",
        adopt,
    ):
        raise SystemExit("nix/scripts/adopt-host: NAS baseline may not write saveconfig.json")
    if adopt.count('"$saveconfig"') != 3:
        raise SystemExit(
            "nix/scripts/adopt-host: saveconfig.json use must remain existence check, SHA-256, and cat only"
        )
    if re.search(
        r"zpool (?:list|get)[^\n]*\b(alloc|allocated|free|size|capacity|fragmentation|expandsize)\b",
        adopt,
    ):
        raise SystemExit("nix/scripts/adopt-host: NAS equality baseline includes volatile pool capacity")
    if re.search(r"zfs list[^\n]*\b(used|available|avail|usedby)\b", adopt):
        raise SystemExit("nix/scripts/adopt-host: NAS equality baseline includes volatile dataset capacity")
    for excluded in (
        "*/action|*/action/*",
        "*/fabric_statistics|*/fabric_statistics/*",
        "*/pr|*/pr/*",
        "*/statistics|*/statistics/*",
        "*/dynamic_sessions",
        "*/control",
        "*/acls/*/info",
    ):
        if excluded not in adopt:
            raise SystemExit(
                f"nix/scripts/adopt-host: configfs capture does not exclude {excluded!r}"
            )
    if "iscsiadm -m session" in adopt:
        raise SystemExit("nix/scripts/adopt-host: NAS equality baseline includes active iSCSI sessions")
    if "mtime=%Y" in adopt:
        raise SystemExit("nix/scripts/adopt-host: NAS equality baseline includes volatile file mtimes")

    for needle in (
        "assert_preservation_plan_safe()",
        "verify_nas_baseline()",
        "storage_impact_json()",
        "verify_storage_recovery()",
        "storage_recovery_required()",
        'deadline=$((SECONDS + 600))',
        'if ! "$root/nix/scripts/k3s-handoff" rearm "$host"; then',
        'timeout --foreground --kill-after=10s "${capture_timeout}s" "$0" storage-impact "$host"',
        "render_receipt()",
        "verify_storage_inventory_integrity()",
        "nasBaseline:$nasBaseline",
        "storageInventory:$storageInventory",
        'assert_preservation_plan_safe "$host" "$host-commit"',
        'preserves an external NAS data plane; use prepare, activate, reboot, reboot-verify, and commit',
        'if test "$MANAGE_FIREWALL_RULES" = true; then',
        "org.democratic-csi.",
        "volumeattachments.storage.k8s.io",
        "/sys/class/iscsi_session/session*/targetname",
        "select(.value.iscsiClient == true)",
        "systemd/system/smbd.service*",
        'sha256sum -c "$name.sha256"',
        "$capturedPvNames",
        "$capturedPvcNames",
        'if test "$MANAGE_FIREWALL_RULES" = true; then test -s "$FIREWALL_RULES"; fi',
    ):
        if needle not in migration:
            raise SystemExit(f"nix/scripts/homelab-host: missing NAS preservation contract {needle!r}")
    for forbidden in (
        "kubectl scale",
        "kubectl patch",
        "rollout restart",
    ):
        if forbidden in migration:
            raise SystemExit(
                f"nix/scripts/homelab-host: preservation workflow contains mutating command {forbidden}"
            )
    storage_match = re.search(
        r"storage_impact_json\(\) \{\n.*?^}",
        migration,
        re.DOTALL | re.MULTILINE,
    )
    if storage_match is None:
        raise SystemExit("nix/scripts/homelab-host: storage impact helper is missing")
    for line in storage_match.group(0).splitlines():
        if "kubectl " in line and not re.search(r"\bkubectl\b.*\bget\b", line):
            raise SystemExit(
                f"nix/scripts/homelab-host: storage inventory uses a non-read-only Kubernetes command: {line.strip()}"
            )
    recovery_match = re.search(
        r"verify_storage_recovery\(\) \{\n.*?^}",
        migration,
        re.DOTALL | re.MULTILINE,
    )
    if recovery_match is None or not re.search(
        r"deadline=\$\(\(SECONDS \+ 600\)\).*?while :; do.*?k3s-handoff.*?rearm.*?"
        r"capture_timeout.*?timeout --foreground --kill-after=10s.*?storage-impact",
        recovery_match.group(0) if recovery_match else "",
        re.DOTALL,
    ):
        raise SystemExit(
            "nix/scripts/homelab-host: storage recovery is not bounded and rearmed inside the polling loop"
        )
    for function_name, function_match in (
        ("storage_impact_json", storage_match),
        ("verify_storage_recovery", recovery_match),
    ):
        if "storage_recovery_required" not in function_match.group(0):
            raise SystemExit(
                f"nix/scripts/homelab-host: {function_name} does not cover iSCSI client recovery"
            )
    lifecycle_match = re.search(
        r"  prepare\|deploy\).*?^  onboard-k3s-node\)",
        migration,
        re.DOTALL | re.MULTILINE,
    )
    if lifecycle_match is None:
        raise SystemExit("nix/scripts/homelab-host: guarded preservation lifecycle is missing")
    if not re.search(
        r"prepare\|deploy\).*?storage_required=\$\(storage_recovery_required.*?"
        r'if \[ "\$storage_required" = true \]; then.*?capture_storage_impact',
        lifecycle_match.group(0),
        re.DOTALL,
    ):
        raise SystemExit(
            "nix/scripts/homelab-host: prepare does not capture storage recovery for iSCSI clients"
        )
    for pattern in (
        r"\bkubectl\b[^\n]*\bapply\b",
        r"\bkubectl\b[^\n]*\bcreate\b",
        r"\bkubectl\b[^\n]*\bdelete\b",
        r"\bkubectl\b[^\n]*\bedit\b",
        r"\bkubectl\b[^\n]*\blabel\b",
        r"\bkubectl\b[^\n]*\bannotate\b",
        r"\bkubectl\b[^\n]*\bpatch\b",
        r"\bkubectl\b[^\n]*\breplace\b",
        r"\bkubectl\b[^\n]*\bscale\b",
        r"\bkubectl\b[^\n]*\btaint\b",
        r"\bkubectl\b[^\n]*\brollout\s+restart\b",
        r"\bhelm\b",
    ):
        if re.search(pattern, lifecycle_match.group(0)):
            raise SystemExit(
                f"nix/scripts/homelab-host: guarded preservation lifecycle mutates Kubernetes resources: {pattern}"
            )
    for script_name, text in (
        ("nix/scripts/homelab-host", migration),
        ("nix/scripts/k3s-handoff", handoff),
    ):
        if 'diff -u "$manifest"' in text or 'diff -u "$dir/manifest.txt"' in text:
            raise SystemExit(f"{script_name}: NAS manifest mismatch may expose secret content")
        for marker in ("baseline-sha256=", "current-sha256="):
            if marker not in text:
                raise SystemExit(f"{script_name}: NAS mismatch omits safe {marker} evidence")

    ordering_contracts = (
        (
            "prepare must verify the NAS baseline before and after its mutation-capable work",
            r"prepare\|deploy\).*?verify_nas_baseline.*?snapshot-packages.*?stage-secrets.*?verify_nas_baseline",
        ),
        (
            "activate must verify preserved storage recovery before recording activation",
            r"  activate\).*?k3s-handoff.*?arm.*?activate_registered_system.*?verify_storage_recovery.*?write_receipt.*?activated",
        ),
        (
            "commit must verify preserved storage recovery before staging acceptance",
            r"  commit\).*?k3s-handoff.*?rearm.*?activate_registered_system.*?verify_storage_recovery.*?render_receipt.*?committed",
        ),
        (
            "commit must verify preserved NAS state before accepting and deleting rollback recovery",
            r"  commit\).*?verify_nas_baseline.*?k3s-handoff.*?accept",
        ),
        (
            "commit must durably stage the terminal receipt before deleting rollback recovery",
            r"  commit\).*?render_receipt.*?k3s-handoff.*?accept.*?mv -f \"\$staged_receipt\" \"\$\(receipt \"\$host\"\)\"",
        ),
        (
            "reboot verification must verify bounded NAS and preserved storage recovery before disarming rollback",
            r"  reboot-verify\).*?require_receipt_phase.*?yes.*?HOMELAB_STORAGE_WAIT=yes.*?verify_nas_baseline.*?yes.*?verify_storage_recovery.*?yes.*?k3s-handoff.*?disarm",
        ),
    )
    for description, pattern in ordering_contracts:
        if not re.search(pattern, migration, re.DOTALL):
            raise SystemExit(f"nix/scripts/homelab-host: {description}")

    apply_match = re.search(
        r"apply_native_runtime\(\) \{\n.*?^}",
        migration,
        re.DOTALL | re.MULTILINE,
    )
    if apply_match is None:
        raise SystemExit("nix/scripts/homelab-host: apply_native_runtime function missing")
    apply_runtime = apply_match.group(0)
    if apply_runtime.count("iptables-restore --noflush --wait") != 1:
        raise SystemExit("nix/scripts/homelab-host: native firewall apply path is ambiguous")
    if not re.search(
        r'if test "\$MANAGE_FIREWALL_RULES" = true; then.*?iptables-restore --noflush --wait'
        r".*?iptables -P INPUT DROP.*?place_jump INPUT",
        apply_runtime,
        re.DOTALL,
    ):
        raise SystemExit(
            "nix/scripts/homelab-host: external-firewall mode can reach managed firewall mutation"
        )
    managed_firewall_match = re.search(
        r'\nif test "\$MANAGE_FIREWALL_RULES" = true; then\n(.*?)\nfi\n'
        r'if test "\$ROLE" = server',
        apply_runtime,
        re.DOTALL,
    )
    if managed_firewall_match is None:
        raise SystemExit("nix/scripts/homelab-host: managed firewall mutation block missing")
    managed_firewall = managed_firewall_match.group(1)
    role_firewall_match = re.search(
        r'if test "\$ROLE" = server \|\| test "\$ROLE" = agent; then.*?'
        r'  if test "\$MANAGE_FIREWALL_RULES" = true; then\n(.*?)\n  fi\nfi',
        apply_runtime,
        re.DOTALL,
    )
    if role_firewall_match is None:
        raise SystemExit("nix/scripts/homelab-host: managed K3s firewall block missing")
    managed_firewall += role_firewall_match.group(1)
    for mutation in (
        "iptables-restore --noflush --wait",
        "iptables -P INPUT DROP",
        "iptables -P FORWARD DROP",
        "iptables -P OUTPUT ACCEPT",
        'iptables --wait -I "$chain"',
        'iptables --wait -D "$chain"',
        "place_jump INPUT HOMELAB_INPUT",
        "place_jump FORWARD HOMELAB_FORWARD",
    ):
        if apply_runtime.count(mutation) != managed_firewall.count(mutation):
            raise SystemExit(
                f"nix/scripts/homelab-host: external-firewall branch can reach {mutation!r}"
            )
    if (
        'if test "$MANAGE_FIREWALL_RULES" = true; then systemctl enable "$FIREWALL_SERVICE"; fi'
        not in apply_runtime
        or 'systemctl restart "$FIREWALL_SERVICE"' in apply_runtime
        or 'systemctl reload "$FIREWALL_SERVICE"' in apply_runtime
    ):
        raise SystemExit(
            "nix/scripts/homelab-host: external-firewall branch can mutate its native loader"
        )

    for needle in (
        "PRESERVE_NAS_STATE",
        "MANAGE_FIREWALL_RULES",
        'if test "$preserve_nas_state" = true; then test "$manage_firewall_rules" = false; fi',
        'if test "$preserve_nas_state" != true; then',
        'if test "$manage_firewall_rules" = true; then',
        'test -z "$install_packages"',
        "verify_nas_manifest()",
        "manifest.sha256",
        "manifest-remote",
        'command -v bash >/dev/null',
        'bash "$dir/manifest-remote"',
        'test -z "$remove_packages"',
    ):
        if needle not in handoff:
            raise SystemExit(f"nix/scripts/k3s-handoff: missing preservation rollback contract {needle!r}")
    archive_match = re.search(
        r'if ! test -e "\$stages/archive-restored"; then\s+'
        r'if test "\$preserve_nas_state" = true; then\s+tar -C / \\\n'
        r'(?P<arguments>.*?)\n\s+-xf "\$dir/etc-state.tar"',
        handoff,
        re.DOTALL,
    )
    if archive_match is None:
        raise SystemExit("nix/scripts/k3s-handoff: preserved archive restore block is missing")
    actual_exclusions = {
        quoted or bare
        for quoted, bare in re.findall(
            r"--exclude=(?:'([^']+)'|([^ \\\n]+))",
            archive_match.group("arguments"),
        )
    }
    expected_exclusions = {
        "etc/zfs",
        "etc/default/zfs",
        "etc/target",
        "etc/rtslib-fb-target",
        "etc/samba",
        "etc/exports",
        "etc/exports.d",
        "etc/nfs.conf",
        "etc/idmapd.conf",
        "etc/default/nfs-common",
        "etc/default/nfs-kernel-server",
        "etc/default/samba",
        "etc/iptables/rules.v4",
        "etc/iptables/iptables.rules",
        "home/democratic-csi/.ssh",
        "etc/ssh/authorized_keys.d/democratic-csi",
        "etc/sudoers.d/democratic-csi",
        "etc/crontab",
        "etc/cron.d",
        "etc/cron.daily",
        "etc/cron.hourly",
        "etc/cron.monthly",
        "etc/cron.weekly",
        "var/spool/cron",
        "etc/systemd/system/zfs*",
        "etc/systemd/system/target.service*",
        "etc/systemd/system/targetclid.service*",
        "etc/systemd/system/rtslib-fb-targetctl.service*",
        "etc/systemd/system/smbd.service*",
        "etc/systemd/system/nmbd.service*",
        "etc/systemd/system/samba.service*",
        "etc/systemd/system/nfs-server.service*",
        "etc/systemd/system/nfs-kernel-server.service*",
        "etc/systemd/system/cron.service*",
        "etc/systemd/system/crond.service*",
        "etc/systemd/system/iptables.service*",
        "etc/systemd/system/netfilter-persistent.service*",
        "etc/systemd/system/*/zfs*",
        "etc/systemd/system/*/target.service",
        "etc/systemd/system/*/targetclid.service",
        "etc/systemd/system/*/rtslib-fb-targetctl.service",
        "etc/systemd/system/*/smbd.service",
        "etc/systemd/system/*/nmbd.service",
        "etc/systemd/system/*/samba.service",
        "etc/systemd/system/*/nfs-server.service",
        "etc/systemd/system/*/nfs-kernel-server.service",
        "etc/systemd/system/*/cron.service",
        "etc/systemd/system/*/crond.service",
        "etc/systemd/system/*/iptables.service",
        "etc/systemd/system/*/netfilter-persistent.service",
        "etc/init.d/zfs*",
        "etc/init.d/target*",
        "etc/init.d/smb*",
        "etc/init.d/nmb*",
        "etc/init.d/nfs*",
        "etc/init.d/cron*",
        "etc/init.d/iptables*",
        "etc/init.d/netfilter-persistent",
        "etc/rc*.d/*zfs*",
        "etc/rc*.d/*target*",
        "etc/rc*.d/*smb*",
        "etc/rc*.d/*nmb*",
        "etc/rc*.d/*nfs*",
        "etc/rc*.d/*cron*",
        "etc/rc*.d/*iptables*",
        "etc/rc*.d/*netfilter-persistent*",
    }
    if actual_exclusions != expected_exclusions:
        missing = sorted(expected_exclusions - actual_exclusions)
        extra = sorted(actual_exclusions - expected_exclusions)
        raise SystemExit(
            "nix/scripts/k3s-handoff: preserved archive exclusions changed; "
            f"missing={missing}, extra={extra}"
        )
    if not re.search(
        r'if test "\$preserve_nas_state" = true; then verify_nas_manifest; fi'
        r'.*?mkdir -p "\$stages".*?systemctl stop homelab-k3s\.service'
        r'.*?if test "\$preserve_nas_state" = true; then verify_nas_manifest; fi'
        r".*?systemctl disable --now homelab-host-rollback\.timer",
        handoff,
        re.DOTALL,
    ):
        raise SystemExit(
            "nix/scripts/k3s-handoff: watchdog rollback does not equality-verify NAS state before and after mutation"
        )

    require(
        "nix/lib/topology.nix",
        "preserveNasState",
    )
    require(
        "nix/modules/linux/base.nix",
        "preserveNasState",
        "democratic-csi",
    )
    require(
        "nix/modules/linux/packages.nix",
        "preserveNasState",
        "targetcli-fb",
    )
    require(
        "nix/modules/linux/firewall.nix",
        "manageRules",
        "preserveNasState",
    )
    require(
        "nix/modules/linux/k3s-host.nix",
        "manageRules",
    )
    require(
        "nix/hosts/rock5bp.nix",
        "homelab.firewall.manageRules = false;",
    )
    require(
        "flake.nix",
        "preserveNasState",
        "manageRules",
    )


def check_preservation_policy_failure() -> None:
    with tempfile.TemporaryDirectory() as directory:
        directory_path = Path(directory)
        fake_bin = directory_path / "bin"
        fake_bin.mkdir()
        event = directory_path / "remote-mutation"
        fake_nix = fake_bin / "nix"
        fake_nix.write_text(
            "#!/bin/sh\n"
            "case \"$*\" in\n"
            "  *topology.nodes.rock5bp.preserveNasState*)\n"
            "    test \"${PRESERVE_EVAL_FAIL:-0}\" != 1 || exit 95\n"
            "    printf '%s\\n' true\n"
            "    ;;\n"
            "  *)\n"
            "    printf 'unexpected nix invocation: %s\\n' \"$*\" >&2\n"
            "    exit 97\n"
            "    ;;\n"
            "esac\n"
        )
        fake_nix.chmod(0o755)
        fake_ssh = fake_bin / "ssh"
        fake_ssh.write_text(
            "#!/bin/sh\n"
            "printf 'remote mutation attempted\\n' >> \"$MUTATION_EVENT\"\n"
            "exit 98\n"
        )
        fake_ssh.chmod(0o755)
        environment = {
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "HOMELAB_REPO_ROOT": str(root),
            "HOMELAB_STATE_DIR": str(directory_path / "state"),
            "MUTATION_EVENT": str(event),
            "PRESERVE_EVAL_FAIL": "1",
        }
        recovery = directory_path / "recovery"
        recovery.mkdir()
        cases = (
            ("nix/scripts/adopt-host", ("manifest", "rock5bp")),
            ("nix/scripts/homelab-host", ("storage-impact", "rock5bp")),
            ("nix/scripts/k3s-handoff", ("snapshot-packages", "rock5bp", str(recovery))),
        )
        for relative, arguments in cases:
            event.unlink(missing_ok=True)
            result = subprocess.run(
                ["bash", str(root / relative), *arguments],
                capture_output=True,
                text=True,
                env=environment,
            )
            if result.returncode == 0 or "preserveNasState could not be evaluated" not in result.stderr:
                raise SystemExit(
                    f"{relative} {' '.join(arguments)}: failed preservation lookup did not fail closed\n"
                    f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
                )
            if event.exists():
                raise SystemExit(
                    f"{relative} {' '.join(arguments)}: remote access was attempted after preservation lookup failed"
                )


def check_storage_inventory_failure_propagation() -> None:
    migration = source("nix/scripts/homelab-host")
    if migration.count('if ! session_nodes=$(') != 1 or migration.count(
        'done <<< "$session_nodes"'
    ) != 1:
        raise SystemExit(
            "nix/scripts/homelab-host: iSCSI node enumeration failures are not propagated"
        )
    with tempfile.TemporaryDirectory() as directory:
        directory_path = Path(directory)
        fake_bin = directory_path / "bin"
        fake_bin.mkdir()
        event = directory_path / "remote"
        fake_nix = fake_bin / "nix"
        fake_nix.write_text(
            "#!/bin/sh\n"
            "case \"$*\" in\n"
            "  *topology.nodes.rock5bp.preserveNasState*) printf 'true\\n' ;;\n"
            "  *topology.nodes) exit 91 ;;\n"
            "  *) printf 'unexpected nix invocation: %s\\n' \"$*\" >&2; exit 92 ;;\n"
            "esac\n"
        )
        fake_nix.chmod(0o755)
        fake_kubectl = fake_bin / "kubectl"
        fake_kubectl.write_text(
            "#!/bin/sh\n"
            "case \"$*\" in\n"
            "  *' get pv -o json'*) printf '{\"items\":[]}\\n' ;;\n"
            "  *' get pvc --all-namespaces -o json'*) printf '{\"items\":[]}\\n' ;;\n"
            "  *' get pods --all-namespaces -o json'*) printf '{\"items\":[]}\\n' ;;\n"
            "  *' get volumeattachments.storage.k8s.io -o json'*) printf '{\"items\":[]}\\n' ;;\n"
            "  *) printf 'unexpected kubectl invocation: %s\\n' \"$*\" >&2; exit 93 ;;\n"
            "esac\n"
        )
        fake_kubectl.chmod(0o755)
        fake_ssh = fake_bin / "ssh"
        fake_ssh.write_text(
            "#!/bin/sh\n"
            "printf 'remote access attempted\\n' >> \"$REMOTE_EVENT\"\n"
            "exit 94\n"
        )
        fake_ssh.chmod(0o755)
        result = subprocess.run(
            [
                "bash",
                str(root / "nix/scripts/homelab-host"),
                "storage-impact",
                "rock5bp",
            ],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "HOMELAB_REPO_ROOT": str(root),
                "HOMELAB_STATE_DIR": str(directory_path / "state"),
                "REMOTE_EVENT": str(event),
            },
        )
        if result.returncode == 0:
            raise SystemExit(
                "nix/scripts/homelab-host: failed topology evaluation produced a partial storage inventory"
            )
        if event.exists():
            raise SystemExit(
                "nix/scripts/homelab-host: storage inventory continued after topology evaluation failed"
            )



def check_storage_capture_readiness_guard() -> None:
    migration = source("nix/scripts/homelab-host")
    capture_match = re.search(
        r"capture_storage_impact\(\) \{\n.*?^}",
        migration,
        re.DOTALL | re.MULTILINE,
    )
    if capture_match is None:
        raise SystemExit("nix/scripts/homelab-host: storage capture helper is missing")
    with tempfile.TemporaryDirectory() as directory:
        directory_path = Path(directory)
        fixture = directory_path / "fixture.json"
        output = directory_path / "storage-consumers.json"
        harness = directory_path / "capture-storage-impact"
        harness.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'storage_impact_json() { cat "$FIXTURE"; }\n'
            f"{capture_match.group(0)}\n"
            'capture_storage_impact rock5bp "$OUTPUT"\n'
        )
        harness.chmod(0o755)
        environment = {
            **os.environ,
            "FIXTURE": str(fixture),
            "OUTPUT": str(output),
        }
        fixture.write_text(
            json.dumps(
                {
                    "pods": [
                        {
                            "phase": "Running",
                            "ready": False,
                        }
                    ]
                }
            )
        )
        result = subprocess.run(
            ["bash", str(harness)],
            capture_output=True,
            text=True,
            env=environment,
        )
        if (
            result.returncode == 0
            or "unready democratic-csi storage consumers" not in result.stderr
            or output.exists()
            or Path(f"{output}.sha256").exists()
        ):
            raise SystemExit(
                "nix/scripts/homelab-host: prepare did not fail closed on an unready storage consumer\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        fixture.write_text(
            json.dumps(
                {
                    "pods": [
                        {
                            "phase": "Running",
                            "ready": True,
                        },
                        {
                            "phase": "Succeeded",
                            "ready": False,
                        },
                    ]
                }
            )
        )
        result = subprocess.run(
            ["bash", str(harness)],
            capture_output=True,
            text=True,
            env=environment,
        )
        checksum = subprocess.run(
            ["sha256sum", "-c", output.name + ".sha256"],
            cwd=directory_path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or checksum.returncode != 0:
            raise SystemExit(
                "nix/scripts/homelab-host: ready storage consumers were rejected or not checksummed\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
                f"checksum:\n{checksum.stdout}{checksum.stderr}"
            )

require(
    "nix/modules/linux/base.nix",
    "10-homelab-lan.network",
    "DNSSEC=yes",
    "DNSOverTLS=yes",
    "MulticastDNS=yes",
    "systemd/timesyncd.conf",
    "NTP=162.159.200.1 162.159.200.123",
    "FallbackNTP=",
    "LLMNR=no",
    "lib.mkIf k8sMember",
    "systemd/zram-generator.conf",
    "zram-size = ram / 2",
    "tmpfiles.d/60-homelab-runtime-tuning.conf",
    "tmpfiles.d/20-homelab-resolv.conf",
    'source = "${pkgs.tzdata}/share/zoneinfo/Asia/Seoul"',
    '"ssh/sshd_config"',
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
    "replaceExisting = true;",
    'root.shell = "/bin/bash";',
    "DNS=1.1.1.1#cloudflare-dns.com",
)
forbid("nix/modules/linux/base.nix", "zramSizeMiB")
forbid(
    "nix/modules/linux/base.nix",
    '"ssh/sshd_config.d/90-homelab-hardening.conf"',
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
    "wg0PeerNames",
    'Endpoint=${topology.nodes.${peer}.lanAddress}',
    "[WireGuardPeer]",
    "PrivateKeyFile=${credentialPath",
    "PresharedKeyFile=${credentialPath",
    "PersistentKeepalive=25",
    "LoadCredentialEncrypted=",
    "/var/lib/homelab-secrets/active",
)
forbid(
    "nix/modules/linux/wireguard.nix",
    "systemd.services.homelab-wireguard",
    "wg syncconf",
    "/run/homelab-wireguard-",
    "PersistentKeepaliveSec=",
)
wireguard_runtime = source("nix/scripts/sync-wireguard-runtime")
if not wireguard_runtime.isascii():
    raise SystemExit(
        "nix/scripts/sync-wireguard-runtime: shell source must remain ASCII-only"
    )
require(
    "nix/scripts/sync-wireguard-runtime",
    "wg syncconf",
    "--check",
    "PrivateKeyFile=",
    "PresharedKeyFile=",
    'cmp -s "$work/expected-peers" "$work/actual-peers"',
    'cmp -s "$work/expected-allowed" "$work/actual-allowed"',
    'cmp -s "$work/expected-keepalive" "$work/actual-keepalive"',
    'awk \'{ print $1 "\\t" $2 }\' "$work/actual-keepalive.raw"',
    'cmp -s "$work/expected-endpoint-peers" "$work/actual-endpoint-peers"',
    'wg show "$interface" preshared-keys',
)
forbid(
    "nix/scripts/sync-wireguard-runtime",
    "$(NF - 1)",
)
require(
    "nix/scripts/homelab-host",
    'sync_wireguard_runtime "$host" "$interface"',
    'verify_wireguard_runtime "$host" "$interface"',
    "sudo -n sh -s -- --check",
)
require(
    "nix/scripts/rollout-peers",
    'sync_wireguard_runtime "$host" wg0',
)
require(
    "nix/scripts/k3s-handoff",
    "$rollback_root/.staging/sync-wireguard-runtime",
    '"$dir/sync-wireguard-runtime" "$interface"',
)
require(
    "nix/modules/darwin/base.nix",
    "peerCount = builtins.length",
    "topology.wg0.peerNodes",
    "-eq ${toString peerCount}",
)
require(
    "nix/scripts/render-macbook-wireguard",
    "$root#topology.wg0.peerNodes",
)
require(
    "nix/scripts/rollout-peers",
    "systemd/network/99-wg0.netdev",
    "systemd/network/99-wg0.network",
    "$root#topology.wg0.nodes.$target.publicKey",
    "networkctl reconfigure wg0",
    "wg show wg0 peers",
)
rollout_peers = source("nix/scripts/rollout-peers")
apply_loops = re.findall(
    r"for host in \$apply_hosts; do\n(.*?)\n    done",
    rollout_peers,
    re.DOTALL,
)
apply_loop = next((body for body in apply_loops if "stage_result=" in body), None)
if apply_loop is None:
    raise SystemExit("nix/scripts/rollout-peers: mutating apply loop missing")
secret_stage = 'stage_result="$($root/nix/scripts/wireguard-secrets stage-secrets "$host")"'
record_mutation = 'printf \'%s\\n\' "$host" >> "$applied"'
install_networkd = 'remote "$host" "sudo -n install -D -m 0644'
restart_networkd = "systemctl restart systemd-networkd.service"
sync_wireguard = 'sync_wireguard_runtime "$host" wg0'
for fragment in (
    secret_stage,
    record_mutation,
    install_networkd,
    restart_networkd,
    sync_wireguard,
):
    if fragment not in apply_loop:
        raise SystemExit(
            f"nix/scripts/rollout-peers: apply loop missing {fragment}"
        )
if not (
    apply_loop.index(secret_stage)
    < apply_loop.index(record_mutation)
    < apply_loop.index(install_networkd)
    < apply_loop.index(restart_networkd)
    < apply_loop.index(sync_wireguard)
):
    raise SystemExit(
        "nix/scripts/rollout-peers: mutation must be recorded before networkd files, restart, and runtime sync"
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
    "etcd-snapshot ls",
    'grep -F -- "$SNAPSHOT-"',
    'test -s "$recovery/etcd-snapshot.txt"',
    "pre-Nix state",
    "iptables-backend=",
    "ntp-synchronized=",
    'printf "etcd=%s\\n" "$etcd"',
    "current_remote_generation",
    "nix_env=$(command -v nix-env || true)",
    'test -n "$nix_env" || nix_env=/nix/var/nix/profiles/default/bin/nix-env',
    'test -x "$nix_env"',
    'generations=$("$nix_env" --profile "$profile" --list-generations)',
    'generation=$(current_remote_generation "$host")',
    "uname -n",
)
adopt = source("nix/scripts/adopt-host")
generic_baseline = adopt.split("generic_baseline() {", 1)[1].split(
    "\nnas_baseline() {", 1
)[0]
if not re.search(
    r"if sudo -n test -d /var/lib/rancher/k3s/server/db; then\s+"
    r'etcd=\$\(sudo -n /usr/local/bin/k3s etcd-snapshot ls',
    generic_baseline,
):
    raise SystemExit(
        "nix/scripts/adopt-host: agent baseline may create K3s server state"
    )
require(
    "nix/scripts/homelab-host",
    "bootstrap-host",
    r"user=\$(id -un)",
    "arch|archarm)",
    'test "$(uname -n)" = "$HOST_NAME"',
    r'trap \"rm -f -- \$tmp\"',
    "secretGeneration",
    "different Git revision",
    "--baseline",
    "restore-host",
    "rollback_armed_host",
    "apply_native_runtime",
    "systemd-tmpfiles --create",
    "iptables-restore --noflush --wait",
    "authorizedkeysfile( \\.ssh/authorized_keys)?",
    'sudo -n grep -Fx "$ADMIN_USER ALL=(ALL) NOPASSWD: ALL" /etc/sudoers.d/homelab-admin',
    "cleanup_legacy_files",
    "verify-legacy-cleanup <host>",
    'verify_legacy_cleanup "${2:?host required}"',
    "! systemctl cat",
    "prepare_native_runtime_handoff",
    "swapoff /dev/zram0",
    "K3s API did not become ready within 180 seconds",
    "Cilium feeder chains did not become ready within 180 seconds",
    "Cilium and HOMELAB firewall ordering did not stabilize within 120 seconds",
    "host verification failed during $stage",
    "place_jump()",
    'iptables --wait -I "$chain" "$position" -j "$target"',
    "systemctl cat homelab-k3s.service",
    "/var/lib/homelab-secrets/active/k3s-token.cred",
    "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin HOST_NAME=",
    'iptables --wait -D "$chain" "$index"',
    'systemctl enable iscsid.service "$ISCSI_LOGIN_SERVICE"',
    'systemctl start iscsid.service "$ISCSI_LOGIN_SERVICE"',
    "reconcile_distro_packages",
    "--version 1.20.0",
    "etc-state.tar",
    "policy-rc.d",
    "FIREWALL_SERVICE",
    "locale -a",
    "LOCALTIME_SOURCE",
    'test "$actual" = "$LOCALTIME_SOURCE"',
    'grep -qx "Asia/Seoul" /etc/timezone',
    "resolvedDnsOverTls",
    "RESOLVED_DNS_OVER_TLS=%q",
    'DNSOverTLS=$RESOLVED_DNS_OVER_TLS',
    "verify_legacy_cleanup",
    '"(nf_tables)"',
    "reconcile)",
    "lifecycle",
    "committed_flake",
    "remote_system_manager",
    "current_remote_generation",
    "/nix/var/nix/profiles/default/bin/nix-env",
    "nix_env=/nix/var/nix/profiles/default/bin/nix-env",
    'test -x "$nix_env"',
    'generations=$("$nix_env" --profile "$profile" --list-generations)',
    "activate_registered_system",
    "storePath",
    "system-manager generation changed after prepare",
    "systemd-timesyncd.service",
    "NTPSynchronized",
    "age curl git sudo xz",
    "age ca-certificates curl git sudo xz-utils",
    "command -v git",
)
forbid("nix/scripts/homelab-host", "sudo -n nix-env")
forbid("nix/scripts/adopt-host", "sudo -n nix-env")
forbid("nix/scripts/homelab-host", "--list-generations 2>/dev/null")
forbid("nix/scripts/adopt-host", "--list-generations 2>/dev/null")
forbid("nix/scripts/homelab-host", "command -v nix-env")
forbid(
    "nix/scripts/homelab-host",
    '"$nix_env" --profile "$profile" --list-generations |',
)
forbid(
    "nix/scripts/adopt-host",
    '"$nix_env" --profile "$profile" --list-generations |',
)
forbid(
    "nix/scripts/homelab-host",
    "trap 'rm -f",
    "localectl set-locale",
    "timedatectl set-timezone",
    "timedatectl show -p Timezone",
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
    "nix/scripts/homelab-host",
    'for unit in k3s.service k3s-agent.service homelab-k3s.service; do',
    'systemctl is-active "$unit"',
    'systemctl is-enabled "$unit"',
)
forbid(
    "nix/scripts/homelab-host",
    "systemctl is-active k3s.service k3s-agent.service homelab-k3s.service",
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
require(
    "nix/scripts/homelab-host",
    "systemctl is-active iscsid.service",
    'systemctl is-enabled "$ISCSI_LOGIN_SERVICE"',
    "find /etc/iscsi/nodes -mindepth 1 -print -quit",
    'systemctl is-active "$ISCSI_LOGIN_SERVICE"',
)
forbid(
    "nix/scripts/homelab-host",
    "systemctl is-active iscsid.service open-iscsi.service",
)
forbid(
    "nix/scripts/k3s-handoff",
    'systemctl is-active systemd-networkd.service systemd-resolved.service systemd-timesyncd.service "$ssh_service"',
)
host_migration = source("nix/scripts/homelab-host")
for description, pattern in (
    (
        "runtime firewall capture must assert nft before iptables-save",
        r"capture_runtime_firewall\(\).*?assert_iptables_nft_backend.*?iptables-save",
    ),
    (
        "prepare must reconcile completed watchdog rollback before a new preflight",
        r"  prepare\|deploy\).*?sync_completed_rollback.*?k3s-handoff.*?preflight",
    ),
    (
        "reconcile must reconcile completed watchdog rollback before host mutation",
        r"  reconcile\).*?sync_completed_rollback.*?host_field.*?lifecycle",
    ),
    (
        "prepare must assert nft before secret staging",
        r"prepare\|deploy\).*?reconcile_distro_packages.*?assert_iptables_nft_backend.*?stage_result=",
    ),
    (
        "prepare must snapshot package state before reconciliation",
        r"prepare\|deploy\).*?adopt-host.*?snapshot-packages.*?reconcile_distro_packages",
    ),
    (
        "reconcile must snapshot package state before reconciliation",
        r"  reconcile\).*?capture_managed_recovery.*?snapshot-packages.*?reconcile_distro_packages",
    ),
    (
        "reconcile must read the current generation through the fixed Nix profile path",
        r"  reconcile\).*?previous=\$\(current_remote_generation \"\$host\"\)",
    ),
    (
        "prepare must read the current generation through the fixed Nix profile path",
        r"prepare\|deploy\).*?previous=\$\(current_remote_generation \"\$host\"\)",
    ),
    (
        "remote generation lookup must pin nix-env and preserve list-generations failures",
        r"current_remote_generation\(\).*?nix_env=/nix/var/nix/profiles/default/bin/nix-env"
        r".*?test -x \"\$nix_env\""
        r".*?generations=\$\(\"\$nix_env\" --profile \"\$profile\" --list-generations\)"
        r".*?printf.*?\$generations.*?awk",
    ),
    (
        "manual rollback must pin and validate nix-env before switching generations",
        r"  rollback\).*?nix_env=/nix/var/nix/profiles/default/bin/nix-env"
        r".*?test -x.*?\\\$nix_env.*?--switch-generation",
    ),
    (
        "reconcile must quiesce legacy tuning after arming and before activation",
        r"  reconcile\).*?k3s-handoff.*?arm.*?prepare_native_runtime_handoff.*?activate_registered_system",
    ),
    (
        "activate must quiesce legacy tuning after arming and before activation",
        r"  activate\).*?k3s-handoff.*?arm.*?prepare_native_runtime_handoff.*?activate_registered_system",
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
        "phase guards must reconcile completed watchdog rollback before drift checks",
        r"require_receipt_phase\(\).*?sync_completed_rollback.*?actual=.*?active secret generation changed",
    ),
    (
        "guarded reboot must synchronize rollback, rearm with failure synchronization, capture boot ID, and record rebooting before reboot",
        r"reboot_host\(\).*?sync_completed_rollback"
        r".*?activated\|rebooting\)"
        r".*?k3s-handoff.*?rearm"
        r".*?sync_completed_rollback.*?return 1"
        r".*?require_receipt_phase.*?\$phase"
        r".*?activated\)"
        r".*?boot_id=.*?kernel/random/boot_id"
        r".*?write_receipt.*?rebooting.*?boot_id"
        r".*?systemctl --no-block reboot",
    ),
    (
        "reboot retry must synchronize rollback and rearm before rejecting an already rebooted host",
        r"reboot_host\(\).*?sync_completed_rollback"
        r".*?activated\|rebooting\)"
        r".*?k3s-handoff.*?rearm"
        r".*?require_receipt_phase.*?\$phase"
        r".*?rebooting\)"
        r".*?active_boot_id=.*?kernel/random/boot_id"
        r".*?already rebooted",
    ),
    (
        "commit must rearm persistent rollback before activating the destructive generation",
        r"  commit\).*?committed_store_path=\$\(register_system.*?k3s-handoff.*?rearm"
        r".*?activate_registered_system",
    ),
    (
        "reboot verification must synchronize rollback, gate locally, and rearm with failure synchronization before remote checks",
        r"  reboot-verify\).*?sync_completed_rollback"
        r".*?receipt_file=.*?phase=.*?test.*?\$phase.*?rebooting"
        r".*?k3s-handoff.*?rearm"
        r".*?sync_completed_rollback.*?exit 1"
        r".*?require_receipt_phase.*?rebooting"
        r".*?assert_host_rebooted"
        r".*?timeout --foreground --kill-after=30s 12m.*?verify-host-while-armed"
        r".*?k3s-handoff.*?disarm",
    ),
    (
        "armed verification must rearm before ordinary verification",
        r"  verify-host-while-armed\).*?k3s-handoff.*?rearm"
        r".*?exec.*?verify-host",
    ),
    (
        "reconcile verification and acceptance must each renew the armed window",
        r"  reconcile\).*?k3s-handoff.*?arm"
        r".*?verify-host-while-armed"
        r".*?k3s-handoff.*?accept",
    ),
    (
        "activation verification must renew the armed window",
        r"  activate\).*?k3s-handoff.*?arm"
        r".*?verify-host-while-armed"
        r".*?k3s-handoff.*?rearm",
    ),
    (
        "commit verification and acceptance must each renew the armed window",
        r"  commit\).*?k3s-handoff.*?rearm"
        r".*?verify-host-while-armed"
        r".*?reconcile_distro_packages"
        r".*?verify-host-while-armed"
        r".*?k3s-handoff.*?accept",
    ),
    (
        "firewall jump replacement must insert the new path before deleting duplicates",
        r"place_jump\(\).*?iptables --wait -I \"\$chain\" \"\$position\" -j \"\$target\""
        r".*?for index in .*?iptables --wait -D \"\$chain\" \"\$index\"",
    ),
    (
        "native runtime must preserve an already-active generated zram swap",
        r"apply_native_runtime\(\).*?if test \"\$ZRAM\" = true; then"
        r"\s+systemctl start dev-zram0\.swap"
        r"\s+else"
        r"\s+systemctl stop dev-zram0\.swap systemd-zram-setup@zram0\.service",
    ),
    (
        "activation must synchronize the system clock before restarting K3s",
        r"apply_native_runtime\(\).*?systemctl restart systemd-timesyncd\.service"
        r".*?NTPSynchronized.*?systemctl restart homelab-k3s\.service",
    ),
    (
        "native handoff must defer firewall reconciliation during system-manager activation",
        r"prepare_native_runtime_handoff\(\).*?install -m 0600 /dev/null "
        r"/run/homelab-k3s-firewall-reconcile\.defer",
    ),
    (
        "system-manager activation must clear the firewall deferral before runtime convergence",
        r"activate_registered_system\(\).*?system-manager/bin/activate"
        r".*?rm -f /run/homelab-k3s-firewall-reconcile\.defer",
    ),
):
    if not re.search(pattern, host_migration, re.DOTALL):
        raise SystemExit(f"nix/scripts/homelab-host: {description}")
adopt_host = source("nix/scripts/adopt-host")
for description, pattern in (
    (
        "baseline generation lookup must validate nix-env and preserve list failures",
        r"current_remote_generation\(\).*?nix_env=\$\(command -v nix-env \|\| true\)"
        r".*?test -n \"\$nix_env\" \|\| nix_env=/nix/var/nix/profiles/default/bin/nix-env"
        r".*?test -x \"\$nix_env\""
        r".*?generations=\$\(\"\$nix_env\" --profile \"\$profile\" --list-generations\)"
        r".*?printf.*?\$generations.*?awk",
    ),
    (
        "baseline capture must fail before recording when generation lookup fails",
        r"baseline\(\).*?generation=\$\(current_remote_generation \"\$host\"\)"
        r".*?system-manager-generation=%s",
    ),
):
    if not re.search(pattern, adopt_host, re.DOTALL):
        raise SystemExit(f"nix/scripts/adopt-host: {description}")
handoff = source("nix/scripts/k3s-handoff")
for needle in (
    "state <host>",
    "cleanup-restored <host>",
    "rollback already completed; refusing to rearm",
    "rollback already started; refusing to rearm",
    "assert_rearmable",
):
    if needle not in handoff:
        raise SystemExit(f"nix/scripts/k3s-handoff: missing reboot race contract {needle!r}")
if handoff.count("assert_rearmable") != 3:
    raise SystemExit("nix/scripts/k3s-handoff: rearm must guard before and after timer restart")
for description, pattern in (
    (
        "accept must rearm before validating and deleting armed recovery",
        r'  accept\).*?"\$BASH" "\$0" rearm.*?remote'
        r".*?test ! -f .*?/restored"
        r".*?test ! -d .*?/stages"
        r".*?rollback_unit\.timer.*?active"
        r".*?disable --now",
    ),
    (
        "completed rollback cleanup must require a restored marker without rearming",
        r"  cleanup-restored\).*?remote"
        r".*?test -f .*?/restored"
        r".*?disable --now",
    ),
):
    if not re.search(pattern, handoff, re.DOTALL):
        raise SystemExit(f"nix/scripts/k3s-handoff: {description}")
cleanup_block = host_migration.split("cleanup_legacy_files()", 1)[1].split(
    "verify_legacy_cleanup()", 1
)[0]
if "/usr/local/bin/k3s" in cleanup_block:
    raise SystemExit("nix/scripts/homelab-host: commit cleanup must retain the Rancher-managed K3s binary")
if 'rm -f "/etc/systemd/system/$unit"' not in cleanup_block:
    raise SystemExit("nix/scripts/homelab-host: commit cleanup must remove direct legacy unit paths")
if 'rm -rf "/etc/systemd/system/$unit.d"' not in cleanup_block:
    raise SystemExit("nix/scripts/homelab-host: commit cleanup must remove legacy systemd drop-ins")
if 'rm -f -- "$link"' not in cleanup_block:
    raise SystemExit("nix/scripts/homelab-host: commit cleanup must remove legacy enablement links")
verify_cleanup_block = host_migration.split("verify_legacy_cleanup()", 1)[1].split(
    "rollback_state()", 1
)[0]
if 'test ! -e "$1"' not in verify_cleanup_block or 'test ! -L "$1"' not in verify_cleanup_block:
    raise SystemExit("nix/scripts/homelab-host: legacy path verifier must reject dangling symlinks")
for path in (
    "/etc/systemd/system/$unit",
    "/etc/systemd/system/$unit.env",
    "/etc/systemd/system/$unit.d",
):
    if f'assert_path_absent "{path}"' not in verify_cleanup_block:
        raise SystemExit(f"nix/scripts/homelab-host: legacy path removal is not verified: {path}")
for pattern in (
    '/etc/systemd/system/*.wants/"$unit"',
    '/etc/systemd/system/*.requires/"$unit"',
):
    if pattern not in cleanup_block:
        raise SystemExit(f"nix/scripts/homelab-host: legacy enablement cleanup is missing: {pattern}")
    if pattern not in verify_cleanup_block:
        raise SystemExit(f"nix/scripts/homelab-host: legacy enablement verification is missing: {pattern}")
if 'assert_path_absent "$link"' not in verify_cleanup_block:
    raise SystemExit("nix/scripts/homelab-host: legacy enablement link removal is not verified")
for needle in (
    'role=$(nix_eval --json "$root#topology.nodes.$host.k3sRole") || return 1',
    '\'"server"\'|\'"agent"\') require_k3s_binary=true',
    'null) ;;',
    'REQUIRE_K3S_BINARY=$require_k3s_binary',
):
    if needle not in verify_cleanup_block:
        raise SystemExit(
            "nix/scripts/homelab-host: K3s cleanup role mapping is incomplete: "
            f"{needle}"
        )
if (
    'if test "$REQUIRE_K3S_BINARY" = true; then\n'
    "      test -x /usr/local/bin/k3s\n"
    "    fi"
    not in verify_cleanup_block
):
    raise SystemExit(
        "nix/scripts/homelab-host: K3s install layout retention must be role-aware"
    )
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
    'Type = "exec";',
    "homelab-k3s-firewall-reconcile",
    "/run/homelab-k3s-firewall-reconcile.defer",
    "if manageRules then",
    "Cilium and HOMELAB firewall ordering did not stabilize after K3s start",
    'ExecStartPost = "-${firewallReconcile}";',
    'Restart = "always";',
)
require(
    "nix/scripts/k3s-handoff",
    "rm -f /run/homelab-k3s-firewall-reconcile.defer",
)
forbid("nix/modules/linux/k3s-host.nix", '${firewallReconcile} &')
forbid("nix/modules/linux/k3s-host.nix", "Externally managed HOMELAB firewall ordering")
forbid(
    "nix/modules/linux/k3s-host.nix",
    "k3sPackage",
    "../../k3s-package.nix",
)
forbid("nix/modules/linux/k3s-host.nix", "homelab-k3s-legacy-cleanup =")
forbid("nix/modules/linux/k3s-host.nix", 'Type = if server then "notify" else "exec";')
forbid(
    "nix/scripts/homelab-host",
    "while iptables -C INPUT -j HOMELAB_INPUT 2>/dev/null; do iptables -D INPUT -j HOMELAB_INPUT; done",
    "while iptables -C FORWARD -j HOMELAB_FORWARD 2>/dev/null; do iptables -D FORWARD -j HOMELAB_FORWARD; done",
    "sudo -n test -s /run/credentials/homelab-k3s.service/k3s-token",
)
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
    "/usr/bin/pacman --noconfirm --needed -S $install_packages",
    "/usr/bin/apt-get -o Dpkg::Options::=--force-confold install -y --no-install-recommends $install_packages",
    "/usr/bin/apt-get purge -y $remove_packages",
    "distro-packages-remove.txt",
    "snapshot-packages <host> <recovery-directory>",
    "systemctl mask --runtime dev-zram0.swap systemd-zram-setup@zram0.service",
    'if ip link show "$interface" >/dev/null 2>&1; then',
    "networkctl reconfigure",
    "systemd-timesyncd.service",
    "NTPSynchronized",
)
require(
    "nix/scripts/k3s-handoff",
    'export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"',
    "$stages/secrets-restored",
    "$stages/system-manager-restored",
    "$stages/archive-restored",
    "$stages/firewall-restored",
    "rollback failed during system-manager deactivation",
    "rollback failed while restoring the host archive",
    "rollback failed while restoring the runtime firewall",
    "> /etc/systemd/system/$rollback_unit.service",
    "--- rollback.log ---",
    "journalctl -u $rollback_unit.service",
)
forbid(
    "nix/scripts/k3s-handoff",
    "/run/homelab-secrets",
    "/run/homelab-k3s-handoff-rollback",
    "systemd-run --quiet",
    "localectl set-locale",
    "timedatectl set-timezone",
)
forbid("nix/scripts/k3s-handoff", "tar --overwrite")
handoff = source("nix/scripts/k3s-handoff")
rearm_block = handoff.split("  rearm)", 1)[1].split("  disarm)", 1)[0]
if not re.search(
    r"assert_rearmable\(\).*?current/restored"
    r".*?current/stages"
    r".*?service_state.*?inactive\|failed"
    r".*?assert_rearmable"
    r".*?systemctl restart \$rollback_unit\.timer"
    r".*?assert_rearmable",
    rearm_block,
    re.DOTALL,
):
    raise SystemExit(
        "nix/scripts/k3s-handoff: rearm must reject rollback before and after timer restart"
    )
if not re.search(
    r'for unit in systemd-networkd\.service systemd-resolved\.service '
    r'systemd-timesyncd\.service "\$ssh_service"; do'
    r'.*?systemctl is-active "\$unit"'
    r".*?systemctl disable --now homelab-host-rollback\.timer",
    handoff,
    re.DOTALL,
):
    raise SystemExit("nix/scripts/k3s-handoff: rollback timer must remain armed until every restored service is active")
if not re.search(
    r"systemctl restart systemd-timesyncd\.service.*?NTPSynchronized"
    r".*?install_packages=\$\(tr '\\n' ' ' < \"\$dir/distro-packages\.txt\"\)",
    handoff,
    re.DOTALL,
):
    raise SystemExit("nix/scripts/k3s-handoff: rollback must synchronize time before package restore")
if not re.search(
    r"systemctl enable --now \"\$legacy_unit\""
    r".*?iptables-restore --test --wait"
    r".*?iptables-restore --wait < \"\$dir/firewall-runtime\.rules\""
    r".*?crictl.*?stop --timeout 10 \"\$previous_cilium_id\""
    r".*?/usr/bin/curl -fsS --max-time 2 http://127\.0\.0\.1:9879/healthz"
    r".*?package_restore_blocked=false",
    handoff,
    re.DOTALL,
):
    raise SystemExit(
        "nix/scripts/k3s-handoff: rollback must start K3s for dependencies, restore the snapshot, then restart and verify cilium-agent"
    )
restore_block = handoff.split("  restore)", 1)[1].split("  status)", 1)[0]
if "systemctl disable --now $rollback_unit.timer" in restore_block:
    raise SystemExit("nix/scripts/k3s-handoff: explicit restore must leave retry control to the rollback script")
if not re.search(
    r"  restore\).*?if ! systemctl cat \$rollback_unit\.service"
    r".*?> /etc/systemd/system/\$rollback_unit\.service"
    r".*?systemctl start \$rollback_unit\.service"
    r".*?test -f \$rollback_root/current/restored",
    handoff,
    re.DOTALL,
):
    raise SystemExit(
        "nix/scripts/k3s-handoff: explicit restore must recreate and start a persistent recovery service"
    )
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
    "darwinNativeSsh",
    'exec /usr/bin/ssh "$@"',
    "pkgs.lib.optionals pkgs.stdenv.isDarwin [ darwinNativeSsh ]",
    "bootstrap-host",
)
package_apps = source("nix/packages.nix")
runtime_input_expression = package_apps.split("runtimeInputs =", 1)[1].split("]);", 1)[0]
if runtime_input_expression.index("darwinNativeSsh") > runtime_input_expression.index("openssh"):
    raise SystemExit("nix/packages.nix: Darwin native ssh must precede packaged OpenSSH")
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
forbid("argocd/appsets/k3s-upgrade.yaml", "- cluster: prod")
forbid("argocd/appprojects/system-upgrade.yaml", "name: prod")
for relative in (
    "charts/cluster-secrets/templates/cluster-secret-store.yaml",
    "charts/cluster-secrets/values.yaml",
):
    forbid(relative, "oracle", "vaultOCID", "tenancyOCID", "userOCID")
if (root / "values/adguard-home.yaml").exists():
    raise SystemExit("values/adguard-home.yaml: retired Oracle-pinned values remain")
chart_text = source("charts/cluster-secrets/Chart.yaml")
chart_version_match = re.search(r"^version:\s*(\S+)\s*$", chart_text, re.MULTILINE)
if chart_version_match is None:
    raise SystemExit("charts/cluster-secrets/Chart.yaml: chart version missing")
chart_version = chart_version_match.group(1)
cluster_secrets_appset = source("argocd/appsets/external-secrets.yaml")
if not re.search(
    rf"chart:\s*cluster-secrets.*?targetRevision:\s*{re.escape(chart_version)}(?:\s|$)",
    cluster_secrets_appset,
    re.DOTALL,
):
    raise SystemExit("cluster-secrets chart version and ApplicationSet targetRevision differ")
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
check_receipt_round_trip()
check_completed_rollback_receipt_sync()
check_record_rolled_back_order()
check_guarded_reboot()
check_reboot_verify_phase_gate()
check_reboot_boot_id_proof()
check_restore_host_guard()
check_rollback_state_classification()
check_rearm_guards()
check_accept_rearms_before_cleanup()
check_armed_verify_entrypoint()
check_rollback_restore_failure()
check_rollback_stage_resume()
check_nas_manifest_runtime_index_normalization()
check_preserved_rollback_manifest_guard()
check_authorized_keys_verification()
check_ssh_strict_modes_guard()
check_wireguard_handshake_probe()
check_register_system_failure()
check_time_sync_waits()
check_new_node_rollback_managed_k3s_state()
check_new_node_rollback_cleanup()
check_wireguard_rollback_failure_continuation()
check_firewall_restore_waits()
check_cilium_restart_waits()
check_onboard_k3s_install_guard()
check_iscsi_service_verification()
check_rollback_restored_services()
check_legacy_cleanup_path_verification()
check_ansible_cutover_partition()
check_static_nix_hosts_render()
check_static_nix_hosts_expression()
check_nas_preservation_contracts()
check_preservation_policy_failure()
check_storage_inventory_failure_propagation()
check_storage_capture_readiness_guard()
check_shell_syntax()
print("migration-contracts: ok")
