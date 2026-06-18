# Backbone Cluster Audit Summary
Generated: 2026-04-18T18:09:57+09:00

## 노드 구성

| Node | eth0 IP | wg0 IP | 커널 | Arch | CPU | RAM | NIC 드라이버 | Role |
|------|---------|--------|------|------|-----|-----|--------------|------|
| rpi5    | 192.168.219.5 | 10.222.0.3 | 6.12.75+rpt-rpi-2712 | arm64 | 4  | 7.9G  | macb     | master |
| rock5bp | 192.168.219.6 | 10.222.0.4 | 6.1.84-999-rk2410    | arm64 | 8  | 31.0G | r8125    | master |
| rpi4    | 192.168.219.7 | 10.222.0.5 | 6.12.75+rpt-rpi-v8   | arm64 | 4  | 3.7G  | bcmgenet | master |
| n2p1    | 192.168.219.3 | 10.222.0.1 | 6.6.0-odroid-arm64   | arm64 | 6  | 3.5G  | st_gmac  | worker |
| n2p2    | 192.168.219.4 | 10.222.0.2 | 6.6.0-odroid-arm64   | arm64 | 6  | 3.5G  | st_gmac  | worker |

## 커널 eBPF 기능 매트릭스

| Feature | rpi5 | rock5bp | rpi4 | n2p1/n2p2 |
|---------|------|---------|------|-----------|
| CONFIG_BPF | y | y | y | y |
| CONFIG_CGROUP_BPF | y | y | y | y |
| CONFIG_NET_CLS_BPF | y (builtin) | m (module) | y (builtin) | m (module) |
| CONFIG_TCP_CONG_BBR | m | m | m | m |
| **CONFIG_NETKIT** | **y** | **missing** | **y** | **missing** |
| CONFIG_VXLAN | m | m | m | m |
| CONFIG_NF_TABLES | m | m | m | m |

**중요**: netkit은 rpi5/rpi4만 지원. Cilium `bpf.datapathMode: auto`는 노드별 자동 감지가 아니라 **클러스터 전역 설정**이므로 혼합 환경에서는 `veth`로 강제해야 함.

## NIC 드라이버 및 XDP 호환성

| Node | Driver | Native XDP | Generic XDP |
|------|--------|------------|-------------|
| rpi5 | macb (BCM/Cadence) | 미지원 | 가능 |
| rock5bp | r8125 (Realtek 2.5G) | 미지원 | 가능 |
| rpi4 | bcmgenet (BCM GENET) | 미지원 | 가능 |
| n2p1/n2p2 | st_gmac (STMicro) | 미지원 | 가능 |

**결론**: Cilium XDP native acceleration 불가. `loadBalancer.acceleration: best-effort`는 generic XDP로 fallback되어 성능 이득 제한적. 홈랩 규모에선 무시 가능.

## 현재 네트워킹 상태

### iptables 규칙 수 (kube-proxy 생성분)
- rpi5: 893 lines
- rock5bp: 908 lines
- rpi4: 875 lines
- n2p1: 776 lines
- n2p2: 714 lines

### 현재 BPF 프로그램 (Cilium 없으므로 0 예상)
(확인 결과: 모든 노드에서 bpftool 명령어 없음 - 기본 설치에 미포함. BPF 프로그램 로드는 실제로는 없는 것으로 추정됨 - tc filter도 비어있음)

## 클러스터 컴포넌트

### Namespaces (22개)
NAME                 STATUS   AGE
argocd               Active   349d
cert-manager         Active   349d
cloudflare-gateway   Active   31d
cnpg-system          Active   349d
default              Active   349d
democratic-csi       Active   191d
dns-manager          Active   349d
hindsight            Active   13d
immich               Active   349d
ingress-ctrl         Active   349d
jay-coin-bot         Active   28d
jay-stock-bot        Active   19d
jellyfin             Active   119d
kube-node-lease      Active   349d
kube-public          Active   349d
kube-system          Active   349d
loadbalancer         Active   349d
loki                 Active   47d
object-storage       Active   33d
openebs              Active   157d
prometheus           Active   349d
system-upgrade       Active   349d

