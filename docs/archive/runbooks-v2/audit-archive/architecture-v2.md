# Target Architecture v2

## 설계 원칙

1. **기능적 최소주의**: 실제로 필요한 기능만 활성화. 가능성만 있는 기능은 켜지 않음.
2. **혼합 커널 현실 수용**: netkit은 2개 노드만 지원 → 전체 veth 사용.
3. **WireGuard mesh 독립성 존중**: Cilium은 wg0 건드리지 않음.
4. **GitOps 우선**: 모든 설정은 ArgoCD가 배포. 롤백도 git revert+push로.
5. **Node IPAM LB로 단순화**: static-lb → 1줄 helm value.
6. **명시적 비활성**: 기본값에 의존하지 않고, 의도한 것만 켠다.

## Before/After

```
BEFORE (현재)
─────────────────────────────────────────────────────────
  Flannel host-gw        ──> Pod 네트워킹
  k3s kube-proxy         ──> Service 라우팅 (iptables)
  static-lb (DaemonSet)  ──> LoadBalancer IP 자동 할당
  Traefik (DaemonSet)    ──> L7 Ingress + TLS 종료
  Ansible iptables role  ──> 노드 방화벽
  (없음)                  ──> 네트워크 관측성

AFTER (v2)
─────────────────────────────────────────────────────────
  Cilium CNI             ──> Pod 네트워킹 (native routing + eBPF host routing)
  Cilium eBPF KPR        ──> Service 라우팅 (kube-proxy 제거)
  Cilium Node IPAM LB    ──> LoadBalancer IP 자동 할당 (static-lb 대체)
  Cilium Gateway API     ──> L7 Ingress + TLS 종료 (Traefik 대체, 내장 Envoy)
  Ansible iptables role  ──> 노드 방화벽 (유지, Cilium 포트 허용만 추가)
  Hubble                 ──> 네트워크 관측성 (server + relay)

동일 유지:
  WireGuard 메쉬 (wg0)   ──> VPN 오버레이 (CNI와 무관)
  CoreDNS                ──> DNS
  cert-manager           ──> TLS 인증서 발급
  external-dns           ──> DNS 레코드 자동화
  ArgoCD                 ──> GitOps
  cloudflare-gateway     ──> 외부 터널 (독립 GatewayClass)
```

## Cilium 기능 활성화 목록 (확정)

```yaml
# values/cilium/backbone.yaml

# k3s API server (KPR 필수)
k8sServiceHost: k8s.backbone.homelab.bhyoo.com
k8sServicePort: 6443

# CNI: native routing (같은 L2)
routingMode: native
autoDirectNodeRoutes: true
ipv4NativeRoutingCIDR: 10.42.0.0/16
ipv6.enabled: false

# IPAM: k3s가 할당한 Pod CIDR 사용
ipam:
  mode: kubernetes

# kube-proxy 완전 대체
kubeProxyReplacement: true

# Socket LB (syscall 단 서비스 해석)
socketLB:
  enabled: true

# Node IPAM LB (static-lb 대체) — 핵심 기능
nodeIPAM:
  enabled: true
defaultLBServiceIPAM: nodeipam  # 모든 LB 서비스 기본 할당기

# Gateway API (Traefik 대체)
gatewayAPI:
  enabled: true
  enableProxyProtocol: false
  enableAppProtocol: true
  enableAlpn: true

# eBPF 최적화
bpf:
  datapathMode: veth         # netkit 혼합 지원 불가 → 명시적 veth
  masquerade: true           # iptables MASQUERADE → eBPF
  # hostLegacyRouting: false (기본) - eBPF host routing 활성
  # CT/NAT 테이블 축소 (70 pods, 56 svc 규모)
  ctTcpMax: 65536
  ctAnyMax: 32768
  natMax: 65536
  neighMax: 65536
  lbMapMax: 4096
  policyMapMax: 4096
  monitorAggregation: medium
  monitorInterval: "5s"

# iptables conntrack 우회
installNoConntrackIptablesRules: true

# Bandwidth Manager + BBR
bandwidthManager:
  enabled: true
  bbr: true

# Hubble
hubble:
  enabled: true
  metrics:
    enabled:
      - dns
      - drop
      - tcp
      - flow
      - httpV2:exemplars=true
    serviceMonitor:
      enabled: true
  relay:
    enabled: true
    replicas: 1
    resources:
      requests: {cpu: 10m, memory: 64Mi}
      limits: {memory: 256Mi}
  ui:
    enabled: false  # 리소스 절약

# Operator
operator:
  replicas: 1
  resources:
    requests: {cpu: 10m, memory: 64Mi}
    limits: {memory: 256Mi}

# Agent 리소스 (rpi4/n2p1/n2p2 메모리 제약 고려)
resources:
  requests: {cpu: 50m, memory: 128Mi}
  limits: {memory: 512Mi}

# Envoy (Gateway API용 DaemonSet)
envoy:
  resources:
    requests: {cpu: 10m, memory: 64Mi}
    limits: {memory: 256Mi}

# Prometheus
prometheus:
  enabled: true
  serviceMonitor:
    enabled: true
    trustCRDsExist: true

# 명시적 비활성
encryption:
  enabled: false             # WG 메쉬 별도 존재
enableIPv4BIGTCP: false      # netkit 없이 효과 제한
l2announcements:
  enabled: false             # Node IPAM으로 충분, ARP 방식 불필요
loadBalancer:
  acceleration: disabled     # NIC 드라이버 native XDP 미지원
hostFirewall:
  enabled: false             # 별도 iptables-firewall role 유지

# master/taint 전부 허용
tolerations:
  - operator: Exists
```

