# Issue Agent operations

There are three operator scripts. The scripts that call `kubectl` default to
`--context homelab-backbone` and never use the current kubectl context. They need
bash ≥ 4.4. Hub, bridge, and n8n run in `issue-agent`; the runner pod (runner,
publisher, and the privileged `dockerd` sidecar) runs in `issue-agent-runner`.

| Script | Purpose | Side effects |
|---|---|---|
| `issue-agent-records` | Read-only query/export of records for people and external readers | None. Needs `pods/exec` in both namespaces |
| `issue-agent-backup` | Consistent online backup of the record stores. This is a **private operator artifact**: never give it to agents or external readers | Snapshot temp files next to each database, removed afterwards. Needs `pods/exec` in both namespaces |
| `issue-agent-docker-smoke` | Checks the pod-local Docker daemon from inside the runner container; `--policy` also checks its authorization policy | Builds and runs containers on the privileged daemon; keeps an artifact directory under `/tmp/issue-agent` |

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
- `n8n.tar`: the `database.sqlite` snapshot, per-workflow import state, event logs, and
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
   `issue-agent-runner-home` claim. The old `issue-agent/issue-agent-runner-home`
   Retain backup PVC is preserved but is not mounted by the active Deployment. Delete
   the pod.
3. Scale up hub, bridge, n8n, and runner, in that order. Check `/health`, `/healthz`,
   the dockerd startup probe, and runner readiness. Then use
   `issue-agent-records hub-sessions` and `codex-sessions` to confirm the history is
   present.
4. Recreate worktrees from `checkouts-manifest.txt`. The branches are on GitHub.
   Uncommitted or unpushed work listed there cannot be recovered from this backup.

## Runner lifecycle and HAPI v0.34.4

The active runner starts directly in `issue-agent-runner`; there is no
`issue-agent-runner-home-migrate` command and no `.issue-agent-home-ready` marker.
The old `issue-agent/issue-agent-runner-home` Retain backup PVC remains preserved
for separately approved recovery, but it is not part of normal startup or cutover.

HAPI `v0.34.4` includes the runner lifecycle patch: `stopSession` removes an
orphaned
`serverPid` tree only when no sibling session is active and waits for the final
root process to exit normally. Linux `acquireRunnerLock` and `CodexRuntimeRecord`
use `/proc/1/stat` starttime plus `boot_id` for the namespace generation and
`/proc/<pid>/stat` starttime markers for PID-reuse detection. `hapi runner status
--check [--max-age 180]` exits 1 when runner status is unhealthy and 0 when it is
healthy; without `--check` it retains the normal status output.

`runner-healthcheck` is removed. `runner/bootstrap.sh` remains, but its old
previous-generation state and ownership-file deletion blocks are gone.
`HAPI_RUNNER_WEBHOOK_TIMEOUT_MS` is removed; HAPI uses its built-in 30-second
webhook default. `n8n-bootstrap.sh` remains, while its old single
`workflow-import.json` state-handling block is removed. The three operator scripts
otherwise keep their existing scope.

For bridge operations, `ensure_session` runs a synchronous 95-second archive barrier
before a 65-second resume for inactive sessions. `finish` and cancelled reviews
share one `archive_pending` queue; completion is committed before archive retry.
Bridge front-door `step_retries` performs at most 10 quiet retries with 120 seconds
between attempts. n8n has no duplicate session/send retry nodes; HTTP nodes retain
their 5×5-second engine retry.

## Exact-start initialization for fresh reviews

A fresh `pr_review` session must start at the event's expected PR head before
model startup hooks or MCP run. The bridge asks the publisher to
`POST /review-ref {repo, pr_number, expected_sha}`. The publisher fetches
`refs/pull/<pr_number>/head` from the trusted GitHub base repository, including
for fork PRs, and returns `{"sha": "<exact SHA>"}` only when that commit matches
`expected_sha` and its object is available in the runner clone. It does not
change the default checkout's HEAD, branch, or working files.

