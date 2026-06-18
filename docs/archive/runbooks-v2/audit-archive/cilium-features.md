# Cilium v1.19 — Exhaustive Feature Catalog

> **Latest stable**: Cilium v1.19 (first GA Nov 2025, current patch line v1.19.x as of 2026-04-18)
> **Docs baseline**: https://docs.cilium.io/en/stable/ (v1.19.3 at time of writing)
> **Release notes**: https://github.com/cilium/cilium/releases/tag/v1.19.0
> **Helm reference**: https://docs.cilium.io/en/stable/helm-reference/
> **Upgrade guide**: https://docs.cilium.io/en/stable/operations/upgrade/

**Dependencies pinned in v1.19**: Kubernetes client v1.35, Envoy v1.35, Gateway API v1.4, GoBGP v3.37, LLVM >= 18.1.
**Minimum kernel**: 5.10 (or 4.18 on RHEL 8.10). Base eBPF features require `CONFIG_BPF=y`, `CONFIG_BPF_SYSCALL=y`, `CONFIG_BPF_JIT=y`, `CONFIG_CGROUPS=y`, `CONFIG_CGROUP_BPF=y`.

Production-readiness labels: **GA** (stable/default-safe), **Beta** (usable, some constraints, stable API not guaranteed), **Experimental/Limited** (behind flags, may change).

---

## 1. CNI / Datapath

### 1.1 CNI / IPAM modes
| Mode | Helm key | Status | Notes |
| --- | --- | --- | --- |
| `kubernetes` (uses `podCIDR` from Node) | `ipam.mode=kubernetes` | GA | Default for kube-controller-manager-driven IPAM. |
| `cluster-pool` (Cilium-managed) | `ipam.mode=cluster-pool` + `ipam.operator.clusterPoolIPv4PodCIDRList` | GA | **Default** for standalone Cilium. |
| `cluster-pool-v2beta` | `ipam.mode=cluster-pool-v2beta` | Beta | Dynamic sub-CIDR allocation from operator. |
| `multi-pool` (Multi-Pool IPAM) | `ipam.mode=multi-pool`, CRD `CiliumPodIPPool` | **Promoted to GA in v1.19** | Multiple pod CIDR pools per cluster; now supports IPsec and direct routing. |
| `crd` (CRD-backed, user populates `CiliumNode`) | `ipam.mode=crd` | GA | Bring-your-own-IPAM; operator does not allocate. |
| `eni` (AWS ENI) | `ipam.mode=eni` | GA | AWS VPC CNI-style ENI per node. |
| `azure` | `ipam.mode=azure` | GA | Azure IPAM. |
| `alibabacloud` | `ipam.mode=alibabacloud` | GA | |
| `gke` (alias for kubernetes on GKE) | `gke.enabled=true` | GA | |
| `delegated-plugin` | `ipam.mode=delegated-plugin` | GA | Delegates to another CNI plugin for IPAM. |
| **Multi-Pool node annotations** | `ipam.multiPoolNode*` fields on Node | GA | Assigns pool per workload. |
| Docs: https://docs.cilium.io/en/stable/network/concepts/ipam/ | | | |

### 1.2 Datapath (pod networking) modes
| Mode | Helm key | Kernel | Status | Notes |
| --- | --- | --- | --- | --- |
| `veth` (classic) | `bpf.datapathMode=veth` | any | GA | Traditional veth pair. |
| `netkit` (L3) | `bpf.datapathMode=netkit` | Linux **6.8+**, `CONFIG_NETKIT=y`, requires eBPF host-routing | GA | Near-zero-overhead pod device; requires `routingMode=native`, `kubeProxyReplacement=true`, `bpf.masquerade=true`. |
| `netkit-l2` | `bpf.datapathMode=netkit-l2` | 6.8+ | GA | netkit with L2 semantics (ARP/NDP). |
| `auto` | `bpf.datapathMode=auto` | — | GA (v1.17+) | Probes kernel; prefers netkit, falls back to veth. |
| **Incompatibility** | | | | netkit is **incompatible with `bpf.tproxy`**. |
| Docs: https://docs.cilium.io/en/stable/operations/performance/tuning/ | | | |

### 1.3 Routing modes
| Mode | Helm key | Status | Notes |
| --- | --- | --- | --- |
| Tunnel / **VXLAN** (default) | `routingMode=tunnel` + `tunnelProtocol=vxlan` | GA | UDP 8472. |
| Tunnel / **Geneve** | `routingMode=tunnel` + `tunnelProtocol=geneve` | GA | UDP 6081. |
| **Native / Direct routing** | `routingMode=native` + `ipv4NativeRoutingCIDR=...` (and/or `ipv6NativeRoutingCIDR`) | GA | Requires underlay that can route pod CIDRs. |
| **Auto-Direct Node Routes** | `autoDirectNodeRoutes=true` | GA | Installs direct routes between nodes sharing an L2 domain. |
| **IPv6 Underlay** | `tunnel.ipv6=true` or `underlay=ipv6` | **New GA in v1.19** | Dual-stack clusters can choose IPv6 as tunnel underlay. |
| **Endpoint routes** | `endpointRoutes.enabled=true` | GA | Install routes per-endpoint in main netns; useful for certain CNI chaining / telemetry setups. |
| **eBPF host-routing** | `bpf.hostLegacyRouting=false` (default) | GA | Bypass netfilter for pod <-> pod on same node; needed for BBR/netkit. |
| Docs: https://docs.cilium.io/en/stable/network/concepts/routing/ | | | |

### 1.4 MTU handling
- `MTU` auto-detected; override via Helm `MTU` or `cilium-agent --mtu=<n>`.
- Tunnel mode subtracts VXLAN (50) / Geneve (60+) overhead automatically.
- **Packetization-Layer Path MTU Discovery (PLPMTUD)**: **new GA in v1.19** — TCP-based MTU probing.
- **BIG TCP**:
  - IPv6 BIG TCP: `bpf.bigTCPIPv6=true`, Linux **5.19+**.
  - IPv4 BIG TCP: `bpf.bigTCPIPv4=true`, Linux **6.3+**.
  - **BIG TCP over VXLAN/Geneve tunnels**: **new GA in v1.19** (`--enable-tunnel-big-tcp` / Helm `bpf.tunnelBigTCP`).
  - BIG TCP over netkit: supported on kernel 6.8+.

