# Issue Agent record operations

There are two operator scripts. Both default to `--context homelab-backbone` and never
use the current kubectl context. They need bash ≥ 4.4 and `kubectl` with `pods/exec`
in `issue-agent`. Neither script restarts, scales, or patches a workload, and neither
reads a Kubernetes Secret.

| Script | Purpose |
|---|---|
| `issue-agent-records` | Read-only query/export of records for people and external readers |
| `issue-agent-backup` | Consistent online backup of the record stores. This is a **private operator artifact**: never give it to agents or external readers |

Both outputs contain issue text, agent transcripts, and tool output. Treat them as
private data. Files are 0600 and directories are 0700. The scripts never overwrite an
existing path. Only `issue-agent-records` output is suitable for external readers.

## Read-only export (`issue-agent-records`)

```sh
ops=apps/objects/issue-agent/operations
$ops/issue-agent-records hub-sessions
$ops/issue-agent-records --out /secure/path/s.json hub-session <hapi-session-id>
$ops/issue-agent-records codex-sessions
$ops/issue-agent-records --out /secure/path/t.jsonl codex-session <codex-uuid>
$ops/issue-agent-records bridge issues
$ops/issue-agent-records n8n-executions --limit 20
$ops/issue-agent-records --out /secure/path/cc-lb-42 issue isac322/cc-lb 42
```

- **Hub:** requests run inside the bridge pod, which already mounts the HAPI access
  token. The token exchange happens in that process, and after it the program sends
  only `GET` requests. The token and JWT are never written or printed. `hub-session`
  uses the Hub export endpoint (`schemaVersion` 2). If a session is too large for that
  endpoint, the script paginates its messages instead.
- **Codex:** the only files the script reads are regular `rollout-*-<uuid>.jsonl` files
  under `CODEX_HOME/sessions` and `CODEX_HOME/archived_sessions`. It does not follow
  symlinks. Everything else is refused, including `config.toml`, `auth.json`, SQLite
  state, `.hapi`, and checkouts. When a session is archived, its file moves to
  `archived_sessions` and remains exportable.
- **Bridge and n8n:** both databases are opened read-only. n8n queries are limited to an
  allowlist of workflow and execution tables. The script never reads credentials,
  users, settings, or API keys. n8n stores incoming webhook request headers in its run
  data, including the bridge's `Authorization: Bearer …`. The export replaces every
  `Bearer`/`Basic` value with `[REDACTED]`. Run data uses n8n's `flatted` encoding.
- **Issue bundle:** `issue` collects the bridge rows for the issue. It then follows the
  chain of superseded HAPI sessions and maps each session to its native Codex
  transcript through `metadata.codexSessionId`/`codexSourceSessionId`. It also collects
  the n8n executions whose run data contains the issue's delivery IDs. The bundle
  includes a `mapping.json`.

## Consistent backup (`issue-agent-backup`)

```sh
$ops/issue-agent-backup create            # → .host-state/issue-agent/backups/<UTC> (gitignored)
$ops/issue-agent-backup verify <dir>      # checksums + PRAGMA integrity_check, local only
```

Each SQLite database is copied online with SQLite's own snapshot API. The backup uses
only the existing images, needs no quiesce, and does not restart anything:

| Store | Path | Method |
|---|---|---|
| HAPI Hub | `/var/lib/hapi/hapi.db` (+WAL) | `BUN_BE_BUN=1 hapi -e`: `bun:sqlite` `VACUUM INTO` in the Bun-compiled hapi binary |
| n8n | `/home/node/.n8n/database.sqlite` | n8n's bundled node `sqlite3` `VACUUM INTO` |
| bridge | `/var/lib/issue-agent-bridge/state.sqlite3` | Python `sqlite3` online backup API |
| runner | every SQLite file in `.codex`/`.hapi` | Python `sqlite3` online backup API |

Every snapshot must pass `PRAGMA integrity_check` in the pod before it is streamed.
Snapshots are stored as self-contained files with no WAL. Each database snapshot is
consistent by itself, but the set is **not** atomic across stores. The script captures
components in reference order (bridge → n8n → hub → runner). That ordering reduces
skew but does not remove it: a record written between two captures can reference data
that is missing from a store captured earlier. Plain files, such as rollout JSONL and
logs, are read live. A rollout that is being written during the backup can end with a
partial last line.

The backup directory contains:

- `hub.tar`: the `hapi.db` snapshot, `owner-id.json`, and logs.
- `n8n.tar`: the `database.sqlite` snapshot, workflow-import state, event logs, and
  binary data.
- `bridge.tar`: the `state.sqlite3` snapshot.
- `runner.tar`: `.codex` (rollouts, archived rollouts, history, SQLite state snapshots)
  and `.hapi` (runner `machineId`, state, logs), plus `checkouts-manifest.txt`. The
  manifest records each worktree's branch, HEAD, dirty files, and unpushed commits.
  Checkouts themselves are not copied.
- `MANIFEST` (pods, image digests, sizes) and `SHA256SUMS`.

The database snapshots are byte-faithful so they can be restored. As a result, they
still contain credential material. For example, n8n execution data records the bridge's
webhook `Authorization` header, and n8n credentials are stored encrypted. Known
credential and config files are deliberately left out: hub `settings.json` (persisted
`cliApiToken`) and `jwt-secret.json`; n8n `config` (a copy of the encryption key);
runner `.codex/config.toml`, `.codex/auth.json`, `.codex/shell_snapshots` (a captured
shell environment), `.codex/app-server-control`, `.codex/hapi-runtime-owners`, and
`.hapi/codex-runtimes` (live runtime endpoints and ownership). Regenerated tool bundles
(`runtime/`, `.codex/skills/.system`) and lock files are also left out.

Snapshot temp files (`.issue-agent-backup.*`) are created next to each database on the
same PVC and removed afterwards. Run only one backup at a time.

## Restore prerequisites and procedure (manual, destructive, needs explicit approval)

The backup contains no Secrets. Before you restore, make sure the ESO-generated Secrets
still exist in `issue-agent` or have been restored from a separately authorized source.
Otherwise ESO regenerates them:

- `issue-agent-n8n-encryption`: without the original key, n8n cannot decrypt the
  credentials in the restored DB, and n8n startup fails when it detects the key
  mismatch. The three header credentials are machine-owned and re-upserted from
  Secrets at every start. Other stored credentials would be lost.
- `issue-agent-webhook`: if this is regenerated, update the GitHub App webhook secret.
- `issue-agent-hapi-auth`, `issue-agent-bridge-ops`, `issue-agent-n8n-owner`: these can
  be regenerated. The consumers read them from the same Secrets. The hub regenerates
  `jwt-secret.json`, which only invalidates existing browser sessions.

Procedure:

1. Run `issue-agent-backup verify <dir>`.
2. Scale the workload to 0. Mount its PVC in a one-off pod that complies with the
   restricted Pod Security profile (uid 1000). Remove the old database and its
   `-wal`/`-shm` files. Extract the component tar into the mount root. Delete the pod.
3. Scale up hub, bridge, n8n, and runner, in that order. Check `/health`, `/healthz`,
   and the runner healthcheck. Then use `issue-agent-records hub-sessions` and
   `codex-sessions` to confirm the history is present.
4. Recreate worktrees from `checkouts-manifest.txt`. The branches are on GitHub.
   Uncommitted or unpushed work listed there cannot be recovered from this backup.
