# Backbone Cluster: Flannel → Cilium Migration Runbook

## Overview

Flannel(host-gw) + kube-proxy(iptables) + static-lb + Traefik을
Cilium 하나로 통합하는 마이그레이션 런북.

### Before

| 컴포넌트 | 역할 |
|----------|------|
| Flannel host-gw | CNI (Pod 네트워킹) |
| kube-proxy (k3s 내장) | Service 라우팅 (iptables) |
| static-lb | LoadBalancer IP 할당 (node external-ip → svc ingress) |
| Traefik | L7 Ingress (TLS 종료, 호스트 라우팅) |

### After

| Cilium 기능 | 대체 대상 |
|-------------|----------|
| Cilium CNI (native routing) | Flannel |
| kubeProxyReplacement | kube-proxy |
| LB-IPAM + L2 Announcement | static-lb |
| Gateway API (내장 Envoy) | Traefik |

### Cluster Info

- k3s v1.34.6+k3s1, HA embedded etcd (3 master + 2 worker)
- 전 노드 ARM64, 커널 6.1+
- Pod CIDR: `10.42.0.0/16`, Service CIDR: `10.43.0.0/16`
- k8s Internal: `192.168.219.0/24` (ethernet)
- WireGuard (VPN, CNI 무관): `10.222.0.0/26` (wg0, gateway=rpi5)

---

## Phase 0: 백업 (Cilium 전환 전 반드시 실행)

> 목표: Cilium 전환이 실패했을 때, **현재 상태 그대로** 복원할 수 있는 스냅샷 확보.

### Step 0.1: etcd 스냅샷 생성 (클러스터 상태 전체 백업)

마스터 노드 **하나**에서 실행 (예: rpi5):

```bash
# SSH로 rpi5 접속
ssh bhyoo@192.168.219.5

# etcd 스냅샷 생성 (sudo 필요)
sudo k3s etcd-snapshot save --name pre-cilium-migration

# 스냅샷 파일 확인
sudo ls -la /var/lib/rancher/k3s/server/db/snapshots/
# pre-cilium-migration-<timestamp> 파일이 생성되어야 함

# 로컬로 복사 (SSH에서 나온 후)
exit
```

로컬에서 스냅샷 복사:
```bash
scp bhyoo@192.168.219.5:/var/lib/rancher/k3s/server/db/snapshots/pre-cilium-migration* \
  ~/backup/cilium-migration/
```

### Step 0.2: 각 노드의 k3s 설정 + iptables 규칙 백업

```bash
BACKUP_DIR=~/backup/cilium-migration/$(date +%Y%m%d)
mkdir -p "$BACKUP_DIR"

# 마스터 노드 (rpi5, rock5bp, rpi4)
for node in "bhyoo@192.168.219.5:rpi5" "bhyoo@192.168.219.6:rock5bp" "bhyoo@192.168.219.7:rpi4"; do
  IFS=: read -r ssh_target name <<< "$node"
  mkdir -p "$BACKUP_DIR/$name"
  scp "$ssh_target:/etc/rancher/k3s/config.yaml" "$BACKUP_DIR/$name/" 2>/dev/null
  ssh "$ssh_target" "sudo cat /etc/iptables/rules.v4" > "$BACKUP_DIR/$name/iptables-rules.v4"
  ssh "$ssh_target" "sudo ls /etc/cni/net.d/" > "$BACKUP_DIR/$name/cni-files.txt"
  ssh "$ssh_target" "sudo cat /etc/cni/net.d/*" > "$BACKUP_DIR/$name/cni-config.txt" 2>/dev/null
done

# 워커 노드 (n2p1, n2p2) — root 직접 접속
for node in "root@192.168.219.3:n2p1" "root@192.168.219.4:n2p2"; do
  IFS=: read -r ssh_target name <<< "$node"
  mkdir -p "$BACKUP_DIR/$name"
  scp "$ssh_target:/etc/rancher/k3s/config.yaml" "$BACKUP_DIR/$name/" 2>/dev/null
  ssh "$ssh_target" "cat /etc/iptables/rules.v4" > "$BACKUP_DIR/$name/iptables-rules.v4"
  ssh "$ssh_target" "ls /etc/cni/net.d/" > "$BACKUP_DIR/$name/cni-files.txt"
  ssh "$ssh_target" "cat /etc/cni/net.d/*" > "$BACKUP_DIR/$name/cni-config.txt" 2>/dev/null
done
```