### 1.5 Masquerading
| Option | Helm key | Status | Notes |
| --- | --- | --- | --- |
| iptables masquerading | `enableIPv4Masquerade=true` + `bpf.masquerade=false` | GA | Legacy; slower. |
| **eBPF masquerading** | `bpf.masquerade=true` | GA | Required for netkit/BBR/DSR; recommended default. |
| IPv6 masquerade | `enableIPv6Masquerade=true` (+ `bpf.masquerade=true`) | GA | |
| Native routing CIDR exclusion | `ipv4NativeRoutingCIDR`, `ipv6NativeRoutingCIDR` | GA | Traffic in this CIDR is not masqueraded. |
| **Configurable inter-subnet masquerade** | `ipMasqAgent.config` / `enable-ip-masq-agent` | **New in v1.19** | Customize masquerade for inter-subnet traffic. |
| **Exclude IPAM pools from masquerade** | Multi-Pool IPAM pool flag | **New in v1.19** | |
| IP-Masq-Agent compat | `ipMasqAgent.enabled=true` | GA | Google ip-masq-agent config format. |
| Docs: https://docs.cilium.io/en/stable/network/concepts/masquerading/ | | | |

### 1.6 Transparent encryption
| Mode | Helm key | Kernel | Status | Notes |
| --- | --- | --- | --- | --- |
| Off | `encryption.enabled=false` | — | GA | Default. |
| **IPsec** | `encryption.enabled=true`, `encryption.type=ipsec`, `encryption.ipsec.keyFile`/`encryption.ipsec.secretName` | XFRM kernel config | GA | Node-to-node ESP tunnels. |
| **IPsec BPF host routing** | auto with `bpf.hostLegacyRouting=false` | — | **New GA in v1.19** | Faster route lookups in IPsec mode. |
| **IPsec key rotation** | `cilium encrypt rotate-key` CLI | — | GA | |
| **VXLAN-in-IPsec (VinE)** | auto when IPsec + VXLAN | — | Beta (v1.18+) | |
| **IPIP-in-IPsec** | via virtual netdev config | — | Beta (v1.18+) | |
| **WireGuard** | `encryption.type=wireguard` | `CONFIG_WIREGUARD=y` (5.6+) | GA | Pod-to-pod via WG tunnels. |
| **Node-to-node WG** | `encryption.nodeEncryption=true` | — | GA | Also encrypts host/node traffic. |
| **Strict mode (IPsec + WG)** | `encryption.strictMode.enabled=true`, `encryption.strictMode.cidr`, `.nodeCIDRList`, `encryption.strictMode.allowRemoteNodeIdentities` | — | **New GA in v1.19** | Drops unencrypted traffic between nodes. |
| **Ztunnel** | `encryption.type=ztunnel`; namespace labels to enroll | — | **Beta in v1.19** | Per-node L4 mTLS ztunnel proxy; namespace opt-in. DaemonSet now Helm-managed (moved from operator). |
| Docs: https://docs.cilium.io/en/stable/security/network/encryption/ | | | |

---

## 2. Service & Load Balancing

### 2.1 kube-proxy replacement (KPR)
| Feature | Helm key | Kernel | Status |
| --- | --- | --- | --- |
| Full KPR | `kubeProxyReplacement=true` | 4.19.57+ (5.7+ for socketLB) | GA |
| Partial / hybrid | `kubeProxyReplacement=false` + individual `socketLB.enabled`, `nodePort.enabled`, `externalIPs.enabled`, `hostPort.enabled` | — | GA |
| Socket LB | `socketLB.enabled=true` | 5.7+ | GA |
| Socket LB host-namespace only | `socketLB.hostNamespaceOnly=true` | 5.7+ | GA |
| NodePort | `nodePort.enabled=true`, `nodePort.range` | — | GA |
| HostPort | `hostPort.enabled=true` | — | GA |
| ExternalIPs | `externalIPs.enabled=true` | — | GA |
| Session affinity | Service `sessionAffinity: ClientIP` | — | GA |
| External Traffic Policy (Local/Cluster) | Service field | — | GA |
| Internal Traffic Policy | Service field | — | GA |
| KPR healthz | `kubeProxyReplacementHealthzBindAddr` | — | GA |
| HostPort / HostNetwork services | `hostPort.enabled=true` | — | GA |
| Docs: https://docs.cilium.io/en/stable/network/kubernetes/kubeproxy-free/ | | | |

### 2.2 Load-balancing algorithms & DSR
| Option | Helm key | Status | Notes |
| --- | --- | --- | --- |
| `random` (default) | `loadBalancer.algorithm=random` | GA | |
| `maglev` (consistent hashing) | `loadBalancer.algorithm=maglev`, `maglev.tableSize` | GA | Per-service override via annotation `service.cilium.io/lb-algorithm`. |
| SNAT mode | `loadBalancer.mode=snat` (default) | GA | |
| DSR mode | `loadBalancer.mode=dsr` | GA | Requires native routing. |
| Hybrid SNAT/DSR | `loadBalancer.mode=hybrid` | GA | TCP → DSR, UDP → SNAT. |
| **DSR dispatch: `opt`** (default) | `loadBalancer.dsrDispatch=opt` | GA | Carries svc IP/port in IP options. |
| **DSR dispatch: `ipip`** | `loadBalancer.dsrDispatch=ipip` | GA | IPIP encapsulation. |
| **DSR dispatch: `geneve`** | `loadBalancer.dsrDispatch=geneve` | GA | Geneve encap; avoids IP option drops. |
| **XDP acceleration** | `loadBalancer.acceleration=native` (or `best-effort`) | requires XDP-capable NIC driver | GA | XDP fast-path for N-S LB. |
| Service topology aware | `endpointRoutes` + `service.kubernetes.io/topology-mode=Auto` | GA | Per standard K8s topology-aware routing. |
| Docs: https://docs.cilium.io/en/stable/network/kubernetes/kubeproxy-free/ | | | |

