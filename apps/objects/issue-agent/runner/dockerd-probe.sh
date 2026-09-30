#!/bin/sh
# Startup/liveness probe for the issue-agent dockerd sidecar. Exits 0 only when
# the daemon answers `docker info` on the pod-local unix socket AND a real vgem
# DRM card exists. Installed in the issue-agent-dockerd image as
# /opt/issue-agent/bin/dockerd-probe; invoked by kubelet exec probes with no
# arguments. Every failure prints its reason to stderr (kubectl describe /
# probe events).
set -u

SOCKDIR="${ISSUE_AGENT_DOCKER_SOCKDIR:-/run/issue-agent-docker}"
SOCK="$SOCKDIR/docker.sock"

if ! docker -H "unix://$SOCK" info >/dev/null 2>&1; then
  echo "dockerd-probe: dockerd is not answering on $SOCK" >&2
  exit 1
fi

# vgem registers a platform device via platform_device_register_simple and does
# not bind a platform_driver, so card*/device has no driver symlink; identify
# the card by its resolved platform path instead. This must not pass on a real
# GPU node — the runner would silently test against host hardware.
if [ ! -d /sys/module/vgem ]; then
  echo 'dockerd-probe: vgem kernel module is not loaded on this node' >&2
  exit 1
fi
card=''
for c in /sys/class/drm/card[0-9]*; do
  [ -e "$c" ] || continue
  dev="$(readlink -f "$c/device" 2>/dev/null || true)"
  case "$dev" in
    /sys/devices/platform/vgem | /sys/devices/platform/vgem.*)
      card="${c##*/}"
      break
      ;;
  esac
done
if [ -z "$card" ]; then
  echo 'dockerd-probe: no vgem DRM card (no /sys/class/drm/card* resolving to /sys/devices/platform/vgem*)' >&2
  exit 1
fi
if [ ! -c "/dev/dri/$card" ]; then
  echo "dockerd-probe: character device /dev/dri/$card is missing" >&2
  exit 1
fi
exit 0
