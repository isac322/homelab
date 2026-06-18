# Feature Matrix: Current Stack × Cilium v1.19 대체/보조 매핑

## 범례

- **Replace**: 현재 컴포넌트를 Cilium 기능으로 완전 대체
- **Augment**: 기존 유지 + Cilium 기능으로 강화
- **Keep**: 현재 유지, Cilium과 무관
- **Skip**: 활성화하지 않음 (부적합 or 불필요)

---

## 1. CNI & 데이터패스

| 현재 컴포넌트 | 대체/보조 | Cilium 기능 | 근거 |
|---|---|---|---|
| Flannel host-gw | Replace | Cilium CNI, `routingMode: native` + `autoDirectNodeRoutes: true` | 같은 L2 네트워크(192.168.219.0/24), 터널 오버헤드 제거 |
| 없음 | Augment | `bpf.masquerade: true` | iptables MASQUERADE → eBPF |
| 없음 | Augment | eBPF host routing (기본) | iptables/상위 스택 우회 |
| 없음 | Skip | `bpf.datapathMode: netkit` | rock5bp/n2p1/n2p2 커널에서 미지원. `veth` 사용 |
| 없음 | Skip | `enableIPv4BIGTCP` | 효과는 있지만 netkit과 함께 쓸 때 최대. veth에선 제한적 |
| WireGuard mesh (wg0) | Keep | Cilium transparent encryption 불사용 | 기존 WG 메쉬 유지. 이중 암호화 불필요 |

## 2. kube-proxy 대체

| 현재 컴포넌트 | 대체/보조 | Cilium 기능 | 근거 |
|---|---|---|---|
| k3s 내장 kube-proxy (iptables) | Replace | `kubeProxyReplacement: true` | 수백줄의 KUBE-* iptables 규칙 → eBPF map. 성능↑ |
| 없음 | Augment | `socketLB.enabled: true` | connect()/sendmsg() syscall 단에서 서비스 해석 |
| 없음 | Augment | `installNoConntrackIptablesRules: true` | Pod 트래픽 netfilter conntrack 우회 |
| 없음 | Augment | `bandwidthManager.enabled: true` + `bbr: true` | EDT-based 대역폭, BBR 혼잡 제어 |

## 3. LoadBalancer IP 할당

| 현재 컴포넌트 | 대체/보조 | Cilium 기능 | 근거 |
|---|---|---|---|
| **static-lb** (isac322/static-lb:0.4.0) | **Replace** | **Node IPAM LB** (`nodeIPAM.enabled: true`) | **v1.16+ 기본 기능. 각 노드 ExternalIP 자동으로 모든 LB 서비스의 ingress에 매핑. static-lb와 100% 동일 동작.** |
| 없음 | Skip | `CiliumLoadBalancerIPPool` + `L2Announcement` | wg0은 L3 터널이라 ARP 불가. LAN 별도 대역이 필요한 경우에만 |
| 없음 | Skip | BGP Control Plane | 홈랩 라우터 BGP 미지원 |

**활성화 방법:**
```yaml
nodeIPAM:
  enabled: true
defaultLBServiceIPAM: nodeipam  # 모든 LB 서비스 기본값
```

**Gateway API 제약**: Cilium이 Gateway Service에 dummy EndpointSlice를 쓰므로 `externalTrafficPolicy: Local`을 정확히 반영 못함. Gateway Service는 `Cluster` 사용.

## 4. L7 Ingress / Gateway

| 현재 컴포넌트 | 대체/보조 | Cilium 기능 | 근거 |
|---|---|---|---|
| Traefik (DaemonSet, 6개 Ingress) | Replace | Cilium Gateway API (내장 Envoy) | Traefik 전용 기능(IngressRoute CRD, Middleware) 미사용. HTTP3만 유일한 Traefik 특화 기능 |
| Traefik IngressClass | Replace | Cilium `gatewayAPI.enabled: true` → GatewayClass `cilium` | |
| Traefik + cert-manager | Augment | `gatewayAPI.enableProxyProtocol: false` + cert-manager Gateway API 연동 | cert-manager 1.15+ Gateway API 지원 |
| Traefik HTTP/3 | Skip (손실) | 미지원 | Cilium Envoy HTTP/3 미지원. HTTP/1.1 + HTTP/2만 |

**HTTP/3 손실 허용**: 현재 설정에 있지만 대부분 브라우저가 HTTP/2로 자동 fallback.

## 5. NetworkPolicy

| 현재 컴포넌트 | 대체/보조 | Cilium 기능 | 근거 |
|---|---|---|---|
| k3s 기본 NetworkPolicy controller (kube-router) | Replace | `enable-k8s-networkpolicy: true` (기본) | Cilium이 기본 NetworkPolicy 처리 |
| 없음 | Augment | `CiliumNetworkPolicy` (CNP) | L3/L4 + 더 풍부한 selector |
| 없음 | Augment | `CiliumClusterwideNetworkPolicy` (CCNP) | 클러스터 전역 정책 |
| 없음 | Skip (지금은) | L7 policy (HTTP/Kafka/DNS) | 필요 시 추가 |
| 없음 | Skip (지금은) | FQDN policy (toFQDNs) | 필요 시 추가. egress 제어에 유용 |

**기존 NetworkPolicy 4개 (Thanos namespace)**: 표준 NetworkPolicy이므로 Cilium이 그대로 처리. 재작성 불필요.