### 2.3 LoadBalancer IPAM (LB IPAM)
| Feature | Helm key / CRD | Status | Notes |
| --- | --- | --- | --- |
| LB IPAM controller | Always on (activates on first `CiliumLoadBalancerIPPool`) | GA | |
| CRD `CiliumLoadBalancerIPPool` | cilium.io/v2 | GA | Pool with `blocks`, optional `serviceSelector`. |
| IP sharing annotation | `lbipam.cilium.io/sharing-key` | GA | Multiple services share one LB IP. |
| IP requesting annotation | `lbipam.cilium.io/ips` | GA | Request specific IPs. |
| Namespace-scoped sharing | `lbipam.cilium.io/sharing-cross-namespace` | GA | |
| Docs: https://docs.cilium.io/en/stable/network/lb-ipam/ | | | |

### 2.4 Node IPAM LB
| Feature | Helm key | Status | Notes |
| --- | --- | --- | --- |
| Node IPAM LB | `nodeIPAM.enabled=true` | GA (introduced v1.16) | Service with `loadBalancerClass: io.cilium/node` uses node IPs as external IPs. |
| Default LB IPAM class | `defaultLBServiceIPAM=nodeipam` | GA | Make it the default. |
| Docs: https://docs.cilium.io/en/stable/network/node-ipam/ | | | |

### 2.5 L2 announcements (ARP/NDP-based LB)
| Feature | Helm key / CRD | Status | Notes |
| --- | --- | --- | --- |
| L2 announcements | `l2announcements.enabled=true`, plus `k8sClientRateLimit.*` tuning | **Beta** | Requires `kubeProxyReplacement=true` (or socketLB + externalIPs). |
| CRD `CiliumL2AnnouncementPolicy` | cilium.io/v2alpha1 | Beta | Leader-elected ARP responder per service. |
| **IPv6 NDP advertisements** | part of L2 announcements | **New GA in v1.19** | ND support added. |
| Gratuitous ARP | automatic on leadership change | Beta | |
| Docs: https://docs.cilium.io/en/stable/network/l2-announcements/ | | | |

### 2.6 BGP Control Plane
| Feature | Helm key / CRD | Status | Notes |
| --- | --- | --- | --- |
| BGP Control Plane | `bgpControlPlane.enabled=true` | GA | GoBGP-backed. |
| **v1 API (deprecated)**: `CiliumBGPPeeringPolicy` | cilium.io/v2alpha1 | Removed in v1.19 | Migrate to v2. |
| **v2 API**: `CiliumBGPClusterConfig` | cilium.io/v2alpha1 → v2 | GA | Cluster-wide BGP config per node selector. |
| **v2 API**: `CiliumBGPPeerConfig` | cilium.io/v2alpha1 → v2 | GA | Reusable peer settings. |
| **v2 API**: `CiliumBGPAdvertisement` | cilium.io/v2alpha1 → v2 | GA | Service/Pod CIDR/Primary IP advertisement. |
| **v2 API**: `CiliumBGPNodeConfig` | per-node, operator-managed | GA | |
| **v2 API**: `CiliumBGPNodeConfigOverride` | cilium.io/v2alpha1 → v2 | GA | Finer per-node overrides. |
| MD5 TCP auth | `CiliumBGPPeerConfig.authSecretRef` | GA | |
| Graceful restart | `gracefulRestart.*` on peer | GA | |
| Multi-hop | `ebgpMultihop` | GA | |
| BFD | `bfdProfileRef` | Beta | |
| **Interface advertisement** | `CiliumBGPAdvertisement` type `Interface` | **New GA in v1.19** | Advertise IPs from local interfaces (multi-homed setups). |
| **Source IP override** | `CiliumBGPPeerConfig.sourceInterface` | **New GA in v1.19** | Bind BGP session to loopback. |
| **Empty-route withdrawal** | advertisement `withdrawOnEmptyEndpoints` | **New GA in v1.19** | Withdraw route when 0 endpoints. |
| Docs: https://docs.cilium.io/en/stable/network/bgp-control-plane/ | | | |

---

## 3. Ingress / Gateway API

### 3.1 Gateway API (v1.4, pinned in v1.19)
| Feature | Helm key / CRD | Status | Notes |
| --- | --- | --- | --- |
| Gateway API enable | `gatewayAPI.enabled=true`, `gatewayAPI.gatewayClassName` | GA | GatewayClass `cilium`. |
| `Gateway` | gateway.networking.k8s.io/v1 | GA | |
| `HTTPRoute` | v1 | GA | |
| `TLSRoute` | v1alpha2 | Beta | TLS passthrough. |
| `GRPCRoute` | v1 | GA | |
| `TCPRoute` | v1alpha2 | **Experimental** in v1.19 | |
| `UDPRoute` | v1alpha2 | **Experimental** in v1.19 | |
| `ReferenceGrant` | v1beta1 | GA | |
| `GatewayClassConfig` / parameters | CEL-validated | GA | |
| **GAMMA support** (mesh via Services) | `gatewayAPI.enableGatewayAPIGAMMA=true` | Beta | HTTPRoute and (**new in v1.19**) GRPCRoute attach to Services. |
| Static gateway addresses | `Gateway.spec.addresses` | GA | (since v1.17). |
| HTTPS / TLS termination | `Gateway.spec.listeners[].tls` | GA | |
| Passthrough TLS | `TLSRoute` + listener mode `Passthrough` | GA | |
| HTTPS redirect | `HTTPRoute.filters.RequestRedirect` | GA | |
| Traffic splitting / weighting | `HTTPRoute.backendRefs[].weight` | GA | |
| Header/URL rewriting | `HTTPRoute.filters.RequestHeaderModifier`, `URLRewrite` | GA | |
| **HTTP retries** | `HTTPRoute.retry` (added v1.17) | GA | |
| **Request mirroring fractions** | `HTTPRoute.filters.RequestMirror.fraction` (added v1.17) | GA | |
| Method/query-param matching | `HTTPRoute.match` | GA | |
| cert-manager integration | via `Gateway` with cert-manager annotations | GA | |
| Proxy protocol | `gatewayAPI.enableProxyProtocol=true` (listener option) | GA | |
| ALPN / HTTP/2 | via Envoy listener defaults | GA | Envoy v1.35. |
| Docs: https://docs.cilium.io/en/stable/network/servicemesh/gateway-api/gateway-api/ | | | |

