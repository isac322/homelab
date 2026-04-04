---
name: homelab-version-checker
description: "Scan a GitOps repository to detect all deployed Kubernetes workloads (Helm charts, Kustomize, raw YAML, pinned container images), check upstream sources for version updates, and generate a detailed upgrade report with changelog summaries, breaking change analysis, and safety-level classifications (Safe / Config / External / Migration / Breaking). Then optionally execute upgrades with appropriate caution per safety level. Use this skill whenever the user mentions version updates, checking for outdated workloads, upgrade planning, dependency updates, or wants to know if anything in their cluster needs updating — even if they don't explicitly say 'version check'. Also trigger when the user asks about Helm chart updates, image tag bumps, or GitOps maintenance."
---

# Homelab Version Checker

Scan a GitOps repository managed by ArgoCD to build a complete inventory of deployed workloads, check upstream sources for version updates, analyze changelogs and breaking changes, classify upgrade safety, and produce a concise, actionable report. Then, on user request, execute upgrades with the right level of caution.

## Phase 0: Memory — Recall Prior Knowledge

Before scanning, load prior knowledge from the Hindsight long-term memory bank.

### 0a. Ensure Bank Exists

Check if the `homelab-version-mgmt` bank exists. If not, create it:
```
create_bank(bank_id="homelab-version-mgmt", name="Homelab Version Management", mission="Kubernetes GitOps and Terraform infrastructure version management knowledge")
```

### 0b. Recall

Query the bank for relevant prior knowledge. This saves re-discovering architecture patterns and avoids repeating past mistakes:

```
recall(bank_id="homelab-version-mgmt", query="K8s deployment architecture, workload types, image tag pinning patterns, dependency relationships", tags=["domain:k8s"], budget="mid")
recall(bank_id="homelab-version-mgmt", query="known gotchas, pitfalls, and upgrade warnings for K8s workloads", tags=["domain:k8s", "type:gotcha"], budget="mid")
```

If the user asked about specific workloads, also recall those:
```
recall(bank_id="homelab-version-mgmt", query="<workload-name> upgrade history and context", tags=["workload:<name>"], budget="mid")
```

Use recalled knowledge to:
- Understand deployment types without re-reading every YAML file (but verify against actual files if memory seems outdated)
- Pre-load known gotchas to inform safety classification — if Hindsight says "Mimir 6.x requires Kafka", you don't need to rediscover this from release notes
- Recall past safety classifications and their reasoning to maintain consistency

If Hindsight is not available or the bank is empty, proceed normally with Step 1.

---

## Phase 1: Scan & Report

### Step 1: Build Workload Inventory

#### 1a. Parse ArgoCD Manifests

Read every file under `argocd/apps/*.yaml` and `argocd/appsets/*.yaml`. Use Glob to find them, then read each one.

**Exclude disabled apps:** Files whose name starts with `_` (e.g., `_rook.yaml`, `_mysql.yaml`) are disabled — they have been removed from ArgoCD and are kept in git only for reference. Skip these files during automatic scanning. However, if the user explicitly names a disabled workload (e.g., "mimir" when `_mimir.yaml` exists), include it in the report but clearly mark it as disabled.

For each Application or ApplicationSet, extract:

| Field | YAML path | Notes |
|-------|-----------|-------|
| Name | `metadata.name` | Workload ID |
| Chart | `spec.sources[].chart` | Helm chart name (absent for non-Helm) |
| Repo URL | `spec.sources[].repoURL` | Helm repo, OCI registry, or Git URL |
| Version | `spec.sources[].targetRevision` | Current pinned version |
| Helm params | `spec.sources[].helm.parameters` | Check for `image.tag` overrides |
| Values refs | `spec.sources[].helm.valueFiles` | Paths like `$homelab/values/foo/bar.yaml` |
| Path | `spec.sources[].path` | For raw YAML / Kustomize deploys |
| Cluster | `spec.destination.name` | Target cluster |

**Multi-source pattern:** This repo commonly uses two sources — one Git ref (`ref: homelab` pointing at the homelab repo) and one chart source whose `valueFiles` reference `$homelab/values/<app>/<cluster>.yaml`. Parse both.

**ApplicationSets:** Extract the generator (`clusters`, `list`) and the template. Expand the template mentally to understand which clusters each app targets.

