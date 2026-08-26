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
    migrated_backbone = {"n2p1", "n2p2", "rpi4"}
    for host in sorted(migrated_backbone):
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
        inventory_hostname="rpi4",
        inventory_hostname_short="rpi4",
        hosts_ipv4_address="192.168.219.7",
        ansible_lo={},
        hosts_ipv6=False,
        ansible_play_batch=["rpi4"],
        hostvars={"rpi4": {"ansible_interfaces": []}},
        hosts_excludes_interfaces=[],
        hosts_all_private=True,
        hosts_all_public=False,
        hosts_dns_hostname=[
            {"address": "192.168.219.3", "hostname": "n2p1"},
            {"address": "192.168.219.4", "hostname": "n2p2"},
        ],
    )
    for expected in ("192.168.219.3 n2p1", "192.168.219.4 n2p2"):
        if rendered.splitlines().count(expected) != 1:
            raise SystemExit(
                "cluster-setup/etc-hosts.yaml: static Nix-managed host render "
                f"differs for {expected!r}"
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
        for host in ("n2p1", "n2p2")
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
        r"(write_receipt\(\) \{\n.*?^\})",
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
write_receipt test-host prepared "" legacy recovery secret store
jq -e '.previousGeneration == "" and .bootId == ""' "$STATE/receipt.json" >/dev/null
write_receipt test-host rebooting "" legacy recovery secret store boot-1
jq -e '.phase == "rebooting" and .bootId == "boot-1"' "$STATE/receipt.json" >/dev/null
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
        r"(write_receipt\(\) \{\n.*?^\})",
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
{write_match.group(1)}
{sync_match.group(1)}
seed() {{
  write_receipt test-host activated "" k3s.service recovery secret store
}}
seed
ROLLBACK_STATUS=restored
export ROLLBACK_STATUS
sync_completed_rollback test-host
test "$(jq -r .phase "$(receipt test-host)")" = rolled-back
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
write_receipt test-host prepared "" k3s.service recovery secret store
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
        r"(write_receipt\(\) \{\n.*?^\})",
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
{write_match.group(1)}
{record_match.group(1)}
ACCEPT_FAIL=1
export ACCEPT_FAIL
if record_rolled_back test-host "" k3s.service recovery secret; then
  echo "completed rollback cleanup failure was ignored" >&2
  exit 1
fi
test "$(jq -r .phase "$TEST_RECEIPT")" = rolled-back
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
printf '%s\\n' sync rearm sync guard boot-id receipt:rebooting reboot > "$EXPECTED"
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
printf '%s\\n' sync rearm sync > "$EXPECTED"
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
printf '%s\\n' sync rearm sync > "$EXPECTED"
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
printf '%s\\n' sync > "$EXPECTED"
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
printf '%s\\n' sync rearm sync guard > "$EXPECTED"
cmp "$EXPECTED" "$EVENTS"
test "$(jq -r .phase "$RECEIPT")" = activated
unset FAIL_GUARD

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
printf '%s\\n' sync rearm sync guard boot-id reboot > "$EXPECTED"
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
printf '%s\\n' sync rearm sync guard boot-id > "$EXPECTED"
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
printf '%s\\n' sync rearm sync guard boot-id > "$EXPECTED"
cmp "$EXPECTED" "$EVENTS"
unset CURRENT_BOOT_ID

seed activated
guard_count=0
: > "$EVENTS"
REBOOT_RC=255
export REBOOT_RC
reboot_host test-host
printf '%s\\n' sync rearm sync guard boot-id receipt:rebooting reboot > "$EXPECTED"
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
            != "sync\nrearm\nsync\nguard\nboot\nverify\ndisarm\nreceipt:reboot-verified\n"
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
        (mock_bin / "nix").write_text("#!/bin/sh\nprintf 'test-target\\n'\n")
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
            != "rearm:test-host\nverify:verify-host test-host --baseline baseline\n"
        ):
            raise SystemExit(
                "nix/scripts/homelab-host: armed verification did not rearm before checks\n"
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
        if result.returncode == 0 or events.read_text() != "rearm:test-host\n":
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
            "\n\niptables.service\nsshd.service\neth0\n\nagent\napt\n"
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
    start = "if grep -q 'CILIUM_' \"$dir/firewall-runtime.rules\"; then"
    end = '\n  touch "$stages/firewall-restored"'
    if start not in handoff or end not in handoff:
        raise SystemExit("nix/scripts/k3s-handoff: cilium-agent restart wait missing")
    block = start + handoff.split(start, 1)[1].split(end, 1)[0]
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
            input=f'set -eu\ndir="$DIR"\n{block}\n',
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
            input=f'set -eu\ndir="$DIR"\n{block}\n',
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

def check_provision_active_service_guard() -> None:
    provision = source("nix/scripts/provision-host")
    match = re.search(
        r"(for unit in k3s\.service k3s-agent\.service homelab-k3s\.service; do.*?\ndone)\ncurl",
        provision,
        re.DOTALL,
    )
    if match is None:
        raise SystemExit("nix/scripts/provision-host: active K3s service guard missing")
    with tempfile.TemporaryDirectory() as directory:
        systemctl = Path(directory) / "systemctl"
        systemctl.write_text(
            "#!/bin/sh\n"
            "test \"$1\" = is-active || exit 2\n"
            "shift\n"
            "test \"$1\" = --quiet || exit 2\n"
            "shift\n"
            "test \"$1\" = k3s-agent.service\n"
        )
        systemctl.chmod(0o755)
        result = subprocess.run(
            ["sh"],
            input=f"set -eu\n{match.group(1)}\n",
            text=True,
            capture_output=True,
            env={**os.environ, "PATH": f"{directory}:{os.environ['PATH']}"},
        )
        if result.returncode == 0 or "k3s-agent.service is already active" not in result.stderr:
            raise SystemExit(
                "nix/scripts/provision-host: middle active K3s service was not rejected"
            )

def check_iscsi_service_verification() -> None:
    migration = source("nix/scripts/homelab-host")
    match = re.search(
        r'(if test "\$ISCSI_CLIENT" = true; then\n.*?^fi)',
        migration,
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
            'case "$1:$2" in\n'
            '  is-active:iscsid.service) test "$ISCSID_ACTIVE" = yes ;;\n'
            '  is-enabled:open-iscsi.service) test "$OPEN_ISCSI_ENABLED" = yes ;;\n'
            '  is-active:open-iscsi.service) test "$OPEN_ISCSI_ACTIVE" = yes ;;\n'
            "  *) exit 2 ;;\n"
            "esac\n"
        )
        systemctl.chmod(0o755)
        environment = {
            **os.environ,
            "PATH": f"{mock_bin}:{os.environ['PATH']}",
            "TEST_NODES": str(nodes),
            "EVENTS": str(events),
        }

        def run(*, has_nodes: bool, iscsid: str, enabled: str, active: str) -> subprocess.CompletedProcess[str]:
            shutil.rmtree(nodes)
            nodes.mkdir()
            if has_nodes:
                (nodes / "target").write_text("fixture\n")
            events.unlink(missing_ok=True)
            return subprocess.run(
                ["sh"],
                input=f"set -eu\nISCSI_CLIENT=true\n{block}\n",
                text=True,
                capture_output=True,
                env={
                    **environment,
                    "ISCSID_ACTIVE": iscsid,
                    "OPEN_ISCSI_ENABLED": enabled,
                    "OPEN_ISCSI_ACTIVE": active,
                },
            )

        result = run(has_nodes=False, iscsid="yes", enabled="yes", active="no")
        if result.returncode != 0:
            raise SystemExit("nix/scripts/homelab-host: target-free iSCSI client was rejected")
        if "is-active open-iscsi.service" in events.read_text():
            raise SystemExit("nix/scripts/homelab-host: target-free open-iscsi was required active")
        if run(has_nodes=True, iscsid="yes", enabled="yes", active="no").returncode == 0:
            raise SystemExit("nix/scripts/homelab-host: configured open-iscsi target may be inactive")
        if run(has_nodes=True, iscsid="yes", enabled="yes", active="yes").returncode != 0:
            raise SystemExit("nix/scripts/homelab-host: active configured iSCSI client was rejected")
        if run(has_nodes=False, iscsid="no", enabled="yes", active="no").returncode == 0:
            raise SystemExit("nix/scripts/homelab-host: inactive iscsid was accepted")
        if run(has_nodes=False, iscsid="yes", enabled="no", active="no").returncode == 0:
            raise SystemExit("nix/scripts/homelab-host: disabled open-iscsi was accepted")


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
        r'(    assert_path_absent\(\) \{\n'
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
    verify_block = verify_match.group(1).replace(
        "/etc/systemd/system", "${TEST_SYSTEMD}"
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
        environment = {
            **os.environ,
            "PATH": f"{mock_bin}:{os.environ['PATH']}",
            "TEST_SYSTEMD": str(systemd),
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
    "reconcile_distro_packages",
    "--version 1.20.0",
    "etc-state.tar",
    "policy-rc.d",
    "FIREWALL_SERVICE",
    "locale -a",
    "LOCALTIME_SOURCE",
    'test "$(readlink /etc/localtime)" = "$LOCALTIME_SOURCE"',
    'grep -qx "Asia/Seoul" /etc/timezone',
    "DNSSEC=yes",
    "DNSOverTLS=yes",
    "verify_legacy_cleanup",
    '"(nf_tables)"',
    "reconcile)",
    "lifecycle",
    "committed_flake",
    "remote_system_manager",
    "current_remote_generation",
    "/nix/var/nix/profiles/default/bin/nix-env",
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
    "nix/scripts/provision-host",
    'for unit in k3s.service k3s-agent.service homelab-k3s.service; do',
    'systemctl is-active --quiet "$unit"',
)
forbid(
    "nix/scripts/provision-host",
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
    "systemctl is-enabled open-iscsi.service",
    "find /etc/iscsi/nodes -mindepth 1 -print -quit",
    "systemctl is-active open-iscsi.service",
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
):
    if not re.search(pattern, host_migration, re.DOTALL):
        raise SystemExit(f"nix/scripts/homelab-host: {description}")
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
    'Type = "exec";',
    "homelab-k3s-firewall-reconcile",
    "Cilium and HOMELAB firewall ordering did not stabilize after K3s start",
    'ExecStartPost = "-${firewallReconcile}";',
    'Restart = "always";',
)
forbid("nix/modules/linux/k3s-host.nix", '${firewallReconcile} &')
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
    r".*?service_state.*?inactive"
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
    r".*?systemctl disable homelab-host-rollback\.timer",
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
check_authorized_keys_verification()
check_ssh_strict_modes_guard()
check_wireguard_handshake_probe()
check_register_system_failure()
check_time_sync_waits()
check_firewall_restore_waits()
check_cilium_restart_waits()
check_provision_active_service_guard()
check_iscsi_service_verification()
check_rollback_restored_services()
check_legacy_cleanup_path_verification()
check_ansible_cutover_partition()
check_static_nix_hosts_render()
check_static_nix_hosts_expression()
check_shell_syntax()
print("migration-contracts: ok")
