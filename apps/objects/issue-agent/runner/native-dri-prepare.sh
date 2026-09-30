#!/bin/sh
# Projects the node's native DRM pair into the dockerd sidecar's /dev/dri.
# Internal to dockerd-start (no arguments, no options); installed in the
# issue-agent-dockerd image as /opt/issue-agent/bin/native-dri-prepare.
#
# The manifest mounts the pod's dri emptyDir at RAW with the host's card0 and
# renderD128 CharDevice hostPaths as submounts. A privileged container's
# runtime creates every host device under /dev after the volume mounts, so a
# mask at /dev/dri itself would be repopulated (e.g. rock5bp's RKNPU
# card1/renderD129). RAW lives outside /dev and is never populated.
#
# This recursively bind-mounts RAW over /dev/dri in the caller's own mount
# namespace after making /dev private, so nothing propagates back to the
# node. It never creates, deletes or modifies device nodes or host paths.
# Every unexpected state fails closed with exit 1.
set -eu

RAW=/run/issue-agent-dri
DRI=/dev/dri

fail() {
  printf 'native-dri-prepare: %s\n' "$*" >&2
  exit 1
}

# Requires DIR to hold exactly the character devices card0 and renderD128 and
# nothing else (dotfiles included).
check_pair() {
  dir="$1"
  count=0
  for entry in "$dir"/* "$dir"/.[!.]* "$dir"/..?*; do
    [ -e "$entry" ] || [ -L "$entry" ] || continue
    name="${entry##*/}"
    case "$name" in
      card0 | renderD128) ;;
      *) fail "unexpected entry $entry; only card0 and renderD128 are allowed" ;;
    esac
    [ ! -L "$entry" ] && [ -c "$entry" ] || fail "$entry is not a character device"
    count=$((count + 1))
  done
  [ "$count" -eq 2 ] || fail "$dir must contain exactly card0 and renderD128 (found $count entries)"
}

[ -d "$RAW" ] && [ ! -L "$RAW" ] || fail "$RAW is not a directory"
[ "$(readlink -f "$RAW")" = "$RAW" ] || fail "$RAW does not resolve to itself"
check_pair "$RAW"

mkdir -p "$DRI" || fail "cannot create $DRI"
mount --make-rprivate /dev || fail 'cannot make /dev mount propagation private'
mount --rbind "$RAW" "$DRI" || fail "cannot bind $RAW over $DRI"

check_pair "$DRI"
for node in card0 renderD128; do
  [ "$(stat -c '%t:%T' "$RAW/$node")" = "$(stat -c '%t:%T' "$DRI/$node")" ] ||
    fail "$DRI/$node does not match $RAW/$node after projection"
done
exit 0