#### 1b. Detect Image Tag Pinning

Some charts bundle the application version in the chart's `appVersion` (upgrading the chart upgrades the app). Others require you to pin the image tag separately. The skill must distinguish these.

**Check ArgoCD helm.parameters:**
```yaml
helm:
  parameters:
    - name: image.tag
      value: sha-12f5f20   # ← explicit pin
```

**Check values files** for image tag patterns. Read each referenced values file and look for:
- `image.tag: <value>` (top-level or nested)
- `<component>.image.tag: <value>`
- `controllers.<name>.containers.<name>.image.tag: <value>`
- `tenant.image.tag: <value>`

A tag set to `""` or absent means the chart controls the app version — no separate image check needed.

#### 1c. Classify Each Workload

| Type | How to detect | Versions to check |
|------|--------------|-------------------|
| `helm` | Has `chart`, no explicit image tag | Chart version in upstream repo |
| `helm+image` | Has `chart` AND explicit image tag(s) | Chart version AND image version(s) |
| `kustomize` | Uses `path` + external Git repo, or has `kustomize` config | Git tag/release |
| `raw-yaml` | Uses `path` pointing to local `apps/objects/` dir | Usually no upstream version — note as internally managed |
| `image-sha` | Image tag is a Git SHA (`sha-XXXXXXX`) | Latest stable tag in container registry |

### Step 2: Check for Updates

Run these checks in parallel where possible (use subagents for large batches).

#### Helm Charts (HTTP repos)

Batch-add all repos, then search:
```bash
helm repo add <alias> <url> --force-update 2>/dev/null
# ... repeat for all repos
helm repo update 2>/dev/null

# Then for each chart:
helm search repo <alias>/<chart> -o json 2>/dev/null
```

The JSON output includes `version` (chart version) and `app_version`. Compare `version` with the current `targetRevision`.

#### Helm Charts (OCI repos)

OCI registries (ghcr.io, registry-1.docker.io, etc.):
```bash
# Option A: crane (if available)
crane ls <registry>/<path> 2>/dev/null | sort -V | tail -10

# Option B: skopeo
skopeo list-tags docker://<registry>/<path> 2>/dev/null | jq -r '.Tags[]' | sort -V | tail -10

# Option C: helm show (specific version)
helm show chart oci://<registry>/<path> 2>/dev/null
```

If none of these tools are available, use the OCI registry HTTP API or fall back to web search for the latest version.

#### Container Images

For workloads with explicit image tags, check the container registry for newer stable releases:
```bash
crane ls <image> 2>/dev/null | grep -E '^v?[0-9]+\.[0-9]+' | sort -V | tail -10
# or
skopeo list-tags docker://<image> 2>/dev/null
```

Filter out pre-release, nightly, RC, and platform-suffix tags. Only compare against stable versions.

Identify the image registry and repository from the chart's default values or from the values override files.

#### Git Repos (Kustomize)

```bash
# GitHub API
curl -sL "https://api.github.com/repos/<owner>/<repo>/releases/latest" | jq -r '.tag_name'
# or
git ls-remote --tags <repo-url> | grep -v '{}' | sort -t/ -k3 -V | tail -5
```

### Step 2b: Validate Compatibility (for Helm charts with updates)

Before researching changelogs, run a quick mechanical check to detect values schema incompatibilities. This catches issues that release notes might understate.

**Compare default values between versions:**
```bash
helm show values <repo>/<chart> --version <current> > /tmp/old-defaults.yaml 2>/dev/null
helm show values <repo>/<chart> --version <latest> > /tmp/new-defaults.yaml 2>/dev/null
diff /tmp/old-defaults.yaml /tmp/new-defaults.yaml | head -100
```
This reveals renamed, removed, or restructured keys between versions.

**Test current values against the new chart:**
```bash
helm template test <repo>/<chart> --version <latest> -f <values-file> 2>&1
```
If this fails with schema validation errors, those errors tell you exactly which values keys are incompatible. Include the specific errors in the report — they're more reliable than release notes for identifying required values changes.

For OCI charts:
```bash
helm template test oci://<registry>/<chart> --version <latest> -f <values-file> 2>&1
```

Skip this step for workloads without values overrides or for non-Helm deployments.

### Step 3: Analyze Changes

