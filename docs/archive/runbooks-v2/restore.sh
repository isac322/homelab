#!/usr/bin/env bash
# restore.sh — Cilium 마이그레이션 Level 2 복원
#
# 핵심 아이디어: Git 레이어와 실제 Cluster 레이어를 순서대로 분리 복원.
#   (A) GitOps 레이어 롤백 (git revert + push + backbone-cilium App 삭제)
#   (B) 노드 레이어 복원 (k3s 중지 → CNI 제거 → reboot → k3s 재설치 with Flannel)
#   (C) ArgoCD가 (A)의 revert를 traefik/static-lb로 재반영하도록 sync 대기
#       ← 이 시점에 Flannel CNI가 다시 동작하므로 Pod 생성 가능
#
# Usage: SSHPASS='<pw>' ./restore.sh <backup_dir>

set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/_lib.sh"

require_sshpass

BACKUP_DIR="${1:-}"
if [[ -z "$BACKUP_DIR" || ! -d "$BACKUP_DIR" ]]; then
  error "Usage: $0 <backup_dir>"
  exit 1
fi

ORIGINAL_COMMIT=$(head -1 "$BACKUP_DIR/git-head.txt" 2>/dev/null || echo "")
if [[ -z "$ORIGINAL_COMMIT" ]]; then
  error "백업에서 Git commit 해시를 찾을 수 없음"
  exit 1
fi

echo "========================================"
info "Cilium Migration Level 2 복원"
echo "========================================"
info "백업: $BACKUP_DIR"
info "복원 대상 commit: $ORIGINAL_COMMIT"
echo
warn "전체 클러스터 다운타임 발생 + 모든 노드 reboot"
warn "예상 소요 시간: 현실적 ~60분 / worst case ~145분"
warn "  breakdown (worst case, 합 = 145분):"
warn "    reboot sequential   : 65분 (노드당 180s down + 600s up × 5)"
warn "    k3s master 순차     : 35분 (3 master × ~10분 ansible + Ready wait + 안정화 대기)"
warn "    ArgoCD sync         : 25분 (appsets sync 15s + traefik 10분 + static-lb 10분 + Pod wait 4분)"
warn "    firewall+Pod+cleanup: 10분"
warn "    verify              : 10분"
ask "진행하시겠습니까?"

cd "$REPO_ROOT"

# ─── Step 0: 사전 검증 ───
step "[0/11] 사전 검증..."

CURRENT_BRANCH=$(git branch --show-current)
DEFAULT_BRANCH=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's@^origin/@@' || echo "master")
if [[ "$CURRENT_BRANCH" != "$DEFAULT_BRANCH" ]]; then
  error "현재 브랜치: '$CURRENT_BRANCH' (필요: '$DEFAULT_BRANCH')"
  error "git checkout $DEFAULT_BRANCH && git pull 후 다시 실행"
  exit 1
fi

if ! git diff-index --quiet HEAD --; then
  error "Git working tree가 clean하지 않음. commit 또는 stash 필요"
  git status --short
  exit 1
fi

git fetch origin "$DEFAULT_BRANCH" 2>/dev/null || { error "git fetch 실패"; exit 1; }
AHEAD=$(git rev-list --count "origin/$DEFAULT_BRANCH..HEAD")
BEHIND=$(git rev-list --count "HEAD..origin/$DEFAULT_BRANCH")
if [[ "$AHEAD" -gt 0 ]] || [[ "$BEHIND" -gt 0 ]]; then
  error "로컬과 origin/$DEFAULT_BRANCH 불일치 (ahead=$AHEAD, behind=$BEHIND). git pull/push 후 재실행"
  exit 1
fi
pass "사전 검증 통과 ($DEFAULT_BRANCH, clean, synced)"

# ─── Step 1: GitOps 롤백 (git revert + push) ───
step "[1/11] GitOps 롤백..."

CURRENT_HEAD=$(git rev-parse HEAD)
if [[ "$CURRENT_HEAD" == "$ORIGINAL_COMMIT" ]]; then
  info "이미 원래 commit. revert 생략."
else
  COMMITS_TO_REVERT=$(git rev-list --reverse "$ORIGINAL_COMMIT..HEAD")
  if [[ -z "$COMMITS_TO_REVERT" ]]; then
    warn "revert할 커밋 없음"
  else
    NUM=$(echo "$COMMITS_TO_REVERT" | wc -l)
    info "$NUM 커밋 revert 중..."
    while IFS= read -r hash; do
      [[ -z "$hash" ]] && continue
      if ! git revert --no-edit "$hash"; then
        error "revert 충돌: $hash — 수동 해결 + push 후 Step 2부터 수동 진행"
        exit 1
      fi
    done <<< "$COMMITS_TO_REVERT"

    if ! git push origin "$DEFAULT_BRANCH"; then
      error "git push 실패 (권한/branch protection 확인)"
      exit 1
    fi
    pass "Git revert + push 완료 ($NUM 커밋)"
  fi
