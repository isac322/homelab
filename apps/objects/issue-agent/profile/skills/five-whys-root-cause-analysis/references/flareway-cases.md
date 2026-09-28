# Flareway Case Studies: Issues #11–#14

Four real defects walked through the `five-whys-root-cause-analysis` workflow. The cases emphasize evidence-bearing causal graphs, counterfactuals, occurrence/escape/containment branches, stopping points, and extent sweeps. They are compact case studies, not complete report templates: backward “therefore” reads, corrective-action tables, and interim-containment fields are omitted for brevity and remain required by the skill.

## Observation context

All four effects were observed on 2026-09-17 on a QA image (`ghcr.io/isac322/flareway@sha256:8a746b11…`) built from commit `9187ade`, an earlier head of open PR #8 rather than `main`, a release, or the PR's current head. For case #11, the dataplane-retraction amplifier existed only on that deployed commit while the SSA status hazard predated it; the full artifact/tag/main matrix remains in the `issue-validation` reference.

Fix provenance belongs to `issue-validation` and is intentionally omitted here.

## Case #11 — Gateway dataplane recycles while connector credentials flap

**Defect.** The public e2e spec never reaches `Programmed=True` (poll expired at ~307s); the dataplane Deployment is scaled to zero and back roughly every two seconds for the entire wait.

**Sequence.** A Gateway reconcile first observes a tunnel with verified ownership and credentials, then a later status apply from a stale informer-cached object omits tunnel-owned fields. The same SSA field manager interprets omission as deletion. A following Gateway reconcile enters the credential-wait state, and the deployed `9187ade` branch retracts the dataplane. A later successful tunnel reconcile restores the fields and the Gateway recreates the dataplane; the cycle repeats.

**Causal graph.**

```text
Programmed never converges + pods recycle every ~2s
└── AND: two concurrent mechanisms
    ├── Tunnel-owned credential/identity status can disappear
    │   └── flareway-tunnel applies a full SSA status document built
    │       from informer-cached state
    │       evidence: Kubernetes 1.35 envtest showed a stale apply by
    │       the same manager deletes omitted credential refs while
    │       leaving ownershipVerified=true; another manager does not
    │       └── omission and intentional revocation are not distinct
    │           in the apply contract
    └── Credential-wait branch tears down the dataplane
        evidence: code-path attribution — 9187ade added
        retractGatewayDataplane() and created=true to that
        branch (gateway_cloudflare.go:294-296), so every 2s
        requeue patches replicas to zero and a recovered pass
        restores them (gateway_controller.go:73, :286-287,
        :1113-1151); the ~2s recycling itself was observed live
        on the deployed image
```

**Bounded open branch — exact stale-apply trigger.** The deletion mechanism is executed-proven. The specific early-return path that supplied each stale document remains open: first-convergence informer lag alone, or that lag combined with a transient `GetTunnel`, `GetTunnelToken`, or connection-listing failure. The discriminator is a continuous tunnel condition/status/Secret/managedFields series. This uncertainty does not weaken the proven invariant failure.

**Counterfactuals.**

- If same-manager status applies preserve live protected fields unless revocation is explicit, credential status cannot flap from omission.
- If the recoverable credential-wait branch does not scale down an already-owned dataplane, a transient status gap clears publication but does not recycle pods.
- Either correction removes pod churn; both are required to repair the independent status-ownership and dataplane-lifecycle invariants.

**Branches.**

- *Occurrence:* cached partial state was used as an authoritative full SSA replacement without an explicit omission-versus-clear contract. The deployed branch separately treated a recoverable dependency wait as teardown.
- *Escape:* tests wrote tunnel status atomically and did not exercise stale same-manager applies or both reconcilers against a transitioning status.
- *Containment:* dataplane retraction amplified a self-healing status deletion into repeated workload disruption; failure diagnostics omitted the series needed to attribute the exact early-return trigger.

**Stop point.** Two actionable invariants: preserve live tunnel-owned fields unless a caller declares revocation, and never tear down an owned dataplane for a recoverable credential convergence gap.

## Case #12 — NetworkRoute ipLookup failure poisons peers and blocks deletion

**Defect.** A managed `NetworkRoute` whose `spec.ipLookup` fails after remote creation persists `status.routeId` with empty `status.applied`; that zombie state invalidates every peer route on the account and makes the object undeletable, leaking the remote route.

**Causal graph.**

```text
routeId persisted, applied empty (the zombie node)
evidence: patchStatusInternal writes identity under
remote.ID != "" && (ConditionTrue || owned || observeOnly)
but writes applied only under ConditionTrue
(networkroute_controller.go ≈L452-475); finishIPLookupError
runs with owned=true, ConditionFalse
├── Effect 1: every peer on the account flips to Invalid
│   evidence: checkOverlap treats RouteID != "" as proof the
│   applied claim is complete and hard-rejects before any
│   namespace/vnet/prefix comparison (≈L264-268); live QA showed
│   non-overlapping CIDRs in unrelated vnets rejected
└── Effect 2: object undeletable, remote route leaks
    evidence: reconcileDelete builds the expected identity solely
    from status.applied (≈L345-350); empty applied →
    validateObservedNetworkRoute mismatch → "refusing to delete
    changed network route" → finalizer stays; live QA required
    manual remote deletion
```

**Counterfactuals.**

- If `applied` were recorded on the converged managed path before the lookup ran, both effects disappear — the zombie node never forms.
- If `checkOverlap` and `reconcileDelete` fell back to the observed identity (`status.network`/`tunnelId`/`virtualNetworkId`, which *is* persisted), both effects also disappear.
- Two adequate fix points exist; the stronger one repairs the invariant "`status.applied` reflects the converged remote claim" because it removes the inconsistent state rather than teaching every consumer to tolerate it.