Before spawning, the bridge requires both Hub `/health`
`capabilities.worktreeStartCommit: true` and `worktree-start-commit` in the
selected machine's `metadata.capabilities`. It passes `worktreeStartCommit`
as a lowercase 40-character hex SHA for a `worktree` session. HAPI validates
the commit and creates the worktree at that commit before starting the model.
A moved pull ref, missing commit, fetch failure, or unsupported hub or runner
blocks the fresh review; none may fall back to the default branch.

This applies only to fresh review spawns. Retained sessions, resume, caches,
issue and repair paths, and normal worktree name-collision suffixes stay
unchanged. Do not reset them to verify or deploy this contract.

The initial rollout failed with `EXDEV` when publishing objects from the mirror's
emptyDir to the checkout PVC, so the bridge invocation was temporarily rolled
back. The corrected transfer creates a pack in the trusted mirror, streams it
to checkout-local temporary files, atomically publishes the pack and index,
and then publishes the ref. It does not rename files across filesystems.
The bridge invocation was restored in `22b140a`, and its rollout completed.
Full end-to-end fresh-review verification remains pending.

Verification checklist (unchecked items remain unverified):

- [ ] Capture the deployed hub, runner, publisher, and bridge image digests and
  both capability advertisements before a controlled fresh review.
- [ ] For ordinary and fork PRs, compare the event's expected SHA, publisher
  response, runner commit object, and initial worktree HEAD. Confirm that the
  default checkout stays unchanged.
- [x] On Linux with mirror and checkout on different filesystems, the original
  transfer failed with `EXDEV` and the corrected transfer passed.
- [x] The deployed `/review-ref` endpoint returned HTTP 200 and the expected SHA
  (prefix `82aa`) for QA 1259, with the shared checkout HEAD unchanged. Receipt:
  `cross-filesystem-live-receipt.json`. This verifies the live endpoint, not a
  complete fresh review.
- [ ] Verify the image digests and live bridge → publisher `/review-ref` →
  HAPI fresh-spawn route. Compare the returned SHA, runner object, initial
  worktree HEAD, and model startup order. New exact-start control samples are
  running; their complete end-to-end result is still pending.
- [ ] Confirm that the exact HEAD is established before model startup hooks and
  MCP. Confirm that invalid SHA syntax, a non-worktree request, and a missing
  commit are rejected before the model starts.
- [ ] Exercise a moved pull ref, a fetch failure, and each missing capability
  independently. Confirm that no fresh model starts on another commit.
- [ ] Check retained-session reuse and resume, issue and repair paths, existing
  caches, and normal suffix behavior when the requested worktree name exists.

## Temporary single-job benchmark admission

For the approved measurement window, `deployment-bridge.yaml` sets
`MAX_ACTIVE_EVENTS: "1"` on the bridge container only. This trusted environment
setting controls new dispatcher slots across issue, review, and repair jobs.
Unset or blank means the normal default of 10; an explicit value must be an ASCII
decimal integer from 1 through 10. Invalid values prevent startup. The separate
`MAX_ACTIVE_REVIEWS = 6` ceiling stays unchanged. The queue selects the oldest
eligible event, subject to existing per-subject and review limits, rather than
unconditional FIFO.

Lowering admission preserves active jobs and their slots, including retries of
an existing `dispatching` event, even when the active count exceeds the new cap.
It does not cancel model turns or sessions. Admission of one ordinary new job at
a time does not guarantee a quiet runner: late results, time-budget recovery,
and manual turns can overlap. Continue checking actual model-turn overlap
throughout measurement; do not infer isolation from the cap alone. Per-review
`max_threads = 2`, high reasoning, fast service tier, container resources, and all
images remain unchanged. Keep the existing runner image for control measurements;
this override does not roll out a candidate optimization image.

Exact-start behavior is a shared correctness prerequisite for both benchmark
arms, not a candidate optimization. Apply it to control and candidate, then
start a new measurement cohort with expected SHA, initial HEAD, and image
digests recorded for each run. Keep earlier wrong-base runs out of that cohort;
do not attribute their source-reading or indexing overhead to the candidate's
performance improvement.

