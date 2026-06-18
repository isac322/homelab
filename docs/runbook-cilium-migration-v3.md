# Cilium Single-Stack Migration Runbook v3 — Backbone (WireGuard-only)

> **Status: ✅ 모든 Phase 완료 (2026-06-18).** 본 문서는 실행 후 기록으로 보존한다.
>
> v2 (`docs/archive/runbook-cilium-migration-v2.md`)의 Phase 0–3(CNI/KPR/Gateway 부트스트랩) 위에서, v3은 다음을 실행했다:
> 1. **즉시 복구**: 5개 hostname 404 outage 해소 (`apps/objects/cilium-gateway/httproutes/*` git 추가 + `networking` AppProject 확장)
> 2. **Traefik → Cilium Gateway HTTPRoute 전환**: chart-native `httpRoute`/`route` values 사용. hindsight만 chart 미지원으로 standalone YAML 유지
> 3. **static-lb → Cilium Node IPAM 일원화**: `argocd/appsets/_static-lb.yaml` rename으로 비활성
> 4. **외부 노출 plane 단일화**: WireGuard만 사용. LAN VIP / L2 Announcement / LB-IPAM은 본 범위 밖
>
> 실행 기록 (master에 직접 commit):
>
> | Phase | Commit | 설명 |
> |---|---|---|
> | A | `f4a5564` | networking AppProject 확장 + 4 HTTPRoute git tracking → outage 해소 |
> | C | `3e5d83b` | Gateway `match-node-labels` annotation + 4 노드 라벨링 → rpi4 제외 |
> | B | `f845ece` | external-dns에 `gateway-httproute` source 추가 |
> | D | `4e18856` | traefik AppSet에서 backbone 제거 + `ingress.enabled=false` + chart-native HTTPRoute 전환 + standalone 3개 삭제 |
> | E | `b8044f8` | static-lb AppSet `_` rename으로 비활성 |
> | F | `af38b97` | external-dns에서 `ingress` source 제거 |
> | 위생 정리 | `(이 commit)` | runbook archive 이동 + Traefik CRD 삭제 + hindsight HTTPRoute SSA drift 해소 + 본 문서 갱신 |
>
> 최종 상태: Traefik 자원 0, Ingress 자원 0, IngressClass 0, static-lb 0. Gateway `Attached Routes: 9`. 10 hostname 모두 정상 응답.

---

## 진행 결과 요약 (참고용)

| 항목 | 마이그레이션 전 | 마이그레이션 후 |
|---|---|---|
| Ingress 컨트롤러 | Traefik (rpi5 단독) | Cilium Envoy DS (4 노드) |
| LB IP 관리자 | static-lb | Cilium Node IPAM |
| 노출 IP 후보 | 5 노드 WG IP | 4 노드 WG IP (rpi4 제외) |
| Ingress 자원 | 5개 (`traefik` class) | 0 |
| HTTPRoute 자원 | 2 (argocd만) | 9 (chart-native 7 + hindsight 2) |
| external-dns sources | `node, service, ingress` | `node, service, gateway-httproute` |
| ArgoCD Apps | `backbone-traefik`, `backbone-static-lb` 활성 | 둘 다 제거됨 |

> 아래 0~6 절은 실행 당시 계획서 원본을 그대로 보존한 것이다. 이미 실행됨.

---

## 0. 현재 상태 (kubectl 검증 기준, 2026-06-18)

### 0.1 Cilium 스택 (정상)

- Cilium agent: 5/5 노드 Running (rpi5, rock5bp, rpi4, n2p1, n2p2)
- cilium-envoy DS: **4/5 노드 (rpi4 제외)**. `values/cilium/backbone.yaml`의 nodeAffinity가 `rpi4`를 명시 제외 (tcmalloc/VA bits 이슈)
- `kube-proxy-replacement: true`, `routing-mode: native`, `enable-node-ipam: true`, `default-lb-service-ipam: nodeipam`, `enable-gateway-api: true`
- GatewayClass `cilium` Accepted=True
- Gateway `ingress-ctrl/bhyoo-gateway`: Programmed=True, Listener `https` Accepted+Programmed
- Wildcard cert `ingress-ctrl/wildcard-bhyoo-com-tls`: Ready, valid
- LB Service `cilium-gateway-bhyoo-gateway`: ExternalIP=`10.222.0.1,10.222.0.2,10.222.0.3,10.222.0.4,10.222.0.5` (5 노드 WG IP 모두, **rpi4 포함**)

### 0.2 Legacy 스택 (제거 대상)