**Branches.**

- *Occurrence:* the persist split — identity written under a wider condition than `applied` — is the root cause.
- *Escape:* the envtest fake converts a no-match into a `missing` error and can never return a 200-with-empty-ID, so the `remote.ID == ""` branch is unreachable in tests; no fault-isolation test exists.
- *Containment:* two independent containment failures — peer poisoning (missing isolation between routes) and delete refusal (missing identity fallback) — turned one bad status write into a cluster-wide outage plus a remote leak.

**Latent twin.** The identical persist split and `checkOverlap` guard exist in `hostnameroute_controller.go` (≈L486/499, ≈L352-356). A fix scoped to NetworkRoute alone leaves the mechanism alive.

**Stop point.** Broken invariant: a partially written status must not be interpreted as a complete claim by other code paths. Actionable and in scope.


## Case #13 — Namespace grant label changes do not requeue ServiceToken

**Defect.** A `Ready=True` ServiceToken keeps its authorization after its namespace stops matching the account's `namespaceSelector`; it flips to `RefNotPermitted` only after an unrelated annotation forces a reconcile (observed live).

**Causal graph.**

```text
Stale authorization after namespace-label revocation
└── No event source enqueues the token on label change
    evidence: ServiceTokenReconciler.SetupWithManager watches the
    ServiceToken, its owned Secret, and CloudflareAccount — not
    Namespace (source-verified on v0.1.1: For(ServiceToken).Owns(Secret)
    .Watches(CloudflareAccount)); authorization is evaluated from
    current namespace labels inside Reconcile, so after a
    successful reconcile nothing re-triggers evaluation
    └── AND: authorization is a point-in-time check, not a
        continuously enforced gate — correct per reconcile, but
        only as fresh as the last event
```

**Counterfactual.** With a Namespace watch (or an index mapping namespaces to granted objects), the label removal enqueues the token and revocation lands within one reconcile — the observed 30-second-plus staleness cannot occur. Necessity was live-observed; sufficiency is source-verified, with the executed check being PR #16's envtest (fixed-in-PR, unmerged).

**Branches.**

- *Occurrence:* the control loop lacks an event source for one of its inputs — a feedback-loop defect, the cleanest kind of root cause.
- *Escape:* no envtest asserts a watch-triggered transition to `RefNotPermitted` without mutating the resource; existing tests poke the object itself, which masks the missing watch.
- *Containment:* revocation latency is unbounded — the stale grant persists until any unrelated event happens to requeue the object. For an authorization mechanism, delayed revocation *is* the impact; occurrence and containment coincide here.

**Stop point.** Missing watch on an authorization input — an actionable control-loop defect inside the team's scope. The extent-of-condition sweep found 13 grant-gated reconcilers in total with the same missing input event.


## Case #14 — E2E cleanup deletes CloudflareAccount before tunnel finalizers finish

**Defect.** `AfterSuite` deletes the cluster-scoped `CloudflareAccount` while a namespaced `CloudflareTunnel` finalizer still needs it; the tunnel enters `CleanupBlocked=True`/`CredentialsUnavailable` and the test namespace stays `Terminating` indefinitely — after both a passing and a failing run.

**Causal graph.**

```text
Namespace stuck Terminating, tunnel CleanupBlocked
└── Account deleted before dependents finished cleanup
    evidence: code-path attribution — AfterSuite deletes
    CloudflareAccount and the namespace immediately
    (suite_test.go:157-158 on v0.1.1) with no drain of
    namespaced Flareway resources; the missing-account tunnel
    condition "get CloudflareAccount for cleanup: ... not
    found" was observed live
    └── AND: tunnel cleanup legitimately requires account
        credentials — the controller correctly refuses
        unauthenticated remote deletion (fail-closed is the
        intended contract, not a second bug)
```

**Counterfactuals.**

- If teardown waited for each dependency tier (routes → Gateway → tunnels → namespace → account), the account would outlive every finalizer that needs it — defect gone.
- "Let the controller clean up without the account" fails the counterfactual in the other direction: removing the credential requirement would break the fail-closed contract. The defect lives in the harness teardown order, not the controller — an important scoping result.

**Branches.**

- *Occurrence:* teardown violates reverse-dependency ordering — a missing invariant in the suite, not the product.
- *Escape:* no failure-path cleanup test; a delayed tunnel deletion was never exercised, so the ordering assumption held only on the happy path — and not even there, since a *passing* run also stranded the namespace.
- *Containment:* once the account is gone there is no in-suite recovery path; residue collides with later runs and manual remote deletion by recorded ID is required.

**Stop point.** Broken invariant: credentials and shared fixtures must outlive every dependent's finalizer. Actionable: drain in reverse-dependency tiers and abort later stages when a tier cannot converge.


## Cross-case lessons

- **AND branches are common in controller defects.** #11 needed both the status flap and the amplifier; #14 needed both the ordering violation and the legitimate credential requirement. Fixing either side may hide the symptom while leaving another invariant broken.
- **Bound uncertainty without guessing.** #11 confirmed the SSA deletion mechanism while leaving the exact stale-apply trigger as an open branch with a named discriminator.
- **Escape and containment are separate questions.** Every case had a distinct escape cause, and #12 had two containment failures worth independent corrective actions.
- **Sweep the extent of condition.** #12 found the HostnameRoute twin; #13 found 13 grant-gated reconcilers with the same missing input event.
- **The defect may live in the harness.** #14's counterfactual proved the controller's refusal was correct; the causal analysis located the defect in teardown ordering.