### 3.2 Kubernetes Ingress (legacy)
| Feature | Helm key | Status | Notes |
| --- | --- | --- | --- |
| Ingress controller | `ingressController.enabled=true`, `ingressController.default=true`, `ingressController.loadbalancerMode=dedicated|shared` | GA | Ingress class `cilium`. |
| TLS termination | `Ingress.spec.tls` | GA | |
| HTTPS redirect annotation | `ingress.cilium.io/force-https=enabled` | GA | |
| Path types: `Exact`, `Prefix`, `ImplementationSpecific` | standard | GA | |
| cert-manager integration | standard | GA | |
| Migration guide | Ingress → Gateway migration docs | GA | |
| Docs: https://docs.cilium.io/en/stable/network/servicemesh/ingress/ | | | |

### 3.3 Envoy proxy
| Feature | Helm key / CRD | Status | Notes |
| --- | --- | --- | --- |
| Embedded Envoy (default) | `envoy.enabled=false` | GA | Runs inside `cilium` agent pod. |
| **Standalone Envoy DaemonSet** | `envoy.enabled=true` | GA | `cilium-envoy` DS; UDS to agent. |
| CRD `CiliumEnvoyConfig` | cilium.io/v2 | GA | Namespaced custom Envoy filters/listeners. |
| CRD `CiliumClusterwideEnvoyConfig` | cilium.io/v2 | GA | Cluster-scoped. |
| L7 rate limiting | via CEC | GA | |
| L7 circuit breakers | via CEC | GA | |
| L7 URL rewriting | via CEC | GA | |
| **TLS via SDS** (secrets discovery) | default for Envoy-managed TLS | **GA since v1.17** | Faster secret updates, less policy recompute. |
| TPROXY (eBPF) | `bpf.tproxy=true` | GA | **Incompatible with netkit.** |
| Docs: https://docs.cilium.io/en/stable/security/network/proxy/envoy/ | | | |

---

## 4. Network Policy

### 4.1 Policy models
| Policy | API | Scope | Status |
| --- | --- | --- | --- |
| Kubernetes `NetworkPolicy` | networking.k8s.io/v1 | Namespace | GA |
| Kubernetes `AdminNetworkPolicy` (ANP) | policy.networking.k8s.io/v1alpha1 | Cluster, priority | Beta (since v1.17) |
| Kubernetes `BaselineAdminNetworkPolicy` (BANP) | policy.networking.k8s.io/v1alpha1 | Cluster default | Beta |
| `CiliumNetworkPolicy` (CNP) | cilium.io/v2 | Namespace | GA |
| `CiliumClusterwideNetworkPolicy` (CCNP) | cilium.io/v2 | Cluster | GA |
| `CiliumCIDRGroup` | cilium.io/v2alpha1 | Cluster | GA | Reusable CIDR sets. |
| Docs: https://docs.cilium.io/en/stable/security/policy/ | | | |

### 4.2 Selectors & semantics
- `endpointSelector`, `nodeSelector` (CCNP only), `toEndpoints`, `fromEndpoints`, `toServices`, `toCIDR`, `toCIDRSet`, `toEntities` (`world`, `cluster`, `host`, `remote-node`, `kube-apiserver`, `ingress`, `health`, `all`, `init`, `unmanaged`), `fromEntities`.
- `toRequires` / `fromRequires` — **deprecated in v1.19**.
- Default deny per-direction via empty `ingress`/`egress`.
- **Cluster scoping of selectors**: **new default in v1.19** — selectors match local cluster only unless they specify `io.cilium.k8s.policy.cluster` (breaking change for cluster mesh users).

### 4.3 L7 policies
| L7 | Protocols | Status |
| --- | --- | --- |
| HTTP (methods, paths, headers, host) | `toPorts[].rules.http` | GA |
| DNS (`toFQDNs`) | `matchName`, `matchPattern`, plus `toPorts[].rules.dns` | GA |
| **Multi-level DNS wildcards (`**.`)** | — | **New GA in v1.19** |
| Kafka (produce/consume, apiKey) | `toPorts[].rules.kafka` | **Deprecated in v1.19** (still functional) |
| DNS proxy L7 visibility | `toFQDNs` triggers DNS proxy | GA |

### 4.4 FQDN (DNS) policy
| Feature | Helm key | Status |
| --- | --- | --- |
| `toFQDNs` policy | — | GA |
| DNS proxy | `dnsProxy.*` | GA |
| DNS proxy high-availability | — | Beta |
| Max IPs per FQDN | `tofqdns-max-ips-per-hostname` | GA |
| TTL handling | `tofqdns-min-ttl`, etc. | GA |

### 4.5 Deny & advanced
- Deny policies (`ingressDeny`, `egressDeny`) — GA.
- **ICMP reject on deny**: `enable-icmp-rule` / `icmp` rules — return ICMPv4 Destination Unreachable on deny. **New GA in v1.19.**
- Policy audit mode: `policy-audit-mode` — GA.
- Host policies via CCNP with `nodeSelector` — GA. Enable Host Firewall: `hostFirewall.enabled=true`.
- **VRRP / IGMP match in host firewall rules**: **new GA in v1.19.**

---

## 5. Host / Host Firewall
| Feature | Helm key | Status |
| --- | --- | --- |
| Host firewall | `hostFirewall.enabled=true` (+ CCNP with `nodeSelector`) | GA |
| Host-level L3/L4 | CCNP | GA |
| Host-level L7 (ingress only) | CCNP | Limited |
| Host services | `hostServices.enabled=true` | GA |
| SNI passthrough policies | `toPorts.terminatingTLS` / `originatingTLS` secrets | GA |
| Docs: https://docs.cilium.io/en/stable/security/host-firewall/ | | |

---

## 6. Observability — Hubble