- ArgoCD Application `backbone-traefik`: **OutOfSync, Healthy**. DaemonSet 1/1 on rpi5 (`vpn-gateway=true`). Service `traefik` LB IP=`10.222.0.3` (static-lb가 할당).
- ArgoCD Application `backbone-static-lb`: Synced, Healthy. Deployment 1/1 on rpi4.
- Ingress 자원 5개 잔존:
  - `hindsight/hindsight` → `hindsight.bhyoo.com, hindsight-api.bhyoo.com`
  - `immich/immich-server` → `immich.bhyoo.com`
  - `object-storage/versitygw` → `versitygw.bhyoo.com, s3.bhyoo.com, admin-s3.bhyoo.com`
  - `prometheus/shared-grafana` → `grafana.bhyoo.com`
  - `prometheus/shared-prometheus` → `prometheus.bhyoo.com`
- IngressClass `traefik` 1개 (Traefik 컨트롤러가 생성한 동적 리소스).

### 0.3 HTTPRoute 현황

- 배포된 HTTPRoute: **2개**
  - `argocd/argocd-server` (helm chart `values/argo-cd/backbone.yaml`의 `server.httproute`로 배포) — `argocd.bhyoo.com`, parentRef=`bhyoo-gateway`
  - `argocd/argocd-webhook` (file `apps/objects/argocd/httproute-webhook.yaml`로 배포) — `argocd-webhook.bhyoo.com`, parentRef=`cloudflare-gateway/cloudflare-tunnel`
- 작성됐지만 **미배포** HTTPRoute (5개 파일, 8개 route): `apps/objects/cilium-gateway/httproutes/{hindsight,immich,monitoring,versitygw}.yaml` (versitygw 3개, monitoring 2개, hindsight 2개, immich 1개)
  - 미배포 원인: `argocd/appprojects/networking.yaml`의 `destinations`가 `kube-system, cilium-secrets, ingress-ctrl`만 허용. HTTPRoute YAML의 namespace는 `argocd, hindsight, immich, object-storage, prometheus`라 ArgoCD가 거부.
- `bhyoo-gateway` Listener `https`의 `Attached Routes: 1`. 즉 argocd 1개만 연결.

### 0.4 결과적으로 발생한 outage

- DNS `*.bhyoo.com → 10.222.0.3` (rpi5 WG IP).
- rpi5:443 진입 → KPR/eBPF의 BPF service map에서 `cilium-gateway-bhyoo-gateway`가 `traefik` 서비스를 가린 상태. (curl `grafana.bhyoo.com → 10.222.0.3` 결과 `HTTP/2 404, server: envoy` 확인)
- 따라서 다음 hostname들이 현재 **404로 응답**:
  - `grafana.bhyoo.com`
  - `prometheus.bhyoo.com`
  - `hindsight.bhyoo.com`
  - `hindsight-api.bhyoo.com`
  - `immich.bhyoo.com`
  - `versitygw.bhyoo.com`
  - `s3.bhyoo.com`
  - `admin-s3.bhyoo.com`
- 정상: `argocd.bhyoo.com` (HTTPRoute 존재), `argocd-webhook.bhyoo.com` (별도 cloudflare gateway 경유).

### 0.5 외부 DNS 현황

- `backbone-external-dns` Synced, Healthy.
- `values/external-dns/backbone.yaml` `sources: [node, service, ingress]`. **`gateway-httproute` 없음**.
- 따라서 현재 DNS A 레코드는 “LB Service IP (Traefik의 10.222.0.3)” 또는 “Ingress.status” 경유로 작성됨. Traefik 제거 후 자동 갱신 안 됨.

---

## 1. 시급 이슈 정리

| # | 이슈 | 영향 | 우선순위 |
|---|------|------|---------|
| A | Grafana, Prometheus, Hindsight, Immich, VersityGW 5개 hostname 404 | 사용자 영향 활성화 중 | P0 |
| B | external-dns가 HTTPRoute 호스트를 모름 | Traefik 제거 시 DNS 깨짐 | P1 |
| C | bhyoo-gateway가 rpi4 WG IP 포함 (Envoy 없음) | 클라이언트가 rpi4 IP 선택 시 dead end | P2 |
| D | Traefik DaemonSet/Service 잔존 (port 443 conflict 잠재) | KPR shadow로 동작 안 함, 자원만 차지 | P2 |
| E | static-lb 잔존 | Node IPAM과 중복, 부수효과는 없으나 정리 필요 | P3 |
| F | `backbone-traefik` OutOfSync | 진단 필요 | P3 |
| G | 다음 Traefik values 파일 잔존 후 prod 클러스터 영향 | prod 클러스터는 별도 (이번 범위 밖) | P3 |