### Step 0.3: Git 상태 기록

```bash
cd ~/projects/kubernetes/homelab
# 현재 커밋 해시 기록 (ansible, values 등 모든 설정의 기준점)
git rev-parse HEAD > "$BACKUP_DIR/git-commit-hash.txt"
git log --oneline -5 >> "$BACKUP_DIR/git-commit-hash.txt"
```

### Step 0.4: 백업 검증

```bash
echo "=== 백업 검증 ==="
echo "etcd 스냅샷:"
ls -la "$BACKUP_DIR"/../pre-cilium-migration* 2>/dev/null || echo "WARNING: etcd 스냅샷 없음!"

echo ""
echo "노드별 백업:"
for name in rpi5 rock5bp rpi4 n2p1 n2p2; do
  files=$(ls "$BACKUP_DIR/$name/" 2>/dev/null | wc -l)
  echo "  $name: $files files"
done

echo ""
echo "Git commit:"
cat "$BACKUP_DIR/git-commit-hash.txt"
```

> **이 Step이 완료되지 않으면 Phase 2로 진행하지 마세요.**

---

## Phase 1: 사전 준비 (서비스 중단 없음)

### Step 1.1: Cilium Helm chart values 작성

`values/cilium/backbone.yaml` 생성. 내용은 별도 커밋으로 관리.

### Step 1.2: Cilium ArgoCD Application 작성

`argocd/apps/cilium.yaml` 생성. **아직 커밋하지 않음** — Phase 3에서 함께 push.

### Step 1.3: Gateway + HTTPRoute 리소스 작성

현재 Ingress 6개를 Gateway API로 변환:

| 현재 Ingress | 변환 대상 |
|-------------|----------|
| argocd/argocd-server | HTTPRoute (Gateway: external) |
| hindsight/hindsight | HTTPRoute (Gateway: external) |
| immich/immich-server | HTTPRoute (Gateway: external) |
| object-storage/versitygw | HTTPRoute (Gateway: external) |
| prometheus/shared-grafana | HTTPRoute (Gateway: external) |
| prometheus/shared-prometheus | HTTPRoute (Gateway: external) |

Gateway 리소스 2개 생성:
- `external` — WireGuard 네트워크 (10.222.0.3), 외부 VPN 접근
- `internal` — LAN (192.168.219.x), 내부 접근 (필요 시 추후)

### Step 1.4: CiliumLoadBalancerIPPool + CiliumL2AnnouncementPolicy 작성

LB IP 풀과 L2 광고 정책 리소스 작성.

### Step 1.5: iptables-firewall 변수 준비

`cluster-setup/firewall.yaml`에 Cilium 방화벽 변수 추가 준비:
```yaml
use_k8s_cilium: true
use_k8s_cilium_hubble: true
```

---

## Phase 2: k3s 재설정 (서비스 중단 발생)

> **주의**: 이 Phase에서 네트워크 일시 중단이 발생합니다.
> backbone 클러스터의 모든 워크로드에 영향을 미칩니다.

### Step 2.1: 방화벽 규칙 선 적용

Cilium이 사용하는 포트를 먼저 열어둡니다.

```bash
cd cluster-setup
ansible-playbook -i inventory/hosts firewall.yaml --limit backbone \
  -e use_k8s_cilium=true -e use_k8s_cilium_hubble=true
```

**검증**:
```bash
# rpi5에서 iptables 규칙 확인 (SSH 접속 후)
iptables -L TCP -n | grep -E '4240|4244'
# 아래와 비슷한 출력이 나와야 함:
# ACCEPT  tcp  -- 192.168.219.0/24  0.0.0.0/0  tcp dpt:4240 /* cilium health check */
# ACCEPT  tcp  -- 192.168.219.0/24  0.0.0.0/0  tcp dpt:4244:4245 /* cilium hubble */
```

### Step 2.2: k3s.yaml 변경 및 적용