This is the most important step. For each workload with an available update, research what changed. Use subagents in parallel — each workload's research is independent.

For each update, gather:

1. **Release notes** — Find via:
   - GitHub Releases page (`https://github.com/<owner>/<repo>/releases`)
   - ArtifactHub page (`https://artifacthub.io/packages/helm/<repo>/<chart>`)
   - Project's CHANGELOG.md or UPGRADING.md
   - Web search: `"<project> <version> release notes"` or `"<project> upgrade from <old> to <new>"`

2. **Breaking changes** — Scan for: "BREAKING", "breaking change", "migration", "manual", "removed", "renamed", "deprecated". Read ALL release notes between current and latest, not just the latest. Cross-reference with the `helm template` and `helm show values` diff results from Step 2b — mechanical validation catches issues that release notes miss.

3. **Deprecation status** — Is the project/chart:
   - Archived on GitHub?
   - Deprecated on ArtifactHub?
   - Replaced by a successor?
   - Unmaintained (no releases in 12+ months with open security issues)?

4. **Required actions** — What specifically must change beyond bumping the version:
   - Values keys renamed/removed/added (use the `helm show values` diff to confirm)
   - Schema validation errors from `helm template` test
   - CRD updates needing manual steps
   - External service changes
   - Data format or schema changes
   - Dependency changes (other workloads that need coordinated updates)

### Step 4: Classify Safety Level

Assign each update a safety level based on the highest-risk change found across ALL intermediate versions.

Read `references/safety-levels.md` for detailed classification criteria and examples.

| Level | Icon | Label | Meaning |
|-------|------|-------|---------|
| 1 | `GREEN` | **Safe** | Drop-in: bump version, zero other changes |
| 2 | `YELLOW` | **Config** | Values or settings changes needed in the GitOps repo |
| 3 | `ORANGE` | **External** | Work outside k8s required (credentials, webhooks, DNS, etc.) |
| 4 | `RED` | **Migration** | Manual data migration needed (DB dump/restore, PV changes) |
| 5 | `STOP` | **Breaking** | Major code or architecture overhaul required |

Additional flags:
- **Deprecated** — workload should be replaced with a successor
- **EOL** — end of life, security risk

Classify conservatively: when uncertain, round up.

### Step 5: Generate Report

Use this structure. Omit empty sections. Keep descriptions concise — the user can ask for more detail on any specific workload.

```markdown
# Version Update Report
> Generated: YYYY-MM-DD
> Repository: <name>
> Clusters: <list>

## Summary

| | Count |
|---|---|
| Total workloads | N |
| Up to date | N |
| Updates available | N |
| Safe (drop-in) | N |
| Config changes | N |
| External work | N |
| Data migration | N |
| Breaking changes | N |
| Deprecated/EOL | N |

## Safe Updates (drop-in)

### workload-name
- **Type**: Helm Chart
- **Current** v1.2.3 -> **Latest** v1.2.5
- **Clusters**: backbone, prod
- **Summary**: Bug fixes, performance improvements. No breaking changes.

---
(repeat for each workload in this category)

## Config Changes Required

### workload-name
- **Type**: Helm + Image
- **Chart**: v0.11.0 -> v0.12.0
- **Image**: v2.6.3 -> v2.8.0
- **Clusters**: backbone
- **Summary**: New caching layer, API v2 endpoints.
- **Action Required**:
  - Rename `server.cache` to `server.cacheConfig` in values
  - Add `server.cacheConfig.ttl: 300` (new required field)

---

## External Work Required

### workload-name
...
- **Prerequisites** (before upgrade):
  1. Create new API key at <service>
  2. Store key in ExternalSecret store

---

## Data Migration Required

### workload-name
...
- **Migration Plan**:
  1. Backup: <steps>
  2. Migrate: <steps>
  3. Verify: <steps>
- **Rollback**: <steps>
- **Estimated risk**: <assessment>

---

## Breaking Changes

### workload-name
...
- **Impact**: <what breaks and why>
- **Required changes**: <complete list>
- **Recommendation**: <upgrade now vs wait vs migrate to alternative>

---

## Deprecated / EOL

### workload-name
- **Status**: Deprecated since YYYY-MM
- **Successor**: <replacement>
- **Migration path**: <brief description>

---

## Up to Date
(concise list: name — current version)
```