P0 = 시작 즉시. P1~P3 = 순차 정리.

---

## 2. 변경 범위

### 2.1 변경 대상

- `argocd/appprojects/networking.yaml` (destinations 확장)
- `values/external-dns/backbone.yaml` (sources/flag 추가)
- `values/hindsight/backbone.yaml` (Traefik Ingress 비활성)
- `values/immich/backbone.yaml` (Traefik Ingress 비활성)
- `values/versitygw/backbone.yaml` (Traefik Ingress 비활성)
- `values/kube-prometheus-stack/backbone.yaml` (grafana/prometheus ingress 비활성)
- `argocd/appsets/traefik.yaml` (backbone 항목 제거)
- `argocd/appsets/static-lb.yaml` (backbone 항목 제거)
- `apps/objects/cilium-gateway/gateway.yaml` (`infrastructure.annotations`로 노드 후보 제한)
- (선택) cluster-setup ansible: 4 노드에 `homelab.bhyoo.com/cilium-envoy=true` 라벨

### 2.2 비변경 (이 범위 밖)

- `values/cilium/backbone.yaml` (CNI/KPR/Node IPAM 그대로 사용)
- `cluster-setup/k3s.yaml`, `cluster-setup/firewall.yaml` (v2에서 적용 완료)
- prod 클러스터 (별도 마이그레이션 계획 필요. 이번엔 손대지 않음)
- LB-IPAM, L2 Announcement (LG U+ 라우터 검증 후 별도 계획)
- WireGuard 메쉬, k3s 노드 구성 (그대로)

---

## 3. Phase 계획

각 Phase의 verification gate를 모두 통과한 후에만 다음 Phase로 진행. 적어도 한 hostname에 대해 brower-level 동작도 함께 확인.

### Phase A. 즉시 복구 (HTTPRoute 5개 배포)

**목표**: 5개 hostname 200 응답 회복.

**작업**

A.1 `argocd/appprojects/networking.yaml` `destinations`에 다음 namespace 추가:

```yaml
- namespace: argocd
  name: backbone
- namespace: hindsight
  name: backbone
- namespace: immich
  name: backbone
- namespace: object-storage
  name: backbone
- namespace: prometheus
  name: backbone
```

A.2 `apps/objects/cilium-gateway/httproutes/{hindsight,immich,monitoring,versitygw}.yaml`는 이미 작성됨. 추가 변경 없이 그대로 사용.

A.3 commit + push to `master`.

```bash
cd ~/projects/kubernetes/homelab
git checkout master && git pull
git add argocd/appprojects/networking.yaml
git commit -m "feat(networking): expand AppProject destinations for HTTPRoute namespaces"
git push origin master
```

A.4 `argocd-appprojects` App sync 대기 → `backbone-cilium-gateway` selfHeal sync.

```bash
kubectl --context private-backbone -n argocd wait app argocd-appprojects \
  --for=jsonpath='{.status.sync.status}'=Synced --timeout=5m
kubectl --context private-backbone -n argocd wait app backbone-cilium-gateway \
  --for=jsonpath='{.status.sync.status}'=Synced --timeout=5m
kubectl --context private-backbone -n argocd wait app backbone-cilium-gateway \
  --for=jsonpath='{.status.health.status}'=Healthy --timeout=5m
```

**Verification Gate A**

```bash
# 1. HTTPRoute 8개 모두 존재
kubectl --context private-backbone get httproute -A
# expect: argocd/argocd-server, argocd/argocd-webhook,
#         hindsight/hindsight, hindsight/hindsight-api,
#         immich/immich,
#         object-storage/versitygw-ui, versitygw-s3, versitygw-admin,
#         prometheus/grafana, prometheus/prometheus

# 2. 각 HTTPRoute Accepted=True, ResolvedRefs=True
for h in $(kubectl --context private-backbone get httproute -A -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name} {end}'); do
  echo "--- $h ---"
  kubectl --context private-backbone -n "${h%/*}" describe httproute "${h#*/}" 2>&1 | sed -n '/Status:/,/Events:/p' | grep -E "(Accepted|ResolvedRefs|Type|Status|Reason)"
done

# 3. bhyoo-gateway Listener Attached Routes 증가
kubectl --context private-backbone -n ingress-ctrl describe gateway bhyoo-gateway | grep "Attached Routes"
# expect: Attached Routes: 9  (argocd-server + 8 from cilium-gateway dir)

# 4. 외부 curl: 9개 hostname 모두 200 또는 인증 redirect (3xx)
for host in argocd.bhyoo.com argocd-webhook.bhyoo.com \
           hindsight.bhyoo.com hindsight-api.bhyoo.com \
           immich.bhyoo.com \
           versitygw.bhyoo.com s3.bhyoo.com admin-s3.bhyoo.com \
           grafana.bhyoo.com prometheus.bhyoo.com; do
  code=$(curl -sk --resolve "$host:443:10.222.0.3" "https://$host" -o /dev/null -w "%{http_code}" --max-time 10)
  echo "$host => $code"
done
# expect: 모두 2xx/3xx. 5xx 또는 4xx 발생 시 stop.
```

