# Issue Agent operations

There are four operator scripts. The three that call `kubectl` default to
`--context homelab-backbone` and never use the current kubectl context. They need
bash ≥ 4.4. Hub, bridge, and n8n run in `issue-agent`; the runner pod (runner,
publisher, and the privileged `dockerd` sidecar) runs in `issue-agent-runner`.

| Script | Purpose | Side effects |
|---|---|---|
| `issue-agent-records` | Read-only query/export of records for people and external readers | None. Needs `pods/exec` in both namespaces |
| `issue-agent-backup` | Consistent online backup of the record stores. This is a **private operator artifact**: never give it to agents or external readers | Snapshot temp files next to each database, removed afterwards. Needs `pods/exec` in both namespaces |
| `issue-agent-runner-home-migrate` | One-time copy of the runner home into `issue-agent-runner` during the namespace cutover | `status` is read-only. `migrate` patches the old PV, creates and deletes two scratch pods, writes the new home claim, and deletes runner pods that never started. `cleanup` deletes the scratch pods |
| `issue-agent-docker-smoke` | Checks the pod-local Docker daemon from inside the runner container | Builds and runs containers on the privileged daemon; keeps an artifact directory under `/tmp` |

`issue-agent-records` and `issue-agent-backup` read hub, bridge, and n8n from
`--namespace` (default `issue-agent`) and the runner from `--runner-namespace`
(default `issue-agent-runner`). Neither restarts, scales, or patches a workload, and
neither reads a Kubernetes Secret.

Records and backups contain issue text, agent transcripts, and tool output. Treat them
as private data. Files are 0600 and directories are 0700. The scripts never overwrite
an existing path. Only `issue-agent-records` output is suitable for external readers.

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
- **Codex:** `codex-sessions`, `codex-session`, and `issue` read the runner pod in
  `--runner-namespace`. The only files the script reads are regular
  `rollout-*-<uuid>.jsonl` files under `CODEX_HOME/sessions` and
  `CODEX_HOME/archived_sessions`. It does not follow symlinks. Everything else is
  refused, including `config.toml`, `auth.json`, SQLite state, `.hapi`, and checkouts.
  When a session is archived, its file moves to `archived_sessions` and remains
  exportable.
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

| Store | Namespace | Path | Method |
|---|---|---|---|
| HAPI Hub | `--namespace` | `/var/lib/hapi/hapi.db` (+WAL) | `BUN_BE_BUN=1 hapi -e`: `bun:sqlite` `VACUUM INTO` in the Bun-compiled hapi binary |
| n8n | `--namespace` | `/home/node/.n8n/database.sqlite` | n8n's bundled node `sqlite3` `VACUUM INTO` |
| bridge | `--namespace` | `/var/lib/issue-agent-bridge/state.sqlite3` | Python `sqlite3` online backup API |
| runner | `--runner-namespace` | every SQLite file in `.codex`/`.hapi` | Python `sqlite3` online backup API |

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
  Checkouts themselves are not copied, and neither is the Docker data claim
  (`issue-agent-runner-docker`), which only holds images and build cache.
- `MANIFEST` and `SHA256SUMS`. `MANIFEST` records the context, `namespace`, and
  `runner_namespace`, then one line per component with its namespace, pod, captured
  container `imageID`, and size. The script selects the container by name because the
  runner pod also runs publisher and dockerd.

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
- `issue-agent-runner` does not generate `issue-agent-hapi-auth` or
  `issue-agent-publisher`. Its ESO `SecretStore` mirrors them from `issue-agent`
  (hourly refresh). If a source is regenerated, restart the runner pod after the mirror
  has the new value.

Procedure:

1. Run `issue-agent-backup verify <dir>`.
2. Restore each component in the namespace that `MANIFEST` records for it: `namespace`
   for hub, n8n, and bridge, `runner_namespace` for the runner. Do not assume
   `issue-agent` for the runner. Scale the workload to 0. Mount its PVC in a one-off pod
   in the same namespace that complies with the restricted Pod Security profile (uid
   1000). Remove the old database and its `-wal`/`-shm` files. Extract the component
   tar into the mount root. For the runner, extract into the existing
   `issue-agent-runner-home` claim and leave `checkouts/` in place: it holds
   `.issue-agent-home-ready`, and without that marker the dockerd sidecar keeps the
   runner and publisher from starting. Delete the pod.
3. Scale up hub, bridge, n8n, and runner, in that order. Check `/health`, `/healthz`,
   the dockerd startup probe, and the runner healthcheck. Then use
   `issue-agent-records hub-sessions` and `codex-sessions` to confirm the history is
   present.
4. Recreate worktrees from `checkouts-manifest.txt`. The branches are on GitHub.
   Uncommitted or unpushed work listed there cannot be recovered from this backup.

## Runner home migration (`issue-agent-runner-home-migrate`)

```sh
$ops/issue-agent-runner-home-migrate status
$ops/issue-agent-runner-home-migrate migrate [--wipe-incomplete-destination]
$ops/issue-agent-runner-home-migrate cleanup
```

The runner moved from `issue-agent` to `issue-agent-runner` because its dockerd sidecar
needs a privileged namespace. The new `issue-agent-runner/issue-agent-runner-home`
claim starts empty, and `dockerd-start` exits until
`checkouts/.issue-agent-home-ready` exists on it. Until then the runner and publisher
never start or register with the hub. Only `migrate` writes that marker. There is no
separate fresh-install option: on a new installation, `migrate` copies the empty
retained `issue-agent` claim the same way.

