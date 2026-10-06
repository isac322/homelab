#!/usr/bin/env bash
# Three-arm write-path experiment for isac322/homelab#385, run on the storage
# node itself. Each arm is XFS on its own scratch zvol in the same pool:
#   direct   zvol mounted locally (no target, no TCP)
#   nvmet    zvol exported through the existing nvmet TCP port, connected
#            back over loopback without digests
#   digest   same as nvmet with header and data digests (CRC32C) enabled
# The canary binary then writes and verifies the same objects on all three.
#
# Usage (as a sudo-capable user on the storage node):
#   zvol-path-experiment setup    create zvols, export, connect, mkfs, mount
#   zvol-path-experiment start    start the canary as transient unit t385
#   zvol-path-experiment status   per-arm progress, mismatches, digest errors
#   zvol-path-experiment teardown stop, unmount, disconnect, unexport, destroy
#
# Environment: POOL (hot-data), SIZE (4G), DIR (/var/lib/t385), MBPS (30),
# TARGET_GIB (450), MKFS (mkfs.xfs path), CANARY (storage-canary binary,
# looked up in PATH by default).
set -euo pipefail
pool=${POOL:-hot-data}
size=${SIZE:-4G}
dir=${DIR:-/var/lib/t385}
mbps=${MBPS:-30}
target_gib=${TARGET_GIB:-450}
mkfs=${MKFS:-mkfs.xfs}
canary=${CANARY:-storage-canary}
cfs=/sys/kernel/config/nvmet
nqn_prefix=nqn.2026-10.com.example:t385
arms=(direct nvmet digest)

zvol() { echo "$pool/t385-$1"; }
nqn() { echo "$nqn_prefix-$1"; }