**Failure handling**: 한 hostname이라도 4xx/5xx면 다음 phase로 진행 금지. HTTPRoute의 `backendRefs.name`/`port`가 실제 Service와 일치하는지 검증. 필요한 경우 HTTPRoute YAML 수정 후 재push.

### Phase B. external-dns가 HTTPRoute hostname을 추적하도록 전환

**목표**: Traefik Ingress 제거 후에도 DNS가 자동 동기화되도록.

**작업**

B.1 `values/external-dns/backbone.yaml` 수정:

```yaml
sources:
  - node
  - service
  - gateway-httproute   # ADD
  # - ingress           # KEEP for now; remove after Phase D
```

B.2 (필수 검토) Helm chart가 지원하는 `extraArgs` 또는 `txtSuffix` 설정에서 Gateway source 필터 추가:

```yaml
extraArgs:
  - --service-type-filter=LoadBalancer
  - --gateway-name=bhyoo-gateway
  - --gateway-namespace=ingress-ctrl
```

> external-dns chart의 `gateway-name` flag 지원 버전 확인 필요. 미지원 시 chart 업그레이드 또는 `--label-filter` 활용.

B.3 commit + push.

```bash
git add values/external-dns/backbone.yaml
git commit -m "feat(external-dns/backbone): add gateway-httproute source for Cilium Gateway hostnames"
git push origin master
```

B.4 ArgoCD sync 대기 + external-dns Pod 재시작 확인 + 로그 확인.

```bash
kubectl --context private-backbone -n argocd wait app backbone-external-dns \
  --for=jsonpath='{.status.sync.status}'=Synced --timeout=5m
kubectl --context private-backbone -n dns-manager rollout status deploy/external-dns --timeout=3m
kubectl --context private-backbone -n dns-manager logs deploy/external-dns --tail=100 | grep -iE "(gateway|httproute|argocd|grafana|hindsight)"
```

**Verification Gate B**

```bash
# external-dns가 HTTPRoute를 인식했는지: log에 "Add" 또는 "Update" 로그 + Cloudflare DNS에서 변경 확인
# 1. 로그에 HTTPRoute hostname들이 보여야 함
kubectl --context private-backbone -n dns-manager logs deploy/external-dns --tail=200 \
  | grep -E "(argocd|grafana|prometheus|hindsight|immich|versitygw|s3)\.bhyoo\.com"

# 2. external-dns의 인식 source 종류 확인
kubectl --context private-backbone -n dns-manager exec deploy/external-dns -- \
  /external-dns --help 2>&1 | grep -A2 "source"

# 3. Cloudflare DNS A 레코드 비교 (이전 = 10.222.0.3 only, 변경 후 = 동일하거나 추가)
# Cloudflare 대시보드 또는 API로 확인. flux 변화가 없어야 정상.
```

**Failure handling**: external-dns log에 `error fetching httproutes` 등 RBAC/permission 에러 발생 시 ClusterRole에 `httproutes` 추가 필요. chart values에 `rbac.additionalPermissions` 또는 외부 RBAC manifest 검토.

### Phase C. Gateway 노드 후보 제한 (rpi4 제외)

**목표**: rpi4는 Envoy가 없어 트래픽을 처리 못함. LB Service ingress 목록에서 제거.

**작업**

C.1 4개 노드(`rpi5, rock5bp, n2p1, n2p2`)에 라벨 `homelab.bhyoo.com/cilium-envoy=true` 추가. 두 가지 방법:

**옵션 C.1.a (ansible 권장)**: `cluster-setup/inventory/host_vars/{rpi5,rock5bp,n2p1,n2p2}.yaml`의 `k8s_node_labels`에 추가. 다음 노드 재시작 시 적용. 즉시 적용은 어려움.

