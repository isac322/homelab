---
name: terraform-version-checker
description: "Scan a Terraform project to detect all provider version constraints and lock file pins, check the Terraform Registry for available updates, analyze changelogs and breaking changes, and generate a detailed upgrade report with safety-level classifications (Safe / Config / External / Migration / Breaking). Then optionally execute upgrades. Use this skill whenever the user mentions Terraform provider updates, terraform version checking, provider upgrades, lock file updates, or wants to know if any Terraform providers or the Terraform core version need updating. Also trigger when the user asks about .terraform.lock.hcl, required_providers, or terraform init -upgrade."
---

# Terraform Version Checker

Scan a Terraform project to inventory all provider dependencies and their locked versions, check the Terraform Registry for available updates, analyze changelogs and breaking changes, classify upgrade safety, and produce a concise report. Then, on user request, execute upgrades.

## Phase 0: Memory — Recall Prior Knowledge

Before scanning, load prior knowledge from the Hindsight long-term memory bank.

### 0a. Ensure Bank Exists

Check if the `homelab-version-mgmt` bank exists. If not, create it:
```
create_bank(bank_id="homelab-version-mgmt", name="Homelab Version Management", mission="Kubernetes GitOps and Terraform infrastructure version management knowledge")
```

### 0b. Recall

Query the bank for relevant prior knowledge:
```
recall(bank_id="homelab-version-mgmt", query="Terraform infrastructure roots, providers, module sharing, constraint patterns", tags=["domain:terraform"], budget="mid")
recall(bank_id="homelab-version-mgmt", query="known gotchas and issues for Terraform provider upgrades, lock file problems", tags=["domain:terraform", "type:gotcha"], budget="mid")
```

Use recalled knowledge to:
- Know which roots exist and which modules are shared without re-scanning every `.tf` file
- Pre-load known issues (e.g., "prod-vultr lock file has constraint mismatches") to verify if they're still present
- Recall past provider upgrade experiences to inform safety classification

If Hindsight is not available or the bank is empty, proceed normally with Step 1.

---

## Phase 1: Scan & Report

### Step 1: Build Provider Inventory

#### 1a. Find All Terraform Roots

A Terraform "root" is a directory that can be independently `terraform init`'d — it has its own state and provider locks. Identify roots by looking for directories containing both `.tf` files and either a `backend` block, `cloud` block, or `.terraform.lock.hcl`.

Use Glob to find all `.tf` files and `.terraform.lock.hcl` files. Group them by directory to identify roots.

**Exclude `.terraform/` directories** — these are cache/plugin dirs, not source.

#### 1b. Extract Provider Requirements

For each root and its referenced local modules, read all `.tf` files and extract:

| Field | HCL path | Notes |
|-------|----------|-------|
| Provider source | `required_providers.<name>.source` | e.g., `hashicorp/aws` |
| Version constraint | `required_providers.<name>.version` | e.g., `~> 5.100.0` |
| Terraform version | `terraform.required_version` | e.g., `~> 1.13` |

Also check for local modules (`source = "./..."`) and read their `required_providers` blocks too — they may declare additional providers or tighter constraints.

#### 1c. Read Lock Files

For each root with a `.terraform.lock.hcl`, extract:

| Field | Purpose |
|-------|---------|
| Provider address | `registry.terraform.io/hashicorp/aws` |
| Locked version | `version = "5.100.0"` |
| Constraint recorded | `constraints = "~> 5.100.0"` |
| Hashes | Platform-specific checksums (note which platforms are recorded) |

The lock file is the source of truth for what version is actually installed. The constraint in the lock file may differ from the `.tf` constraint if the lock was created under an older constraint — flag this as a potential inconsistency.

#### 1d. Classify Check Targets

| Type | What to check | How |
|------|--------------|-----|
| `provider` | Provider version in Terraform Registry | Registry API |
| `terraform-core` | Terraform CLI version | GitHub releases API |
| `remote-module` | Module version in registry (if any `source = "registry.terraform.io/..."`) | Registry API |
| `local-module` | No version to check | Skip (note as internally managed) |

### Step 2: Check for Updates

#### Providers — Terraform Registry API

For each provider, query the registry:
```bash
curl -sL "https://registry.terraform.io/v1/providers/<namespace>/<name>/versions" | jq -r '.versions[].version' | sort -V | tail -5
```

For example:
```bash
curl -sL "https://registry.terraform.io/v1/providers/hashicorp/aws/versions" | jq -r '.versions[].version' | sort -V | tail -5
```