tcp_port() {
	local p
	for p in "$cfs"/ports/*; do
		[[ $(<"$p/addr_trtype") == tcp && $(<"$p/addr_trsvcid") == 4420 ]] || continue
		basename "$p"
		return
	done
	echo "no nvmet TCP port on 4420" >&2
	return 1
}

ctrl_of() {
	local c
	for c in /sys/class/nvme/nvme*; do
		[[ -e $c/subsysnqn && $(<"$c/subsysnqn") == "$(nqn "$1")" ]] && basename "$c"
	done
}

blockdev_of() {
	local arm=$1 c d n
	if [[ $arm == direct ]]; then
		echo "/dev/zvol/$(zvol "$arm")"
		return
	fi
	c=$(ctrl_of "$arm")
	[[ -n $c ]] || { echo "$arm: not connected" >&2; return 1; }
	# Native multipath exposes the namespace under the subsystem, otherwise
	# under the controller.
	for d in "/sys/class/nvme/$c/subsystem/" "/sys/class/nvme/$c/"; do
		for n in "$d"nvme*n*; do
			[[ -e /sys/block/$(basename "$n") ]] && { echo "/dev/$(basename "$n")"; return; }
		done
	done
	echo "$arm: no namespace block device" >&2
	return 1
}

wait_for() {
	for _ in $(seq 60); do
		[[ -e $1 ]] && return
		sleep 0.5
	done
	echo "timed out waiting for $1" >&2
	return 1
}

setup() {
	local port arm host uuid opts dev s
	port=$(tcp_port)
	uuid=$(cat /proc/sys/kernel/random/uuid)
	host="nqn.2014-08.org.nvmexpress:uuid:$uuid"
	sudo -n install -d -m 0750 -o "$(id -un)" "$dir" "$dir/evidence"
	for arm in "${arms[@]}"; do
		sudo -n zfs create -V "$size" -o volblocksize=16K -o compression=off \
			-o primarycache=metadata -o logbias=throughput "$(zvol "$arm")"
		wait_for "/dev/zvol/$(zvol "$arm")"
		[[ $arm == direct ]] && continue
		s="$cfs/subsystems/$(nqn "$arm")"
		sudo -n mkdir "$s" "$s/namespaces/1"
		echo 1 | sudo -n tee "$s/attr_allow_any_host" >/dev/null
		echo "/dev/zvol/$(zvol "$arm")" | sudo -n tee "$s/namespaces/1/device_path" >/dev/null
		echo 1 | sudo -n tee "$s/namespaces/1/enable" >/dev/null
		sudo -n ln -s "$s" "$cfs/ports/$port/subsystems/$(nqn "$arm")"
		opts="transport=tcp,traddr=127.0.0.1,trsvcid=4420,nqn=$(nqn "$arm"),hostnqn=$host,hostid=$uuid"
		[[ $arm == digest ]] && opts+=",hdr_digest,data_digest"
		echo "$opts" | sudo -n tee /dev/nvme-fabrics >/dev/null
	done
	for arm in "${arms[@]}"; do
		for _ in $(seq 60); do dev=$(blockdev_of "$arm" 2>/dev/null) && [[ -b $dev ]] && break; sleep 0.5; done
		[[ -b $dev ]] || { echo "$arm: no block device" >&2; return 1; }
		sudo -n "$mkfs" -q -f "$dev"
		sudo -n install -d -o "$(id -un)" "$dir/$arm"
		sudo -n mount -t xfs "$dev" "$dir/$arm"
		sudo -n chown "$(id -un)" "$dir/$arm"
		echo "$arm: $dev -> $dir/$arm"
	done
}

start() {
	local spec="" arm
	for arm in "${arms[@]}"; do spec+="${spec:+,}$arm=$dir/$arm"; done
	sudo -n systemd-run --unit=t385 --uid="$(id -un)" --gid="$(id -gn)" --nice=10 \
		-p WorkingDirectory="$dir" -p StandardOutput=append:"$dir/run.jsonl" \
		-p StandardError=append:"$dir/run.err" \
		"$canary" -mode run -objstore objstore.yml -manifest manifest.json \
		-arms "$spec" -mbps "$mbps" -target-gib "$target_gib" -evidence evidence
}

status() {
	systemctl is-active t385 || true
	jq -sr 'map(select(.msg=="iteration")) | group_by(.arm)[] |
		"\(.[0].arm) iters=\(length) ok=\(map(select(.ok))|length) gib=\(.[-1].verified_gib*100|floor/100)"' "$dir/run.jsonl"
	grep -c MISMATCH "$dir/run.jsonl" || true
	sudo -n dmesg -T | grep -iE "digest error|nvme.*(error|reset)|nvmet.*(error|fail)" | tail -5 || true
}

teardown() {
	local arm port c s
	sudo -n systemctl stop t385 2>/dev/null || true
	sudo -n systemctl reset-failed t385 2>/dev/null || true
	port=$(tcp_port)
	for arm in "${arms[@]}"; do
		mountpoint -q "$dir/$arm" && sudo -n umount "$dir/$arm"
		if [[ $arm != direct ]]; then
			c=$(ctrl_of "$arm")
			[[ -n $c ]] && echo 1 | sudo -n tee "/sys/class/nvme/$c/delete_controller" >/dev/null
			s="$cfs/subsystems/$(nqn "$arm")"
			[[ -L $cfs/ports/$port/subsystems/$(nqn "$arm") ]] && sudo -n rm "$cfs/ports/$port/subsystems/$(nqn "$arm")"
			if [[ -d $s ]]; then
				echo 0 | sudo -n tee "$s/namespaces/1/enable" >/dev/null
				sudo -n rmdir "$s/namespaces/1" "$s"
			fi
		fi
		sudo -n zfs list "$(zvol "$arm")" >/dev/null 2>&1 && sudo -n zfs destroy "$(zvol "$arm")"
	done
	echo "torn down; logs and evidence remain in $dir"
}

case "${1:-}" in
setup | start | status | teardown) "$1" ;;
*)
	sed -n '2,18p' "$0" >&2
	exit 2
	;;
esac
