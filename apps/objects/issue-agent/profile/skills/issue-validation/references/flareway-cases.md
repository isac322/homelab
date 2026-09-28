# Flareway validation cases: issues #11–#14

Snapshot: 2026-09-17T15:11:58Z at `origin/main` `28f84d5` and the PR heads listed below. Repository: `isac322/flareway`. Re-verify moving branch, release, artifact, and deployment state before citing it. These cases show the issue-validation workflow applied end to end: atomic claims, three-state version comparison, verdicts, fix provenance, and the fixed-in-PR / merged / released / deployed distinction.

## Version landscape

Four code states matter for every verdict:

| State | Commit | Notes |
|---|---|---|
| v0.1.0 release | `5554f30` | Published 2026-09-16 |
| v0.1.1 release = `origin/main` | `28f84d5` | Published 2026-09-17; current main HEAD |
| Deployed QA image | `9187ade` | `ghcr.io/isac322/flareway@sha256:8a746b11…`; built from an earlier head of open PR #8, **not** from main, any tag, or the current PR head |
| PR #8 head | `4746765` | `9187ade` plus `fix(controller): preserve dataplane during credential recovery`; still open, unmerged |

The deployed image is the trap this snapshot exists to teach: it was built from a commit on an unmerged PR branch, so "deployed" matched neither main, any release, nor the PR's current head. Every issue below was validated against all relevant states, and `9187ade` was confirmed absent from both `main` and `v0.1.1` by ancestry check.

## Issue #11 — Gateway dataplane recycles while connector credentials flap

**Verdict:** CONFIRMED_CURRENT (evidence grade A for the deletion primitive, B for the trigger attribution).

**Claim split.** One atomic defect with two layers, validated separately:

1. *Origin:* an SSA status-ownership hazard. `flareway-tunnel` is the sole field manager for `status.connectorTokenSecretRef`; `patchOwnedStatus` builds its SSA document from the cached object, `omitempty` drops nil fields, and SSA treats omission of an owned field as deletion. Executed reproduction against a Kubernetes 1.35 envtest API server: a stale same-manager apply deleted both credential refs while leaving `ownershipVerified=true`; an apply from another manager did not.
2. *Amplifier:* in `9187ade` only, the credential-waiting branch calls `retractGatewayDataplane`, scaling the Gateway-owned Deployment to zero on every failing pass (~2s requeue). Before `9187ade` the branch only cleared the xDS snapshot. Code-path attribution is source-level; the ~2s pod recycling itself was observed live on the deployed image. This explains the observed pod recycling; it is an amplifier relation, not the cause.

**Version states.** SSA hazard: present in v0.1.0, v0.1.1/main, and the deployed image. Amplifier: introduced by `9187ade` and behaviorally present only in the deployed image; PR #8's current head `4746765` already removes it. The tunnel controller source is byte-identical across v0.1.0, main, and `9187ade`.

**Fix status.** PR #19 (`fix/tunnel-status-preservation`, head `32dc23d`, "Related to #11") is **open — fixed-in-PR only** for the SSA status-ownership hazard. It preserves live tunnel-owned fields, including `deletedAt`, unless the current path declares authoritative clear intent, and preserves a recorded Gateway binding until Direct-mode drain completes. PR #8 head `4746765` separately stops scaling the dataplane down in the recoverable credential-waiting state. Neither repair is merged, released, or deployed. The exact early-return trigger for each deleting reconcile remains bounded but not attributed; the issue lists the status/Secret/managedFields series needed to distinguish it.

## Issue #12 — NetworkRoute ipLookup failure poisons peers and blocks deletion

**Verdict:** CONFIRMED_CURRENT (evidence grade A; reproduced on a live QA cluster).

**Claim split.** One producer defect with two consumer blast radii, each validated:

1. *Producer:* `patchStatusInternal` persists observed identity (`status.routeId`, network, tunnel, vnet) when `owned=true`, but writes `status.applied` only on terminal `ConditionTrue`. A post-write `ipLookup` failure leaves `routeId` set with `applied` empty.
2. *Peer poisoning:* `checkOverlap` treats `routeId != ""` plus incomplete `applied` as a hard `Invalid` before any namespace/vnet/prefix comparison — every peer route on the account flips `Accepted=False`, including non-overlapping CIDRs.
3. *Undeletable object:* `reconcileDelete` builds its expected target solely from `status.applied`; with it empty, the live remote mismatches, the delete is refused, the finalizer stays, and the remote route leaks. Requires `deletionPolicy: Delete`; the default `Orphan` skips remote deletion.

**Version states.** Present in v0.1.0, v0.1.1/main, and the deployed image; the route controller is byte-identical across all three. Not introduced by `9187ade`.