## 트래픽 흐름

### Pod → Pod (cross-node)

```
Pod A (node X, 10.42.X.Y)
  ↓ Pod eBPF program
  ↓ eBPF host routing (iptables 우회)
  ↓ Node X eth0
  ↓ LAN (192.168.219.0/24, direct route)
  ↓ Node Y eth0
  ↓ eBPF host routing
Pod B (node Y, 10.42.Y.Z)
```

### 외부 → LoadBalancer Service (WireGuard 경유)

```
VPN client (10.222.0.128)
  ↓ WireGuard tunnel
  ↓ rpi5 wg0 (10.222.0.3)
  ↓ 목적지 IP 10.222.0.3 = Node IPAM이 할당한 LB IP
  ↓ Cilium eBPF: Service match → LB → Backend Pod 선택
  ↓ eBPF host routing
Envoy Pod (Cilium Gateway) or Backend Pod
```

### Gateway API HTTP 요청

```
VPN client
  ↓ WG
  ↓ 10.222.0.3:443 (Node IPAM LB → Gateway Service)
  ↓ cilium-envoy DaemonSet (TLS 종료, HTTPRoute 매칭)
  ↓ Service → Pod
Backend Pod
```

## Gateway API 설계

### Gateway 리소스 (1개)

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: bhyoo-gateway
  namespace: ingress-ctrl
spec:
  gatewayClassName: cilium
  # spec.addresses 생략 → Node IPAM이 자동으로 모든 노드 IP 할당
  # (service externalTrafficPolicy는 Cluster - Gateway의 dummy EndpointSlice 제약)
  listeners:
    - name: https
      port: 443
      protocol: HTTPS
      hostname: "*.bhyoo.com"
      tls:
        mode: Terminate
        certificateRefs:
          - name: wildcard-bhyoo-com-tls  # cert-manager가 생성
      allowedRoutes:
        namespaces:
          from: All
```

### HTTPRoute (서비스별, 총 9개)

각 서비스 namespace에 배포. 예시:
```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: argocd
  namespace: argocd
spec:
  parentRefs:
    - name: bhyoo-gateway
      namespace: ingress-ctrl
  hostnames: [argocd.bhyoo.com]
  rules:
    - backendRefs:
        - name: argocd-server
          port: 80
