#!/bin/sh
# Docker janitor for the issue-agent runner pod. Runs as root inside the
# dockerd sidecar (issue-agent-dockerd image), started and restarted by
# dockerd-start in the daemon's mount namespace; it never signals dockerd.
# Installed as /opt/issue-agent/bin/dockerd-janitor (no arguments).
#
# $CHECKOUTS is agent-writable, so root never touches it through a shell
# pathname: every filesystem change below it goes through
# issue-agent-chown-sweep (runner/chown-sweep), which walks from an
# O_DIRECTORY|O_NOFOLLOW fd of the checkouts root and opens, stats and chowns
# one component at a time relative to directory fds, never following a link.
#
# Every ISSUE_AGENT_JANITOR_INTERVAL seconds (default 300):
#  1. Ownership: containers that bind-mount a worktree write into it as root,
#     and the publisher (uid 1000) cannot remove such trees (/cleanup answers
#     foreign_owner). `issue-agent-chown-sweep sweep` chowns every entry below
#     $CHECKOUTS/<owner>/<repo>-worktrees/ not owned by 1000:1000 (symlinks
#     themselves, same filesystem only).
#  2. Prune, under a maintenance lease: the bridge, after a cleanup sweep that
#     finds nothing able to use Docker, stops dispatching until lease_until and
#     asks for a prune (publisher POST /janitor/prune-request writes
#     $CHECKOUTS/.issue-agent-janitor/prune-request = {requested_at,
#     lease_until}). The janitor prunes only while at least MIN_LEASE seconds
#     of that lease remain (every Docker call below is bounded so the whole
#     prune ends within it), no container is running and /var/lib/docker is
#     above ISSUE_AGENT_JANITOR_PRUNE_PCT; above ISSUE_AGENT_JANITOR_FULL_PCT
#     after the age-filtered prune, every unused image and build cache entry
#     goes. The served lease is recorded as last_prune_lease so the bridge can
#     end its maintenance window early. No request, no prune.
#  3. Pressure prune, without a lease: under continuous activity the bridge
#     never grants one, so when /var/lib/docker is above
#     ISSUE_AGENT_JANITOR_PRESSURE_PCT (default 85) the janitor removes only
#     what no running work can be using: images no container references that
#     were created more than 12 h ago (turn images are built locally and are
#     newer; older pulled base images can be pulled again) and build cache
#     older than 12 h (BuildKit skips records in use). Volumes, containers and
#     the lease bookkeeping are left alone; the result is only logged.
#  4. Status: $CHECKOUTS/.issue-agent-janitor/status = {checked_at,
#     docker_used_pct, last_prune_at, last_prune_lease, last_prune_result},
#     served to the bridge by publisher GET /janitor/status. These fields
#     describe lease prunes only.
#
# Docker calls use the daemon socket and pass the authz plugin like any client
# (GET /containers/json, POST /containers/prune, /images/prune, /build/prune
# are all allowed by runner/authz/policy.go).
set -u

CHECKOUTS="${ISSUE_AGENT_CHECKOUTS:-/home/agent/checkouts}"
SOCK="${ISSUE_AGENT_DOCKER_SOCK:-/run/issue-agent-docker/docker.sock}"
DOCKER_DATA="${ISSUE_AGENT_DOCKER_DATA:-/var/lib/docker}"
INTERVAL="${ISSUE_AGENT_JANITOR_INTERVAL:-300}"
PRUNE_PCT="${ISSUE_AGENT_JANITOR_PRUNE_PCT:-70}"
FULL_PCT="${ISSUE_AGENT_JANITOR_FULL_PCT:-85}"
PRESSURE_PCT="${ISSUE_AGENT_JANITOR_PRESSURE_PCT:-85}"
PRESSURE_AGE=12h
FS_HELPER=/opt/issue-agent/bin/issue-agent-chown-sweep
# A prune starts only with this much lease left. The Docker timeouts below sum
# to 530 s (ps 30 + container prune 60 + 4 image/builder prunes x 110).
MIN_LEASE=600
# A lease further out than this is not one the bridge issued (it asks for
# 1200 s): drop it rather than prune at some later, unguarded moment.
MAX_LEASE=3600
PS_TIMEOUT=30
CONTAINER_PRUNE_TIMEOUT=60
PRUNE_TIMEOUT=110

# This container's own /run: lost with the container. The bridge then simply
# waits out its lease instead of releasing it early.
STATE_DIR=/run/issue-agent-janitor
LAST_PRUNE="$STATE_DIR/last-prune"

export DOCKER_HOST="unix://$SOCK"

log() {
  printf '%s dockerd-janitor: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2
}

is_uint() {
  case "$1" in
  '' | *[!0-9]*) return 1 ;;
  esac
}

usage_pct() {
  df -P "$DOCKER_DATA" 2>/dev/null | awk 'NR == 2 { sub(/%$/, "", $5); print $5 }'
}

# last_prune_at, last_prune_lease, last_prune_result ("-" = none yet).
last_prune_at=-
last_prune_lease=-
last_prune_result=-
if [ -f "$LAST_PRUNE" ]; then
  read -r last_prune_at last_prune_lease last_prune_result <"$LAST_PRUNE" || :
  if ! is_uint "$last_prune_at" || ! is_uint "$last_prune_lease"; then
    last_prune_at=-
    last_prune_lease=-
  fi
  case "$last_prune_result" in
  ok | error) ;;
  *) last_prune_result=- ;;
  esac
fi

record_prune() { # AT LEASE RESULT
  last_prune_at="$1"
  last_prune_lease="$2"
  last_prune_result="$3"
  mkdir -p "$STATE_DIR" &&
    printf '%s %s %s\n' "$1" "$2" "$3" >"$LAST_PRUNE.tmp" &&
    mv -f "$LAST_PRUNE.tmp" "$LAST_PRUNE" ||
    log "cannot persist the last prune in $STATE_DIR"
}