### LoadBalancer Services
```
ingress-ctrl         traefik                                         LoadBalancer   10.43.12.96     10.222.0.3    443:30697/TCP,443:30697/UDP    349d   app.kubernetes.io/instance=traefik-ingress-ctrl,app.kubernetes.io/name=traefik
```

### Ingress (전부 traefik class, 총 6개)
argocd           argocd-server       traefik   argocd.bhyoo.com                                      10.222.0.3   80, 443   349d
hindsight        hindsight           traefik   hindsight.bhyoo.com,hindsight-api.bhyoo.com           10.222.0.3   80, 443   9d
immich           immich-server       traefik   immich.bhyoo.com                                      10.222.0.3   80, 443   157d
object-storage   versitygw           traefik   versitygw.bhyoo.com,s3.bhyoo.com,admin-s3.bhyoo.com   10.222.0.3   80, 443   33d
prometheus       shared-grafana      traefik   grafana.bhyoo.com                                     10.222.0.3   80, 443   158d
prometheus       shared-prometheus   traefik   prometheus.bhyoo.com                                  10.222.0.3   80, 443   157d

### Gateway API (이미 설치됨)
GatewayClass:
NAME         CONTROLLER                                        ACCEPTED   AGE
cloudflare   github.com/pl4nty/cloudflare-kubernetes-gateway   True       31d
Gateways:
NAMESPACE            NAME                CLASS        ADDRESS   PROGRAMMED   AGE
cloudflare-gateway   cloudflare-tunnel   cloudflare             True         31d
HTTPRoutes:
NAMESPACE   NAME             HOSTNAMES                      AGE
argocd      argocd-webhook   ["argocd-webhook.bhyoo.com"]   31d

### NetworkPolicies (Thanos용 4개만)
NAMESPACE    NAME                    POD-SELECTOR                                                                                                 AGE
prometheus   thanos-compactor        app.kubernetes.io/component=compactor,app.kubernetes.io/instance=thanos,app.kubernetes.io/name=thanos        32d
prometheus   thanos-query            app.kubernetes.io/component=query,app.kubernetes.io/instance=thanos,app.kubernetes.io/name=thanos            32d
prometheus   thanos-query-frontend   app.kubernetes.io/component=query-frontend,app.kubernetes.io/instance=thanos,app.kubernetes.io/name=thanos   32d
prometheus   thanos-storegateway     app.kubernetes.io/component=storegateway,app.kubernetes.io/instance=thanos,app.kubernetes.io/name=thanos     32d

### DaemonSets (네트워킹 관련)
NAMESPACE        NAME                            DESIRED   CURRENT   READY   UP-TO-DATE   AVAILABLE   NODE SELECTOR                        AGE    CONTAINERS                                      IMAGES                                                                                                                                                                     SELECTOR
democratic-csi   hdd-iscsi-democratic-csi-node   5         5         5       5            5           kubernetes.io/os=linux               32d    csi-driver,csi-proxy,driver-registrar,cleanup   docker.io/isac322/democratic-csi:next,ghcr.io/democratic-csi/csi-grpc-proxy:v0.5.7,registry.k8s.io/sig-storage/csi-node-driver-registrar:v2.9.0,docker.io/busybox:1.37.0   app.kubernetes.io/component=node-linux,app.kubernetes.io/csi-role=node,app.kubernetes.io/instance=hdd-iscsi,app.kubernetes.io/managed-by=Helm,app.kubernetes.io/name=democratic-csi
democratic-csi   ssd-iscsi-democratic-csi-node   5         5         5       5            5           kubernetes.io/os=linux               158d   csi-driver,csi-proxy,driver-registrar,cleanup   docker.io/isac322/democratic-csi:next,ghcr.io/democratic-csi/csi-grpc-proxy:v0.5.7,registry.k8s.io/sig-storage/csi-node-driver-registrar:v2.9.0,docker.io/busybox:1.37.0   app.kubernetes.io/component=node-linux,app.kubernetes.io/csi-role=node,app.kubernetes.io/instance=ssd-iscsi,app.kubernetes.io/managed-by=Helm,app.kubernetes.io/name=democratic-csi
ingress-ctrl     traefik                         1         1         1       1            1           homelab.bhyoo.com/vpn-gateway=true   349d   traefik                                         docker.io/traefik:v3.3.6                                                                                                                                                   app.kubernetes.io/instance=traefik-ingress-ctrl,app.kubernetes.io/name=traefik
openebs          zfs-localpv-node                1         1         1       1            1           homelab.bhyoo.com/zfs-node=true      157d   csi-node-driver-registrar,openebs-zfs-plugin    registry.k8s.io/sig-storage/csi-node-driver-registrar:v2.13.0,docker.io/openebs/zfs-driver:2.9.1                                                                           name=openebs-zfs-node,release=zfs-localpv
prometheus       shared-node-exporter            5         5         5       5            5           kubernetes.io/os=linux               158d   node-exporter                                   quay.io/prometheus/node-exporter:v1.11.1                                                                                                                                   app.kubernetes.io/instance=shared,app.kubernetes.io/name=node-exporter