**옵션 C.1.b (kubectl 즉시)**: 다음 명령 4회.

```bash
for n in rpi5 rock5bp n2p1 n2p2; do
  kubectl --context private-backbone label node "$n" homelab.bhyoo.com/cilium-envoy=true --overwrite
done
kubectl --context private-backbone get node -L homelab.bhyoo.com/cilium-envoy
```

GitOps 정합성을 위해 옵션 a + b 둘 다 적용 권장 (즉시 적용 + 향후 재생성에도 유지).

C.2 `apps/objects/cilium-gateway/gateway.yaml`에 infrastructure annotation 추가:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: bhyoo-gateway
  namespace: ingress-ctrl
  annotations:
    cert-manager.io/cluster-issuer: cluster-issuer-acme
    cert-manager.io/private-key-algorithm: ECDSA
    cert-manager.io/private-key-size: "384"
spec:
  gatewayClassName: cilium
  infrastructure:
    annotations:
      io.cilium.nodeipam/match-node-labels: "homelab.bhyoo.com/cilium-envoy=true"
  listeners: [ ... 기존 그대로 ... ]
```

C.3 commit + push.

```bash
git add cluster-setup/inventory/host_vars/{rpi5,rock5bp,n2p1,n2p2}.yaml \
        apps/objects/cilium-gateway/gateway.yaml
git commit -m "feat(cilium-gateway): restrict Node IPAM exposure to Envoy-eligible nodes (exclude rpi4)"
git push origin master
```

C.4 ArgoCD sync.

**Verification Gate C**

```bash
# Gateway Service EXTERNAL-IP에서 10.222.0.5 (rpi4) 사라져야 함
kubectl --context private-backbone -n ingress-ctrl get svc cilium-gateway-bhyoo-gateway -o wide
# expect: EXTERNAL-IP = 10.222.0.1,10.222.0.2,10.222.0.3,10.222.0.4 (4개)

# Gateway.status.addresses 동일 확인
kubectl --context private-backbone -n ingress-ctrl get gateway bhyoo-gateway -o jsonpath='{.status.addresses[*].value}'

# 9개 hostname 200/3xx 유지 (위 Phase A의 curl 반복)
```

**Failure handling**: rollback은 annotation 제거 + label 유지(harmless). curl이 깨지면 즉시 revert.

### Phase D. Traefik 제거

**목표**: Traefik DaemonSet/Service/AppProject 전면 제거.

> 이미 Cilium이 port 443을 선점 중이라 사용자 트래픽 영향은 거의 없음. 그래도 안전 절차 따름.

**작업**

D.1 5개 hostname 대응하는 values 파일에서 Traefik Ingress 비활성. 일반 패턴:

```yaml
# Before
ingress:
  enabled: true
  ingressClassName: traefik
  annotations:
    traefik.ingress.kubernetes.io/router.entrypoints: websecure
    cert-manager.io/cluster-issuer: cluster-issuer-acme
    ...
  hosts: [...]
  tls: [...]

# After
ingress:
  enabled: false
```

대상 파일:

- `values/hindsight/backbone.yaml` — block at line 81 `ingress:` → set `enabled: false`
- `values/immich/backbone.yaml` — block at line 118 `ingress:` → set `enabled: false`
- `values/versitygw/backbone.yaml` — block at line 28 `ingress:` → set `enabled: false`
- `values/kube-prometheus-stack/backbone.yaml` — 두 곳:
  - line 33 `grafana.ingress` → `enabled: false`
  - line 280 `prometheus.ingress` → `enabled: false`

D.2 ApplicationSet `argocd/appsets/traefik.yaml`에서 `backbone` 항목 삭제:

```yaml
generators:
  - list:
      elements:
        - cluster: prod   # backbone 줄 삭제
```

D.3 `argocd/apps/_traefik-internal.yaml` — `_` 접두사 그대로 두면 ArgoCD에 미배포라 영향 없음. 정리 차원에서 삭제는 선택.

D.4 commit + push.

```bash
git add values/hindsight/backbone.yaml values/immich/backbone.yaml \
        values/versitygw/backbone.yaml values/kube-prometheus-stack/backbone.yaml \
        argocd/appsets/traefik.yaml
