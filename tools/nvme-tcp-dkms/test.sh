#!/usr/bin/env bash
set -euo pipefail

root=$(mktemp -d "${TMPDIR:-/tmp}/nvme-tcp-dkms-test.XXXXXX")
trap 'rm -rf "$root"' EXIT
selector=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/common/select-modules.sh
kernel=6.12.0-test
module_root="${root}/lib/modules"
mkdir -p "${module_root}/${kernel}/kernel/drivers/nvme/host" \
  "${module_root}/${kernel}/kernel/drivers/nvme/target" \
  "${module_root}/${kernel}/updates/dkms"
: > "${module_root}/${kernel}/modules.builtin"

run_selector() {
  NVME_TCP_MODULES_ROOT="$module_root" "$selector" "$kernel" "$1"
}

assert_output() {
  local expected=$1 actual=$2
  [[ "$actual" == "$expected" ]] || {
    printf 'expected <%s>, got <%s>\n' "$expected" "$actual" >&2
    exit 1
  }
}

printf '%s\n' 'kernel/drivers/nvme/host/nvme-core.ko' > "${module_root}/${kernel}/modules.builtin"
assert_output 'nvme-fabrics nvme-tcp' "$(run_selector host)"

touch "${module_root}/${kernel}/kernel/drivers/nvme/host/nvme-fabrics.ko.xz"
assert_output 'nvme-tcp' "$(run_selector host)"

touch "${module_root}/${kernel}/updates/dkms/nvme-tcp.ko.xz"
assert_output 'nvme-tcp' "$(run_selector host)"

touch "${module_root}/${kernel}/kernel/drivers/nvme/host/nvme-tcp.ko.zst"
assert_output '' "$(run_selector host)"

touch "${module_root}/${kernel}/kernel/drivers/nvme/target/nvmet.ko.xz"
assert_output 'nvmet-tcp' "$(run_selector target)"

touch "${module_root}/${kernel}/updates/dkms/nvmet-tcp.ko.xz"
assert_output 'nvmet-tcp' "$(run_selector target)"

touch "${module_root}/${kernel}/kernel/drivers/nvme/target/nvmet-tcp.ko.gz"
assert_output '' "$(run_selector target)"

NVME_TCP_MODULES_ROOT="$module_root" "$selector" "$kernel" has-stock nvme_core
NVME_TCP_MODULES_ROOT="$module_root" "$selector" "$kernel" has-stock nvmet

printf '%s\n' 'module selection tests passed'