`cluster-setup/k3s.yaml`의 backbone 섹션을 수정:

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
  # ... 나머지 기존 설정 유지
```

### Step 2.3: k3s 재시작 (rolling)

> **이 시점부터 Pod 네트워킹이 중단됩니다.**
> Flannel은 비활성화되었지만 Cilium은 아직 설치되지 않은 상태.

마스터 노드부터 순서대로:

```bash
# 1. 마스터 노드 (rpi5 → rock5bp → rpi4)
ansible-playbook -i inventory/hosts k3s.yaml --limit rpi5
ansible-playbook -i inventory/hosts k3s.yaml --limit rock5bp
ansible-playbook -i inventory/hosts k3s.yaml --limit rpi4

# 2. 워커 노드 (n2p1 → n2p2)
ansible-playbook -i inventory/hosts k3s.yaml --limit n2p1
ansible-playbook -i inventory/hosts k3s.yaml --limit n2p2
```

**검증** (각 노드 재시작 후):
```bash
# k3s가 정상 기동되었는지 확인
kubectl --context private-backbone get nodes
# STATUS가 NotReady일 수 있음 — CNI가 없으므로 정상

# flannel이 비활성화되었는지 확인
kubectl --context private-backbone get node rpi5 \
  -o jsonpath='{.metadata.annotations.k3s\.io/node-args}' | grep flannel
# "flannel-backend","none" 이 보여야 함
```

---

## Phase 3: Cilium 설치 (네트워크 복구)

### Step 3.1: Git push (ArgoCD 자동 배포)

Phase 1에서 준비한 파일들을 커밋 & push:

```
values/cilium/backbone.yaml
argocd/apps/cilium.yaml
```

ArgoCD가 자동으로 Cilium Helm chart을 배포합니다.

**또는** ArgoCD sync를 기다리지 않고 수동 설치:

```bash
helm install cilium cilium/cilium \
  --version 1.17.x \
  --namespace kube-system \
  -f values/cilium/backbone.yaml
```

### Step 3.2: Cilium 설치 검증

```bash
# Cilium Pod 상태 확인
kubectl --context private-backbone get pods -n kube-system -l app.kubernetes.io/name=cilium
# 모든 노드에서 Running + Ready 상태여야 함 (5개)

# Cilium operator 확인
kubectl --context private-backbone get pods -n kube-system -l app.kubernetes.io/name=cilium-operator

# 노드 상태 확인
kubectl --context private-backbone get nodes
# 모든 노드가 Ready 상태여야 함

# Cilium 상태 확인 (cilium CLI가 있는 경우)
kubectl --context private-backbone exec -n kube-system ds/cilium -- cilium status --brief
```

### Step 3.3: 기존 Pod 재시작

Flannel로 할당된 기존 Pod 네트워크를 Cilium으로 전환:

```bash
# 모든 네임스페이스의 Pod 재시작 (kube-system 제외)
for ns in $(kubectl --context private-backbone get ns -o jsonpath='{.items[*].metadata.name}' \
  | tr ' ' '\n' | grep -v kube-system); do
  kubectl --context private-backbone rollout restart deploy -n "$ns" 2>/dev/null
  kubectl --context private-backbone rollout restart sts -n "$ns" 2>/dev/null
  kubectl --context private-backbone rollout restart ds -n "$ns" 2>/dev/null
done
```

**검증**:
```bash
# Pod간 통신 테스트
kubectl --context private-backbone run test-ping --rm -it --image=busybox -- \
  wget -qO- --timeout=5 http://kubernetes.default.svc.cluster.local/healthz

# CoreDNS 동작 확인
kubectl --context private-backbone run test-dns --rm -it --image=busybox -- \
  nslookup kubernetes.default.svc.cluster.local
```

---

## Phase 4: LB-IPAM + L2 Announcement 설정 (static-lb 대체)

### Step 4.1: CiliumLoadBalancerIPPool 배포

```bash
kubectl --context private-backbone apply -f - <<'EOF'
apiVersion: cilium.io/v2alpha1
kind: CiliumLoadBalancerIPPool
metadata:
  name: wireguard
spec:
  blocks:
    - cidr: 10.222.0.0/26
