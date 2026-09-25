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

# --- prepare.sh upstream patch application ------------------------------- #
# Exercises the same code paths DKMS runs: the copied target module sources
# are a flat directory, so the upstream patch is applied with -p4. The target
# role must patch a vulnerable source, accept an already-fixed source, and
# fail closed on anything else or when the payload lost its patches.

tool_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
fixture_dir="${root}/fixtures"
mkdir -p "$fixture_dir"

make_source_tree() {
  local dir=$1
  mkdir -p "${dir}/drivers/nvme/host" "${dir}/drivers/nvme/target"
  : > "${dir}/drivers/nvme/host/tcp.c"
}

run_prepare() {
  local prepare_script=$1 source_root_dir=$2
  shift 2
  NVME_TCP_MODULES_ROOT="$module_root" \
  NVME_TCP_SOURCE_DIR="$source_root_dir" \
  NVME_TCP_SOURCE_CONFIG="${root}/unused-source.conf" \
  NVME_TCP_CACHE_DIR="${root}/cache" \
    "$prepare_script" "$kernel" "$@"
}

assert_file_contains() {
  local needle=$1 file=$2
  grep -Fq -- "$needle" "$file" || {
    printf 'expected %s to contain <%s>\n' "$file" "$needle" >&2
    exit 1
  }
}

assert_file_lacks() {
  local needle=$1 file=$2
  if grep -Fq -- "$needle" "$file"; then
    printf 'expected %s to lack <%s>\n' "$file" "$needle" >&2
    exit 1
  fi
}

# The exact nvmet_tcp_install_queue() body from linux v6.1.84, the vendor
# source layout after prepare.sh copies drivers/nvme/target/ flat.
vulnerable_src="${fixture_dir}/vulnerable"
make_source_tree "$vulnerable_src"
cat > "${vulnerable_src}/drivers/nvme/target/tcp.c" <<'VULNERABLE_EOF'
static u16 nvmet_tcp_install_queue(struct nvmet_sq *sq)
{
	struct nvmet_tcp_queue *queue =
		container_of(sq, struct nvmet_tcp_queue, nvme_sq);

	if (sq->qid == 0) {
		/* Let inflight controller teardown complete */
		flush_workqueue(nvmet_wq);
	}

	queue->nr_cmds = sq->size * 2;
	if (nvmet_tcp_alloc_cmds(queue))
		return NVME_SC_INTERNAL;
	return 0;
}
VULNERABLE_EOF

fixed_src="${fixture_dir}/fixed"
make_source_tree "$fixed_src"
cat > "${fixed_src}/drivers/nvme/target/tcp.c" <<'FIXED_EOF'
static u16 nvmet_tcp_install_queue(struct nvmet_sq *sq)
{
	struct nvmet_tcp_queue *queue =
		container_of(sq, struct nvmet_tcp_queue, nvme_sq);

	if (sq->qid == 0) {
		/* Let inflight controller teardown complete */
		flush_workqueue(nvmet_wq);
	}

	queue->nr_cmds = sq->size * 2;
	if (nvmet_tcp_alloc_cmds(queue)) {
		queue->nr_cmds = 0;
		return NVME_SC_INTERNAL;
	}
	return 0;
}
FIXED_EOF

incompatible_src="${fixture_dir}/incompatible"
make_source_tree "$incompatible_src"
cat > "${incompatible_src}/drivers/nvme/target/tcp.c" <<'INCOMPATIBLE_EOF'
static u16 nvmet_tcp_install_queue(struct nvmet_sq *sq)
{
	/* rewritten transport; the upstream fix does not apply here */
	return nvmet_tcp_register_sq(sq);
}
INCOMPATIBLE_EOF

# Simulate the installed target package payload, the layout debian/rules and
# the PKGBUILD produce under /usr/src/nvmet-tcp-target-<version>/.
installed_pkg="${root}/usr/src/nvmet-tcp-target-9.9.9-test"
mkdir -p "${installed_pkg}/patches"
cp "${tool_dir}/common/prepare.sh" "${tool_dir}/common/select-modules.sh" "$installed_pkg/"
cp "${tool_dir}/common/patches/"*.patch "${installed_pkg}/patches/"

# Vulnerable vendor source: forward dry-run succeeds, patch applies, and the
# compiled source gains the nr_cmds reset that prevents the NULL deref.
run_prepare "${installed_pkg}/prepare.sh" "$vulnerable_src" target nvmet-tcp "${root}/build-patched"
assert_file_contains 'queue->nr_cmds = 0;' "${root}/build-patched/tcp.c"
assert_file_contains 'queue->nr_cmds = sq->size * 2;' "${root}/build-patched/tcp.c"
assert_file_contains 'obj-m += nvmet-tcp.o' "${root}/build-patched/Makefile"

# Already-fixed vendor source (newer kernel.org/Arch tarball): reverse
# dry-run detects it and the build proceeds unchanged.
run_prepare "${installed_pkg}/prepare.sh" "$fixed_src" target nvmet-tcp "${root}/build-fixed"
assert_file_contains 'queue->nr_cmds = 0;' "${root}/build-fixed/tcp.c"

# Neither vulnerable nor already fixed: fail closed instead of skipping the
# patch or leaving a half-applied source.
if run_prepare "${installed_pkg}/prepare.sh" "$incompatible_src" target nvmet-tcp "${root}/build-bad" \
    2>"${root}/incompatible.err"; then
  printf 'expected prepare.sh to reject an incompatible nvmet source\n' >&2
  exit 1
fi
assert_file_contains 'incompatible' "${root}/incompatible.err"

# A target payload that lost its patches directory must fail closed too.
unpatched_pkg="${root}/usr/src/nvmet-tcp-target-unpatched"
mkdir -p "$unpatched_pkg"
cp "${tool_dir}/common/prepare.sh" "${tool_dir}/common/select-modules.sh" "$unpatched_pkg/"
if run_prepare "${unpatched_pkg}/prepare.sh" "$vulnerable_src" target nvmet-tcp "${root}/build-unpatched" \
    2>"${root}/unpatched.err"; then
  printf 'expected prepare.sh to fail when the payload has no patches\n' >&2
  exit 1
fi
assert_file_contains 'no upstream fixes found' "${root}/unpatched.err"

# The host role ships no patches directory; it must not require one.
run_prepare "${unpatched_pkg}/prepare.sh" "$vulnerable_src" \
  host 'nvme-fabrics nvme-tcp' "${root}/build-host"
assert_file_contains 'obj-m += nvme-fabrics.o' "${root}/build-host/Makefile"
assert_file_contains 'obj-m += nvme-tcp.o' "${root}/build-host/Makefile"

printf '%s\n' 'prepare.sh patch application tests passed'