**Fix status.** PR #18 (`fix/private-route-partial-status`, head `75699d6`, "Closes #12") is **open — fixed-in-PR only**. It persists `status.applied` independently of later IP lookup readiness and repairs the structurally identical HostnameRoute twin. Nothing is merged, released, or deployed.

## Issue #13 — Namespace grant label changes do not requeue ServiceToken authorization

**Verdict:** CONFIRMED_CURRENT (evidence grade A; reproduced live).

**Mechanism bound.** `ServiceTokenReconciler.SetupWithManager` watches the ServiceToken, its owned Secret, and CloudflareAccount — but not Namespace. Grant evaluation is correct and fail-closed when it runs; a label-only Namespace change produces no event, so stale `Accepted=True` authorization persists until an unrelated reconcile (periodic requeue is capped at six hours). An audit found 13 grant-gated reconcilers missing the Namespace watch; eight others already register it.

**Version states.** Present in v0.1.0, v0.1.1/main, and the deployed image; byte-identical across all three.

**Fix status.** PR #16 (`fix/namespace-grant-watch`, head `79378f9`, "Closes #13") is **open — fixed-in-PR only**. It adds the Namespace watch to all 13 reconcilers, scopes namespaced mappers to the changed namespace with no label predicate (label removal is exactly the event that must fire), and adds an envtest proving revocation and restoration without Cloudflare calls. Not merged, not in any release, not deployed. It deliberately does not revoke already-issued remote tokens — that is a separate lifecycle design decision.

## Issue #14 — E2E cleanup deletes CloudflareAccount before tunnel finalizers finish

**Verdict:** CONFIRMED_CURRENT (evidence grade A) — and a verdict-precision case: the defect is in the **e2e harness**, not the controller. The controller correctly fails closed (`CleanupBlocked=True/CredentialsUnavailable`) when the harness removes the account and its credential Secret while a managed CloudflareTunnel finalizer still needs them.

**Mechanism bound.** `AfterSuite` deletes `GatewayClass`, `GatewayClassConfig`, and `CloudflareAccount` before the namespace; the credential Secret lives inside the per-run namespace, so dependents must finish finalizing before Namespace deletion is issued. `deleteObject` is fire-and-forget and the namespace wait discards its result, so teardown failure cannot fail the suite. Controller-created tunnels (owned by Gateway reconciliation) are invisible to spec-declared cleanup lists.

**Version states.** The e2e code and the tunnel cleanup path are byte-identical across v0.1.0, v0.1.1/main, and the deployed image; the fail-closed refusal predates v0.1.0.

**Fix status.** PR #17 (`fix/e2e-cleanup-order`, head `a41ec86`, "Closes #14") is **open — fixed-in-PR only**. It discovers Flareway/Gateway API kinds via RESTMapper, drains them in reverse-dependency tiers with per-tier waits, deletes the namespace only after all namespaced finalizers complete, then removes cluster-scoped fixtures, and aggregates teardown failures into suite failures. Not merged, not in any release, not deployed.

## PR ledger

| PR | State | Head | Relation to issues |
|---|---|---|---|
| #8 `fix(controller): fail closed on dependency loss` | OPEN | `4746765` | **Amplifier** of #11: its earlier head `9187ade` is the deployed QA image and introduced dataplane retraction; the current head contains the separate dataplane-preservation correction. |
| #16 `fix(controller): requeue grants on namespace changes` | OPEN | `79378f9` | Fix for #13 — fixed-in-PR only |
| #17 `fix(e2e): drain resources before fixture teardown` | OPEN | `a41ec86` | Fix for #14 — fixed-in-PR only |
| #18 `fix(controller): preserve private route applied state` | OPEN | `75699d6` | Fix for #12 — fixed-in-PR only |
| #19 `fix(controller): preserve tunnel status ownership` | OPEN | `32dc23d` | Fix for #11's SSA hazard — fixed-in-PR only |

## Status vocabulary these cases enforce

- **Fixed-in-PR:** #11–#14. The commits exist on open PR branches; saying only "fixed" would be wrong.
- **Merged:** none of the four issue fixes.
- **Released:** none; v0.1.1 contains none of the fix commits.
- **Deployed:** none; the deployed image predates every fix and is itself built from an unmerged PR head.
- **Amplifier:** PR #8's deployed head worsened #11's symptom without causing it — a distinct relation label, not "duplicate" or "related".
- **Harness vs product:** #14's verdict names the e2e harness as the defective component; the controller's refusal was correct fail-closed behavior, and the fix must not weaken it.

Each issue's comment thread carries the completed validation record; confirmed claims were then handed to causal analysis (Five Whys) with the mechanism bound, disproved hypotheses, and open trigger questions intact.