### 6.1 Hubble components
| Component | Helm key | Status | Notes |
| --- | --- | --- | --- |
| Hubble (in-agent) | `hubble.enabled=true` | GA | Embedded in cilium-agent. |
| Hubble Relay | `hubble.relay.enabled=true` | GA | Cluster-wide flow aggregation. |
| Hubble UI | `hubble.ui.enabled=true` + `hubble.ui.service.*` | GA | Service map, flow browser. |
| Hubble CLI | `hubble` binary | GA | `hubble observe` streams. |
| Hubble TLS | `hubble.tls.*`, `hubble.tls.auto.method` (cert-manager/helm/certgen) | GA | **Simplified certificate management in v1.19** (GitOps-friendly). |
| Redacted URLs / tokens | `hubble.redact.*` | GA | |
| Docs: https://docs.cilium.io/en/stable/observability/hubble/ | | | |

### 6.2 Hubble metrics
| Feature | Helm key | Status |
| --- | --- | --- |
| Hubble Prometheus metrics | `hubble.metrics.enabled=[...]` | GA |
| **Dynamic metrics (ConfigMap)** | `hubble.metrics.dynamic.enabled=true`, `hubble.metrics.dynamic.config.configMapName` | **GA since v1.17** | Live reconfigure without restart. |
| Flow export to Prometheus | `hubble.metrics` | GA |
| ServiceMonitor support | `hubble.metrics.serviceMonitor.enabled=true` | GA |
| Dashboards | `hubble.metrics.dashboards.enabled=true` | GA | Grafana dashboards ConfigMap. |
| Metric context options | `sourceContext`, `destinationContext`, `labelsContext`, etc. | GA |

### 6.3 Hubble flow types / visibility
- DNS flow visibility (with DNS proxy).
- HTTP / gRPC / Kafka L7 flows (with proxy redirection).
- Policy verdict flows (allow/deny/audit).
- Drop reasons (`forwarding-reason`, `drop-reason`).
- **Encryption-aware flow filters**: `hubble observe --encrypted / --unencrypted` — **new GA in v1.19.**
- **Policy-name attribution on drops**: drop messages now include originating Network Policy. **New GA in v1.19.**
- **IP-Options packet tracing**: Cilium/Hubble can trace specific packets. **New GA in v1.19.**

### 6.4 Exporters / integrations
| Integration | Helm key | Status |
| --- | --- | --- |
| Hubble exporter (JSON/Jaeger files) | `hubble.export.*` (static + dynamic) | GA |
| Dynamic exporter | `hubble.export.dynamic.enabled=true`, `hubble.export.dynamic.config.configMapName` | GA |
| OpenTelemetry (via hubble-otel) | external deploy (Hubble OTel collector receiver) | Beta |
| Grafana dashboards | `hubble.metrics.dashboards.enabled` | GA |
| Tetragon integration | separate `tetragon` chart | GA (separate project) |

---

## 7. Cluster Mesh / Multi-cluster

| Feature | Helm key / CRD | Status | Notes |
| --- | --- | --- | --- |
| Cluster Mesh | `cluster.name`, `cluster.id`, `clustermesh.useAPIServer=true`, `clustermesh.apiserver.*` | GA | |
| **KVStoreMesh** | `clustermesh.apiserver.kvstoremesh.enabled=true` | **GA, default since v1.16** | Relays identities via local etcd. |
| Global Services | Service annotation `service.cilium.io/global="true"` | GA | Cross-cluster load-balancing. |
| Shared vs affinity | `service.cilium.io/shared` / `service.cilium.io/affinity=local|remote|none` | GA | |
| MCS-API (Multi-Cluster Services) | `clustermesh.mcsapi.enabled=true`, CRDs `ServiceExport`/`ServiceImport` | **Beta** | |
| Cluster-aware policies | `io.cilium.k8s.policy.cluster` selector | GA | |
| Max clusters per mesh | **v1.19 scale target: 511 clusters** | GA | |
| **Auto-install MCS CRDs** | operator-managed | **New GA in v1.19** | |
| clustermesh certs | `clustermesh.apiserver.tls.auto.*` | GA | Cert-manager or helm-certgen. |
| Docs: https://docs.cilium.io/en/stable/network/clustermesh/ | | | |

---

## 8. Security / Identity

### 8.1 Identity allocation
| Mode | Helm key | Status | Notes |
| --- | --- | --- | --- |
| CRD-based | `identityAllocationMode=crd` | GA | Default since v1.14. |
| KVStore-based | `identityAllocationMode=kvstore` + etcd | GA | |
| **Double-Write (KVStore authoritative)** | `identityAllocationMode=doublewrite-readkvstore` | **GA since v1.17** | Migration mode. |
| **Double-Write (CRD authoritative)** | `identityAllocationMode=doublewrite-readcrd` | **GA since v1.17** | Migration mode. |
| Identity limits | `identityManagementMode` | GA | |
| Well-known identities | auto | GA | |
| Docs: https://docs.cilium.io/en/stable/operations/upgrade/ | | | |

### 8.2 Mutual Authentication (mTLS / SPIFFE)
| Feature | Helm key | Status | Notes |
| --- | --- | --- | --- |
| Mutual Authentication | `authentication.mutual.spire.enabled=true` | **Beta, disabled by default in v1.19** | Out-of-band mTLS w/ SPIFFE. |
| Bundled SPIRE | `authentication.mutual.spire.install.enabled=true` | Beta | |
| External SPIRE | point to existing trust domain | Beta | |
| Policy field | CNP/CCNP `authentication.mode: required` | Beta | |
| Docs: https://docs.cilium.io/en/stable/network/servicemesh/mutual-authentication/ | | | |

### 8.3 Secrets management (TLS in CCNP)
- `terminatingTLS` / `originatingTLS` secret refs in CNP/CCNP for L7 TLS inspection — GA.
- Secret sync namespace: `ingressController.secretsNamespace` / `gatewayAPI.secretsNamespace` — GA.

---

## 9. Egress

