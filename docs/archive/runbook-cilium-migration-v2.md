# Cilium Migration Runbook v2 — Backbone Cluster

## 변경 개요

Flannel(host-gw) + k3s 내장 kube-proxy + static-lb + Traefik → Cilium v1.19.2 통합
(CNI + kubeProxyReplacement + Node IPAM LB + Gateway API)

### v1 결함 12개 해결 방식

| # | v1 결함 | v2 해결 |
|---|---------|---------|
| 1 | ArgoCD 롤백이 branch-push로는 반영 안 됨 | **모든 커밋/revert는 default branch(master)에서 직접 수행**. feature branch 금지 |
| 2 | LB-IPAM 풀이 노드 IP와 충돌 | Node IPAM LB 사용, 풀 개념 제거 |
| 3 | wg0에서 L2 ARP 불가 | L2 announcement 사용 안 함 |
| 4 | Traefik↔Gateway VIP 충돌 | **Traefik을 먼저 완전 제거한 뒤 Gateway 설치 (시간 분리)**. 공존 모델 포기 |
| 5 | 스냅샷 실패 숨김 | 각 명령 exit code + 파일 크기 검증 |
| 6 | CoreDNS 재시작 제외 | kube-system 포함 전체 재시작 |
| 7 | grep -c "Ready" 버그 | awk '$2=="Ready"' |
| 8 | Gateway 분리 prose만 | 단일 Gateway + Node IPAM |
| 9 | verify.sh 약함 | **READY==desired, HTTP 200-399만 pass, 9개 hostname 전부 테스트** |
| 10 | HA etcd 재합류 순서 | **ansible-playbook을 master 순차(--limit rpi5 → rock5bp → rpi4), 각 Ready 대기** |
| 11 | datapathMode auto 불확실 | veth 명시 고정 |
| 12 | Gateway + netkit 호환 | veth 통일, tproxy false |

### 현재 인프라 감안

| Node | eth0 | wg0 | 커널 | netkit | Traefik Pod 배포 |
|------|------|-----|------|--------|------------------|
| rpi5 | .5 | 10.222.0.3 | 6.12 | ✅ | ✅ (vpn-gateway=true) |
| rock5bp | .6 | 10.222.0.4 | 6.1 | ❌ | ❌ |
| rpi4 | .7 | 10.222.0.5 | 6.12 | ✅ | ❌ |
| n2p1 | .3 | 10.222.0.1 | 6.6 | ❌ | ❌ (worker) |
| n2p2 | .4 | 10.222.0.2 | 6.6 | ❌ | ❌ (worker) |

**핵심 제약**:
- Traefik은 `externalTrafficPolicy: Local` + `nodeSelector: vpn-gateway=true` → rpi5에만. Node IPAM도 rpi5 wg0 IP(10.222.0.3)만 할당.
- Cilium Gateway Service도 동일 IP(10.222.0.3)를 원함 → **동시 운영 시 port 충돌**.
- 해결: **Traefik 먼저 완전 제거 → Gateway 설치** (단일 프런트엔드 시점 분리).
- 마스터 3대 동시 재시작하면 etcd quorum 손실. `--limit master1 → master2 → master3` 순차 필요.

---

## Reproducibility 설계

이 프로젝트 전반의 원칙: **fresh install도 `make argocd` 하나로 k3s + Cilium + ArgoCD + 전체 앱이 자동 구성**.

- `k3s.yaml`에 Cilium helm bootstrap play가 포함됨 (backbone 섹션 마지막에 추가)
- `make k3s` 실행 → k3s 설치 + CNI 없는 상태에서 k3s 기동 + 즉시 Cilium helm install + CNI 복구
- 이후 `make argocd` → ArgoCD 설치 (CNI 있는 상태) → argocd-apps가 전체 App-of-Apps sync
- `backbone-cilium` App이 ansible이 설치한 Helm release를 자동 adopt (releaseName=cilium, ns=kube-system 일치)

이 방식의 migration: **k3s.yaml 한 번만 재실행**해도 Cilium까지 설치됨. 수동 helm install 단계 없음.

## Phase 구조

각 Phase는 실패 시 rollback 가능한 체크포인트.