---

## Phase 2: Execute Upgrades

When the user asks to proceed with upgrades after reviewing the report, follow this approach. The user may say things like "safe 한 것들 전부 업그레이드 해줘" or "이 중에서 immich만 올려줘" — interpret their intent and act accordingly.

### General Principles

- Make decisions autonomously based on safety level, then explain your reasoning
- Process one safety level at a time, lowest first
- Within a level, group commits logically (by function, cluster, or related workloads)
- Always show the planned changes before committing (but don't ask permission for L1 unless the diff looks surprising)
- For L3+, confirm external prerequisites are complete before proceeding
- Never mix different safety levels in a single commit

### L1: Safe — Just Do It

1. Update `targetRevision` in the ArgoCD Application/ApplicationSet YAML
2. If the workload also has a separate image tag, update that too
3. Batch multiple L1 upgrades into logical commits:
   - `chore: upgrade monitoring stack (alloy v1.6.2 -> v1.7.0, loki v9.3.6 -> v9.4.0)`
   - `chore: upgrade cert-manager v1.20.0 -> v1.21.0`
4. Explain what you upgraded and why it's safe
5. **→ Push + Verify + Retain** (see below)

### L2: Config — Change and Explain

1. List the exact file changes needed (ArgoCD manifest + values files)
2. Show the diff
3. Explain each change: what it does and why it's needed
4. Apply the changes
5. Commit: `chore: upgrade <workload> to <version>` with a body listing config changes
6. **→ Push + Verify + Retain** (see below)

### L3: External — Checklist First

1. Present the prerequisite checklist with clear steps
2. Ask the user to confirm when external steps are done
3. Then apply version + config changes as in L2
4. Commit and explain what was done
5. **→ Push + Verify + Retain** (see below)

### L4: Migration — Plan and Verify

1. Present the full migration plan with:
   - Pre-migration backup steps
   - Migration procedure
   - Post-migration verification
   - Rollback plan
2. Walk through each step, waiting for user confirmation at critical points
3. Update versions only after migration is verified successful
4. **→ Push + Verify + Retain** (see below)

### L5: Breaking — Impact-Driven Planning

1. Present a detailed impact analysis:
   - What breaks and why
   - All dependent workloads affected
   - Complete list of required changes
2. Propose a phased approach (e.g., upgrade CRDs first, then operator, then workloads)
3. Each phase needs explicit user approval
4. Consider whether waiting for next major release or migrating to an alternative is better
5. **→ Push + Verify + Retain** (see below)

### Deprecated Workloads

When a workload is deprecated:
1. Research the recommended successor
2. Present a migration plan comparing the current workload with its replacement
3. If the user wants to proceed, treat it as a new deployment + decommission of the old one
4. **→ Push + Verify + Retain** (see below)

### Push + Verify + Retain (automatic after every upgrade batch)

This sequence runs automatically after every commit+push. It is not optional — it is part of the upgrade workflow.

**Step A: Push**
```bash
git push
```

**Step B: Verify ArgoCD Sync**

Wait ~30-60 seconds for ArgoCD to detect the change, then check sync status:
```bash
# Check specific app sync status
kubectl --context private-backbone get app -n argocd <app-name> -o jsonpath='{.status.sync.status} {.status.health.status}' 2>/dev/null
# Or check all apps at once
kubectl --context private-backbone get apps -n argocd -o custom-columns='NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status' 2>/dev/null | grep -v Synced
```

If sync failed or health is Degraded:
1. Check the ArgoCD Application events: `kubectl --context private-backbone describe app -n argocd <app-name> | tail -20`
2. Diagnose the issue (CRD mismatch, values schema error, resource conflict, etc.)
3. Fix the issue (edit files, re-commit, re-push)
4. Verify again until sync succeeds

**Step C: Retain to Hindsight (automatic)**

After push+verify, always retain the upgrade outcome. This builds institutional knowledge that makes future upgrades faster and safer.

**On success:**
```
retain(bank_id="homelab-version-mgmt", 
  content="Upgraded <workloads> from <old> to <new> (<safety-level>). ArgoCD sync successful, no issues. <brief note on what changed>",
  context="upgrade-event", 
  tags=["domain:k8s", "type:upgrade-event", "workload:<name>"],
  timestamp="<ISO8601 now>")
```

**On failure + fix:**
```
retain(bank_id="homelab-version-mgmt",
  content="Upgraded <workload> from <old> to <new>. ArgoCD sync FAILED: <error>. Root cause: <diagnosis>. Fixed by: <what was changed>. Lesson: <what to check next time>.",
  context="upgrade-event",
  tags=["domain:k8s", "type:upgrade-event", "type:gotcha", "workload:<name>"],
  timestamp="<ISO8601 now>")
```

Failure retains are the most valuable — they prevent the same mistake from happening twice. Include enough detail that a future agent can recognize the same situation and avoid it.

---

## Scoping

When the user asks about a specific workload (e.g., "immich"), report only on that workload. If the same ArgoCD Application file defines multiple sources (e.g., immich chart + cnpg cluster chart), only report on the one the user asked about. Mention related workloads briefly in a "Related" note, but do not include them in the "Total workloads" count or in the main report body.

When the user asks for a full scan or doesn't specify workloads, include everything.

## Efficiency Guide

Scanning 30-40 workloads can be slow if done sequentially. Optimize:

1. **Batch YAML parsing**: Use Glob to find all files, then Grep for version patterns before reading individual files
2. **Batch helm operations**: Add all HTTP repos in one script, then search all charts in another
3. **Parallel research**: Spawn subagents for changelog research — each workload is independent
4. **Smart filtering**: After Step 2, only research changelogs for workloads that actually have updates. Don't waste time researching changelogs for up-to-date workloads.
5. **Cache-friendly**: If the user runs this again soon, the helm repo data is already cached locally
6. **Targeted research**: For changelog analysis, focus on breaking changes and required actions. Don't exhaustively list every minor bug fix — summarize non-breaking changes briefly and spend your effort on the changes that actually affect upgrade safety.

## Automatic Memory (built into every phase)

Memory retention is NOT a separate phase — it happens automatically at the end of Phase 1 and after each upgrade batch in Phase 2. If you completed Phase 1 or Phase 2 without retaining, you did it wrong.

### When to retain (automatic triggers)

| Trigger | What to retain | Tags |
|---------|---------------|------|
| After Phase 1 report | Classification reasoning for non-obvious decisions, newly discovered gotchas, new deployment context | `type:classification-reasoning`, `type:gotcha`, `type:structure` |
| After each Phase 2 push+verify | Upgrade outcome (success/failure), sync issues and fixes | `type:upgrade-event`, `type:gotcha` (if failure) |

### What to retain

Retain the **reasoning and context** — things that save time or prevent mistakes next time:

- **Safety classification reasoning**: WHY a level was assigned, especially when the conclusion was non-obvious (e.g., "L1 despite upstream breaking changes because this deployment doesn't use that feature")
- **Deployment context**: Features actually in use vs not (e.g., "alloy only uses loki.write, not OTel")
- **Gotchas**: helm template failures, schema incompatibilities, version discrepancies, sync failures and their fixes
- **Upgrade outcomes**: What was upgraded, did ArgoCD sync succeed, what broke and how it was fixed
- **Dependency discoveries**: Shared modules, coordinated upgrades needed

### What NOT to retain

- Full report text (stale snapshot)
- Raw API responses, version lists, changelog text (fetch fresh)
- CLI commands executed (repeatable)
- "Upgraded successfully, no issues" without specific learnings (noise)
- Current version numbers alone (only as part of upgrade events)

### Retain sparingly

One well-written retain about WHY a safety level was chosen is worth more than ten retains listing version numbers. Focus on knowledge that can't be derived by re-scanning the repo.

---

## Notes on Specific Patterns in This Repo

- **Multi-source Applications**: Most apps use two sources — a Git ref to the homelab repo (for values) and a chart source. The version is on the chart source.
- **ApplicationSets with generators**: `clusters: {}` generates per registered cluster; `list` generators hardcode cluster names. Both the template and the generated apps share the same chart version.
- **Values path convention**: `$homelab/values/<app>/<cluster>.yaml` where `$homelab` is the Git ref source.
- **Custom chart repo** `charts.bhyoo.com`: The user's own charts — still check for updates but note these are self-published.
- **OCI chart repos**: Several charts use OCI registries (ghcr.io, registry-1.docker.io). These need different commands than HTTP repos.
