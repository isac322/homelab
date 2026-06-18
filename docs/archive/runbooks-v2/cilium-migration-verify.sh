#!/usr/bin/env bash
# cilium-migration-verify.sh
# Cilium 마이그레이션 복원 후, 스냅샷과 비교하여 원래 상태로 돌아왔는지 검증합니다.
#
# Usage: ./cilium-migration-verify.sh <backup_dir>
#
# 모든 검증 항목에 PASS/FAIL/WARN을 표시합니다.
# FAIL이 하나라도 있으면 exit code 1로 종료합니다.

set -uo pipefail

CTX="private-backbone"
BACKUP_DIR="${1:-}"
MASTERS=("bhyoo@192.168.219.5:rpi5" "bhyoo@192.168.219.6:rock5bp" "bhyoo@192.168.219.7:rpi4")
WORKERS=("root@192.168.219.3:n2p1" "root@192.168.219.4:n2p2")
ALL_NODES=("${MASTERS[@]}" "${WORKERS[@]}")

FAIL_COUNT=0
WARN_COUNT=0
PASS_COUNT=0

pass() { echo "  PASS: $1"; ((PASS_COUNT++)); }
fail() { echo "  FAIL: $1"; ((FAIL_COUNT++)); }
warn() { echo "  WARN: $1"; ((WARN_COUNT++)); }

if [[ -z "$BACKUP_DIR" || ! -d "$BACKUP_DIR" ]]; then
  echo "Usage: $0 <backup_dir>"
  echo "  backup_dir: cilium-migration-snapshot.sh로 생성한 디렉토리"
  exit 1
fi

echo "=== Cilium Migration 복원 검증 ==="
echo "스냅샷: $BACKUP_DIR"
echo ""

# ─── 1. 노드 상태 ───
echo "[1/9] 노드 상태 검증..."
EXPECTED_NODES=$(grep -c "Ready" "$BACKUP_DIR/cluster/nodes.txt" 2>/dev/null || echo 0)
CURRENT_NODES=$(kubectl --context "$CTX" get nodes --no-headers 2>/dev/null | grep -c "Ready" || echo 0)
if [[ "$CURRENT_NODES" -eq "$EXPECTED_NODES" ]]; then
  pass "노드 수 일치 ($CURRENT_NODES/$EXPECTED_NODES Ready)"
else
  fail "노드 수 불일치 (현재: $CURRENT_NODES, 기대: $EXPECTED_NODES)"
fi

# NotReady 노드 확인
NOT_READY=$(kubectl --context "$CTX" get nodes --no-headers 2>/dev/null | grep -v "Ready" | grep -v "^$" || true)
if [[ -n "$NOT_READY" ]]; then
  fail "NotReady 노드 존재: $NOT_READY"
else
  pass "모든 노드 Ready"
fi

# ─── 2. Flannel 복원 확인 ───
echo ""
echo "[2/9] Flannel CNI 복원 검증..."
for entry in "${ALL_NODES[@]}"; do
  IFS=: read -r ssh_target name <<< "$entry"

  # flannel annotation
  BACKEND=$(kubectl --context "$CTX" get node "$name" \
    -o jsonpath='{.metadata.annotations.flannel\.alpha\.coreos\.com/backend-type}' 2>/dev/null)
  if [[ "$BACKEND" == "host-gw" ]]; then
    pass "$name: flannel backend-type=host-gw"
  else
    fail "$name: flannel backend-type='$BACKEND' (기대: host-gw)"
  fi

  # CNI 설정 파일
  CNI_FILES=$(ssh "$ssh_target" "sudo ls /etc/cni/net.d/ 2>/dev/null" 2>/dev/null || true)
  if echo "$CNI_FILES" | grep -q "flannel"; then
    pass "$name: flannel CNI 설정 존재"
  else
    fail "$name: flannel CNI 설정 없음 (현재: $CNI_FILES)"
  fi
done