0. **Backup** — etcd snapshot + 노드별 설정/iptables + 클러스터 리소스
1. **Preparation** — Cilium values, Gateway/HTTPRoute, ArgoCD app 작성 (master 브랜치 직접, 아직 push X)
2. **Pre-flight** — dry-run 시뮬레이션
3. **CNI cutover** — Pre-stop + cold start + k3s.yaml (k3s + Cilium 자동 bootstrap)
4. **Ingress cutover** — Traefik 완전 제거 → Gateway API 설치
5. **static-lb 제거** — Node IPAM이 LB IP 관리 확인 후
6. **최종 검증**

---

## Phase 0: Backup

```bash
SSHPASS='<password>' ./docs/runbooks/v2/snapshot.sh
# 결과: ~/backup/cilium-migration/<timestamp>/
```

검증: `SUMMARY.txt` 생성됨 + 모든 파일 size > 0 + etcd snapshot sha256 기록.

---

## Phase 1: Preparation

> **모든 Git 작업은 default branch(`master`)에서 직접 수행**.
> ArgoCD Application의 `targetRevision: HEAD`가 `master`를 추적하므로 feature branch push는 반영되지 않음.

### 1.1 Cilium values 확정

`values/cilium/backbone.yaml` 이미 작성 완료 (Helm template + dry-run=server 통과).

### 1.2 ArgoCD Application 2개 작성

`argocd/apps/cilium.yaml`, `argocd/apps/cilium-gateway.yaml` — 이미 작성 완료.

### 1.3 Gateway + HTTPRoute 매니페스트

`apps/cilium-gateway/` 아래에 `gateway.yaml`, `certificate.yaml`, `httproutes/*.yaml` (9개) — 이미 작성 완료.

cert-manager `cluster-issuer-acme`가 Cloudflare DNS-01 지원 확인됨 → wildcard `*.bhyoo.com` 발급 가능.

### 1.4 k3s.yaml 수정

`cluster-setup/k3s.yaml` backbone 섹션:
```yaml
k3s_server:
  etcd-expose-metrics: true
  flannel-backend: 'none'           # 변경: host-gw → none
  disable-network-policy: true      # 추가
  disable-kube-proxy: true          # 추가
  disable-helm-controller: true
  disable:
    - traefik
    - servicelb
  # ... 기존 유지
```

### 1.5 firewall.yaml 수정

`cluster-setup/firewall.yaml` backbone role 변수에 추가:
```yaml
use_k8s_cilium: true
use_k8s_cilium_hubble: true
```

### 1.6 Phase별로 **각각 그 Phase 시점에 commit + push** (미리 commit하지 않음)

> **중요 변경**: Phase 3와 Phase 4 사이 시점 분리를 위해,
> Phase 1.6 단계에선 **파일만 working tree에 준비**해두고 commit하지 않음.
> Phase 3에서 Cilium 관련만 commit+push, Phase 4에서 Gateway 관련만 commit+push.
>
> 이유: 미리 2개 commit을 만든 뒤 hash 기반으로 부분 push하는 방식은
> `git push origin ":master"` 같은 재앙(원격 master 삭제)을 유발할 위험이 있음.
> Phase별 직접 commit+push가 가장 안전.

```bash
cd ~/projects/kubernetes/homelab
git checkout master && git pull
# 파일은 이미 working tree에 존재 (Cilium values, ArgoCD apps, Gateway manifest 등)
# 여기서는 아무것도 commit하지 않고 파일만 준비 상태 유지
git status --short
```

---

## Phase 2: Pre-flight (dry-run)

```bash
./docs/runbooks/v2/dry-run.sh ~/backup/cilium-migration/<timestamp>
```

검증 항목:
1. 백업 파일 완전성 (etcd snapshot 체크섬 포함)
2. Helm template 렌더링 + 핵심 values 반영 확인
3. `helm install --dry-run=server` (실제 API 검증)
4. `ansible-playbook --check` (k3s.yaml, firewall.yaml) — **모든 host에서 failed=0이어야만 PASS**
5. cert-manager ClusterIssuer DNS-01 지원 확인
6. ArgoCD auto-sync 상태
7. 스크립트 구문 검사
8. 필수 매니페스트 파일 존재

**FAIL 하나라도 있으면 Phase 3로 진행하지 마세요.**

---

## Phase 3: CNI Cutover — Pre-stop + Cold Start 방식