fi

# ─── Step 2: backbone-cilium App 삭제 (self-heal 차단) ───
step "[2/11] backbone-cilium Application 삭제..."
# ArgoCD가 Cilium을 재배포하지 못하도록 명시적 삭제.
# --ignore-not-found는 App이 이미 없을 때 OK.
# 다른 에러(예: API 접근 불가, finalizer hang)는 치명적이므로 `|| true` 없음.
for app in backbone-cilium backbone-cilium-gateway; do
  if ! kubectl --context "$CTX" -n argocd delete app "$app" \
      --cascade=foreground --ignore-not-found --timeout=5m; then
    error "$app 삭제 실패. ArgoCD self-heal이 계속 Cilium을 재생성할 위험"
    error "수동 조치: kubectl -n argocd edit app $app → metadata.finalizers 제거 → 다시 삭제"
    exit 1
  fi
  # 삭제 확인
  if kubectl --context "$CTX" -n argocd get app "$app" &>/dev/null; then
    error "$app 삭제 후에도 리소스가 존재"
    exit 1
  fi
done
pass "Cilium Application 완전 삭제"

# ─── Step 3: 모든 노드 k3s/k3s-agent 중지 (role 기반) ───
step "[3/11] 모든 노드 k3s 중지..."

cd "$ANSIBLE_DIR"
STOP_FAIL=0
for name in "${NODE_NAMES[@]}"; do
  role=$(get_role "$name")
  unit=$(k3s_unit_for "$role")
  if ansible -i inventory/hosts "$name" -m systemd -a "name=$unit state=stopped" --become 2>/dev/null; then
    info "  $name: $unit stopped"
  else
    error "  $name: $unit 중지 실패"
    STOP_FAIL=1
  fi
done
[[ "$STOP_FAIL" -eq 1 ]] && { error "일부 노드 중지 실패"; exit 1; }
sleep 5

# ─── Step 4: Cilium CNI 설정 파일 제거 ───
step "[4/11] Cilium CNI 설정 파일 제거..."

for entry in "${NODES[@]}"; do
  IFS=: read -r target name _ <<< "$entry"
  _sudo "$target" "rm -f /etc/cni/net.d/*cilium* 2>/dev/null; true" 2>/dev/null \
    && info "  $name: OK" \
    || warn "  $name: 실패 (reboot으로 커버됨)"
done

# ─── Step 5: 모든 노드 reboot (per-node pairing + boot time 검증) ───
step "[5/11] 모든 노드 reboot..."
info "  이유: tc eBPF 프로그램은 파일 삭제만으로 제거되지 않음"
info "  방식: 각 노드를 dispatch+down 순차 확인 후 복구 대기 (race 방지)"

if ! reboot_all_nodes_safely; then
  error "reboot 실패. 수동 확인 후 재실행"
  exit 1
fi
pass "모든 노드 재부팅 완료"

# ─── Step 6: k3s 재설치 (master 순차, worker 병렬) ───
step "[6/11] ansible-playbook k3s.yaml (Flannel 복원)..."

cd "$ANSIBLE_DIR"

# Master 순차
for name in "${MASTER_NAMES[@]}"; do
  info "  master $name: 기동..."
  if ! ansible-playbook -i inventory/hosts k3s.yaml --limit "$name" 2>&1 | tail -5; then
    error "$name: k3s.yaml 실패"
    exit 1
  fi
  info "  $name Ready 대기 (최대 5분)..."
  if kubectl --context "$CTX" wait node "$name" --for=condition=Ready --timeout=5m 2>/dev/null; then
    pass "  $name: Ready"
  else
    fail "$name Ready 타임아웃"
    exit 1
  fi
done

# Worker 병렬
info "  workers 병렬..."
if ! ansible-playbook -i inventory/hosts k3s.yaml \
    --limit "$(IFS=,; echo "${WORKER_NAMES[*]}")" 2>&1 | tail -5; then
  error "worker k3s.yaml 실패"
  exit 1
fi

# 모든 노드 Ready 대기
info "  전체 Ready 대기..."
kubectl --context "$CTX" wait node --all --for=condition=Ready --timeout=5m || {
  fail "전체 노드 Ready 실패"
  kubectl --context "$CTX" get nodes
  exit 1
}
pass "모든 노드 Ready"

# ─── Step 7: firewall.yaml 재실행 ───
step "[7/11] ansible-playbook firewall.yaml..."

if ansible-playbook -i inventory/hosts firewall.yaml --limit backbone 2>&1 | tail -5; then
  pass "firewall.yaml 적용"
else
  warn "firewall.yaml 일부 에러 — 수동 확인"
fi

# ─── Step 8: ArgoCD auto-sync 복원 + traefik/static-lb sync 대기 ───
# 이제 Flannel CNI가 동작하므로 Pod 생성 가능 → Traefik/static-lb 복원 가능
step "[8/11] traefik/static-lb ArgoCD App sync..."