### ArgoCD Applications (backbone 관련, 총 11개)
backbone-cert-manager                  Synced      Healthy       <none>
backbone-cert-manager-cluster-issuer   Synced      Healthy       <none>
backbone-cluster-secrets               Synced      Healthy       <none>
backbone-descheduler                   Synced      Healthy       <none>
backbone-external-dns                  Synced      Healthy       <none>
backbone-external-dns-cf-api-token     Synced      Healthy       https://github.com/isac322/homelab.git
backbone-external-secrets              Synced      Healthy       <none>
backbone-k3s-upgrade                   Synced      Healthy       <none>
backbone-prometheus-stack              Synced      Healthy       <none>
backbone-static-lb                     Synced      Healthy       <none>
backbone-traefik                       OutOfSync   Healthy       <none>

### Traefik CRDs 설치됨 (교체 대상)
22
(전부 제거 대상)

### Gateway API CRDs (이미 설치됨)
backendtlspolicies.gateway.networking.k8s.io            2026-04-04T15:33:49Z
gatewayclasses.gateway.networking.k8s.io                2025-05-04T08:59:00Z
gateways.gateway.networking.k8s.io                      2025-05-04T08:59:00Z
grpcroutes.gateway.networking.k8s.io                    2025-05-04T08:59:00Z
httproutes.gateway.networking.k8s.io                    2025-05-04T08:59:00Z
listenersets.gateway.networking.k8s.io                  2026-04-04T15:33:49Z
referencegrants.gateway.networking.k8s.io               2025-05-04T08:59:00Z
tlsroutes.gateway.networking.k8s.io                     2026-04-04T15:33:49Z

## 주요 발견 및 제약

1. **netkit 부분 지원**: rpi5/rpi4만 가능. 전역 설정이므로 veth 사용 필요.
2. **XDP native 불가**: NIC 드라이버 제약. generic XDP로 fallback.
3. **WireGuard 메쉬 존재**: wg0 인터페이스는 Cilium CNI와 무관. 유지.
4. **Traefik 전용 annotation 미사용**: router.entrypoints만 사용 - Gateway API로 이전 용이.
5. **Gateway API CRDs 이미 설치됨**: 새 CRD 설치 불필요.
6. **ArgoCD app 중 backbone-traefik이 OutOfSync**: 전환 시 이 상태 고려.
7. **cloudflare-tunnel Gateway 사용 중**: cloudflare-gateway class, 독립적이므로 영향 없음.
8. **CiliumNetworkPolicy로 교체 가능한 기존 NetworkPolicy 4개**: Thanos 네임스페이스 내부.
9. **hostNetwork Pod 16개**: democratic-csi, node-exporter, zfs-localpv - Cilium과 호환성 이슈 없음.