> **설계 원칙**: live migration 대신, 전 클러스터를 먼저 정지시킨 뒤
> 깨끗한 상태에서 Cilium으로 cold start. 이유:
>  - 중간 상태(Flannel 꺼짐 + Cilium 아직 없음) 경합 제거
>  - eBPF/iptables/tc 잔여물 reboot로 확정 정리
>  - migration/rollback 절차가 동형 (중지→reboot→설정→기동) → 검증 단순
>
> **Pod 네트워킹 중단 시작.** 예상 소요: 25-35분 (reboot 포함).

### 3.1 ArgoCD auto-sync 일시 해제 (Phase 3 실행 전 정지)

k3s가 살아있는 마지막 시점. Cilium 설치 후 ArgoCD가 traefik/static-lb를
재sync해서 간섭하지 않도록 미리 auto-sync 해제:
```bash
for app in backbone-traefik backbone-static-lb; do
  kubectl --context private-backbone -n argocd patch app "$app" --type=merge \
    -p '{"spec":{"syncPolicy":{"automated":null}}}'
done
```

### 3.2 Cilium 방화벽 포트 개방 (k3s 중지 전)

살아있는 상태에서 firewall 규칙 먼저 반영 (재부팅 후에도 persist):
```bash
cd cluster-setup
# 아래 명령은 사용자가 직접 실행 (ansible 실행 규칙)
ansible-playbook -i inventory/hosts firewall.yaml --limit backbone \
  -e use_k8s_cilium=true -e use_k8s_cilium_hubble=true
```

### 3.3 전 노드 k3s/k3s-agent 중지

> **이 시점부터 클러스터 완전 정지.** 모든 서비스 접근 불가.

```bash
cd cluster-setup
# 각 노드 role에 따라 k3s(master) 또는 k3s-agent(worker) 중지
# 사용자가 직접 실행:
for n in rpi5 rock5bp rpi4; do
  ansible -i inventory/hosts "$n" -m systemd -a "name=k3s state=stopped" --become
done
for n in n2p1 n2p2; do
  ansible -i inventory/hosts "$n" -m systemd -a "name=k3s-agent state=stopped" --become
done

# 확인
for n in rpi5 rock5bp rpi4 n2p1 n2p2; do
  echo "=== $n ==="
  ansible -i inventory/hosts "$n" -m shell -a "systemctl is-active k3s k3s-agent 2>/dev/null || true"
done
# 모두 inactive 또는 'unit not found' (해당 노드에 없는 유닛)
```

### 3.4 Flannel CNI 설정 파일 제거 (reboot 전에 정리)

reboot 후 k3s가 Cilium 설정으로 재기동할 때 방해하지 않도록:
```bash
for entry in "bhyoo@192.168.219.5:rpi5" "bhyoo@192.168.219.6:rock5bp" \
             "bhyoo@192.168.219.7:rpi4" "root@192.168.219.3:n2p1" \
             "root@192.168.219.4:n2p2"; do
  IFS=: read -r target name <<< "$entry"
  echo "=== $name ==="
  # Flannel이 만든 설정 파일 제거 (k3s에 내장된 기본 경로)
  case "$target" in
    bhyoo@*)
      ssh "$target" "echo haZldGoQh3! | sudo -S -p '' rm -f /etc/cni/net.d/10-flannel* /etc/cni/net.d/*cilium* 2>&1 | grep -v password"
      ;;
    root@*)
      ssh "$target" "rm -f /etc/cni/net.d/10-flannel* /etc/cni/net.d/*cilium*"
      ;;
  esac
done
```

### 3.5 전 노드 병렬 reboot

HA etcd quorum 걱정 없음 (이미 전부 shutdown). 병렬 dispatch → down/up 검증:

```bash
# 스크립트로 실행 (_lib.sh의 reboot_all_nodes_parallel_safely 사용)
SSHPASS='<password>' bash -c '
source ./docs/runbooks/v2/_lib.sh
reboot_all_nodes_parallel_safely || { echo "FAIL"; exit 1; }
'
```

확인: 전 노드 booting 완료, SSH 응답, boot time 변경됨.

### 3.6 k3s + Cilium 설치 (단일 명령)

`k3s.yaml`이 이제 두 play로 구성됨: ① k3s 설치, ② Cilium helm bootstrap.
따라서 한 번의 `ansible-playbook k3s.yaml`이 k3s 기동 + CNI 복구까지 수행.