| Feature | Helm key / CRD | Status | Notes |
| --- | --- | --- | --- |
| Egress Gateway | `egressGateway.enabled=true` + `bpf.masquerade=true` | GA | Requires KPR + eBPF masquerade. |
| CRD `CiliumEgressGatewayPolicy` | cilium.io/v2 | GA | |
| **Multiple gateway nodes in a single policy** | `egressGateways[]` list field | **GA since v1.18** | Still single-gateway per flow. |
| Egress NAT | via egress gateway + `egressIP` | GA | |
| HA Egress Gateway | via BGP redundancy or multi-gateway field | Beta | |
| Multi-pool IPAM egress | via pool selection + gateway | GA (v1.19 pool-stable) | |
| Docs: https://docs.cilium.io/en/stable/network/egress-gateway/ | | | |

---

## 10. Advanced / Miscellaneous

| Feature | Helm key / CRD | Status | Notes |
| --- | --- | --- | --- |
| **Local Redirect Policy** | `localRedirectPolicy=true`, CRD `CiliumLocalRedirectPolicy` | GA | Node-local DNS, node-local anything. |
| **IPv4 / IPv6 dual stack** | `ipv4.enabled=true` + `ipv6.enabled=true` | GA | |
| **IPv6-only** | `ipv4.enabled=false` + `ipv6.enabled=true` + `routingMode=native` | GA | |
| **IPv6 Service loopback** | auto with IPv6-only/dual-stack | **New GA in v1.19** | Pod can hit its own Service VIP via loopback. |
| **IPv6 BIG TCP** | `bpf.bigTCPIPv6=true` | GA | 5.19+. |
| **IPv4 BIG TCP** | `bpf.bigTCPIPv4=true` | GA | 6.3+. |
| **Multicast** | `multicast.enabled=true`, CRD `CiliumEndpointSlice` | Beta | AMD64 kernel 5.10+, AArch64 6.0+. |
| Pod CIDR allocation per-node | via IPAM CRD operator | GA | |
| kube-apiserver direct connectivity | `k8sServiceHost`, `k8sServicePort` | GA | Skip in-cluster service → apiserver. |
| **Per-node configuration** | CRD `CiliumNodeConfig` (cilium.io/v2) | **GA since v1.17** | Overrides cilium-config per node selector. |
| Connection tracking options | `bpf.ctTcpMax`, `bpf.ctAnyMax`, GC intervals | GA | |
| NAT / LB table sizing | `bpf.nat*`, `bpf.lb*`, `bpf.policyMapMax` | GA | |
| **Efficient CT (tunnels + WG)** | auto | **New GA in v1.19** | Reduced tracked connections for Geneve/VXLAN/WireGuard. |
| Pod-to-Pod bandwidth | `bandwidthManager.enabled=true`, `bandwidthManager.bbr=true` | GA | Per-pod via `kubernetes.io/egress-bandwidth`. |
| **Ingress rate limiting (bandwidth manager)** | `bandwidthManager.enabled=true`, `kubernetes.io/ingress-bandwidth` | **GA since v1.18** | |
| BBR congestion control | `bandwidthManager.bbr=true` | GA (kernel 5.18+) | |
| Cilium Monitor (events) | `cilium monitor` | GA | |
| Policy map | `bpf.policyMapFullReconciliation` | GA | |
| **VTEP integration** | `vtep.enabled=true`, `vtep.endpoint`, `vtep.cidr`, `vtep.mac`, `vtep.mask` | Beta | External BIG-IP-style integration. |
| **SRv6** | `srv6.enabled=true` | Experimental | Limited. |
| **Session Recovery / graceful termination** | `gracefulTermination=true` | GA | |

---

## 11. Operations

### 11.1 CRDs installed by Cilium v1.19
- `CiliumNetworkPolicy` (cilium.io/v2)
- `CiliumClusterwideNetworkPolicy` (cilium.io/v2)
- `CiliumEndpoint` (cilium.io/v2)
- `CiliumEndpointSlice` (cilium.io/v2alpha1)
- `CiliumIdentity` (cilium.io/v2)
- `CiliumNode` (cilium.io/v2)
- `CiliumNodeConfig` (cilium.io/v2) — v2alpha1 deprecated
- `CiliumExternalWorkload` (cilium.io/v2)
- `CiliumLocalRedirectPolicy` (cilium.io/v2)
- `CiliumEgressGatewayPolicy` (cilium.io/v2)
- `CiliumEnvoyConfig` (cilium.io/v2)
- `CiliumClusterwideEnvoyConfig` (cilium.io/v2)
- `CiliumLoadBalancerIPPool` (cilium.io/v2)
- `CiliumL2AnnouncementPolicy` (cilium.io/v2alpha1)
- `CiliumPodIPPool` (cilium.io/v2alpha1)
- `CiliumCIDRGroup` (cilium.io/v2alpha1)
- `CiliumBGPClusterConfig`, `CiliumBGPPeerConfig`, `CiliumBGPAdvertisement`, `CiliumBGPNodeConfig`, `CiliumBGPNodeConfigOverride` (cilium.io/v2alpha1 / promoted to v2)
- `CiliumGatewayClassConfig` (cilium.io/v2alpha1)

### 11.2 Cilium Operator roles
- IPAM pool management (cluster-pool, ENI, Azure, etc.)
- Identity GC
- CRD installation / schema upgrade
- LB IPAM, BGP reconciliation
- Clustermesh secret sync
- Endpoint GC / CiliumEndpointSlice GC
- Multi-Pool IPAM reconciliation
- Gateway API controller (in v1.19 operator)

### 11.3 CLIs
| Tool | Purpose |
| --- | --- |
| `cilium` (cilium-cli) | Install / upgrade / status / connectivity test (`cilium connectivity test`). |
| `cilium status` | Overall health. |
| `cilium-dbg` | In-pod debug CLI (maps, endpoints, policy). |
| `cilium-health` | Node-to-node connectivity probes. |
| `hubble` | Stream flows. |
| `cilium preflight` | Pre-upgrade validation (`cilium preflight check`, `cilium preflight verify --validate-cnp`). |