# parent App(argocd-appsets) 먼저 sync하여 traefik/static-lb Application 리소스가
# Git revert 후 재생성되도록 유도
kubectl --context "$CTX" -n argocd patch app argocd-appsets --type=merge \
  -p '{"operation":{"sync":{"prune":true}}}' 2>/dev/null || true
sleep 15

# 필수 App이 존재하는지 엄격 확인 + sync 대기. 실패 시 즉시 abort.
REQUIRED_APPS=(backbone-traefik backbone-static-lb)
for app in "${REQUIRED_APPS[@]}"; do
  # 최대 5분간 App 리소스 등장 대기
  APP_OK=0
  for i in $(seq 1 30); do
    if kubectl --context "$CTX" -n argocd get app "$app" >/dev/null 2>&1; then
      APP_OK=1; break
    fi
    sleep 10
  done
  if [[ "$APP_OK" -eq 0 ]]; then
    error "$app Application 리소스가 5분 후에도 나타나지 않음. ArgoCD parent sync 확인 필요"
    exit 1
  fi

  # auto-sync 복원 + sync 트리거
  kubectl --context "$CTX" -n argocd patch app "$app" --type=merge \
    -p '{"spec":{"syncPolicy":{"automated":{"prune":true,"selfHeal":true}}}}' 2>/dev/null || true
  kubectl --context "$CTX" -n argocd patch app "$app" --type=merge \
    -p '{"operation":{"sync":{"prune":true}}}' 2>/dev/null || true

  info "$app Synced+Healthy 대기 (최대 10분)..."
  if ! wait_argocd_app "$app" 10m; then
    STATUS=$(kubectl --context "$CTX" -n argocd get app "$app" \
      -o jsonpath='{.status.sync.status}/{.status.health.status}' 2>/dev/null)
    error "$app 타임아웃. 현재 상태: $STATUS"
    kubectl --context "$CTX" -n argocd get app "$app" -o jsonpath='{.status.conditions}' | head -c 800
    echo
    exit 1
  fi
  pass "$app: Synced + Healthy"
done

# Pod 확인 — Running 이상인지 엄격 체크
for ns_app in "ingress-ctrl:traefik" "loadbalancer:static-lb"; do
  IFS=: read -r ns app <<< "$ns_app"
  POD_OK=0
  for i in $(seq 1 12); do  # 최대 2분
    RUNNING=$(kubectl --context "$CTX" -n "$ns" get pods -l "app.kubernetes.io/name=$app" \
      --no-headers 2>/dev/null | awk '$3=="Running"' | wc -l)
    if [[ "$RUNNING" -ge 1 ]]; then
      pass "$ns/$app: $RUNNING Pod Running"
      POD_OK=1
      break
    fi
    sleep 10
  done
  if [[ "$POD_OK" -eq 0 ]]; then
    error "$ns/$app Pod이 Running에 도달하지 못함"
    exit 1
  fi
done

# ─── Step 9: 전체 Pod 재시작 (kube-system 포함) ───
step "[9/11] 전체 Pod 재시작 (CoreDNS 포함)..."

for ns in $(kubectl --context "$CTX" get ns -o jsonpath='{.items[*].metadata.name}'); do
  for kind in deploy sts ds; do
    kubectl --context "$CTX" -n "$ns" rollout restart "$kind" 2>/dev/null || true
  done
done
info "rollout 대기 (60초)..."
sleep 60

# ─── Step 10: Cilium k8s 잔여물 정리 ───
step "[10/11] Cilium k8s 잔여물 정리..."

if helm list -n kube-system --kube-context "$CTX" 2>/dev/null | grep -q cilium; then
  helm uninstall cilium -n kube-system --kube-context "$CTX" 2>/dev/null || true
  info "  Cilium Helm release 삭제"
fi

CILIUM_CRDS=$(kubectl --context "$CTX" get crd -o name 2>/dev/null | grep cilium || true)
if [[ -n "$CILIUM_CRDS" ]]; then
  echo "$CILIUM_CRDS" | xargs kubectl --context "$CTX" delete --ignore-not-found 2>/dev/null || true
  info "  Cilium CRD 삭제"
fi

kubectl --context "$CTX" delete ns cilium-secrets --ignore-not-found 2>/dev/null || true
kubectl --context "$CTX" -n ingress-ctrl delete gateway bhyoo-gateway --ignore-not-found 2>/dev/null || true
for ns in argocd hindsight immich object-storage prometheus; do
  kubectl --context "$CTX" -n "$ns" delete httproute --all --ignore-not-found 2>/dev/null || true
done

# ─── Step 11: 검증 ───
step "[11/11] 복원 검증..."

if [[ -x "$SCRIPT_DIR/verify.sh" ]]; then
  if ! "$SCRIPT_DIR/verify.sh" "$BACKUP_DIR"; then
    error "verify.sh FAIL"
    exit 1
  fi
else
  warn "verify.sh 없음"
fi

echo
echo "========================================"
info "복원 완료"
echo "========================================"