git commit -m "chore(backbone): disable Traefik Ingress for 5 apps (moved to Cilium Gateway HTTPRoute)"
git push origin master
```

D.5 ArgoCD sync 진행. `backbone-traefik` App 자동 삭제 + finalizer로 종속 리소스 cleanup.

```bash
# Application 삭제 진행 확인
kubectl --context private-backbone -n argocd get app backbone-traefik -o wide
# 사라질 때까지 대기 (5분 이내)

# Pod, DaemonSet, Service 모두 사라졌는지
kubectl --context private-backbone -n ingress-ctrl get all -l app.kubernetes.io/name=traefik
# expect: No resources found.

# Ingress 자원 사라짐
kubectl --context private-backbone get ingress -A
# expect: hindsight, immich, versitygw, shared-grafana, shared-prometheus 모두 사라짐.

# IngressClass 사라짐
kubectl --context private-backbone get ingressclass
# expect: traefik 사라짐. 다른 자동 생성 IngressClass는 없을 것.
```

D.6 (선택) Phase D 후 `values/external-dns/backbone.yaml`의 `sources:`에서 `ingress` 제거.

**Verification Gate D**

```bash
# 1. Traefik 잔존 0
kubectl --context private-backbone get all,ingress,ingressclass,daemonset -A 2>/dev/null \
  | grep -i traefik || echo "OK: no traefik resources"

# 2. 9개 hostname 200/3xx 유지
# (Phase A의 curl 루프 재실행)

# 3. cert-manager가 traefik 관련 Challenge 생성 안 함 (자동, 확인용)
kubectl --context private-backbone -n ingress-ctrl get challenge,order 2>&1 | head
```

**Failure handling**: hostname 응답이 깨지면 `git revert <commit>` + push. ArgoCD가 Traefik 자동 복원 (App `backbone-traefik` 다시 생성 + Helm install).

### Phase E. static-lb 제거

**목표**: Node IPAM이 LB IP를 단독 관리.

> static-lb는 LoadBalancer Service.status.loadBalancer.ingress[]를 채우는 도구. Node IPAM이 같은 역할을 하고, 현재 Cilium Gateway는 이미 Node IPAM이 채우고 있다. Traefik이 사라진 뒤에도 static-lb가 채우는 LB가 더는 없는지 확인 후 제거.

**작업**

E.1 다른 LoadBalancer Service 목록 확인.

```bash
kubectl --context private-backbone get svc -A --field-selector spec.type=LoadBalancer -o wide
# Phase D 후 expect: cilium-gateway-bhyoo-gateway, (가능하면 jellyfin, dolfan 등 일부 앱이 LB 사용 시)
```

E.2 각 LB Service가 Node IPAM에서 정상 IP를 받는지 확인. 만약 `loadBalancerClass`가 명시되지 않은 LB가 있다면 `default-lb-service-ipam: nodeipam` 덕에 자동 할당.

E.3 ApplicationSet `argocd/appsets/static-lb.yaml` 수정 (생성 list에서 `backbone` 제거하거나 전체 제거).

```yaml
generators:
  - list:
      elements: []   # 또는 prod만
```

E.4 commit + push.

```bash
git add argocd/appsets/static-lb.yaml
git commit -m "chore(backbone): remove static-lb (replaced by Cilium Node IPAM)"
git push origin master
```

E.5 ArgoCD sync. `backbone-static-lb` App 자동 삭제.

**Verification Gate E**

```bash
# static-lb Pod/Deployment 사라짐
kubectl --context private-backbone -n loadbalancer get all 2>&1
# expect: No resources found.

# 모든 LoadBalancer Service가 EXTERNAL-IP 유지
kubectl --context private-backbone get svc -A --field-selector spec.type=LoadBalancer -o wide \
  | awk 'NR==1 || $5!="<pending>"'
# expect: cilium-gateway-bhyoo-gateway가 4개 WG IP 유지. 다른 LB 서비스 IP도 유지.

# 9 hostname 정상
```

**Failure handling**: LB Service의 EXTERNAL-IP가 `<pending>`이 되면 static-lb 의존 Service가 있다는 뜻. App 삭제 전에 해당 Service의 loadBalancerClass를 명시(`io.cilium/node`)하거나, Phase E를 일시 보류.

### Phase F. 정리와 검증

**작업**

F.1 `values/external-dns/backbone.yaml`에서 `ingress` source 제거.

```yaml
sources:
  - node
  - service
  - gateway-httproute
```

F.2 commit + push + sync.

F.3 추가 검증:

```bash
# 1. ArgoCD 전체 App Healthy
kubectl --context private-backbone -n argocd get app -o wide \
  | awk 'NR==1 || $2!="Synced" || $3!="Healthy"'
