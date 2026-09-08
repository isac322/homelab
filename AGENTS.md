# Homelab Operating Principles

## Core Operating Principles

- Follow repository instructions and existing conventions before personal defaults.
- Preserve unrelated user changes.
- Fix root causes instead of suppressing symptoms.
- Ask only when ambiguity would materially change the result.
- Verify significant behavioral changes and report exactly what was exercised.
- **Ambiguity Guard**: If workload classification, tier assignment, or resource behavior is ambiguous or difficult to determine, an agent MUST NOT guess or make an arbitrary decision: it MUST stop and ask the user before editing.

## Kubernetes Resource Management

These rules apply to every Kubernetes workload and every container in this repository, including sidecars, init containers, controllers, DaemonSets, Jobs, and operator-managed resources. Size each container independently. A product may contain workloads in different tiers; for example, an application can be Tier 3 while its database is Tier 2.

Use `MUST`, `MUST NOT`, `SHOULD`, and `MAY` as defined by RFC 2119.

### Core Sizing Rules

1. **CPU limits are unset by default.** General applications, core infrastructure, controllers, and stateful databases MUST NOT set `resources.limits.cpu`. CPU limits cause Linux CFS quota throttling (even on completely idle nodes) and induce latency jitter.
   - **Approved Exceptions**: A CPU limit MAY be set only for heavy batch/CI/build jobs (BuildKit, ARC runners, Thanos compactor) or approved CPU-heavy background tasks (Jellyfin transcoding, Immich ML) where capping node impact is intentional. Any other CPU-limit exception requires explicit user approval.
2. **CPU requests are progress guarantees, not usage caps.** Set `resources.requests.cpu` to the minimum floor that lets the workload make acceptable progress during contention. Do NOT copy historical CPU peaks into requests.
3. **Memory requests protect the active working set.** Set `resources.requests.memory` to `1.10–1.25 ×` the observed 14-day P50 of `container_memory_working_set_bytes`. This ensures the pod can start and is protected from premature Kubelet eviction under node pressure without locking up unused memory.
4. **Memory limits are blast walls.** Set `resources.limits.memory` to `1.10–1.25 ×` the greater of the observed 14-day P99 and the highest known legitimate 14-day peak. The limit acts as a blast wall to contain memory leaks or rogue queries via OOMKill before the host node (and ZFS/etcd) is endangered.
5. **Round upward.** Convert calculated memory values to practical `Mi` or `Gi` quantities by rounding up, never down.
6. **Use representative history.** Size from active, healthy periods in Thanos/Prometheus that include normal peaks, startup, compaction, and scheduled work. Do not size from a single snapshot or `kubectl top` reading.
7. **Preserve application-level constraints.** Account for configured JVM heaps, buffer pools, worker concurrency, and vendor minimums.

### Workload Tiers and Sizing Matrix

Every workload MUST be assigned exactly one tier before its resources are changed.

| Tier | Classification and Examples | CPU Request | CPU Limit | Memory Posture |
| :--- | :--- | :--- | :--- | :--- |
| **Tier 1 — Core Infrastructure** | Network, DNS, storage, GitOps, certificates, observability: Cilium, CoreDNS, CSI drivers, ZFS driver, cert-manager, external-dns, external-secrets, VersityGW, ArgoCD, Prometheus, Thanos, Loki, Alloy. | Normally `100m–250m` per primary container; sidecars/exporters `5m–25m`. | **Unset** (except Thanos compactor: 500m). | `1.10–1.25 × P50` request. Limit covers reconciliation and recovery peaks. |
| **Tier 2 — Stateful and Database** | Primary durable data services: PostgreSQL (CNPG), Valkey/Redis, MariaDB. | Steady-state demand plus startup/checkpoint progress floor (`100m–1c`). | **Unset** (CFS throttling on DB causes connection stalls). | Upper end of `1.10–1.25 × P50`. Must accommodate buffer pools and shared memory. |
| **Tier 3 — General Web and App** | General services and user applications: Hermes, Immich web/server, Jellyfin, bots, Gatus. | `10m–100m` per container floor. | **Unset** (Exception: Jellyfin transcoding `cpu: 2`). | `1.10–1.25 × P50` request; `1.10–1.25 × P99/Peak` limit. Size replicas/sidecars independently. |
| **Tier 4 — Batch, CI, and Build** | Finite, parallel, or throughput-oriented work: BuildKit, ARC runner workloads, system-upgrade jobs. | `1–1.5c` per active worker or job container floor. | **MAY be set** (e.g. BuildKit `6c`, ARC runners) to protect node from saturation. | Sized to representative successful runs. Peak in-process artifacts dictate limit blast wall. |

### Cluster-Wide Overcommit Budget

Resource changes MUST preserve host headroom. Sizing MUST respect the following cluster-wide ratios:

$$\frac{\sum \text{CPU Requests}}{\text{Allocatable Cluster CPU}} \le 1.00 \sim 1.20$$
$$\frac{\sum \text{Memory Requests}}{\text{Allocatable Cluster Memory}} \le \mathbf{0.70 \sim 0.75}$$

The memory request ceiling is strictly capped at **70–75%** because homelab nodes host ZFS ARC storage caches, kernel slab, network buffers, and OS page caches that operate outside container cgroups.

### Mandatory Operating Procedure

Before adding a workload or changing any resource request or limit, an agent MUST complete the following procedure:

1. **Identify the scheduling unit**: Enumerate all containers, sidecars, and init containers.
2. **Classify the tier**: Assign Tier 1, 2, 3, or 4 based on operational role and failure impact.
3. **Query Thanos/Prometheus**: Query at least 14 days of historical working set bytes and CPU usage.
4. **Resolve ambiguity before editing**: If the tier, expected behavior, legitimate peak, or progress requirement is ambiguous, **STOP and ask the user**. Never guess.
5. **Apply manifest shape**: Set CPU and memory requests and memory limit. Omit CPU limit unless an approved Tier 4 / high-load exception applies.
6. **Check cluster budget**: Verify that cluster-wide memory request ratio remains $\le 0.75$.
7. **Verify after rollout**: Confirm the workload becomes healthy and no unexpected scheduling failures or OOMKills occur.
