#!/usr/bin/env bash
# verify.sh — 복원/마이그레이션 후 엄격 검증
#
# 모드:
#   - restore (기본): 복원 후 Flannel 상태 검증
#   - migration (--mode migration): Cilium 마이그레이션 성공 검증
#
# v2 개선:
#   - READY==desired 체크 (STATUS만이 아닌)
#   - HTTP 200-399만 pass (400+는 fail)
#   - 9개 hostname 전부 테스트
#   - 모든 LB IP 설정 확인 (첫 IP만이 아닌)
#
# Usage:
#   SSHPASS='<pw>' ./verify.sh <backup_dir> [--mode migration]

set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/_lib.sh"

BACKUP_DIR="${1:-}"
MODE="restore"
if [[ "${2:-}" == "--mode" ]]; then
  MODE="${3:-restore}"
fi

if [[ -z "$BACKUP_DIR" || ! -d "$BACKUP_DIR" ]]; then
  error "Usage: $0 <backup_dir> [--mode migration|restore]"
  exit 1
fi

require_sshpass

info "검증 모드: $MODE"
info "백업: $BACKUP_DIR"
echo

# migration 모드에서 전환할 9개 hostname
EXPECTED_HOSTNAMES=(
  argocd.bhyoo.com
  hindsight.bhyoo.com
  hindsight-api.bhyoo.com
  immich.bhyoo.com
  versitygw.bhyoo.com
  s3.bhyoo.com
  admin-s3.bhyoo.com
  grafana.bhyoo.com
  prometheus.bhyoo.com
)

# ─── 1. 노드 상태 ───
step "[1/11] 노드 상태..."

