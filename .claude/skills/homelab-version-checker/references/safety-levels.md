# Safety Level Classification — Detailed Guide

## Classification Principle

Read ALL release notes between the current version and the latest version. The safety level is determined by the **highest-risk change** across the entire version range. A single breaking change in v1.5.0 makes the entire v1.3.0 -> v1.7.0 upgrade a Level 5, even if v1.6.0 and v1.7.0 were clean.

---

## Level 1: Safe (Drop-in Upgrade)

**ALL of these must be true:**
- No configuration keys renamed, removed, or restructured
- No new required configuration fields
- No CRD changes requiring manual intervention
- No database or storage format changes
- No deprecated features currently in use by this deployment
- Release notes contain no mention of "breaking", "migration", or "manual steps"
- Patch or minor version bump (major version unchanged) — though a major bump CAN be L1 if the project explicitly states full backward compatibility

**Typical scenarios:**
- Bug fix releases (1.2.3 -> 1.2.4)
- Security patches
- Performance improvements
- New optional features with backward-compatible defaults

**Execution:** Bump `targetRevision` (and image tag if separately pinned). No other changes.

---

## Level 2: Config (Values/Settings Changes)

**At least one of these is true:**
- Configuration keys renamed or restructured in values schema
- New required values without sensible defaults
- Deprecated config options the deployment currently uses (still functional but warn)
- Default behavior changed in ways that affect this deployment
- Chart template restructured (e.g., Deployment -> StatefulSet for a component)

**Typical scenarios:**
- Helm chart reorganizes values.yaml structure
- New required environment variable or secret reference
- Default feature toggled (opt-out became opt-in or vice versa)
- prometheus-stack minor bumps often rename nested values
- Chart switches from Deployment to StatefulSet for a sub-component

**Execution:**
1. Identify the exact values diff between old and new chart defaults:
   ```bash
   # Compare default values between versions
   helm show values <repo>/<chart> --version <old> > /tmp/old-values.yaml
   helm show values <repo>/<chart> --version <new> > /tmp/new-values.yaml
   diff /tmp/old-values.yaml /tmp/new-values.yaml
   ```
2. Cross-reference with the deployment's values override files
3. Update values files to match new schema
4. Bump `targetRevision`

---

## Level 3: External (Outside-Cluster Work)

**At least one of these is true:**
- New credentials, API keys, or tokens needed from an external service
- Webhook endpoints need creation or updating
- DNS record changes required
- Cloud provider configuration changes (IAM policies, storage buckets, etc.)
- TLS certificate regeneration or new certificate issuance
- External service API migration (e.g., provider deprecated an API version)
- Coordination with external teams or services needed

**Typical scenarios:**
- Auth provider changed OAuth flow, new client ID/secret needed
- Monitoring service requires new API key for a new feature
- cert-manager issuer needs updated credentials after provider API change
- External DNS provider changed authentication method

**Execution:**
1. List all external prerequisites as a numbered checklist
2. Provide direct links or commands for each external step
3. Wait for user confirmation that all prerequisites are done
4. Then apply config + version changes

---

## Level 4: Migration (Data Migration Required)

**At least one of these is true:**
- Database schema migration needed (not automatic)
- Persistent volume data format changed
- Data export and re-import required
- Storage backend migration
- Stateful component needs draining, rebuilding, or reprovisioning
- CRD stored version migration (e.g., v1alpha1 -> v1)

**Typical scenarios:**
- PostgreSQL major version upgrade (dump/restore cycle)
- Rook-Ceph OSD upgrade requiring controlled restart sequence
- Mimir/Loki storage format change
- CRD apiVersion bump requiring stored object migration
- etcd data format changes

**Execution:**
1. **Backup plan**: Document exactly what to back up and how
2. **Migration steps**: Ordered, specific, with verification at each stage
3. **Rollback plan**: How to revert if migration fails
4. **Downtime estimate**: Will the service be unavailable? For how long?
5. Execute only with user confirmation at each critical step

---

## Level 5: Breaking (Major Architecture Changes)

**At least one of these is true:**
- Major version bump with incompatible API changes
- Fundamental architecture redesign
- Complete rewrite of core components
- Removal of features the deployment depends on
- Changes requiring coordinated updates to other cluster workloads
- Helm chart fundamentally restructured (different sub-charts, different CRDs)

**Typical scenarios:**
- Traefik v2 -> v3 (IngressRoute CRD API changes, middleware restructuring)
- Rook-Ceph major version (operator + cluster + OSD coordinated upgrade)
- ArgoCD major version with RBAC model or Application spec changes
- Kubernetes API removals (e.g., PodSecurityPolicy -> Pod Security Standards)
- Complete chart rewrite (different maintainer, different architecture)

**Execution:**
1. **Impact analysis**: Which other workloads are affected? What breaks?
2. **Phased plan**: Break the upgrade into safe, sequential phases
3. **Testing**: Recommend testing approach (non-prod cluster first if available)
4. **Rollback**: Full rollback procedure for each phase
5. **Alternative assessment**: Is waiting or switching to an alternative better?

---

## Special Flags

### Deprecated

**Indicators:**
- GitHub repo archived
- ArtifactHub "deprecated" badge
- README or release notes mention successor
- Helm chart marked as deprecated in Chart.yaml
- Moved to a new repo/org with old repo redirecting

**Action:** Plan migration to successor. Not urgent unless combined with EOL, but should be tracked. Include the successor name and a rough migration effort estimate in the report.

### EOL (End of Life)

**Indicators:**
- Officially announced end of life
- No releases in 12+ months AND open unpatched CVEs
- Community has fully moved to successor
- Dependencies themselves are EOL

**Action:** Prioritize migration. This is a security liability. Flag prominently in the report.

---

## Edge Cases

**Multiple version dimensions**: When a workload has both a chart version AND a separate image tag (e.g., Immich chart v0.11.0 + image v2.6.3), classify based on the higher-risk of the two dimensions. Report both updates clearly.

**Coordinated upgrades**: Some upgrades must happen together (e.g., operator + CRDs, or rook-ceph operator + cluster chart). Flag these as a group and classify the group by the highest individual level.

**Rollback complexity**: A seemingly simple upgrade can be hard to roll back if it triggers irreversible changes (CRD schema changes, storage format migrations). Factor rollback difficulty into your classification.

**Skip versions**: If the gap is large (e.g., skipping 5+ minor versions), there may be accumulated breaking changes even if each individual version was minor. Read ALL intermediate release notes.