Compare the locked version against the latest available. Also check whether the current version constraint would even allow the latest (e.g., `~> 5.100.0` won't allow `5.101.0`).

Report three things for each provider:
1. **Locked version** vs **latest within current constraint** (safe, no constraint change needed)
2. **Locked version** vs **latest overall** (may require constraint widening)
3. Whether the constraint needs updating to allow the latest

**Major version availability**: If a new major version exists (e.g., aws v6.x when locked at v5.x), always flag it prominently with a safety classification. Major provider versions typically involve breaking changes and deserve at least a brief impact note, even if upgrading isn't recommended right now.

#### Terraform Core — GitHub API

```bash
curl -sL "https://api.github.com/repos/hashicorp/terraform/releases/latest" | jq -r '.tag_name'
```

Also check OpenTofu if the project uses it:
```bash
curl -sL "https://api.github.com/repos/opentofu/opentofu/releases/latest" | jq -r '.tag_name'
```

#### Remote Modules (if any)

```bash
curl -sL "https://registry.terraform.io/v1/modules/<namespace>/<name>/<provider>/versions" | jq -r '.modules[0].versions[].version' | sort -V | tail -5
```

### Step 2b: Validate Compatibility

For provider upgrades that cross minor or major version boundaries, check compatibility:

```bash
# Compare provider schema changes (if terraform CLI is available)
cd <root-dir>
terraform providers lock -platform=linux_amd64 <provider>=<new-version> 2>&1
```

If terraform CLI isn't available or requires auth, skip this step and rely on changelog analysis.

### Step 3: Analyze Changes

For each provider/component with an available update, research what changed. Use subagents in parallel for efficiency.

For each update, gather:

1. **Changelog** — Find via:
   - Terraform Registry page (`https://registry.terraform.io/providers/<ns>/<name>/latest/docs`)
   - GitHub Releases (`https://github.com/<owner>/<repo>/releases`)
   - Provider's CHANGELOG.md or UPGRADE-GUIDE.md
   - Web search: `"<provider> <version> changelog"` or `"terraform provider <name> upgrade guide"`

2. **Breaking changes** — For Terraform providers, look for:
   - Resource/data source removals or renames
   - Attribute removals, renames, or type changes
   - Changed default values that affect behavior
   - Minimum Terraform version bumps
   - Required new authentication configuration
   - State migration requirements

3. **Deprecation status** — Is the provider:
   - Archived on GitHub?
   - Replaced by a fork or successor? (e.g., `terraform-provider-x` → new org)
   - No longer maintained?

4. **Required actions** — What changes beyond version bump:
   - Constraint widening in `required_providers`
   - Lock file regeneration (`terraform init -upgrade`)
   - Resource/attribute renames in `.tf` files
   - State migration commands
   - New required provider configuration

### Step 4: Classify Safety Level

Use the same 5-level system as the homelab-version-checker for consistency:

| Level | Label | Terraform-specific meaning |
|-------|-------|---------------------------|
| 1 (Safe) | **Safe** | Widen constraint + `terraform init -upgrade`. No `.tf` code changes, no state migration. |
| 2 (Config) | **Config** | `.tf` code changes needed: renamed attributes, new required fields, deprecated features to update. |
| 3 (External) | **External** | External work needed: new API credentials, service configuration changes, cloud provider console actions. |
| 4 (Migration) | **Migration** | State migration required: `terraform state mv`, manual state surgery, import/remove operations. |
| 5 (Breaking) | **Breaking** | Major provider rewrite: resources completely restructured, multiple state migrations, potential data loss risk. |

Read the homelab-version-checker's `references/safety-levels.md` for the general classification philosophy (classify conservatively, check ALL intermediate versions, etc.), but apply the Terraform-specific criteria above.

### Step 5: Generate Report

```markdown
# Terraform Version Update Report
> Generated: YYYY-MM-DD
> Project: <path>
> Roots: <list of terraform root directories>

## Summary

| | Count |
|---|---|
| Total providers | N |
| Up to date | N |
| Updates available | N |
| Safe (drop-in) | N |
| Config changes | N |
| External work | N |
| State migration | N |
| Breaking changes | N |
| Terraform core | <current> -> <latest> |

## Provider Updates by Root

### <root-directory>

#### <provider-name> (e.g., hashicorp/aws)
- **Locked**: v5.100.0
- **Constraint**: ~> 5.100.0
- **Latest in constraint**: v5.100.x
- **Latest overall**: v5.xxx.0
- **Safety**: L1 Safe / L2 Config / etc.
- **Summary**: <what changed>
- **Action Required**: <specific steps>

---

## Terraform Core
- **Current constraint**: ~> 1.13
- **Latest**: v1.x.x
- **Notes**: <compatibility notes>

## Constraint vs Lock Inconsistencies
(List any providers where the lock file constraint doesn't match the .tf constraint)

## Up to Date
(List of providers already on latest)
```

**Consolidation**: When the same provider appears at the same version in multiple roots with identical analysis, consolidate into a single entry listing all affected roots. Don't repeat the same changelog analysis for each root — just reference it once and note which roots are affected.

**Context-aware analysis**: When summarizing changelogs, note which new features or changes are actually relevant to THIS deployment based on the resources used in `.tf` files. For example, if a provider adds K8s-specific features but the deployment only uses plain VMs, note that the new features aren't relevant.

Organize by provider (not by root) to reduce duplication. List affected roots per provider.

---

## Phase 2: Execute Upgrades

When the user requests upgrades:

### L1: Safe — Constraint + Lock Update

**Workflow** (important — do not commit constraints without lock file):
1. Widen the version constraint in `required_providers` if needed:
   ```hcl
   # Before
   version = "~> 5.100.0"
   # After  
   version = "~> 5.110.0"
   ```
2. Update constraint in ALL files that declare the same provider (root + modules)
3. The user then runs `terraform init -upgrade` locally to regenerate `.terraform.lock.hcl`
4. Commit BOTH `.tf` changes AND the updated `.terraform.lock.hcl` together

For **Terraform Cloud** users: the user must run `terraform init -upgrade` locally with TFC auth configured (or `terraform login` first). Committing only constraint changes without the updated lock file will cause TFC runs to fail because the lock won't match the constraint.

### L2: Config — Code Changes

1. List all `.tf` code changes needed with before/after examples
2. Apply changes to `.tf` files
3. Update version constraints
4. Commit with descriptive message

### L3: External — Prerequisites

1. List external prerequisites
2. Wait for user confirmation
3. Then proceed as L2

### L4: Migration — State Surgery

1. Document the full migration plan:
   - Pre-migration: `terraform state pull > backup.tfstate`
   - State move commands: `terraform state mv old.resource new.resource`
   - Post-migration: `terraform plan` should show no changes
2. Walk through each step with user confirmation
3. Update code + constraints only after state is migrated

### L5: Breaking — Impact-Driven

1. Detailed impact analysis
2. Phased migration plan
3. Consider whether to upgrade in stages through intermediate versions

### After Each Upgrade: Verify + Retain (automatic)

This runs automatically after every upgrade. It is not optional.

**Verify**: The user runs `terraform plan` after `init -upgrade`. If plan shows unexpected changes or errors:
1. Diagnose the issue
2. Fix .tf code
3. Re-run plan until clean

**Retain to Hindsight** (automatic after every upgrade):
```
# On success:
retain(bank_id="homelab-version-mgmt", content="Upgraded <provider> from <old> to <new> in <roots>. terraform plan clean, no unexpected changes.", context="upgrade-event", tags=["domain:terraform", "type:upgrade-event"], timestamp="<now>")

# On failure + fix:
retain(bank_id="homelab-version-mgmt", content="Upgraded <provider> from <old> to <new>. Plan FAILED: <error>. Root cause: <diagnosis>. Fixed by: <change>. Lesson: <what to check next time>.", context="upgrade-event", tags=["domain:terraform", "type:upgrade-event", "type:gotcha"], timestamp="<now>")
```

### General Rules

- Always update constraints in ALL files that declare the same provider (root + referenced modules)
- Keep constraints consistent across environments that share modules
- Never commit lock file changes directly — the user runs `terraform init -upgrade` to regenerate them
- For multi-root projects, upgrade one root at a time and verify with `terraform plan`

---

## Efficiency Guide

- Batch all Registry API calls — they're fast and don't require auth
- Only research changelogs for providers with actual updates
- Group providers by namespace (hashicorp providers often share release patterns)
- For `~>` constraints, calculate the maximum allowed version before checking if an update exists within the constraint

## Automatic Memory (built into every phase)

Memory retention is NOT a separate phase — it happens automatically at the end of Phase 1 and after each upgrade in Phase 2. If you completed a phase without retaining, you did it wrong.

### When to retain (automatic triggers)

| Trigger | What to retain | Tags |
|---------|---------------|------|
| After Phase 1 report | Classification reasoning, new gotchas, constraint/lock mismatches, deployment context | `type:classification-reasoning`, `type:gotcha`, `type:structure` |
| After each Phase 2 upgrade+verify | Upgrade outcome, plan failures and fixes | `type:upgrade-event`, `type:gotcha` (if failure) |

### What to retain

- **Classification reasoning**: WHY a level was assigned (e.g., "AWS 6.x L5 because boolean strictification affects any resource")
- **Deployment context**: What resources are actually used (e.g., "vultr-cluster uses plain VPS only, not VKE")
- **Gotchas**: Lock mismatches, plan failures, constraint conflicts
- **Upgrade outcomes**: Success or failure with details

### What NOT to retain

- Full report text, raw API responses, version numbers alone
- "All providers up to date" without learnings
- Sub-agent verbose output

---

## Notes on Specific Patterns

- **Terraform Cloud backends**: Lock file regeneration requires TFC auth. Note this in upgrade instructions.
- **Multi-root with shared modules**: When a local module declares `required_providers`, the constraint must be compatible with ALL roots that use it. Check for constraint conflicts.
- **Lock file platform hashes**: After `terraform init -upgrade`, hashes are only generated for the current platform. If the project needs multi-platform support, use `terraform providers lock -platform=linux_amd64 -platform=darwin_amd64` etc.
- **Constraint mismatches**: If a lock file's `constraints` field differs from the current `.tf` constraint, flag it. This usually means the constraint was updated without re-running `terraform init`.