---
apiVersion: cilium.io/v2alpha1
kind: CiliumLoadBalancerIPPool
metadata:
  name: lan
spec:
  blocks:
    - cidr: 192.168.219.0/24
EOF
```

### Step 4.2: CiliumL2AnnouncementPolicy 배포

```bash
kubectl --context private-backbone apply -f - <<'EOF'
apiVersion: cilium.io/v2alpha1
kind: CiliumL2AnnouncementPolicy
metadata:
  name: wireguard
spec:
  interfaces:
    - ^wg0$
  loadBalancerIPs: true
---
apiVersion: cilium.io/v2alpha1
kind: CiliumL2AnnouncementPolicy
metadata:
  name: lan
spec:
  interfaces:
    - ^eth0$
  loadBalancerIPs: true
EOF
```

### Step 4.3: Traefik Service가 LB IP를 정상 수신하는지 확인

```bash
kubectl --context private-backbone get svc traefik -n ingress-ctrl
# EXTERNAL-IP가 10.222.0.3 (또는 풀에서 할당된 IP)인지 확인
```

> 이 시점에서 Traefik은 아직 동작 중이고,
> LB IP 할당만 static-lb → Cilium LB-IPAM으로 변경됨.

### Step 4.4: static-lb 제거

LB IP가 정상 동작하는 것을 확인한 후:

1. ArgoCD에서 `backbone-static-lb` 앱 삭제
2. 또는 `argocd/appsets/static-lb.yaml`에서 backbone 제거 후 push

**검증**:
```bash
# static-lb Pod가 제거되었는지
kubectl --context private-backbone get pods -n loadbalancer
# No resources found

# Traefik LB IP가 여전히 정상인지
curl -k --resolve argocd.bhyoo.com:443:10.222.0.3 https://argocd.bhyoo.com
```

---

## Phase 5: Traefik → Cilium Gateway API 전환

### Step 5.1: Gateway 리소스 배포

```bash
kubectl --context private-backbone apply -f - <<'EOF'
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: external
  namespace: ingress-ctrl
  annotations:
    cert-manager.io/cluster-issuer: cluster-issuer-acme
    cert-manager.io/private-key-algorithm: ECDSA
    cert-manager.io/private-key-size: "384"
spec:
  gatewayClassName: cilium
  addresses:
    - type: IPAddress
      value: "10.222.0.3"
  listeners:
    - name: https-wildcard
      port: 443
      protocol: HTTPS
      tls:
        mode: Terminate
        certificateRefs:
          - name: wildcard-bhyoo-com-tls
      allowedRoutes:
        namespaces:
          from: All
EOF
```

> 참고: cert-manager의 Gateway API 연동 방식에 따라
> TLS 설정을 listener별 또는 HTTPRoute별로 조정해야 할 수 있음.
> Gateway 리소스의 TLS 설정은 실제 인증서 구조에 맞게 최종 조정 필요.

### Step 5.2: HTTPRoute 배포 (서비스별)

각 서비스를 하나씩 전환하면서 테스트:

```bash
# 예시: ArgoCD
kubectl --context private-backbone apply -f - <<'EOF'
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: argocd-server
  namespace: argocd
spec:
  parentRefs:
    - name: external
      namespace: ingress-ctrl
  hostnames:
    - argocd.bhyoo.com
  rules:
    - backendRefs:
        - name: argocd-server
          port: 80