# ─── 3. Cilium 잔여물 확인 ───
echo ""
echo "[3/9] Flannel 동작을 방해하는 Cilium 잔여물 검증..."
for entry in "${ALL_NODES[@]}"; do
  IFS=: read -r ssh_target name <<< "$entry"

  # [FAIL] Cilium CNI 설정 — kubelet이 flannel 대신 cilium CNI를 로드함
  CILIUM_CNI=$(ssh "$ssh_target" "sudo ls /etc/cni/net.d/ 2>/dev/null" 2>/dev/null | grep cilium || true)
  if [[ -z "$CILIUM_CNI" ]]; then
    pass "$name: Cilium CNI 설정 없음"
  else
    fail "$name: Cilium CNI 설정 잔여: $CILIUM_CNI (kubelet이 flannel 대신 이것을 로드함)"
  fi

  # [FAIL] tc eBPF 프로그램 — 패킷 경로를 가로채서 flannel/kube-proxy 방해
  TC_PROGS=$(ssh "$ssh_target" "sudo tc filter show dev eth0 ingress 2>/dev/null; sudo tc filter show dev eth0 egress 2>/dev/null" 2>/dev/null | grep -i "bpf\|cilium" || true)
  if [[ -z "$TC_PROGS" ]]; then
    pass "$name: eth0에 Cilium tc 프로그램 없음"
  else
    fail "$name: eth0에 Cilium tc 프로그램 잔여 — 패킷을 가로채서 flannel 라우팅 방해 (노드 reboot 필요)"
  fi

  # [WARN] 아래는 동작에 영향 없지만 참고용으로 검출
  BPF_MAPS=$(ssh "$ssh_target" "sudo ls /sys/fs/bpf/tc/globals/ 2>/dev/null" 2>/dev/null | grep cilium || true)
  if [[ -n "$BPF_MAPS" ]]; then
    warn "$name: Cilium BPF maps 잔여 (무해 — 참조하는 프로그램 없으면 무시됨)"
  fi

  CILIUM_BIN=$(ssh "$ssh_target" "ls /opt/cni/bin/cilium-cni 2>/dev/null" 2>/dev/null || true)
  if [[ -n "$CILIUM_BIN" ]]; then
    warn "$name: Cilium CNI 바이너리 잔여 (무해 — CNI 설정이 없으면 호출 안 됨)"
  fi
done

# ─── 4. kube-proxy 복원 확인 ───
echo ""
echo "[4/9] kube-proxy 복원 검증..."
# k3s 내장 kube-proxy는 별도 Pod 없이 k3s 프로세스 안에서 동작
# k3s 실행 인자에서 disable-kube-proxy가 없어야 함
KP_CHECK=$(kubectl --context "$CTX" get node rpi5 \
  -o jsonpath='{.metadata.annotations.k3s\.io/node-args}' 2>/dev/null)
if echo "$KP_CHECK" | grep -q "disable-kube-proxy"; then
  fail "kube-proxy가 비활성 상태 (disable-kube-proxy 플래그 존재)"
else
  pass "kube-proxy 활성 상태 (disable-kube-proxy 없음)"
fi

# flannel-backend 값 확인
if echo "$KP_CHECK" | grep -q '"flannel-backend","host-gw"'; then
  pass "flannel-backend=host-gw 확인"
elif echo "$KP_CHECK" | grep -q '"flannel-backend","none"'; then
  fail "flannel-backend=none (Cilium 설정이 남아있음)"
else
  warn "flannel-backend 값을 확인할 수 없음"
fi

# ─── 4b. Cilium k8s 잔여물 (동작에 무해, 참고용) ───
echo ""
echo "[4b/9] Cilium k8s 잔여물 (동작 무관, 참고)..."
CILIUM_CRDS=$(kubectl --context "$CTX" get crd -o name 2>/dev/null | grep cilium || true)
if [[ -z "$CILIUM_CRDS" ]]; then
  pass "Cilium CRD 없음"
else
  CRD_COUNT=$(echo "$CILIUM_CRDS" | wc -l)
  warn "Cilium CRD ${CRD_COUNT}개 잔여 (무해 — controller가 없으므로 무시됨)"
fi

HELM_SECRETS=$(kubectl --context "$CTX" get secret -n kube-system -l owner=helm,name=cilium --no-headers 2>/dev/null || true)
if [[ -n "$HELM_SECRETS" ]]; then
  warn "Cilium Helm release secret 잔여 (무해)"
fi

CILIUM_NS=$(kubectl --context "$CTX" get ns cilium-secrets --no-headers 2>/dev/null || true)
if [[ -n "$CILIUM_NS" ]]; then
  warn "cilium-secrets namespace 잔여 (무해)"
fi