# expect: 헤더만 출력 (모두 Synced+Healthy)

# 2. 모든 노드 Ready
kubectl --context private-backbone get nodes
# expect: 5 Ready

# 3. cilium-envoy DS 4/4
kubectl --context private-backbone -n kube-system get ds cilium-envoy
# expect: DESIRED=4, READY=4

# 4. Gateway 잘 동작
kubectl --context private-backbone -n ingress-ctrl describe gateway bhyoo-gateway | grep "Attached Routes"
# expect: 9

# 5. 9 hostname 모두 200/3xx
# (Phase A의 curl 루프 반복)

# 6. iptables 룰 수: kube-proxy 0, Cilium 룰만 잔존
ssh bhyoo@192.168.219.5 sudo iptables -L -n -t nat | wc -l
# 비교 기준값: v2 backup 시 측정한 수치. 마이그레이션 전 대비 큰 폭 감소 기대.

# 7. DNS 정합성: Cloudflare에서 9 hostname의 A 레코드가 4개 WG IP를 가리키는지
# (external-dns가 채워야 함)
```

F.4 문서 업데이트: README의 “TODO list” `[ ] traefik 대시보드 추가` 같은 항목 정리 (선택).

---

## 4. 파일별 변경 요약

| Phase | 파일 | 변경 | 확인 |
|-------|------|------|------|
| A | `argocd/appprojects/networking.yaml` | destinations에 5개 namespace 추가 | `kubectl get appproject networking -o yaml` |
| B | `values/external-dns/backbone.yaml` | sources에 `gateway-httproute` 추가, gateway flag 옵션 추가 | external-dns log |
| C | `cluster-setup/inventory/host_vars/{rpi5,rock5bp,n2p1,n2p2}.yaml` | `k8s_node_labels`에 `homelab.bhyoo.com/cilium-envoy=true` | `kubectl get node -L ...` |
| C | `apps/objects/cilium-gateway/gateway.yaml` | `spec.infrastructure.annotations.io.cilium.nodeipam/match-node-labels` | `kubectl get svc cilium-gateway-bhyoo-gateway` |
| D | `values/hindsight/backbone.yaml` | `ingress.enabled: false` | App sync + Ingress 없음 |
| D | `values/immich/backbone.yaml` | `ingress.enabled: false` | ditto |
| D | `values/versitygw/backbone.yaml` | `ingress.enabled: false` | ditto |
| D | `values/kube-prometheus-stack/backbone.yaml` | grafana/prometheus `ingress.enabled: false` | ditto |
| D | `argocd/appsets/traefik.yaml` | backbone 항목 제거 | App `backbone-traefik` 삭제 |
| D (선택) | `argocd/apps/_traefik-internal.yaml` | 파일 삭제 (이미 비활성) | n/a |
| E | `argocd/appsets/static-lb.yaml` | backbone 항목 제거 | App `backbone-static-lb` 삭제 |
| F | `values/external-dns/backbone.yaml` | `ingress` source 제거 | external-dns 재시작 후 정상 |

---

## 5. 위험과 롤백

### 5.1 Phase별 롤백

| Phase | 롤백 방법 | 회복 시간 |
|-------|----------|----------|
| A | `git revert <commit> && git push` → ArgoCD sync → HTTPRoute prune | 2~3분 |
| B | `git revert` → external-dns Pod 재기동 | 2~3분 |
| C | `git revert` → node label은 그대로 유지(harmless) | 2~3분 |
| D | `git revert` → ApplicationSet 다시 backbone 포함 → Traefik Helm install 재실행. 그동안 Cilium Gateway가 트래픽 받음. **단 5분 정도 양쪽 동시 존재 후 KPR shadow 다시 발생** | 5~10분 |
| E | `git revert` → static-lb 재배포 | 2~3분 |
| F | `git revert` | 2분 |

### 5.2 전역 롤백 (Cilium 전체 제거)

`docs/runbook-cilium-migration-v2.md`의 “Rollback Level 2/3” 절차 사용. 그러나 v3 변경만 되돌리고자 한다면 위 Phase별 revert로 충분.

### 5.3 위험 시나리오

| 시나리오 | 가능성 | 영향 | 완화책 |
|---------|-------|------|--------|
| Phase A 후 HTTPRoute backend Service가 실제 Pod 셀렉터와 불일치 | 중 | 일부 hostname 503 | curl 검증 + describe httproute |
| Phase B에서 external-dns chart가 `gateway-httproute` source 미지원 | 낮음 | DNS 자동화 멈춤 | chart version 사전 확인. 미지원 시 chart 업그레이드 또는 수동 DNS 임시 운영 |
| Phase C에서 `io.cilium.nodeipam/match-node-labels` annotation 미인식 | 낮음 | rpi4 IP 계속 노출 (현재 상태) | Cilium v1.16+ 필요. 현재 1.19.4이므로 안전 |
| Phase C에서 ansible inventory 변경이 즉시 반영되지 않음 | 중 | label 누락 노드 발생 시 Gateway IP 누락 | 옵션 C.1.b의 kubectl label도 함께 적용 |
| Phase D에서 Traefik Helm release prune이 5분 안에 안 끝남 | 낮음 | 자원 잔존 | kubectl wait + cascade=foreground 수동 삭제 fallback |
| Phase D에서 cert-manager가 Traefik Ingress의 acme http-01 challenge 운영 중 | 낮음 (DNS-01 사용 중) | 새 인증서 발급 실패 | wildcard cert는 DNS-01이므로 영향 없음. 개별 ingress 인증서가 있다면 별도 확인 |
| Phase E에서 다른 LB Service가 static-lb 의존 | 낮음 | EXTERNAL-IP=pending | Phase E.1 확인. 의존 발견 시 loadBalancerClass 명시 |
| backbone-traefik OutOfSync 원인이 CRD 잔존 | 중 | App 삭제 후에도 CRD 자존 | Phase D 후 `kubectl get crd | grep traefik`로 정리. Traefik CRD는 일반 ingress 동작에 영향 없음 |

### 5.4 절대 하지 말 것

- `kubectl delete --all` 류 와일드카드
- ArgoCD App을 `--cascade=orphan`으로 삭제 (리소스 prune 안 됨)
- `cilium-gateway-bhyoo-gateway` Service 직접 수정 (Cilium operator가 재생성하므로 의미 없고 일관성 깨짐)
- Cilium agent/operator 재시작 (불필요. 현재 안정 동작)

---

## 6. 사전 점검 체크리스트 (Phase A 시작 전)

```bash
# 1. 작업 머신이 master 브랜치, working tree clean
cd ~/projects/kubernetes/homelab
git checkout master && git pull
git status --short
# expect: clean