### 11.4 Upgrade / downgrade
- **Supported path**: one minor at a time (e.g., 1.17 → 1.18 → 1.19).
- **Preflight checker** ships as helm chart `cilium-preflight`.
- CRD conversion / CNP validation during preflight.
- **v1.19 action-required**: review upgrade guide for Network Policy selector cluster-scope change, LoadBalancer IPAM default behavior, BGP v1 → v2 migration, Cluster Mesh certs.
- Docs: https://docs.cilium.io/en/stable/operations/upgrade/

### 11.5 Kubernetes compatibility
- v1.19 supports Kubernetes **1.29 – 1.35** (depends on client vendoring). k3s / RKE2 / OpenShift supported via standard paths.
- Docs: https://docs.cilium.io/en/stable/network/kubernetes/requirements/

### 11.6 Helm distribution
- OCI chart: `oci://quay.io/cilium/charts/cilium` (**new quay registry in v1.19**) plus mirror `helm.cilium.io`.

---

## 12. Integrations

| Integration | Helm key | Status |
| --- | --- | --- |
| **CNI chaining — AWS VPC CNI** | `cni.chainingMode=aws-cni` | GA |
| **CNI chaining — Azure IPAM** | `cni.chainingMode=azure` | GA |
| **CNI chaining — Generic veth (Flannel, etc.)** | `cni.chainingMode=generic-veth` | GA |
| **CNI chaining — portmap** | `cni.chainingMode=portmap` | GA |
| Calico chaining | `cni.chainingMode=generic-veth` | supported-ish | Prefer replace, not chain. |
| Prometheus metrics — agent | `prometheus.enabled=true`, `prometheus.serviceMonitor.enabled=true`, port `9962` | GA |
| Prometheus metrics — operator | `operator.prometheus.enabled=true`, port `9963` | GA |
| **Operator metrics TLS/mTLS** | `operator.prometheus.tls.*` | **New GA in v1.19** |
| Prometheus metrics — envoy | `envoy.prometheus.enabled=true`, port `9964` | GA |
| Prometheus metrics — hubble | `hubble.metrics.port` (default `9665`) | GA |
| ServiceMonitor CRDs (Prometheus Operator) | all above toggles | GA |
| Feature-enabled metrics | `agent_features_*` / `operator_features_*` | **GA since v1.17** |
| OpenTelemetry (flows) | via hubble-otel | Beta |
| Grafana dashboards | `*.dashboards.enabled=true` | GA |
| External workloads (VM mesh) | `externalWorkloads.enabled=true`, CRD `CiliumExternalWorkload` | Beta |
| Runtime security (Tetragon) | separate chart `tetragon` | GA (separate project) |

---

## 13. What's NEW in v1.17, v1.18, v1.19

### 13.1 Cilium v1.17 (Feb 2025) — feature highlights
- **Gateway API v1.2.1** with HTTP retries, mirror fractions, and static gateway addresses.
- **TLS via SDS (Envoy Secret Discovery Service)** — faster secret updates, better policy compute.
- **Hubble dynamic metrics** (`hubble.metrics.dynamic.enabled`) via ConfigMap — live reconfigure.
- **Cluster-health rework** for large-scale clusters (batched probing).
- **Monitor event rate-limiting** to balance CPU and eBPF event throughput.
- **Double-Write identity allocation** — seamless CRD↔KVStore migration (`doublewrite-readkvstore`, `doublewrite-readcrd`).
- **Feature-enabled Prometheus metrics** on agent and operator (`*_features_*`).
- **CiliumNodeConfig promoted to v2 / stable.**
- Kubernetes **AdminNetworkPolicy / BaselineAdminNetworkPolicy (Beta)**.

### 13.2 Cilium v1.18 (Aug 2025) — feature highlights
- **Service load-balancing control-plane redesign** (memory/extensibility).
- **Encrypted Overlay** / new IPsec virtual netdev configs — VXLAN-in-IPsec ("VinE"), IPIP.
- **IPv6 enhancements**: IPsec with IPv6 underlay for IPv6-only clusters.
- **Ingress rate limiting** in Bandwidth Manager (`kubernetes.io/ingress-bandwidth`).
- **Multiple Egress Gateways per policy** (`egressGateways[]`).
- **Router-ID auto-generation** from MAC or from an IP pool for BGP.
- **Expanded IPv6 support** across features.
- **Policy-performance improvements** (selector indexing).

### 13.3 Cilium v1.19 (Nov 2025 GA) — feature highlights
**Encryption & Authentication**
- IPsec **and** WireGuard **Strict Mode**: drop unencrypted node-to-node traffic.
- **IPsec eBPF host-routing** (faster route lookups).
- **Ztunnel (Beta)**: per-namespace opt-in transparent L4 mTLS; DS now Helm-managed.
- Mutual Authentication (SPIFFE) **disabled by default** pending feedback.

**Networking / Datapath**
- **BIG TCP in tunnels** (VXLAN / Geneve).
- **Packetization-Layer PMTUD** (TCP-based MTU discovery).
- **IPv6 underlay** for tunnels in dual-stack clusters.
- **Multi-Pool IPAM promoted to GA**, now compatible with IPsec and direct routing.
- **Configurable inter-subnet masquerade** + pool exclusion.

**Services / Service Mesh**
- **IPv6 L2 announcements** (Neighbor Discovery).
- **IPv6 Service loopback** for pod self-calls.
- **Gateway API GAMMA** now supports **GRPCRoute**.

**BGP**
- **Interface-based advertisement** (multi-homing).
- **Source-interface override** (bind BGP to loopback).
- **Empty-endpoint route withdrawal**.
- **Removed v1 `CiliumBGPPeeringPolicy`** — breaking, migrate to v2.

**Observability**
- **IP Options packet tracing** through the cluster.
- Hubble filters `--encrypted` / `--unencrypted`.
- **Drop events include Network Policy name.**

**Network Policy**
- **`**.` multi-level DNS wildcards**.
- **VRRP / IGMP matchable** in host firewall rules.
- **ICMPv4 Destination Unreachable on deny** (friendlier rejects).
- **Selectors default to local cluster** unless `io.cilium.k8s.policy.cluster` explicitly set (**breaking for clustermesh**).
- **Kafka protocol matchers & `toRequires`/`fromRequires` deprecated.**

