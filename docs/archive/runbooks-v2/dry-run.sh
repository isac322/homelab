#!/usr/bin/env bash
# dry-run.sh — Phase 2: 마이그레이션 실행 전 시뮬레이션
#
# 실제로 변경하지 않고 아래를 검증:
#   1. 백업 완전성
#   2. Helm template (client-side)
#   3. Helm install --dry-run=server (실제 API server 검증)
#   4. Ansible --check (k3s.yaml, firewall.yaml)
#   5. cert-manager ClusterIssuer의 DNS-01 지원
#   6. ArgoCD auto-sync 상태
#   7. 스크립트 구문 검사
#   8. 필요한 파일/리소스 존재 확인
#
# Usage: ./dry-run.sh <backup_dir>

set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/_lib.sh"

BACKUP_DIR="${1:-}"
if [[ -z "$BACKUP_DIR" || ! -d "$BACKUP_DIR" ]]; then
  error "Usage: $0 <backup_dir>"
  exit 1
fi

info "Dry-Run 시뮬레이션 시작"
echo

# ─── 1. 백업 완전성 ───
step "[1/8] 백업 완전성..."

REQUIRED_FILES=(
  "etcd-snapshot"
  "git-head.txt"
  "argocd-sync-policy.tsv"
  "SUMMARY.txt"
)
for f in "${REQUIRED_FILES[@]}"; do
  if assert_nonempty_file "$BACKUP_DIR/$f" 2>/dev/null; then
    pass "$f 존재"
  else
    fail "$f 없음 또는 빈 파일"
  fi
done

for name in "${NODE_NAMES[@]}"; do
  dir="$BACKUP_DIR/nodes/$name"
  if [[ -d "$dir" ]] && [[ $(ls -1 "$dir" | wc -l) -ge 9 ]]; then
    pass "노드 백업: $name ($(ls -1 $dir | wc -l) 파일)"
  else
    fail "노드 백업 부족: $name"
  fi
done

# etcd snapshot 해시 검증
if [[ -f "$BACKUP_DIR/etcd-snapshot.sha256" ]]; then
  if (cd "$BACKUP_DIR" && sha256sum -c etcd-snapshot.sha256 >/dev/null 2>&1); then
    pass "etcd snapshot 체크섬 유효"
  else
    fail "etcd snapshot 체크섬 불일치 (백업 손상)"
  fi
fi

# ─── 2. Helm template (client-side) ───
step "[2/8] Helm template 렌더링..."

if ! command -v helm >/dev/null 2>&1; then
  fail "helm 명령어 없음"
else
  if helm template cilium cilium/cilium \
      --version 1.19.3 \
      --namespace kube-system \
      -f "$REPO_ROOT/values/cilium/backbone.yaml" \
      > /tmp/cilium-v2-rendered.yaml 2>&1; then
    pass "Helm template 렌더링 OK ($(wc -l < /tmp/cilium-v2-rendered.yaml) lines)"

    # 핵심 설정 반영 확인
    for key in "enable-node-ipam: \"true\"" "default-lb-service-ipam: \"nodeipam\"" "routing-mode: \"native\"" "kube-proxy-replacement: \"true\"" "datapath-mode: \"veth\"" "enable-bpf-masquerade: \"true\""; do
      if grep -q "$key" /tmp/cilium-v2-rendered.yaml; then
        pass "values key 반영: $key"
      else
        fail "values key 누락: $key"
      fi
    done
  else
    fail "Helm template 렌더링 실패"
    command cat /tmp/cilium-v2-rendered.yaml | tail -5
  fi
fi

# ─── 3. Helm dry-run=server ───
step "[3/8] Helm dry-run=server..."

if helm install cilium cilium/cilium \
    --version 1.19.3 \
    --namespace kube-system \
    --kube-context "$CTX" \
    -f "$REPO_ROOT/values/cilium/backbone.yaml" \
    --dry-run=server > /tmp/cilium-v2-dryrun.log 2>&1; then
  pass "Helm dry-run=server 성공"
else
  fail "Helm dry-run=server 실패"
  tail -10 /tmp/cilium-v2-dryrun.log
fi

# ─── 4. Ansible --check ───
step "[4/8] Ansible --check 모드..."

cd "$ANSIBLE_DIR"

