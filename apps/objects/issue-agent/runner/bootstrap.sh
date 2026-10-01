#!/usr/bin/env bash
# Prepares the persistent runner home, then execs the HAPI runner in the foreground.
set -euo pipefail
umask 077

fail() {
  printf 'runner-bootstrap: %s\n' "$*" >&2
  exit 1
}

for name in HOME HAPI_HOME CODEX_HOME HAPI_API_URL CLI_API_TOKEN GH_CONFIG_DIR GIT_CONFIG_SYSTEM \
  ISSUE_AGENT_CHECKOUTS ISSUE_AGENT_PROVIDER_DIR \
  GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL GIT_COMMITTER_NAME GIT_COMMITTER_EMAIL; do
  [[ -n "${!name:-}" ]] || fail "$name is required"
done
if [[ -n "${GH_TOKEN:-}${GITHUB_TOKEN:-}" ]]; then
  fail 'GH_TOKEN and GITHUB_TOKEN must be unset; use the rotating GitHub credential files in GH_CONFIG_DIR.'
fi
provider_config="$ISSUE_AGENT_PROVIDER_DIR/config.toml"
[[ -f "$provider_config" ]] || fail "$provider_config is missing"
gh auth token --hostname github.com >/dev/null || fail 'no GitHub token available in GH_CONFIG_DIR'

mkdir -p "$HAPI_HOME" "$CODEX_HOME" "$ISSUE_AGENT_CHECKOUTS"

# Native Codex state (sessions, archived_sessions, history) persists in CODEX_HOME.
# Only the provider config and the image-versioned global instructions are replaced.
install -m 600 "$provider_config" "$CODEX_HOME/config.toml"
if [[ -e "$CODEX_HOME/AGENTS.override.md" ]]; then
  fail "$CODEX_HOME/AGENTS.override.md would replace the common Issue Agent instructions; remove it deliberately."
fi
install -m 644 /opt/issue-agent/profile/AGENTS.md "$CODEX_HOME/AGENTS.md"

# Base clones only; the publisher sidecar clones a repository on first use.
# HAPI creates per-issue worktrees next to each clone (<repo>-worktrees/<name>)
# from the clone's local HEAD, so fast-forward every existing clone.
shopt -s nullglob
for checkout in "$ISSUE_AGENT_CHECKOUTS"/*/*; do
  [[ -d "$checkout" && ! -L "$checkout" ]] || continue
  [[ "$checkout" != *-worktrees ]] || continue
  repository="${checkout#"$ISSUE_AGENT_CHECKOUTS"/}"
  [[ "$repository" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || fail "invalid checkout '$checkout'; expected owner/name"
  origin="https://github.com/$repository.git"
  [[ "$(git -C "$checkout" rev-parse --show-toplevel)" == "$checkout" ]] || fail "$checkout is not a repository root"
  [[ "$(git -C "$checkout" remote get-url origin)" == "$origin" ]] || fail "$checkout origin is not $origin"

  git -C "$checkout" fetch --quiet --prune origin
  git -C "$checkout" remote set-head origin --auto >/dev/null
  default_ref="$(git -C "$checkout" symbolic-ref --short refs/remotes/origin/HEAD)"
  default_branch="${default_ref#origin/}"
  [[ "$(git -C "$checkout" symbolic-ref --quiet --short HEAD || true)" == "$default_branch" ]] ||
    fail "$checkout must stay on $default_branch; agents work only in HAPI worktrees"
  [[ -z "$(git -C "$checkout" status --porcelain --untracked-files=normal)" ]] ||
    fail "$checkout has local changes; refusing to update the base clone"
  git -C "$checkout" merge --quiet --ff-only "$default_ref" ||
    fail "$checkout cannot fast-forward to $default_ref"
done

# HAPI's single-runner state and lock record the runner PID and treat a live PID as a
# running runner. A fresh container reuses the same PID, so files left by a killed
# container (OOM, SIGKILL) make HAPI exit 0 as if a runner were already up. Nothing
# else can run a runner on this home (one replica, Recreate, every HAPI process lives
# in this container), so both files are stale here. The resume and verified-exit
# files next to them carry session recovery state and must stay.
rm -f "$HAPI_HOME/runner.state.json" "$HAPI_HOME/runner.state.json.lock"

exec /usr/local/bin/hapi runner start-sync --workspace-root "$ISSUE_AGENT_CHECKOUTS"
