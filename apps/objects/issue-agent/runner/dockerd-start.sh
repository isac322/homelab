#!/bin/sh
# Starts the pod-local Docker daemon for the issue-agent runner pod. Runs as
# root in the issue-agent-dockerd image (Dockerfile.dockerd) as a native
# sidecar; every unmet precondition fails closed before dockerd launches.
# Installed as /opt/issue-agent/bin/dockerd-start (image ENTRYPOINT, no args).
set -eu

fail() {
  printf 'dockerd-start: %s\n' "$*" >&2
  exit 1
}

SOCKDIR="${ISSUE_AGENT_DOCKER_SOCKDIR:-/run/issue-agent-docker}"
SOCK="$SOCKDIR/docker.sock"
CHECKOUTS="${ISSUE_AGENT_CHECKOUTS:-/home/agent/checkouts}"

# The native sidecar must not start the runner/publisher until the offline home
# copy has been verified. Its startup probe gates all following containers.
[ -s "$CHECKOUTS/.issue-agent-home-ready" ] ||
  fail 'runner home is not ready; complete issue-agent-runner-home-migrate first'

# The nftables firewall backend runs `nft` ("Failed to find nft tool" aborts
# daemon startup); Dockerfile.dockerd installs it.
command -v nft >/dev/null 2>&1 || fail 'nft is missing; --firewall-backend=nftables requires it'

# cgroup containment: nested containers must live under this container's own
# cgroup so the pod-level memory limit bounds every Docker workload.
#
# A private cgroup namespace presents /proc/self/cgroup as "0::/" with our own
# cgroup mounted at /sys/fs/cgroup. Privileged pods on k3s/containerd instead
# share the NODE's cgroup namespace: our path is a node-root subpath like
# /kubepods.../cri-containerd-<id>.scope and /sys/fs/cgroup is the node root.
# In that case, and only then, we re-exec inside `unshare --cgroup --mount
# --propagation private` and remount cgroup2 over /sys/fs/cgroup so the
# namespace root becomes our own scope. Mount propagation stays private; the
# node's mount table is never touched. If no containment view can be
# established the daemon does not start.
CG_PATH="$(awk -F: '$2 == "" { print $3 }' /proc/self/cgroup)"
[ -n "$CG_PATH" ] || fail 'no cgroup v2 entry in /proc/self/cgroup'
if [ "$CG_PATH" != "/" ]; then
  SCOPE="/sys/fs/cgroup$CG_PATH"
  [ -d "$SCOPE" ] || fail "own cgroup scope $SCOPE not found under the shared cgroup mount"
  SCOPE_MAX="$(cat "$SCOPE/memory.max" 2>/dev/null || true)"
  { [ -n "$SCOPE_MAX" ] && [ "$SCOPE_MAX" != "max" ]; } ||
    fail "own cgroup scope memory.max is not a finite limit (got '${SCOPE_MAX:-unreadable}'); refusing to run dockerd at the node cgroup root"
  command -v unshare >/dev/null 2>&1 || fail 'unshare (util-linux) is required to enter a private cgroup namespace'
  [ "${ISSUE_AGENT_DOCKERD_REEXECED:-}" = "1" ] &&
    fail "re-executed into a cgroup namespace but /proc/self/cgroup is still $CG_PATH"
  SELF="$(readlink -f "$0")"
  ISSUE_AGENT_DOCKERD_REEXECED=1 exec unshare --cgroup --mount --propagation private \
    sh -c 'umount /sys/fs/cgroup 2>/dev/null || umount -l /sys/fs/cgroup
mount -t cgroup2 cgroup2 /sys/fs/cgroup || { echo "dockerd-start: cannot remount cgroup2 scoped to our own cgroup" >&2; exit 1; }
exec "$0" "$@"' "$SELF" "$@"
fi
[ -f /sys/fs/cgroup/cgroup.controllers ] ||
  fail 'cgroup v2 is required (/sys/fs/cgroup/cgroup.controllers missing)'
MEM_MAX="$(cat /sys/fs/cgroup/memory.max 2>/dev/null || true)"
{ [ -n "$MEM_MAX" ] && [ "$MEM_MAX" != "max" ]; } ||
  fail "/sys/fs/cgroup/memory.max is not a finite limit (got '${MEM_MAX:-unreadable}'); dockerd children would escape the pod memory boundary"
mkdir -p /sys/fs/cgroup/.issue-agent-write-test 2>/dev/null ||
  fail '/sys/fs/cgroup is not writable; cgroupfs driver cannot create child cgroups'
rmdir /sys/fs/cgroup/.issue-agent-write-test

# With --firewall-backend=nftables dockerd never enables IPv4 forwarding
# itself and fails on bridge creation otherwise. The sysctl is per-network
# namespace, so this affects only the pod.
[ "$(cat /proc/sys/net/ipv4/ip_forward 2>/dev/null || echo 0)" = "1" ] ||
  sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1 ||
  fail 'cannot enable net.ipv4.ip_forward inside the pod network namespace'

# Precreate the checkouts dir inside the shared home PVC. Kubelet auto-creates
# a missing subPath directory but as root:root; chown here (non-recursive) so
# the runner (uid/gid 1000) keeps writing it.
mkdir -p "$CHECKOUTS"
# BusyBox `install -d` does not adjust an existing directory, so fix ownership
# and mode explicitly (non-recursive; contents stay untouched).
chown 1000:1000 "$CHECKOUTS" && chmod 0700 "$CHECKOUTS" ||
  fail "cannot chown 1000:1000 $CHECKOUTS"

mkdir -p "$SOCKDIR"
rm -f "$SOCK" # stale socket inode from a previous daemon run

# Keep Docker's DinD mount setup and PID-1 reaping, but bypass the stock
# dockerd-entrypoint: it probes iptables and may load legacy modules even with
# the nftables backend. Explicit arguments also avoid its default TCP listeners.
#
# --firewall-backend=nftables: Docker never touches the iptables backend in
#   this mode; do NOT pass --iptables=false — upstream docs state that flag
#   disables firewall rule creation for BOTH backends and breaks NAT.
# --ip6tables=false: pods are IPv4-only; skip the ip6 docker-bridges table.
# --cgroup-parent=/issue-agent-docker: with the cgroupfs driver and the
#   private cgroup namespace above, child cgroups land under the container's
#   own cgroup root, inside the pod memory limit.
exec /usr/local/bin/dind docker-init -- dockerd \
  --host="unix://$SOCK" \
  --group=1000 \
  --firewall-backend=nftables \
  --ip6tables=false \
  --exec-opt native.cgroupdriver=cgroupfs \
  --cgroup-parent=/issue-agent-docker