```bash
cd cluster-setup
# 사용자가 직접 실행:
ansible-playbook -i inventory/hosts k3s.yaml --limit backbone
```

내부 실행 흐름:
1. ansible이 각 backbone 노드에 k3s 재설치 (xanmanning.k3s role)
   - `flannel-backend: none`, `disable-kube-proxy: true` 설정 반영
2. k3s 기동 (CNI 없는 상태, 일시적)
3. primary master에서 `kubernetes.core.helm` 모듈로 Cilium bootstrap
4. Cilium DS/Envoy/Operator Ready 대기 (각 5분 timeout)
5. CNI 설치 완료 → 노드 Ready → Pod 생성 가능

**이 시점 상태**: k3s + Cilium 완전 동작. ArgoCD 등 기존 Pod들이 자연 복구 시작.

### 3.7 Pending Pod들 자연 복구 대기

```bash
# 노드 Ready 확인 (CNI 도착했으므로)
kubectl --context private-backbone wait node --all --for=condition=Ready --timeout=10m

# 모든 Pod Running 대기 (Pending → ContainerCreating → Running)
# 최대 10분 대기
for i in $(seq 1 60); do
  PENDING=$(kubectl --context private-backbone get pods -A --no-headers 2>/dev/null \
    | awk '$4!="Running" && $4!="Completed"' | wc -l)
  echo "Pending/비정상 Pod: $PENDING"
  [[ "$PENDING" -eq 0 ]] && break
  sleep 10
done

kubectl --context private-backbone get pods -A | grep -v Running | grep -v Completed
```

### 3.8 Commit 1 push → ArgoCD adopt

이제 ArgoCD가 살아있으므로 Cilium을 ArgoCD로 관리 이관:

```bash
cd ~/projects/kubernetes/homelab
if [[ "$(git branch --show-current)" != "master" ]]; then
  echo "ERROR: not on master"; exit 1
fi

# CNI migration 범위만 stage
git add \
  values/cilium/backbone.yaml \
  argocd/apps/cilium.yaml \
  cluster-setup/k3s.yaml \
  cluster-setup/firewall.yaml \
  docs/runbook-cilium-migration-v2.md \
  docs/runbooks/v2/

# Gateway 관련 파일이 staged되지 않았는지 확인
git diff --cached --name-only | grep -E "cilium-gateway|apps/cilium-gateway" \
  && { echo "ERROR: Gateway 파일이 staged됨. reset 후 재stage"; exit 1; } || true

git commit -m "feat(backbone): Cilium CNI + KPR + Node IPAM LB (migration part 1)"
git push origin master

# ArgoCD sync
kubectl --context private-backbone -n argocd wait app argocd-apps \
  --for=jsonpath='{.status.sync.status}'=Synced --timeout=5m

# backbone-cilium App이 생성되고 기존 helm release를 adopt
# App의 releaseName=cilium + namespace=kube-system과 일치하면 자동 adopt
kubectl --context private-backbone -n argocd wait app backbone-cilium \
  --for=jsonpath='{.status.sync.status}'=Synced --timeout=10m
kubectl --context private-backbone -n argocd wait app backbone-cilium \
  --for=jsonpath='{.status.health.status}'=Healthy --timeout=5m
```

### 3.9 Phase 3 검증

```bash
# CoreDNS
kubectl --context private-backbone run dns-test-$RANDOM --rm -it \
  --image=busybox:1.36 --restart=Never \
  -- nslookup kubernetes.default.svc.cluster.local

# Traefik Pod + LB IP (여전히 rpi5에만, wg0=10.222.0.3)
kubectl --context private-backbone -n ingress-ctrl get svc traefik

# 기존 9개 서비스 접근 (Traefik 경유)
curl -k --resolve argocd.bhyoo.com:443:10.222.0.3 https://argocd.bhyoo.com -I
```

**Phase 3 성공 기준**:
- 모든 노드 Ready
- Cilium DS/Envoy/Operator Ready (DESIRED == READY)
- backbone-cilium App Synced + Healthy
- CoreDNS 응답
- Traefik LB IP 유지 (Node IPAM 자동 인수)
- 기존 Ingress 9개 접근 가능

---

## Phase 4: Ingress Cutover (Traefik 완전 제거 → Gateway 설치)