EOF
```

**검증** (각 HTTPRoute 배포 후):
```bash
curl -k --resolve argocd.bhyoo.com:443:10.222.0.3 https://argocd.bhyoo.com
```

### Step 5.3: 전체 HTTPRoute 목록

| HTTPRoute name | namespace | hostname(s) | backend service:port |
|---|---|---|---|
| argocd-server | argocd | argocd.bhyoo.com | argocd-server:80 |
| hindsight | hindsight | hindsight.bhyoo.com | hindsight-control-plane:3000 |
| hindsight-api | hindsight | hindsight-api.bhyoo.com | hindsight-api:8888 |
| immich-server | immich | immich.bhyoo.com | immich-server:2283 |
| versitygw | object-storage | versitygw.bhyoo.com | versitygw:webui (port name) |
| versitygw-s3 | object-storage | s3.bhyoo.com | versitygw:s3-api (port name) |
| versitygw-admin | object-storage | admin-s3.bhyoo.com | versitygw:admin (port name) |
| grafana | prometheus | grafana.bhyoo.com | shared-grafana:80 |
| prometheus | prometheus | prometheus.bhyoo.com | shared-prometheus:9090 |

### Step 5.4: 기존 Ingress 리소스 제거

모든 HTTPRoute가 정상 동작하는 것을 확인한 후,
각 앱의 Helm values에서 Ingress를 비활성화하거나 Ingress 리소스 삭제.

### Step 5.5: Traefik 제거

```bash
# ArgoCD에서 backbone-traefik 앱 삭제
# 또는 argocd/appsets/traefik.yaml에서 backbone 제거 후 push
```

**검증**:
```bash
# Traefik Pod 제거 확인
kubectl --context private-backbone get pods -n ingress-ctrl
# cilium-gateway-external Pod만 남아야 함

# 모든 서비스 접근 테스트
for host in argocd.bhyoo.com immich.bhyoo.com grafana.bhyoo.com \
  prometheus.bhyoo.com hindsight.bhyoo.com hindsight-api.bhyoo.com \
  versitygw.bhyoo.com s3.bhyoo.com admin-s3.bhyoo.com; do
  echo -n "$host: "
  curl -sk --resolve "$host:443:10.222.0.3" "https://$host" -o /dev/null -w "%{http_code}\n"
done
```

---

## Phase 6: 정리 및 검증

### Step 6.1: 남은 Flannel 잔여물 정리

```bash
# Flannel annotation 확인 (자동으로 남아있을 수 있음)
kubectl --context private-backbone get nodes -o json | \
  python3 -c "import json,sys; [print(n['metadata']['name'], [k for k in n['metadata'].get('annotations',{}) if 'flannel' in k]) for n in json.load(sys.stdin)['items']]"
```

### Step 6.2: 전체 검증 체크리스트

- [ ] 모든 노드 Ready
- [ ] 모든 Cilium agent Pod Running + Ready
- [ ] Cilium operator Pod Running + Ready
- [ ] CoreDNS 정상 동작
- [ ] Pod 간 통신 정상 (cross-node)
- [ ] LoadBalancer Service에 IP 정상 할당
- [ ] WireGuard VPN 통해 서비스 접근 가능
- [ ] LAN에서 서비스 접근 가능 (내부 Gateway 설정 시)
- [ ] cert-manager 인증서 갱신 정상
- [ ] Hubble relay 동작
- [ ] ArgoCD sync 상태 정상

### Step 6.3: firewall.yaml 영구 적용

`cluster-setup/firewall.yaml`에 변수 영구 추가 후 커밋:

```yaml
- role: iptables-firewall
  vars:
    use_k8s_cilium: true
    use_k8s_cilium_hubble: true
    # ...
```

---

## 완전 복원: 스크립트 사용

> 자동화된 복원 스크립트를 제공합니다.
> 수동으로 단계별 실행할 필요 없이, 스크립트가 전체 과정을 처리합니다.

### 복원 스크립트가 하는 일 (순서대로)

1. Cilium Helm release 삭제 + CRD 삭제 + Gateway/HTTPRoute 삭제 (kubectl 접근 가능 시)
2. 모든 노드에서 k3s 중지
3. 각 노드에서 Cilium 잔여물 완전 제거
   - CNI 설정 + 바이너리 (`/etc/cni/net.d/`, `/opt/cni/bin/cilium-cni`)
   - BPF maps (`/sys/fs/bpf/`)
   - tc에 attach된 eBPF 프로그램 (모든 인터페이스)
   - Cilium 네트워크 인터페이스 (`lxc*`, `cilium*`)
   - Cilium 상태 디렉토리 (`/var/run/cilium/`)
4. Git을 백업 시점 커밋으로 checkout
5. **모든 노드 reboot** (eBPF 프로그램 완전 정리 — 유일하게 확실한 방법)
6. k3s를 원래 설정(`flannel-backend: host-gw`)으로 ansible 재설치
7. iptables 복원 + 전체 Pod 재시작
8. 잔여 Cilium CRD/Helm secret 최종 정리

### 실행 방법

```bash
# 복원
./docs/runbooks/cilium-migration-restore.sh ~/backup/cilium-migration/<날짜>