Run `migrate` only after the authorized cutover: syncing the `issue-agent` Argo CD
application prunes the old runner Deployment, and syncing `issue-agent-runner` creates
the empty home claim and a runner pod that waits on the marker. The cutover is not
uninterrupted. From the prune until the marker, no runner serves HAPI sessions and the
bridge cannot reach the publisher. Pause intake for that window, or retry the stopped
events manually with `retry_event` afterwards.

`migrate` does the following, in order:

1. Checks that both claims are Bound, the old runner Deployment is absent or at 0
   replicas, no pod in `issue-agent` is the runner or mounts the old claim, and no
   scratch pod is left from an earlier run.
2. Sets the old PV's reclaim policy to `Retain`.
3. Starts two scratch pods from the new Deployment's runner image, one per namespace.
   They comply with the restricted profile. The source pod mounts the old claim
   read-only with no `fsGroup`, so ownership on the source never changes. Each pod is
   Tier 4 with a 1 CPU request, a 2Gi memory request, an 8Gi memory limit, and no CPU
   limit. The user approved these values as an unmeasured initial exception. Kubernetes
   stops the pods after 24 hours (`activeDeadlineSeconds`).
4. Inspects the destination. A destination that already has the marker stops the run.
   A partial copy stops the run unless `--wipe-incomplete-destination` is given, which
   deletes only that unfinished copy on the new claim.
5. Streams the whole old home through `tar` (pod → kubectl → pod), keeping numeric
   owners and modes. This includes checkouts, worktrees with uncommitted work, and
   native `CODEX_HOME`/`HAPI_HOME` state with its native credentials. File contents
   never reach the terminal or the local disk.
6. Builds a sorted manifest of each tree inside its pod: path, type, mode, owner, and,
   for regular files, size, mtime, and SHA-256; symlink targets and device numbers too.
   Sockets are counted and skipped. If the manifests differ, the run stops without a
   marker.
7. Checks again that the old runner is stopped, then writes the marker (mode, source,
   manifest digest, entry count, time). It deletes the scratch pods and deletes runner
   pods in `issue-agent-runner` whose runner container never started, so they come up
   without crash back-off.

The manifests and a `RESULT` file go to
`.host-state/issue-agent/home-migration/<UTC>/` (gitignored, 0600). They hold paths
and hashes but no file contents; keep them private.

Safety boundary:

- The source claim is only ever mounted read-only and is never deleted. Its PV is
  `Retain`, and both home claims carry `argocd.argoproj.io/sync-options:
  Prune=false,Delete=false`, so removing a declaration or an Application does not
  delete them.
- The tool never deletes data on its own. `--wipe-incomplete-destination` touches only
  an unfinished destination without the marker. Delete the old claim by hand, and only
  after the new runner is verified.
- `cleanup` deletes only this tool's two scratch pods, for example after an interrupted
  run: `issue-agent-home-migrate-src` in `issue-agent` and
  `issue-agent-home-migrate-dst` in `issue-agent-runner`. A pod is deleted only when both
  its exact name and the `app.kubernetes.io/name=issue-agent-home-migrate` label match,
  so a foreign pod with the same name is kept. Each deletion waits up to 120 seconds,
  and the command exits non-zero if one does not finish. Run `status` first to see the
  state.
- Rollback is manual and needs separate approval. Once the new runner has run, the new
  claim holds newer state. Stop the new runner and copy its home back into the old
  claim before the old runner starts again. The tool has no back-copy command.

## Docker smoke test (`issue-agent-docker-smoke`)

The runner image installs this script as `/opt/issue-agent/bin/docker-smoke`. Run it in
the runner container:

```sh
kubectl --context homelab-backbone -n issue-agent-runner exec deploy/issue-agent-runner -c runner -- \
  /opt/issue-agent/bin/docker-smoke
kubectl --context homelab-backbone -n issue-agent-runner exec deploy/issue-agent-runner -c runner -- \
  /opt/issue-agent/bin/docker-smoke --krema-worktree /home/agent/checkouts/<krema-worktree>
```

The script requires `DOCKER_HOST=unix://…` and UID 1000. It prints the daemon version
and cgroup driver, then builds an image from a digest-pinned `busybox` fixture with a
build context under `ISSUE_AGENT_CHECKOUTS`. It runs that image as `1000:1000` with the
context bind-mounted read-only and an artifact directory under `/tmp` bind-mounted
writable, and compares the SHA-256 of the input across the image, the bind mount, and
the artifact. With `--krema-worktree` it then runs Krema's
`tests/appium/run-e2e.sh test_smoke.py test_03_preview.py` from that worktree and
writes its artifacts under the same directory. The daemon only sees
`/home/agent/checkouts` and `/tmp`, so the worktree must be under checkouts.

Side effects: the fixture image stays in the Docker data claim as cache, the tagged
image and the build context are removed on exit, and the artifact directory (0700)
stays in the pod's `/tmp` emptyDir until the pod restarts. Krema's harness builds and
runs its own container on the same daemon. The script reads no Secret and does not
touch GitHub, but the daemon is privileged: anything it runs has node-root reach.