**Performance / Scale**
- Faster policy computation (selector optimization).
- Reduced connection tracking with Geneve/VXLAN/WireGuard.
- AWS operator memory optimization.

**Operations**
- New Helm registry `quay.io/cilium/charts/cilium`.
- Operator Prometheus metrics over TLS/mTLS.
- Multi-Cluster Services CRDs auto-installed.
- Simplified Hubble / ClusterMesh certificate generation (GitOps-friendly).

**Dependency bumps**
- Kubernetes client v1.35, Envoy v1.35, Gateway API v1.4, GoBGP v3.37, LLVM ≥ 18.1.

---

## 14. Quick Helm reference (all commonly-used keys)

```yaml
# --- datapath ---
kubeProxyReplacement: true
routingMode: native            # or "tunnel"
tunnelProtocol: vxlan          # or "geneve"
autoDirectNodeRoutes: false
ipv4NativeRoutingCIDR: "10.0.0.0/8"
ipv6NativeRoutingCIDR: ""
endpointRoutes: { enabled: false }

bpf:
  datapathMode: auto           # veth | netkit | netkit-l2 | auto
  masquerade: true
  hostLegacyRouting: false
  tproxy: false                # incompatible with netkit
  bigTCPIPv4: false
  bigTCPIPv6: false
  tunnelBigTCP: false          # v1.19+

# --- IPAM ---
ipam:
  mode: cluster-pool           # or kubernetes|multi-pool|crd|eni|azure|...
  operator:
    clusterPoolIPv4PodCIDRList: ["10.244.0.0/16"]
    clusterPoolIPv4MaskSize: 24

# --- services ---
nodePort: { enabled: true, range: "30000,32767" }
hostPort: { enabled: true }
externalIPs: { enabled: true }
socketLB: { enabled: true, hostNamespaceOnly: false }
loadBalancer:
  mode: hybrid                 # snat | dsr | hybrid
  algorithm: maglev            # random | maglev
  dsrDispatch: geneve          # opt | ipip | geneve
  acceleration: best-effort    # disabled | native | best-effort

# --- LB announcements ---
l2announcements: { enabled: true }
nodeIPAM: { enabled: false }

# --- BGP ---
bgpControlPlane: { enabled: true }

# --- Gateway API / Ingress ---
gatewayAPI:
  enabled: true
  gatewayClassName: cilium
  enableGatewayAPIGAMMA: true  # HTTPRoute + GRPCRoute on Services (v1.19)
ingressController:
  enabled: false
  default: false
  loadbalancerMode: dedicated  # dedicated | shared

envoy: { enabled: true }       # standalone DaemonSet

# --- encryption ---
encryption:
  enabled: false
  type: wireguard              # ipsec | wireguard | ztunnel
  nodeEncryption: false
  strictMode:                  # v1.19
    enabled: false
    cidr: ""
    nodeCIDRList: []

# --- authentication / mTLS ---
authentication:
  enabled: false               # default in v1.19
  mutual:
    spire:
      enabled: false
      install: { enabled: false }

# --- egress ---
egressGateway: { enabled: false }

# --- local redirect ---
localRedirectPolicy: true

# --- cluster mesh ---
cluster: { name: "default", id: 0 }
clustermesh:
  useAPIServer: false
  apiserver:
    kvstoremesh: { enabled: true }
  mcsapi: { enabled: false }

# --- identity ---
identityAllocationMode: crd    # crd | kvstore | doublewrite-readkvstore | doublewrite-readcrd

# --- observability ---
hubble:
  enabled: true
  relay: { enabled: true }
  ui: { enabled: true }
  metrics:
    enabled: ["dns","drop","tcp","flow","port-distribution","icmp","httpV2"]
    dynamic: { enabled: false }
    serviceMonitor: { enabled: true }
    dashboards: { enabled: true }
  tls: { auto: { enabled: true, method: helm } }
  export: { static: { enabled: false } }

# --- prometheus ---
prometheus: { enabled: true, serviceMonitor: { enabled: true } }
operator:
  prometheus: { enabled: true, serviceMonitor: { enabled: true } }

# --- host firewall ---
hostFirewall: { enabled: false }

# --- per-node overrides ---
# CRD CiliumNodeConfig (cilium.io/v2) - apply cluster-side.
```

---

## 15. References
- Release notes: https://github.com/cilium/cilium/releases/tag/v1.19.0
- Stable docs: https://docs.cilium.io/en/stable/
- Helm values: https://docs.cilium.io/en/stable/helm-reference/
- Tuning guide: https://docs.cilium.io/en/stable/operations/performance/tuning/
- System requirements: https://docs.cilium.io/en/stable/operations/system_requirements/
- Upgrade guide: https://docs.cilium.io/en/stable/operations/upgrade/
- Roadmap: https://docs.cilium.io/en/stable/community/roadmap/
- cilium-cli: https://github.com/cilium/cilium-cli
- Ztunnel docs: https://docs.cilium.io/en/stable/security/network/encryption-ztunnel/
- Gateway API in Cilium: https://docs.cilium.io/en/stable/network/servicemesh/gateway-api/gateway-api/
- BGP control plane: https://docs.cilium.io/en/stable/network/bgp-control-plane/
- Cluster Mesh: https://docs.cilium.io/en/stable/network/clustermesh/
- Envoy proxy: https://docs.cilium.io/en/stable/security/network/proxy/envoy/
- LB IPAM: https://docs.cilium.io/en/stable/network/lb-ipam/
- Node IPAM: https://docs.cilium.io/en/stable/network/node-ipam/
- Local Redirect Policy: https://docs.cilium.io/en/stable/network/kubernetes/local-redirect-policy/
- Masquerading: https://docs.cilium.io/en/stable/network/concepts/masquerading/
- Mutual Authentication: https://docs.cilium.io/en/stable/network/servicemesh/mutual-authentication/
- Isovalent 1.19 blog: https://isovalent.com/blog/post/cilium-1-19/
- Isovalent 1.18 blog: https://isovalent.com/blog/post/cilium-1-18/
- InfoQ 1.19 overview: https://www.infoq.com/news/2026/02/cilium-119/