# ─── 5. iptables 규칙 비교 ───
echo ""
echo "[5/9] iptables 규칙 검증..."
for entry in "${ALL_NODES[@]}"; do
  IFS=: read -r ssh_target name <<< "$entry"
  BACKUP_RULES="$BACKUP_DIR/nodes/$name/iptables.txt"

  if [[ ! -f "$BACKUP_RULES" ]]; then
    warn "$name: 백업 iptables 규칙 없음, 건너뜀"
    continue
  fi

  # KUBE-* 체인 수 비교 (kube-proxy 복원 지표)
  BACKUP_KUBE_CHAINS=$(grep -c "^:KUBE-" "$BACKUP_RULES" 2>/dev/null || echo 0)
  CURRENT_KUBE_CHAINS=$(ssh "$ssh_target" "sudo iptables-save 2>/dev/null" 2>/dev/null | grep -c "^:KUBE-" || echo 0)

  if [[ "$CURRENT_KUBE_CHAINS" -gt 0 && "$BACKUP_KUBE_CHAINS" -gt 0 ]]; then
    pass "$name: KUBE-* iptables 체인 존재 (백업: $BACKUP_KUBE_CHAINS, 현재: $CURRENT_KUBE_CHAINS)"
  elif [[ "$CURRENT_KUBE_CHAINS" -eq 0 && "$BACKUP_KUBE_CHAINS" -gt 0 ]]; then
    fail "$name: KUBE-* iptables 체인 없음 (kube-proxy 미복원)"
  else
    pass "$name: iptables 상태 일치"
  fi

  # Cilium iptables 규칙 잔여 확인
  CILIUM_RULES=$(ssh "$ssh_target" "sudo iptables-save 2>/dev/null" 2>/dev/null | grep -c "cilium" || echo 0)
  if [[ "$CILIUM_RULES" -eq 0 ]]; then
    pass "$name: Cilium iptables 규칙 없음"
  else
    warn "$name: Cilium iptables 규칙 $CILIUM_RULES개 잔여"
  fi
done

# ─── 6. Pod 상태 비교 ───
echo ""
echo "[6/9] Pod 상태 검증..."
EXPECTED_POD_COUNT=$(grep -c "Running\|Completed" "$BACKUP_DIR/cluster/pods.txt" 2>/dev/null || echo 0)
CURRENT_POD_COUNT=$(kubectl --context "$CTX" get pods -A --no-headers 2>/dev/null | grep -c "Running\|Completed" || echo 0)
CURRENT_NOT_RUNNING=$(kubectl --context "$CTX" get pods -A --no-headers 2>/dev/null | grep -v "Running\|Completed" || true)

if [[ "$CURRENT_POD_COUNT" -ge "$EXPECTED_POD_COUNT" ]]; then
  pass "Running/Completed Pod 수 충분 (현재: $CURRENT_POD_COUNT, 백업: $EXPECTED_POD_COUNT)"
else
  fail "Running/Completed Pod 부족 (현재: $CURRENT_POD_COUNT, 백업: $EXPECTED_POD_COUNT)"
fi

if [[ -n "$CURRENT_NOT_RUNNING" ]]; then
  NOT_RUNNING_COUNT=$(echo "$CURRENT_NOT_RUNNING" | wc -l)
  warn "비정상 Pod $NOT_RUNNING_COUNT개:"
  echo "$CURRENT_NOT_RUNNING" | head -10 | sed 's/^/    /'
else
  pass "비정상 Pod 없음"
fi

# Cilium Pod가 남아있지 않은지
CILIUM_PODS=$(kubectl --context "$CTX" get pods -A --no-headers 2>/dev/null | grep cilium || true)
if [[ -z "$CILIUM_PODS" ]]; then
  pass "Cilium Pod 없음"
else
  fail "Cilium Pod 잔여:"
  echo "$CILIUM_PODS" | sed 's/^/    /'
fi

# ─── 7. 서비스 + LB IP 비교 ───
echo ""
echo "[7/9] 서비스/LB 검증..."
EXPECTED_SVC_COUNT=$(wc -l < "$BACKUP_DIR/cluster/service-details.txt" 2>/dev/null || echo 0)
CURRENT_SVC_COUNT=$(kubectl --context "$CTX" get svc -A --no-headers 2>/dev/null | wc -l)

if [[ "$CURRENT_SVC_COUNT" -ge "$EXPECTED_SVC_COUNT" ]]; then
  pass "서비스 수 충분 (현재: $CURRENT_SVC_COUNT, 백업: $EXPECTED_SVC_COUNT)"
else
  fail "서비스 부족 (현재: $CURRENT_SVC_COUNT, 백업: $EXPECTED_SVC_COUNT)"
fi

# Traefik LB IP 확인
TRAEFIK_LB=$(kubectl --context "$CTX" get svc traefik -n ingress-ctrl \
  -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || true)
EXPECTED_TRAEFIK_LB=$(grep "ingress-ctrl/traefik" "$BACKUP_DIR/cluster/service-details.txt" 2>/dev/null | awk -F'\t' '{print $4}' || true)