# 2. kubectl context 정상
kubectl --context private-backbone get nodes
# expect: 5 Ready

# 3. ArgoCD Healthy
kubectl --context private-backbone -n argocd get app -o wide \
  | awk 'NR==1 || $3!="Healthy" && $3!="Progressing"' | head

# 4. Cilium operator + agent Healthy
kubectl --context private-backbone -n kube-system get pods -l io.cilium/app=operator
kubectl --context private-backbone -n kube-system get ds cilium

# 5. cert-manager + wildcard cert Ready
kubectl --context private-backbone -n ingress-ctrl get certificate wildcard-bhyoo-com -o yaml \
  | yq '.status.conditions[] | select(.type=="Ready")'

# 6. backup 확보 (v2 backup이 충분히 최근인지)
ls -lt ~/backup/cilium-migration/ | head
# 일주일 이상 지났으면 새 etcd snapshot 생성 권장
```

---

## 7. 후속 계획 (이 runbook 범위 밖)

1. **prod 클러스터 마이그레이션**: 별도 계획 필요. backbone과 다르게 prod는 노드별 LAN/WG/external IP 매핑이 더 복잡(`values/static-lb/prod.yaml`의 `internalIPMappings/externalIPMappings`). prod도 단일 스택으로 갈지, LAN 노출 plane을 따로 둘지 결정 후 v4 runbook 작성.
2. **LAN VIP 도입 가능성**: LG U+ 라우터 `ARP spoofing 대응` 비활성 + Cilium L2 Announcement + LB-IPAM 도입 검토. 별도 검증 + 별도 plane.
3. **WG VIP 진짜 fail-over**: 현재 rpi5 단일 노드 의존이 아닌 진정한 multi-node WG endpoint failover가 필요하면 BGP 또는 외부 health-checked LB(별도 SBC) 필요. 후속 계획.

---

## 8. 진행 보고 포맷

각 Phase 완료 시 다음 형식으로 요약:

```
Phase X 완료: <시각>
- 변경 commit: <hash>
- ArgoCD sync 시간: Xm Ys
- 9 hostname 응답: 9/9 OK
- 추가 발견: <있다면>
- 다음 Phase 예정: <시각>
```

기록 위치: 본 문서 최하단에 append 또는 별도 progress log.