> **이 Phase는 Traefik과 Gateway가 동시에 10.222.0.3:443을 주장하지 못하게 하기 위해 완전히 분리된 시간대에 실행합니다.**
> 짧은 Ingress 다운타임(수 분)이 발생합니다.

### 4.1 사전 준비: wildcard Certificate 발급 (Gateway 배포 전)

Gateway listener가 바로 동작하려면 Secret이 먼저 존재해야 함.
이 단계에선 Certificate 리소스만 **직접 apply** (아직 ArgoCD Gateway App 없음):

```bash
# Git에는 아직 Gateway App commit이 푸시되지 않았음. 직접 apply로 선행 발급.
kubectl --context private-backbone apply -f apps/cilium-gateway/certificate.yaml

# cert-manager가 DNS-01 validation 후 Ready (Cloudflare API 호출, ~2-5분)
kubectl --context private-backbone -n ingress-ctrl wait certificate wildcard-bhyoo-com \
  --for=condition=Ready --timeout=15m

# Secret 생성 확인
kubectl --context private-backbone -n ingress-ctrl get secret wildcard-bhyoo-com-tls
```

### 4.2 Traefik ArgoCD app 제거 (svc까지 완전 삭제 확인)

```bash
# --cascade=foreground로 하위 리소스까지 동기 삭제
kubectl --context private-backbone -n argocd delete app backbone-traefik \
  --cascade=foreground --timeout=5m
```

**중요: Pod뿐 아니라 `svc/traefik`도 완전히 사라져야 Gateway가 10.222.0.3:443을 받을 수 있음.**
둘 다 사라질 때까지 대기:
```bash
# Pod 제거 확인
kubectl --context private-backbone -n ingress-ctrl wait --for=delete \
  pod -l app.kubernetes.io/name=traefik --timeout=3m 2>/dev/null || true

# Service 제거까지 확인 (가장 중요)
for i in $(seq 1 30); do
  if ! kubectl --context private-backbone -n ingress-ctrl get svc traefik &>/dev/null; then
    echo "Traefik Service 삭제 확인"
    break
  fi
  [[ "$i" -eq 30 ]] && { echo "ERROR: Traefik Service 5분 후에도 존재"; exit 1; }
  sleep 10
done

# LB IP가 아직 할당된 상태로 남아있으면 안 됨
kubectl --context private-backbone get svc -A --field-selector spec.type=LoadBalancer | grep traefik \
  && { echo "ERROR: traefik LB IP 여전히 할당됨"; exit 1; } || echo "OK"
```

### 4.2a 기존 Ingress 리소스도 먼저 제거

Traefik 앱 제거 후에도, 각 앱 Helm chart이 `Ingress` 리소스를 생성해놨을 수 있음.
이것들이 남아있어도 Traefik이 없어 처리되지 않지만, 혼란 방지 위해 먼저 값 변경 + sync하거나 수동 삭제.
**ArgoCD가 재생성하지 못하도록, 먼저 관련 앱의 auto-sync를 끄고 Ingress 삭제**:
```bash
for app in argocd-appsets argocd hindsight-app immich-app versitygw \
           backbone-prometheus-stack; do
  kubectl --context private-backbone -n argocd patch app "$app" --type=merge \
    -p '{"spec":{"syncPolicy":{"automated":null}}}' 2>/dev/null || true
done

# Ingress 수동 삭제
for ns_name in \
  argocd/argocd-server \
  hindsight/hindsight \
  immich/immich-server \
  object-storage/versitygw \
  prometheus/shared-grafana \
  prometheus/shared-prometheus; do
  IFS=/ read -r ns name <<< "$ns_name"
  kubectl --context private-backbone -n "$ns" delete ingress "$name" --ignore-not-found
done
```

### 4.3 Commit 2 (Gateway 관련) + push

이제 Traefik이 사라진 10.222.0.3:443을 Gateway가 받을 수 있음.