READY_COUNT=$(kubectl --context "$CTX" get nodes --no-headers 2>/dev/null | awk '$2=="Ready"' | wc -l)
NOT_READY=$(kubectl --context "$CTX" get nodes --no-headers 2>/dev/null | awk '$2!="Ready"' || true)
EXPECTED_NODES=${#NODE_NAMES[@]}

if [[ "$READY_COUNT" -eq "$EXPECTED_NODES" ]]; then
  pass "모든 노드 Ready ($READY_COUNT/$EXPECTED_NODES)"
else
  fail "Ready 노드 부족 ($READY_COUNT/$EXPECTED_NODES)"
  [[ -n "$NOT_READY" ]] && echo "$NOT_READY" | sed 's/^/    /'
fi

# ─── 2. CNI 상태 ───
step "[2/11] CNI 상태..."

if [[ "$MODE" == "restore" ]]; then
  for name in "${NODE_NAMES[@]}"; do
    BACKEND=$(kubectl --context "$CTX" get node "$name" \
      -o jsonpath='{.metadata.annotations.flannel\.alpha\.coreos\.com/backend-type}' 2>/dev/null)
    if [[ "$BACKEND" == "host-gw" ]]; then
      pass "$name: flannel host-gw"
    else
      fail "$name: flannel backend='$BACKEND' (기대: host-gw)"
    fi
  done
else
  # DS status.desiredNumberScheduled vs status.numberReady
  # jsonpath로 읽는 것이 awk 컬럼 오해 방지. `kubectl get ds --no-headers` 순서:
  # $1=NAME $2=DESIRED $3=CURRENT $4=READY $5=UP-TO-DATE $6=AVAILABLE
  check_ds_ready() {
    local name="$1"
    local ds_desired ds_ready
    ds_desired=$(kubectl --context "$CTX" -n kube-system get ds "$name" \
      -o jsonpath='{.status.desiredNumberScheduled}' 2>/dev/null)
    ds_ready=$(kubectl --context "$CTX" -n kube-system get ds "$name" \
      -o jsonpath='{.status.numberReady}' 2>/dev/null)
    if [[ "${ds_desired:-0}" -gt 0 ]] && [[ "$ds_desired" == "$ds_ready" ]]; then
      pass "$name DS Ready: $ds_ready/$ds_desired"
    else
      fail "$name DS Ready 부족: ${ds_ready:-0}/${ds_desired:-0}"
    fi
  }
  check_ds_ready cilium
  check_ds_ready cilium-envoy

  # Operator Deployment: READY
  READY_STR=$(kubectl --context "$CTX" -n kube-system get deploy cilium-operator --no-headers 2>/dev/null | awk '{print $2}')
  if [[ "$READY_STR" =~ ^([0-9]+)/([0-9]+)$ ]] && [[ "${BASH_REMATCH[1]}" -eq "${BASH_REMATCH[2]}" ]] && [[ "${BASH_REMATCH[1]}" -gt 0 ]]; then
    pass "cilium-operator Ready: $READY_STR"
  else
    fail "cilium-operator Ready 부족: $READY_STR"
  fi

  # Hubble relay
  READY_STR=$(kubectl --context "$CTX" -n kube-system get deploy hubble-relay --no-headers 2>/dev/null | awk '{print $2}')
  if [[ "$READY_STR" =~ ^([0-9]+)/([0-9]+)$ ]] && [[ "${BASH_REMATCH[1]}" -eq "${BASH_REMATCH[2]}" ]]; then
    pass "hubble-relay Ready: $READY_STR"
  else
    note "hubble-relay Ready 부족: $READY_STR"
  fi

  # Node IPAM 활성
  CILIUM_POD=$(kubectl --context "$CTX" -n kube-system get pods -l k8s-app=cilium -o name | head -1)
  if [[ -n "$CILIUM_POD" ]] && kubectl --context "$CTX" -n kube-system exec "$CILIUM_POD" -c cilium-agent -- \
      cilium config get enable-node-ipam 2>/dev/null | grep -q "true"; then
    pass "Node IPAM 활성"
  else
    fail "Node IPAM 비활성"
  fi

  # 모든 노드 datapath-mode 동일
  declare -A DPM_MAP=()
  for name in "${NODE_NAMES[@]}"; do
    POD=$(kubectl --context "$CTX" -n kube-system get pods -l k8s-app=cilium \
      --field-selector spec.nodeName="$name" -o name 2>/dev/null | head -1)
    if [[ -n "$POD" ]]; then
      DPM=$(kubectl --context "$CTX" -n kube-system exec "$POD" -c cilium-agent -- \
        cilium config get datapath-mode 2>/dev/null | tr -d '\r\n')
      DPM_MAP[$name]="$DPM"
    fi
  done
  UNIQUE=$(printf '%s\n' "${DPM_MAP[@]}" | sort -u)
  if [[ "$(echo "$UNIQUE" | wc -l)" -eq 1 ]] && [[ -n "$UNIQUE" ]]; then
    pass "모든 노드 datapath-mode: $UNIQUE"
  else
    fail "datapath-mode 불일치"
    for k in "${!DPM_MAP[@]}"; do echo "    $k=${DPM_MAP[$k]}"; done
  fi
fi

# ─── 3. kube-proxy 상태 ───
step "[3/11] kube-proxy 상태..."

KP_ARGS=$(kubectl --context "$CTX" get node "${NODE_NAMES[0]}" \
  -o jsonpath='{.metadata.annotations.k3s\.io/node-args}' 2>/dev/null || echo "[]")

if [[ "$MODE" == "restore" ]]; then
  if echo "$KP_ARGS" | grep -q "disable-kube-proxy"; then
    fail "disable-kube-proxy 플래그 잔존"
  else
    pass "kube-proxy 활성 (disable 없음)"
  fi
  if echo "$KP_ARGS" | grep -q '"flannel-backend","host-gw"'; then
    pass "flannel-backend=host-gw"
  else
    fail "flannel-backend 설정 잘못됨"
  fi
else
  if echo "$KP_ARGS" | grep -q "disable-kube-proxy"; then
    pass "disable-kube-proxy 활성"
  else
    fail "disable-kube-proxy 없음"
  fi
  if echo "$KP_ARGS" | grep -q '"flannel-backend","none"'; then
    pass "flannel-backend=none"
  else
    fail "flannel-backend 잘못됨 (Cilium 모드여야 함)"
  fi
fi

# ─── 4. LoadBalancer IP 할당 ───
step "[4/11] LoadBalancer IP 할당..."

LB_SVCS=$(kubectl --context "$CTX" get svc -A --field-selector spec.type=LoadBalancer \
  -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}|{.status.loadBalancer.ingress[*].ip}{"\n"}{end}' 2>/dev/null)

if [[ -z "$LB_SVCS" ]]; then
  note "LoadBalancer 서비스 없음"
else
  while IFS='|' read -r svc ips; do
    [[ -z "$svc" ]] && continue
    if [[ -n "$ips" ]]; then
      # IP가 여러개면 공백 분리. 개수 확인.
      IP_COUNT=$(echo "$ips" | wc -w)
      pass "$svc: $IP_COUNT IP ($ips)"
    else
      fail "$svc: IP 미할당"
    fi
  done <<< "$LB_SVCS"
fi

# ─── 5. 노드 CNI 파일 검증 ───
step "[5/11] 노드 CNI 설정 파일..."

for entry in "${NODES[@]}"; do
  IFS=: read -r target name _ <<< "$entry"
  CNI_FILES=$(_sudo "$target" "ls /etc/cni/net.d/ 2>/dev/null; true" 2>&1)

  if [[ "$MODE" == "restore" ]]; then
    if echo "$CNI_FILES" | grep -q "flannel"; then
      pass "$name: flannel CNI 존재"
    else
      fail "$name: flannel CNI 없음"
    fi
    if echo "$CNI_FILES" | grep -q "cilium"; then
      fail "$name: Cilium CNI 잔여 (reboot 필요)"
    else
      pass "$name: Cilium 잔여 없음"
    fi
    TC=$(_sudo "$target" "tc filter show dev eth0 ingress 2>/dev/null; tc filter show dev eth0 egress 2>/dev/null; true" 2>&1)
    if echo "$TC" | grep -qi "bpf\|cilium"; then
      fail "$name: eth0에 Cilium tc 프로그램 잔여"
    else
      pass "$name: tc filter 깨끗"
    fi
  else
    if echo "$CNI_FILES" | grep -q "cilium"; then
      pass "$name: Cilium CNI 존재"
    else
      fail "$name: Cilium CNI 없음 (agent 확인)"
    fi
  fi
done

# ─── 6. Pod READY 상태 ───
step "[6/11] Pod READY 상태..."

# STATUS=Running인데 READY=0/1 같은 경우를 놓치지 않기 위해 READY 컬럼도 체크
# 4번째 컬럼이 STATUS, 2번째가 READY (형식 n/m)
TOTAL=$(kubectl --context "$CTX" get pods -A --no-headers 2>/dev/null | wc -l)
PROBLEMATIC=$(kubectl --context "$CTX" get pods -A --no-headers 2>/dev/null | awk '
  {
    status = $4
    ready = $3
    # ready가 "n/m" 형식
    split(ready, arr, "/")
    n = arr[1]; m = arr[2]

    # Completed / Succeeded는 정상
    if (status == "Completed" || status == "Succeeded") next
    # Running인데 n != m 이면 READY 부족
    if (status == "Running" && n != m) { print; next }
    # Running 이외의 모든 상태
    if (status != "Running") { print; next }
  }' || true)

if [[ -z "$PROBLEMATIC" ]]; then
  pass "모든 Pod Running + READY 완전 ($TOTAL 개)"
else
  PCNT=$(echo "$PROBLEMATIC" | wc -l)
  fail "비정상 Pod $PCNT 개"
  echo "$PROBLEMATIC" | head -15 | sed 's/^/    /'
fi

# Cilium Pod 존재/부재 검증
if [[ "$MODE" == "restore" ]]; then
  CILIUM_PODS=$(kubectl --context "$CTX" get pods -A --no-headers 2>/dev/null | awk '$2 ~ /cilium/' | wc -l)
  if [[ "$CILIUM_PODS" -eq 0 ]]; then
    pass "Cilium Pod 없음"
  else
    fail "Cilium Pod $CILIUM_PODS 개 잔여"
  fi
fi

# ─── 7. CoreDNS ───
step "[7/11] CoreDNS..."

# CoreDNS가 실제로 READY인지 먼저 확인
COREDNS_READY=$(kubectl --context "$CTX" -n kube-system get deploy coredns --no-headers 2>/dev/null | awk '{print $2}')
if [[ "$COREDNS_READY" =~ ^([0-9]+)/([0-9]+)$ ]] && [[ "${BASH_REMATCH[1]}" -eq "${BASH_REMATCH[2]}" ]] && [[ "${BASH_REMATCH[1]}" -gt 0 ]]; then
  pass "CoreDNS Deploy Ready: $COREDNS_READY"
else
  fail "CoreDNS Deploy 미준비: $COREDNS_READY"
fi

# 실제 DNS 쿼리
POD_NAME="verify-dns-$(tr -dc a-z0-9 </dev/urandom | head -c5)"
DNS_OUT=$(kubectl --context "$CTX" run "$POD_NAME" --rm -i --restart=Never \
  --image=busybox:1.36 --timeout=90s \
  -- nslookup kubernetes.default.svc.cluster.local 2>&1 || true)
if echo "$DNS_OUT" | grep -q "Address.*10.43.0.1"; then
  pass "CoreDNS 쿼리 응답 10.43.0.1"
else
  fail "CoreDNS 쿼리 실패"
  echo "$DNS_OUT" | tail -5 | sed 's/^/    /'
fi

# ─── 8. 서비스 접근 (모든 9개 hostname) ───
step "[8/11] 서비스 접근 (${#EXPECTED_HOSTNAMES[@]}개 전부)..."

# LB IP 목록 확보
if [[ "$MODE" == "restore" ]]; then
  LB_IPS=$(kubectl --context "$CTX" -n ingress-ctrl get svc traefik \
    -o jsonpath='{.status.loadBalancer.ingress[*].ip}' 2>/dev/null || echo "")
  LB_SRC="Traefik"
else
  # Gateway service (label 다양한 fallback)
  LB_IPS=$(kubectl --context "$CTX" -n ingress-ctrl get svc \
    -l gateway.networking.k8s.io/gateway-name=bhyoo-gateway \
    -o jsonpath='{.items[*].status.loadBalancer.ingress[*].ip}' 2>/dev/null || echo "")
  if [[ -z "$LB_IPS" ]]; then
    LB_IPS=$(kubectl --context "$CTX" -n ingress-ctrl get svc cilium-gateway-bhyoo-gateway \
      -o jsonpath='{.status.loadBalancer.ingress[*].ip}' 2>/dev/null || echo "")
  fi
  if [[ -z "$LB_IPS" ]]; then
    LB_IPS=$(kubectl --context "$CTX" -n ingress-ctrl get svc --field-selector spec.type=LoadBalancer \
      -o jsonpath='{.items[*].status.loadBalancer.ingress[*].ip}' 2>/dev/null || echo "")
  fi
  LB_SRC="Gateway"
fi

if [[ -z "$LB_IPS" ]]; then
  fail "$LB_SRC LB IP 없음 — 아래 hostname 테스트 전부 건너뜀"
else
  pass "$LB_SRC LB IPs: $LB_IPS"

  # 각 advertised IP 전부에 대해 9개 hostname 전부 테스트
  # 단일 IP 실패를 놓치지 않기 위함
  for IP in $LB_IPS; do
    for host in "${EXPECTED_HOSTNAMES[@]}"; do
      CODE=$(curl -sk --resolve "$host:443:$IP" "https://$host" \
        -o /dev/null -w "%{http_code}" --max-time 15 2>/dev/null || echo "000")
      # 200-399만 pass. 401/403도 fail (docs "HTTP 200-399만 pass" 정책).
      # 보호된 엔드포인트가 있다면 인증 토큰 포함 별도 테스트 필요.
      if [[ "$CODE" -ge 200 && "$CODE" -lt 400 ]]; then
        pass "[$IP] $host: HTTP $CODE"
      else
        fail "[$IP] $host: HTTP $CODE"
      fi
    done
  done
fi

# ─── 9. 리소스 잔여물 (모드별) ───
step "[9/11] 리소스 잔여물..."

if [[ "$MODE" == "restore" ]]; then
  CILIUM_CRDS=$(kubectl --context "$CTX" get crd -o name 2>/dev/null | grep cilium | wc -l)
  if [[ "$CILIUM_CRDS" -eq 0 ]]; then
    pass "Cilium CRD 없음"
  else
    note "Cilium CRD ${CILIUM_CRDS}개 잔여 (무해)"
  fi
else
  TRAEFIK_DS=$(kubectl --context "$CTX" -n ingress-ctrl get ds -l app.kubernetes.io/name=traefik --no-headers 2>/dev/null | wc -l)
  if [[ "$TRAEFIK_DS" -eq 0 ]]; then
    pass "Traefik DS 제거됨"
  else
    note "Traefik DS 잔여 (Phase 4.3 완료 전이면 정상)"
  fi
  STATIC_LB=$(kubectl --context "$CTX" -n loadbalancer get deploy --no-headers 2>/dev/null | wc -l)
  if [[ "$STATIC_LB" -eq 0 ]]; then
    pass "static-lb 제거됨"
  else
    note "static-lb 잔여 (Phase 5 완료 전이면 정상)"
  fi
fi

# ─── 10. iptables 규칙 비교 ───
step "[10/11] iptables 규칙..."

for entry in "${NODES[@]}"; do
  IFS=: read -r target name _ <<< "$entry"
  CURRENT=$(_sudo "$target" "iptables-save 2>/dev/null; true" 2>&1 | wc -l)
  BACKUP_FILE="$BACKUP_DIR/nodes/$name/iptables.txt"

  if [[ "$MODE" == "restore" ]] && [[ -s "$BACKUP_FILE" ]]; then
    BACKUP=$(wc -l < "$BACKUP_FILE")
    if [[ "$BACKUP" -gt 0 ]]; then
      RATIO=$((CURRENT * 100 / BACKUP))
      if [[ "$RATIO" -ge 85 && "$RATIO" -le 115 ]]; then
        pass "$name: iptables 유사 (현재 $CURRENT, 백업 $BACKUP, ${RATIO}%)"
      else
        note "$name: iptables 차이 (현재 $CURRENT, 백업 $BACKUP, ${RATIO}%)"
      fi
    fi
  else
    pass "$name: iptables $CURRENT lines"
  fi
done

# ─── 11. HTTPRoute 검증 (migration 모드만) ───
step "[11/11] HTTPRoute Accepted+ResolvedRefs / Gateway Programmed..."

if [[ "$MODE" == "migration" ]]; then
  for host in "${EXPECTED_HOSTNAMES[@]}"; do
    FOUND=$(kubectl --context "$CTX" get httproute -A \
      -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}|{.spec.hostnames}{"\n"}{end}' 2>/dev/null \
      | grep "$host" | head -1)
    if [[ -z "$FOUND" ]]; then
      fail "$host: HTTPRoute 없음"
      continue
    fi
    ROUTE=$(echo "$FOUND" | awk -F'|' '{print $1}')
    IFS=/ read -r NS NAME <<< "$ROUTE"
    # Accepted + Programmed 조건 모두 True여야 함
    ACCEPTED=$(kubectl --context "$CTX" -n "$NS" get httproute "$NAME" \
      -o jsonpath='{.status.parents[0].conditions[?(@.type=="Accepted")].status}' 2>/dev/null)
    PROGRAMMED=$(kubectl --context "$CTX" -n "$NS" get httproute "$NAME" \
      -o jsonpath='{.status.parents[0].conditions[?(@.type=="ResolvedRefs")].status}' 2>/dev/null)
    # Gateway API spec상 HTTPRoute에는 Accepted + ResolvedRefs가 표준 condition.
    # "Programmed"는 Gateway 리소스의 condition이며, HTTPRoute에는 Accepted와 ResolvedRefs를 사용.
    # ref: https://gateway-api.sigs.k8s.io/reference/spec/#httproutestatus
    if [[ "$ACCEPTED" == "True" && "$PROGRAMMED" == "True" ]]; then
      pass "$host → $NS/$NAME Accepted+ResolvedRefs"
    else
      fail "$host → $NS/$NAME Accepted=$ACCEPTED ResolvedRefs=$PROGRAMMED"
    fi
  done

  # Gateway 자체 Programmed 확인 (HTTPRoute가 아닌 Gateway가 Programmed를 가짐)
  GW_PROGRAMMED=$(kubectl --context "$CTX" -n ingress-ctrl get gateway bhyoo-gateway \
    -o jsonpath='{.status.conditions[?(@.type=="Programmed")].status}' 2>/dev/null)
  if [[ "$GW_PROGRAMMED" == "True" ]]; then
    pass "Gateway bhyoo-gateway Programmed"
  else
    fail "Gateway bhyoo-gateway Programmed=$GW_PROGRAMMED"
  fi
else
  info "restore 모드이므로 HTTPRoute 검증 생략"
fi

# ─── 결과 ───
summary

if [[ "$FAIL_COUNT" -gt 0 ]]; then
  echo
  error "FAIL 항목이 있습니다."
  exit 1
else
  echo
  info "검증 통과 ($MODE 모드)"
  exit 0
fi