fix_ownership() {
  count="$(nice -n 19 "$FS_HELPER" sweep "$CHECKOUTS")" || return $?
  [ "${count:-0}" = 0 ] || log "chowned $count worktree entries to 1000:1000"
}

drop_request() {
  log "prune request dropped: $*"
  "$FS_HELPER" drop-request "$CHECKOUTS" || log 'cannot drop the prune request'
}

docker_step() { # TIMEOUT ARGS...; status 1 if the step failed
  limit="$1"
  shift
  log "running: docker $*"
  timeout "$limit" docker "$@" >/dev/null && return 0
  log "docker $* failed (status $?)"
  return 1
}

maybe_prune() {
  lease="$("$FS_HELPER" read-request "$CHECKOUTS")"
  case $? in
  0) ;;
  3) return 0 ;;
  4)
    drop_request 'unusable request (see above)'
    return 0
    ;;
  *)
    log 'cannot read the prune request; keeping it'
    return 0
    ;;
  esac
  if ! is_uint "$lease"; then
    drop_request "invalid lease_until '$lease'"
    return 0
  fi
  if [ "$lease" = "$last_prune_lease" ]; then
    drop_request "lease $lease already served"
    return 0
  fi
  left=$((lease - $(date +%s)))
  if [ "$left" -lt "$MIN_LEASE" ]; then
    drop_request "lease $lease has ${left}s left (< ${MIN_LEASE}s)"
    return 0
  fi
  if [ "$left" -gt "$MAX_LEASE" ]; then
    drop_request "lease $lease is ${left}s away (> ${MAX_LEASE}s)"
    return 0
  fi
  if ! running="$(timeout "$PS_TIMEOUT" docker ps -q)"; then
    log 'docker ps failed; keeping the prune request'
    return 0
  fi
  if [ -n "$running" ]; then
    log "$(printf '%s\n' "$running" | wc -l | tr -d ' ') container(s) running; keeping the prune request"
    return 0
  fi
  before="$(usage_pct)"
  if ! is_uint "$before"; then
    log "cannot read $DOCKER_DATA usage; keeping the prune request"
    return 0
  fi
  now="$(date +%s)"
  if [ "$before" -le "$PRUNE_PCT" ]; then
    # Nothing to do under this lease: report it served so the bridge resumes.
    record_prune "$now" "$lease" ok
    drop_request "$DOCKER_DATA at ${before}% (threshold ${PRUNE_PCT}%)"
    return 0
  fi
  # docker ps may have used part of the lease.
  left=$((lease - now))
  if [ "$left" -lt "$MIN_LEASE" ]; then
    drop_request "lease $lease has ${left}s left (< ${MIN_LEASE}s)"
    return 0
  fi
  log "pruning under lease $lease (${left}s left): $DOCKER_DATA at ${before}%"
  drop_request "serving lease $lease"
  result=ok
  docker_step "$CONTAINER_PRUNE_TIMEOUT" container prune -f || result=error
  docker_step "$PRUNE_TIMEOUT" image prune -af --filter until=24h || result=error
  docker_step "$PRUNE_TIMEOUT" builder prune -af --filter until=24h || result=error
  mid="$(usage_pct)"
  is_uint "$mid" || mid=100
  if [ "$mid" -gt "$FULL_PCT" ]; then
    log "still at ${mid}% (> ${FULL_PCT}%); pruning all unused images and build cache"
    docker_step "$PRUNE_TIMEOUT" image prune -af || result=error
    docker_step "$PRUNE_TIMEOUT" builder prune -af || result=error
  fi
  record_prune "$(date +%s)" "$lease" "$result"
  log "prune done ($result): $DOCKER_DATA ${before}% -> $(usage_pct)%"
}

pressure_prune() {
  before="$(usage_pct)"
  if ! is_uint "$before"; then
    log "cannot read $DOCKER_DATA usage; skipping the pressure prune"
    return 0
  fi
  [ "$before" -gt "$PRESSURE_PCT" ] || return 0
  log "pressure prune without a lease: $DOCKER_DATA at ${before}% (> ${PRESSURE_PCT}%)"
  result=ok
  docker_step "$PRUNE_TIMEOUT" image prune -af --filter "until=$PRESSURE_AGE" || result=error
  docker_step "$PRUNE_TIMEOUT" builder prune -af --filter "until=$PRESSURE_AGE" || result=error
  log "pressure prune done ($result): $DOCKER_DATA ${before}% -> $(usage_pct)%"
}

write_status() {
  used="$(usage_pct)"
  if ! is_uint "$used"; then
    log "cannot read $DOCKER_DATA usage; status not written"
    return 0
  fi
  "$FS_HELPER" status "$CHECKOUTS" "$(date +%s)" "$used" \
    "$last_prune_at" "$last_prune_lease" "$last_prune_result"
}

if ! is_uint "$PRESSURE_PCT"; then
  log "invalid ISSUE_AGENT_JANITOR_PRESSURE_PCT '$PRESSURE_PCT'; using 85"
  PRESSURE_PCT=85
fi
log "started (interval ${INTERVAL}s, prune above ${PRUNE_PCT}%, full prune above ${FULL_PCT}%, pressure prune above ${PRESSURE_PCT}%)"
while :; do
  fix_ownership || log "ownership sweep failed (status $?)"
  # Lease prune first: its time budget assumes it starts promptly.
  maybe_prune || log "prune step failed (status $?)"
  pressure_prune || log "pressure prune failed (status $?)"
  write_status || log "status write failed (status $?)"
  sleep "$INTERVAL"
done