```bash
cd ~/projects/kubernetes/homelab
if [[ "$(git branch --show-current)" != "master" ]]; then
  echo "ERROR: not on master"; exit 1
fi

git add argocd/apps/cilium-gateway.yaml apps/cilium-gateway/
git commit -m "feat(backbone): Cilium Gateway API (migration part 2)"
git push origin master

# ArgoCD sync 대기
kubectl --context private-backbone -n argocd wait app backbone-cilium-gateway \
  --for=jsonpath='{.status.sync.status}'=Synced --timeout=5m

# Gateway Programmed 대기
kubectl --context private-backbone -n ingress-ctrl wait gateway bhyoo-gateway \
  --for=condition=Programmed --timeout=5m

# Gateway Service LB IP 확인
kubectl --context private-backbone -n ingress-ctrl get svc \
  -l gateway.networking.k8s.io/gateway-name=bhyoo-gateway -o wide
# EXTERNAL-IP 컬럼에 노드 IP들 표시 (Gateway는 externalTrafficPolicy: Cluster 강제이므로 모든 노드 IP 받음)
```

### 4.4 Ingress 제거 → values 반영 commit (별도 PR)

Phase 4.2a에서 이미 Ingress를 수동 삭제했으나 ArgoCD auto-sync가 꺼진 상태.
values 파일에서 `ingress.enabled: false`를 commit하고 auto-sync 다시 켜야 영구 적용:

```bash
cd ~/projects/kubernetes/homelab
# 각 앱의 values에서 ingress 비활성화
# (예시 — 실제 파일 경로는 각 앱 Helm chart 구조에 따름)
# values/argocd/backbone.yaml 에 ingress.enabled: false
# values/immich/backbone.yaml 에 ingress.enabled: false
# ... 등등

git add values/
git commit -m "chore(backbone): disable Traefik Ingress (moved to Cilium Gateway API)"
git push origin master

# ArgoCD sync 재활성화
for app in argocd-appsets argocd hindsight-app immich-app versitygw \
           backbone-prometheus-stack; do
  kubectl --context private-backbone -n argocd patch app "$app" --type=merge \
    -p '{"spec":{"syncPolicy":{"automated":{"prune":true,"selfHeal":true}}}}' 2>/dev/null || true
done
```

### 4.5 Phase 4 검증

```bash
# 9개 hostname × 모든 advertised LB IP 조합 테스트
# (단일 IP만 테스트하면 broken backend 감지 못함 — verify.sh와 동일 정책)
GATEWAY_IPS=$(kubectl --context private-backbone -n ingress-ctrl get svc \
  -l gateway.networking.k8s.io/gateway-name=bhyoo-gateway \
  -o jsonpath='{.items[*].status.loadBalancer.ingress[*].ip}')
# 빈 결과 방어: Gateway Service가 LB IP를 받지 못했으면 즉시 실패
[[ -z "$GATEWAY_IPS" ]] && { echo "ERROR: Gateway Service에 LB IP가 없음. Node IPAM/svc 상태 확인" >&2; exit 1; }
for IP in $GATEWAY_IPS; do
  for host in argocd.bhyoo.com hindsight.bhyoo.com hindsight-api.bhyoo.com \
    immich.bhyoo.com versitygw.bhyoo.com s3.bhyoo.com admin-s3.bhyoo.com \
    grafana.bhyoo.com prometheus.bhyoo.com; do
    CODE=$(curl -sk --resolve "$host:443:$IP" "https://$host" -o /dev/null -w "%{http_code}" --max-time 15)
    echo "[$IP] $host: HTTP $CODE"
  done
done
# 모두 200-399 기대 (verify.sh 정책). 401/403이 나오는 보호 엔드포인트는
# verify.sh가 fail 처리하므로, 해당 호스트는 별도 인증 토큰 포함 수동 확인 필요
```

---

## Phase 5: static-lb 제거

```bash
# Node IPAM이 모든 LB 서비스에 IP 할당 중인지 확인
kubectl --context private-backbone get svc -A --field-selector spec.type=LoadBalancer
# EXTERNAL-IP 채워져 있어야 함

# static-lb 앱 삭제
kubectl --context private-backbone -n argocd delete app backbone-static-lb --cascade=foreground
```

검증: LB Service의 EXTERNAL-IP가 유지되는지 (Node IPAM 인수).

---

## Phase 6: 최종 검증

```bash
SSHPASS='<password>' ./docs/runbooks/v2/verify.sh \
  ~/backup/cilium-migration/<timestamp> --mode migration
```

