#!/bin/sh
# Startup/liveness probe for the issue-agent dockerd sidecar. Exits 0 only when
# the daemon answers `docker info` on the pod-local unix socket AND the node's
# native DRM pair (/dev/dri/card0 + /dev/dri/renderD128) is present, belongs to
# one DRM device, and is bound to a known display driver. Installed in the
# issue-agent-dockerd image as /opt/issue-agent/bin/dockerd-probe; invoked by
# kubelet exec probes with no arguments. Every failure prints its reason to
# stderr (kubectl describe / probe events).
#
# This checks device identity only, not OpenGL capability: Krema's E2E stack
# renders with Mesa's software rasterizer on top of these nodes.
set -u

SOCKDIR="${ISSUE_AGENT_DOCKER_SOCKDIR:-/run/issue-agent-docker}"
SOCK="$SOCKDIR/docker.sock"

if ! docker -H "unix://$SOCK" info >/dev/null 2>&1; then
  echo "dockerd-probe: dockerd is not answering on $SOCK" >&2
  exit 1
fi

# The manifest mounts exactly these two nodes at their host paths. Any other
# DRM node (e.g. the RKNPU's card1/renderD129 on rock5bp) must stay hidden.
backing=''
for node in card0 renderD128; do
  if [ ! -c "/dev/dri/$node" ]; then
    echo "dockerd-probe: character device /dev/dri/$node is missing" >&2
    exit 1
  fi
  if [ ! -r "/sys/class/drm/$node/dev" ]; then
    echo "dockerd-probe: /sys/class/drm/$node is missing on this node" >&2
    exit 1
  fi
  # Reject a remapped node: the mounted device number must match what the
  # kernel reports for the same DRM minor name.
  want="$(cat "/sys/class/drm/$node/dev")"
  have="$(stat -c '%t %T' "/dev/dri/$node")"
  have="$(printf '%d:%d' "0x${have% *}" "0x${have#* }")"
  if [ "$have" != "$want" ]; then
    echo "dockerd-probe: /dev/dri/$node is $have but the kernel's $node is $want" >&2
    exit 1
  fi
  dev="$(readlink -f "/sys/class/drm/$node/device" 2>/dev/null || true)"
  if [ -z "$dev" ]; then
    echo "dockerd-probe: /sys/class/drm/$node/device does not resolve" >&2
    exit 1
  fi
  if [ -z "$backing" ]; then
    backing="$dev"
  elif [ "$dev" != "$backing" ]; then
    echo "dockerd-probe: card0 ($backing) and renderD128 ($dev) are different DRM devices" >&2
    exit 1
  fi
done

driver="$(readlink -f "$backing/driver" 2>/dev/null || true)"
driver="${driver##*/}"
case "$driver" in
  asahi | rockchip-drm) ;;
  *)
    echo "dockerd-probe: DRM device $backing has unsupported driver '${driver:-<none>}' (want asahi or rockchip-drm)" >&2
    exit 1
    ;;
esac
exit 0