## 6. 노드 방화벽

| 현재 컴포넌트 | 대체/보조 | Cilium 기능 | 근거 |
|---|---|---|---|
| ansible `iptables-firewall` role | Keep | Cilium Host Firewall | **v2에선 Keep.** Cilium Host Firewall로 전환은 모든 iptables 규칙을 CCNP로 재작성 필요. 범위 확대. 향후 별도 단계 |
| 없음 (잠재 추가) | Skip (지금은) | `hostFirewall.enabled: true` | 위 이유로 지금은 활성화 X |

**방화벽 role 조정**: `use_k8s_cilium: true`, `use_k8s_cilium_hubble: true` 추가하여 Cilium 포트(4240, 4244-4245) 허용만.

## 7. 관측성

| 현재 컴포넌트 | 대체/보조 | Cilium 기능 | 근거 |
|---|---|---|---|
| 없음 (네트워크 flow 가시성) | Add | **Hubble** (server + relay, UI는 선택) | L4 + L7 flow 메트릭, DNS visibility |
| Prometheus operator (kube-prometheus-stack) | Augment | Cilium metrics + Hubble metrics via ServiceMonitor | 기존 Prometheus에 통합 |
| Grafana | Augment | Cilium/Hubble Grafana 대시보드 import | 공식 대시보드 존재 |
| 없음 | Skip (지금은) | Hubble UI | 메모리 절약. 필요 시 port-forward |
| 없음 | Skip (지금은) | OpenTelemetry integration | 현재 스택에 OTel 없음 |

## 8. DNS

| 현재 컴포넌트 | 대체/보조 | Cilium 기능 | 근거 |
|---|---|---|---|
| CoreDNS (k3s 기본) | Keep | | Cilium은 CoreDNS 대체 X |
| 없음 (잠재) | Skip (지금은) | Local Redirect Policy (CoreDNS 로컬화) | 홈랩 규모에 불필요. NodeLocal DNSCache도 없음 |
| 없음 (잠재) | Skip (지금은) | Cilium DNS proxy | FQDN policy 사용 시만 필요 |

## 9. 서비스 메시 / mTLS

| 현재 컴포넌트 | 대체/보조 | Cilium 기능 | 근거 |
|---|---|---|---|
| 없음 | Skip | Cilium Service Mesh (mTLS via SPIFFE) | 현재 요구사항에 없음. 미래 고려 |
| 없음 | Skip | L7 traffic management (Envoy) | Gateway API로 충분 |

## 10. 클러스터 메시

| 현재 컴포넌트 | 대체/보조 | Cilium 기능 | 근거 |
|---|---|---|---|
| 없음 (prod + backbone 2개 클러스터 존재) | Skip | Cilium Cluster Mesh | 향후 고려. v2 범위 밖 |

## 11. Egress

| 현재 컴포넌트 | 대체/보조 | Cilium 기능 | 근거 |
|---|---|---|---|
| 없음 | Skip | Egress Gateway | 현재 egress NAT 요구사항 없음 |

## 12. 기타

| 현재 컴포넌트 | 대체/보조 | Cilium 기능 | 근거 |
|---|---|---|---|
| cert-manager | Keep | | 유지. Gateway API resource에 annotation 그대로 사용 |
| external-dns | Keep | | Cilium과 무관 |
| ArgoCD | Keep | | GitOps 엔진 |
| democratic-csi, zfs-localpv (hostNetwork Pods) | Keep | | Cilium과 호환성 이슈 없음 |
| cloudflare-gateway (GatewayClass: cloudflare) | Keep | | 독립적 Gateway controller, Cilium Gateway와 공존 |

---

## 요약 통계

| 분류 | 개수 |
|------|------|
| Replace (기존 컴포넌트 제거) | 4개 (Flannel, kube-proxy, static-lb, Traefik) |
| Augment (Cilium으로 강화) | 6개 (bpf.masquerade, socketLB, installNoConntrackIptablesRules, bandwidthManager/BBR, CNP/CCNP, Hubble) |
| Keep (유지) | 주요 6개 (WireGuard, ansible iptables role, CoreDNS, cert-manager, ArgoCD, cloudflare-gateway) |
| Skip (활성화 X) | 주요 10개 (netkit, BIG TCP, L2Announcement, BGP, HTTP3, L7 policy, Host Firewall, Service Mesh, Cluster Mesh, Egress Gateway) |

## 최종 Cilium 활성 기능 체크리스트 (v2 타겟)

### 필수
- [x] CNI (native routing)
- [x] kubeProxyReplacement
- [x] Node IPAM LB
- [x] Gateway API
- [x] Hubble (server + relay)
- [x] Prometheus metrics

### 성능 최적화
- [x] bpf.masquerade
- [x] socketLB
- [x] installNoConntrackIptablesRules
- [x] bandwidthManager + BBR
- [x] eBPF host routing (기본 활성)

### 명시적 비활성 (명확히 하기 위해)
- [x] bpf.datapathMode: veth (netkit 안 씀)
- [x] enableIPv4BIGTCP: false (netkit 없으면 효과 제한)
- [x] l2announcements: false
- [x] loadBalancer.acceleration: disabled (XDP native 미지원)
- [x] hostFirewall: false
- [x] encryption: false
- [x] clustermesh: disabled