# ansible --check: 모든 host에 대해 failed=0 AND unreachable=0 이어야 함
# PLAY RECAP 형식: "host : ok=N changed=N unreachable=N failed=N skipped=N rescued=N ignored=N"
check_ansible_log() {
  local log="$1"
  local label="$2"
  local recap
  recap=$(awk '/PLAY RECAP/,0' "$log" | grep -E "failed=[0-9]+" || true)
  if [[ -z "$recap" ]]; then
    fail "$label: PLAY RECAP 없음 (플레이북 시작 전 실패)"
    tail -20 "$log" | sed 's/^/    /'
    return 1
  fi
  # failed != 0 또는 unreachable != 0 인 host 찾기
  local bad
  bad=$(echo "$recap" | awk '
    /unreachable=[1-9]/ { print; next }
    /failed=[1-9]/ { print; next }
  ')
  if [[ -n "$bad" ]]; then
    fail "$label: 일부 host에 failed>0 또는 unreachable>0"
    echo "$bad" | sed 's/^/    /'
    return 1
  fi
  pass "$label: 전체 failed=0 + unreachable=0"
  return 0
}

ansible-playbook -i inventory/hosts k3s.yaml --limit backbone --check --diff > /tmp/ansible-k3s-check.log 2>&1 || true
check_ansible_log /tmp/ansible-k3s-check.log "k3s.yaml --check"

ansible-playbook -i inventory/hosts firewall.yaml --limit backbone --check --diff \
    -e use_k8s_cilium=true -e use_k8s_cilium_hubble=true > /tmp/ansible-firewall-check.log 2>&1 || true
check_ansible_log /tmp/ansible-firewall-check.log "firewall.yaml --check"

# ─── 5. cert-manager ClusterIssuer DNS-01 확인 ───
step "[5/8] cert-manager ClusterIssuer 검증..."

ISSUER_SPEC=$(kubectl --context "$CTX" get clusterissuer cluster-issuer-acme -o json 2>/dev/null || echo "{}")
if echo "$ISSUER_SPEC" | python3 -c "
import json, sys
d = json.load(sys.stdin)
solvers = d.get('spec', {}).get('acme', {}).get('solvers', [])
has_dns01 = any('dns01' in s for s in solvers)
has_http01 = any('http01' in s for s in solvers)
print(f'dns01: {has_dns01}, http01: {has_http01}')
sys.exit(0 if has_dns01 else 1)
"; then
  pass "ClusterIssuer가 DNS-01 지원 (wildcard 발급 가능)"
else
  note "ClusterIssuer가 DNS-01 미지원. wildcard 인증서 발급 불가. Gateway listener를 per-hostname 방식으로 작성 필요."
fi

# ─── 6. ArgoCD auto-sync 상태 확인 ───
step "[6/8] ArgoCD auto-sync 상태..."

# 마이그레이션 중 backbone-traefik, backbone-static-lb auto-sync를 끌 예정
# 현재 auto-sync 상태 확인
for app in backbone-traefik backbone-static-lb; do
  if kubectl --context "$CTX" -n argocd get app "$app" -o jsonpath='{.spec.syncPolicy.automated}' 2>/dev/null | grep -q prune; then
    pass "$app: auto-sync 활성 (Phase 3에서 비활성 필요)"
  else
    note "$app: auto-sync 이미 비활성"
  fi
done

# ─── 7. 스크립트 구문 검사 ───
step "[7/8] 스크립트 구문 검사..."

for script in "$SCRIPT_DIR"/*.sh; do
  if bash -n "$script" 2>/dev/null; then
    pass "$(basename $script) 구문 OK"
  else
    fail "$(basename $script) 구문 에러"
  fi
done

# shellcheck (있으면)
if command -v shellcheck >/dev/null 2>&1; then
  for script in "$SCRIPT_DIR"/*.sh; do
    if shellcheck -S error "$script" >/dev/null 2>&1; then
      pass "$(basename $script) shellcheck 에러 없음"
    else
      note "$(basename $script) shellcheck warning 있음 (비차단)"
    fi
  done
else
  note "shellcheck 미설치 — 설치 권장"
fi

# ─── 8. 필수 매니페스트 파일 존재 ───
step "[8/8] v2 리소스 파일 존재..."

REQUIRED_MANIFESTS=(
  "values/cilium/backbone.yaml"
  "argocd/apps/cilium.yaml"
)
for rel in "${REQUIRED_MANIFESTS[@]}"; do
  if [[ -f "$REPO_ROOT/$rel" ]]; then
    pass "$rel"
  else
    fail "$rel 없음 (작성 필요)"
  fi
done

# Phase 1에서 작성해야 할 파일들 — 존재 확인만
OPTIONAL_MANIFESTS=(
  "argocd/apps/cilium-gateway.yaml"
  "apps/cilium-gateway/gateway.yaml"
  "apps/cilium-gateway/certificate.yaml"
)
for rel in "${OPTIONAL_MANIFESTS[@]}"; do
  if [[ -f "$REPO_ROOT/$rel" ]]; then
    pass "$rel"
  else
    note "$rel 없음 (Gateway 전환 Phase 4에 필요)"
  fi
done

# ─── 결과 요약 ───
summary

if [[ "$FAIL_COUNT" -gt 0 ]]; then
  echo
  error "FAIL 항목이 있습니다. 수정 후 재실행하세요."
  exit 1
else
  echo
  info "Dry-run 통과. Phase 3 (Cutover) 진행 가능."
  exit 0
fi