if [[ -n "$TRAEFIK_LB" && "$TRAEFIK_LB" == "$EXPECTED_TRAEFIK_LB" ]]; then
  pass "Traefik LB IP 일치: $TRAEFIK_LB"
elif [[ -n "$TRAEFIK_LB" ]]; then
  warn "Traefik LB IP 변경됨 (현재: $TRAEFIK_LB, 백업: $EXPECTED_TRAEFIK_LB)"
else
  fail "Traefik LB IP 없음"
fi

# ─── 8. 네트워크 연결 테스트 ───
echo ""
echo "[8/9] 네트워크 연결 테스트..."

# CoreDNS
DNS_RESULT=$(kubectl --context "$CTX" run verify-dns-$RANDOM --rm -i --restart=Never \
  --image=busybox --timeout=30s -- nslookup kubernetes.default.svc.cluster.local 2>&1 || true)
if echo "$DNS_RESULT" | grep -q "Address"; then
  pass "CoreDNS 정상"
else
  fail "CoreDNS 실패"
fi

# 서비스 접근 (Traefik 경유)
if [[ -n "$TRAEFIK_LB" ]]; then
  for host in argocd.bhyoo.com immich.bhyoo.com grafana.bhyoo.com; do
    HTTP_CODE=$(curl -sk --resolve "$host:443:$TRAEFIK_LB" "https://$host" \
      -o /dev/null -w "%{http_code}" --max-time 10 2>/dev/null || echo "000")
    if [[ "$HTTP_CODE" -ge 200 && "$HTTP_CODE" -lt 500 ]]; then
      pass "$host: HTTP $HTTP_CODE"
    else
      fail "$host: HTTP $HTTP_CODE (접근 불가)"
    fi
  done
else
  warn "Traefik LB IP가 없어 서비스 접근 테스트 건너뜀"
fi

# ─── 9. DaemonSet 비교 ───
echo ""
echo "[9/9] DaemonSet 검증..."
EXPECTED_DS=$(grep -v "^NAMESPACE" "$BACKUP_DIR/cluster/daemonsets.txt" 2>/dev/null | awk '{print $1"/"$2}' | sort)
CURRENT_DS=$(kubectl --context "$CTX" get ds -A --no-headers 2>/dev/null | awk '{print $1"/"$2}' | sort)

MISSING_DS=$(comm -23 <(echo "$EXPECTED_DS") <(echo "$CURRENT_DS") 2>/dev/null || true)
EXTRA_DS=$(comm -13 <(echo "$EXPECTED_DS") <(echo "$CURRENT_DS") 2>/dev/null || true)

if [[ -z "$MISSING_DS" ]]; then
  pass "백업 대비 누락된 DaemonSet 없음"
else
  fail "누락된 DaemonSet: $MISSING_DS"
fi

if [[ -z "$EXTRA_DS" ]]; then
  pass "추가된 DaemonSet 없음"
else
  # Cilium DS가 남아있으면 FAIL, 아니면 WARN
  if echo "$EXTRA_DS" | grep -q "cilium"; then
    fail "Cilium DaemonSet 잔여: $EXTRA_DS"
  else
    warn "추가된 DaemonSet: $EXTRA_DS"
  fi
fi

# ─── 결과 요약 ───
echo ""
echo "========================================"
echo "  검증 결과"
echo "========================================"
echo "  PASS: $PASS_COUNT"
echo "  WARN: $WARN_COUNT"
echo "  FAIL: $FAIL_COUNT"
echo "========================================"

if [[ "$FAIL_COUNT" -gt 0 ]]; then
  echo ""
  echo "FAIL 항목이 있습니다. 위의 FAIL 메시지를 확인하세요."
  echo ""
  echo "FAIL 대응 방법:"
  echo "  - Cilium CNI 설정 잔여 → 해당 노드에서 rm -f /etc/cni/net.d/*cilium* 후 k3s 재시작"
  echo "  - Cilium tc 프로그램 잔여 → 해당 노드 reboot (유일한 확실한 방법)"
  echo "  - flannel 미복원 → ansible-playbook k3s.yaml --limit <node>"
  echo "  - kube-proxy 미복원 → k3s config 확인 후 k3s 재시작"
  echo "  - Pod 비정상 → kubectl rollout restart"
  echo "  - 전체 실패 → etcd 스냅샷 복원 (런북 '비상 복원' 섹션 참조)"
  exit 1
else
  echo ""
  echo "복원 성공. 클러스터가 마이그레이션 전 상태와 일치합니다."
  exit 0
fi