After measurement, remove the bridge container's `MAX_ACTIVE_EVENTS` override
from `deployment-bridge.yaml` through GitOps to restore the default cap of 10.
Both applying and removing the override use the bridge Deployment's existing
`Recreate` strategy, so control API requests can briefly fail and retry while the
bridge restarts. This is not an atomic drain. Preserve the databases and WAL,
event and delivery records, attempt keys, `localId` and session identities, and
stage/publication markers. Do not reset state, cancel sessions, or replay
deliveries as part of applying or restoring this admission policy.

## Docker smoke test (`issue-agent-docker-smoke`)

The runner image installs this script as `/opt/issue-agent/bin/docker-smoke`. Run it in
the runner container:

```sh
kubectl --context homelab-backbone -n issue-agent-runner exec deploy/issue-agent-runner -c runner -- \
  /opt/issue-agent/bin/docker-smoke
kubectl --context homelab-backbone -n issue-agent-runner exec deploy/issue-agent-runner -c runner -- \
  /opt/issue-agent/bin/docker-smoke --policy
kubectl --context homelab-backbone -n issue-agent-runner exec deploy/issue-agent-runner -c runner -- \
  /opt/issue-agent/bin/docker-smoke --krema-worktree /home/agent/checkouts/<krema-worktree>
```

The script requires `DOCKER_HOST=unix://…` and UID 1000. It prints the daemon version
and cgroup driver, then builds an image from a digest-pinned `busybox` fixture with a
build context under `ISSUE_AGENT_CHECKOUTS`. It runs that image as `1000:1000` with the
context bind-mounted read-only and an artifact directory under `/tmp/issue-agent`
bind-mounted writable, and compares the SHA-256 of the input across the image, the bind
mount, and the artifact. With `--krema-worktree` it then runs Krema's
`tests/appium/run-e2e.sh test_smoke.py test_03_preview.py` from that worktree and
writes its artifacts under the same directory. The daemon's policy only allows bind
sources below `/home/agent/checkouts` and `/tmp/issue-agent`, so the worktree must be
under checkouts.

`--policy` (combinable with `--krema-worktree`) asserts the daemon's Docker policy
after the round trip. Each denial must carry the plugin's own message
(`authorization denied by plugin issue-agent-authz`), so an unrelated error does not
count as a pass:

- denied: `--privileged`, `--cap-add SYS_ADMIN`, `--network host`, `--pid host`,
  `-v /:/host`, `-v /run/issue-agent-docker:/s`, `--device /dev/sda`,
  `--security-opt seccomp=unconfined`, a `local` volume with `o=bind,device=/`,
  `docker plugin disable`, `exec --privileged`, `--volumes-from` and `docker update`;
- refused by the BuildKit entitlements (not the plugin): `docker build --allow
  network.host` of a `RUN --network=host` Dockerfile;
- allowed: `--device /dev/dri`, which must expose exactly the curated `card0` and
  `renderD128` inside the container.

The policy itself is the dockerd sidecar's legacy authorization plugin
(`runner/authz`, socket `/run/docker/plugins/issue-agent-authz.sock` inside the
sidecar only). `dockerd-start` starts it before `dockerd` and refuses to start the
daemon without it; if it dies later, every API call fails and the liveness probe
restarts the sidecar. `/etc/docker/daemon.json` in the dockerd image disables the
BuildKit `network-host`, `device` and `security-insecure` entitlements. A failing
`--policy` run means the deployed dockerd image is missing the plugin or the
entitlements; do not hand Docker work to agents until it passes.

Side effects: the fixture image stays in the Docker data claim as cache, the tagged
image, the build contexts, the `--policy` probe container and any probe volume are
removed on exit, and the artifact directory (0700) stays in the pod's `/tmp` emptyDir
until the pod restarts. Krema's harness builds and runs its own container on the same
daemon. The script reads no Secret and does not touch GitHub. The daemon is
privileged; the authorization policy limits what API clients can ask it to run, but a
policy gap still means node-root reach.