# 검증 (복원 완료 후)
./docs/runbooks/cilium-migration-verify.sh ~/backup/cilium-migration/<날짜>
```

### 검증 스크립트가 확인하는 항목

| 카테고리 | 검증 내용 |
|----------|----------|
| 노드 상태 | Ready 노드 수, NotReady 없음 |
| Flannel | 각 노드 flannel annotation(host-gw), CNI 설정 파일 |
| Cilium 잔여물 | CNI 설정, BPF maps, tc 프로그램, CNI 바이너리, lxc 인터페이스, 프로세스 |
| k8s 잔여물 | Cilium CRD, Helm release secret, cilium-secrets ns, 노드 annotation |
| kube-proxy | k3s 실행 인자에서 disable-kube-proxy 없음 |
| iptables | KUBE-* 체인 존재, Cilium 규칙 없음 |
| Pod | Running Pod 수, Cilium Pod 부재 |
| 서비스 | 서비스 수, Traefik LB IP 일치 |
| 네트워크 | CoreDNS, Traefik 경유 HTTP 접근 |
| DaemonSet | 백업 대비 누락/추가 |

FAIL이 하나라도 있으면 exit 1 + 대응 방법을 안내합니다.

---

### 비상 복원: etcd 스냅샷 (위 스크립트가 실패할 때만)

> k3s를 재시작해도 etcd 클러스터 자체가 복구되지 않을 때 사용합니다.

```bash
SNAPSHOT_FILE=~/backup/cilium-migration/<날짜>/etcd-snapshot

# 1. etcd 스냅샷을 rpi5에 복사
scp "$SNAPSHOT_FILE" bhyoo@192.168.219.5:/tmp/etcd-snapshot

# 2. 모든 노드 k3s 중지
cd cluster-setup
for host in rpi5 rock5bp rpi4 n2p1 n2p2; do
  ansible -i inventory/hosts "$host" -m systemd -a "name=k3s state=stopped" --become
done

# 3. rpi5에서 etcd 리셋
ssh bhyoo@192.168.219.5
sudo k3s server --cluster-reset --cluster-reset-restore-path=/tmp/etcd-snapshot
# "Managed etcd cluster membership has been reset" 확인 후 exit

# 4. 다른 마스터에서 etcd 데이터 삭제 (재합류 위해)
for host in rock5bp rpi4; do
  ansible -i inventory/hosts "$host" --become -m shell -a \
    'rm -rf /var/lib/rancher/k3s/server/db/etcd'
done

# 5. 전 노드 reboot
for host in rpi5 rock5bp rpi4 n2p1 n2p2; do
  ansible -i inventory/hosts "$host" --become -m shell -a 'reboot'
done

# 6. 부팅 후 k3s 원래 설정으로 재설치
ansible-playbook -i inventory/hosts k3s.yaml --limit rpi5
# rpi5 Ready 확인 후
ansible-playbook -i inventory/hosts k3s.yaml --limit rock5bp
ansible-playbook -i inventory/hosts k3s.yaml --limit rpi4
ansible-playbook -i inventory/hosts k3s.yaml --limit n2p1
ansible-playbook -i inventory/hosts k3s.yaml --limit n2p2

# 7. 검증
./docs/runbooks/cilium-migration-verify.sh ~/backup/cilium-migration/<날짜>
```

---

## 예상 소요 시간

| 작업 | 영향 | 예상 시간 |
|------|------|----------|
| Phase 2 (k3s 재설정) | Pod 네트워킹 전면 중단 | 10-20분 |
| Phase 3 (Cilium 설치) | 네트워크 복구 | 5-10분 |
| Phase 4 (LB 전환) | LB IP 순단 가능 | 1-2분 |
| Phase 5 (Ingress 전환) | 서비스별 순단 | 서비스당 ~1분 |
| **마이그레이션 총 다운타임** | | **20-35분** |
| **복원 (reboot 포함)** | 전체 중단 | **15-25분** |