```

**9개 HTTPRoute 목록:**
- argocd / argocd.bhyoo.com
- hindsight / hindsight.bhyoo.com
- hindsight-api / hindsight-api.bhyoo.com
- immich / immich.bhyoo.com
- versitygw / versitygw.bhyoo.com
- versitygw-s3 / s3.bhyoo.com
- versitygw-admin / admin-s3.bhyoo.com
- grafana / grafana.bhyoo.com
- prometheus / prometheus.bhyoo.com

## Node IPAM LB 동작 (static-lb와 비교)

| 항목 | static-lb (현재) | Node IPAM LB (v2) |
|------|------------------|-------------------|
| 할당 로직 | Node의 `status.addresses[ExternalIP]` → Service `.status.loadBalancer.ingress[].ip` | 동일 |
| 자동 감지 | O (controller watch) | O (operator watch) |
| 노드 추가 시 반영 | O | O |
| 서비스별 annotation | 불필요 | `loadBalancerClass: io.cilium/node` or `defaultLBServiceIPAM: nodeipam` |
| external vs internal IP | config로 선택 | ExternalIP 우선, 없으면 InternalIP (자동) |
| externalTrafficPolicy: Local 지원 | O | O (Gateway 제외) |

**주의**: Gateway Service는 `externalTrafficPolicy: Cluster` 필수 (Cilium dummy EndpointSlice 이슈).

## 다운타임 및 롤백

### 다운타임 예상

| Phase | 영향 | 시간 |
|-------|------|------|
| k3s 설정 변경 + flannel 비활성 | Pod 네트워킹 전면 중단 | 5-10분 |
| Cilium 설치 + 안정화 | 네트워크 복구 | 5-10분 |
| 전체 Pod 재시작 | Pod 순단 | 5분 |
| Traefik → Gateway 전환 | 각 Ingress → HTTPRoute | 서비스당 2-3분 |
| **총 다운타임** | | **25-40분** |

### 롤백 전략 (3단계 중 선택)

**Level 1 — GitOps 롤백 (가장 빠름)**
- Cilium이 설치되고 안정적으로 작동하지만 특정 서비스에 문제:
- `git revert` + push → ArgoCD가 이전 상태 재배포
- 다운타임: 없음 (ArgoCD sync 시간 5분 이내)

**Level 2 — 완전 복원 (Cilium 자체가 문제)**
- Cilium CNI가 작동하지 않거나 Pod 네트워킹 실패:
- `git revert` + push (GitOps 레이어 먼저)
- 모든 노드 reboot (eBPF 프로그램 + iptables 완전 정리)
- Ansible로 k3s 재설치 (flannel host-gw 복원)
- 다운타임: 20-30분

**Level 3 — etcd 스냅샷 복원 (비상)**
- etcd 데이터 손상 or cluster 완전히 깨진 경우:
- Phase 0에서 저장한 etcd 스냅샷 사용
- `k3s server --cluster-reset --cluster-reset-restore-path`
- 다운타임: 30-60분

## 12개 결함에 대한 v2 대응

| # | v1 결함 | v2 해결 |
|---|---------|---------|
| 1 | ArgoCD가 복원 무효화 | `git revert + push` 명시적 절차화. 스크립트가 자동 revert 커밋 생성 |
| 2 | LB 풀이 노드 IP와 충돌 | Node IPAM LB 사용 (풀 없음) |
| 3 | wg0에서 L2 announcement 불가 | L2 announcement 사용 안 함 |
| 4 | VIP 핸드오프 없음 | Node IPAM이 Traefik과 Gateway 둘 다 모든 노드 IP 할당 → 분리된 hostname으로 단계 전환 |
| 5 | 스냅샷 실패 숨김 | snapshot.sh에 각 명령 exit code 체크 + 파일 크기 검증 |
| 6 | CoreDNS 재시작 제외 | kube-system 포함 전체 재시작 |
| 7 | grep -c "Ready" 버그 | `awk '$2=="Ready"'` 정확한 컬럼 매칭 |
| 8 | internal/external 구분 prose만 | 단일 Gateway + Node IPAM (구분 불필요) |
| 9 | Traefik LB IP 비교 오류 | 검증 로직 재작성 |
| 10 | HA etcd 재합류 순서 | ansible-playbook은 한 번에 전체 backbone 적용 (xanmanning role이 처리) |
| 11 | bpf.datapathMode: auto 불확실 | `veth` 고정 |
| 12 | Gateway API + netkit + tproxy 호환성 | `veth` 사용으로 tproxy 활성화 가능, Gateway API 동작 확인됨 |

## 범위 외 (v2에서 제외)

- **Cilium Host Firewall 전환**: 기존 ansible iptables role 유지. 별도 작업.
- **Cilium Service Mesh / mTLS**: 현재 요구사항에 없음.
- **Cluster Mesh (prod ↔ backbone)**: 향후 고려.
- **Egress Gateway**: 현재 egress NAT 요구사항 없음.
- **HTTP/3**: Cilium Envoy 미지원, 포기.
- **NodeLocal DNSCache + LRP**: 홈랩 규모에 불필요.
- **Transparent encryption (Cilium WG/IPsec)**: 기존 WG 메쉬와 이중 암호화 불필요.