verify.sh 확인 항목 (요약):
- 모든 노드 Ready
- Cilium/Envoy/Operator DS/Deploy READY==desired (STATUS만이 아님)
- Node IPAM 활성
- 모든 노드 datapath-mode 일치
- kube-proxy 비활성
- LoadBalancer IP 할당 (모든 IP 열거)
- 노드별 Cilium CNI 파일 존재
- Pod READY==desired
- CoreDNS 응답
- **9개 hostname 전부 HTTP 200-399** (400+는 fail)
- HTTPRoute 전부 Accepted
- iptables 규칙 수 비교

FAIL 하나라도 있으면 Level 2 복원 검토.

---

## Rollback

### Level 1: 서비스 한두 개만 문제

Cilium은 정상, 특정 HTTPRoute/앱만 문제 → `git revert <commit>` + push로 해당 변경만 롤백.

### Level 2: Cilium 자체 문제

```bash
SSHPASS='<password>' ./docs/runbooks/v2/restore.sh ~/backup/cilium-migration/<timestamp>
```

**스크립트 실제 순서** (script와 문서 일치):
0. 사전 검증 — default branch, working tree clean, origin 동기화
1. Git revert + push to default branch (실패 시 abort)
2. **`backbone-cilium`/`backbone-cilium-gateway` App 삭제** (self-heal 차단)
3. 전 노드 k3s/k3s-agent 중지 (role 기반)
4. Cilium CNI 설정 파일 제거
5. 전 노드 reboot (dispatch 실패 abort + SSH down→up 확인 + boot time 변경 검증)
6. **master 순차** k3s.yaml (rpi5 → rock5bp → rpi4, 각 Ready 대기), worker 병렬 — Flannel 복원 시점
7. firewall.yaml 재실행
8. **이 시점에 Flannel CNI가 동작하므로 Pod 생성 가능** → argocd-appsets sync → `backbone-traefik`/`backbone-static-lb` App 등장 대기 → Synced+Healthy 대기 + Pod Running 검증 (실패 시 abort)
9. 전체 Pod 재시작 (CoreDNS 포함)
10. Cilium CRD/Helm release secret/Gateway 잔여물 정리
11. verify.sh 자동 실행

### Level 3: etcd 손상

```bash
SSHPASS='<password>' ./docs/runbooks/v2/restore-etcd.sh ~/backup/cilium-migration/<timestamp>
# 인자는 backup_dir (snapshot 파일이 포함된 디렉토리)
```

스크립트 절차:
1. etcd snapshot 복사 + 원격 체크섬 검증
2. 전 노드 k3s/k3s-agent 중지 (role 기반)
3. rpi5에서 `k3s server --cluster-reset --cluster-reset-restore-path=...`
4. rock5bp/rpi4의 etcd 데이터 삭제
5. 전 노드 reboot + SSH per-node 엄격 체크
6. **master 순차** k3s.yaml, 각 Ready 대기
7. verify.sh 자동 실행

---

## 소요 시간

| Phase | Pod 네트워킹 중단 | 예상 시간 |
|-------|--------------------|-----------|
| 0. Backup | X | 5분 |
| 1. Preparation | X | 30분 |
| 2. Dry-run | X | 5분 |
| 3. CNI Cutover | **15-20분 전면** | 20분 |
| 4. Ingress Cutover | Ingress만 수 분 | 30-40분 |
| 5. static-lb 제거 | 없음 | 5분 |
| 6. 검증 | X | 10분 |
| **총계** | | ~2시간 |

복원 Level 2: 30-40분. Level 3: 1시간+.

## 파일 목록

```
values/cilium/backbone.yaml                 # Cilium v1.19.2 values
argocd/apps/cilium.yaml                     # ArgoCD App: Cilium Helm
argocd/apps/cilium-gateway.yaml             # ArgoCD App: Gateway/HTTPRoute
apps/cilium-gateway/
  gateway.yaml
  certificate.yaml
  httproutes/{argocd,hindsight,immich,versitygw,monitoring}.yaml
cluster-setup/k3s.yaml                       # modified (Phase 1.4)
cluster-setup/firewall.yaml                  # modified (Phase 1.5)
docs/runbook-cilium-migration-v2.md          # this file
docs/runbooks/v2/
  _lib.sh, snapshot.sh, dry-run.sh,
  restore.sh, restore-etcd.sh, verify.sh
  audit-archive/                             # audit/feature catalog 아카이브
```
