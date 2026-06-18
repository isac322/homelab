#!/usr/bin/env bash
# cilium-migration-restore.sh
# Cilium 마이그레이션 실패 시 원래 Flannel 상태로 완전 복원합니다.
#
# 이 스크립트가 하는 일:
#   1. Cilium Helm release 삭제 (k8s 리소스 정리)
#   2. Cilium CRD 삭제 (operator가 런타임에 생성한 것)
#   3. Git을 원래 커밋으로 복원
#   4. 모든 노드 reboot (eBPF 프로그램 완전 정리 — 유일하게 확실한 방법)
#   5. k3s를 원래 설정(flannel host-gw)으로 재설치
#   6. 전체 Pod 재시작
#
# Usage: ./cilium-migration-restore.sh <backup_dir>
#
# 주의: 이 스크립트는 클러스터 전체 다운타임을 발생시킵니다.

set -uo pipefail

BACKUP_DIR="${1:-}"
CTX="private-backbone"
ANSIBLE_DIR="$(cd "$(dirname "$0")/../../cluster-setup" && pwd)"
REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }
ask()   { echo -e "${YELLOW}[확인]${NC} $1"; read -r -p "  계속하려면 Enter, 중단하려면 Ctrl+C: "; }

MASTERS_SSH=("bhyoo@192.168.219.5" "bhyoo@192.168.219.6" "bhyoo@192.168.219.7")
WORKERS_SSH=("root@192.168.219.3" "root@192.168.219.4")
ALL_SSH=("${MASTERS_SSH[@]}" "${WORKERS_SSH[@]}")
MASTER_NAMES=("rpi5" "rock5bp" "rpi4")
WORKER_NAMES=("n2p1" "n2p2")
ALL_NAMES=("${MASTER_NAMES[@]}" "${WORKER_NAMES[@]}")

if [[ -z "$BACKUP_DIR" || ! -d "$BACKUP_DIR" ]]; then
  echo "Usage: $0 <backup_dir>"
  echo "  backup_dir: cilium-migration-snapshot.sh로 생성한 디렉토리"
  exit 1
fi

ORIGINAL_COMMIT=$(head -1 "$BACKUP_DIR/git-head.txt" 2>/dev/null || true)
if [[ -z "$ORIGINAL_COMMIT" ]]; then
  error "백업에서 Git commit을 찾을 수 없습니다."
  exit 1
fi

echo "============================================"
echo "  Cilium Migration 전체 복원"
echo "============================================"
echo "백업 디렉토리: $BACKUP_DIR"
echo "복원 대상 Git commit: $ORIGINAL_COMMIT"
echo ""
warn "이 작업은 클러스터 전체 다운타임을 발생시킵니다."
warn "모든 노드가 reboot됩니다."
ask "진행하시겠습니까?"

# ─── Step 1: kubectl 접근 가능 시 Cilium k8s 리소스 정리 ───
info "[1/7] Cilium k8s 리소스 정리 시도..."
if kubectl --context "$CTX" get nodes &>/dev/null; then
  info "  클러스터 접근 가능. Helm uninstall 실행..."

  # Cilium Gateway/HTTPRoute 삭제 (있는 경우)
  kubectl --context "$CTX" delete gateway --all -A --ignore-not-found 2>/dev/null || true
  kubectl --context "$CTX" delete httproute --all -A --ignore-not-found 2>/dev/null || true

  # CiliumLoadBalancerIPPool, CiliumL2AnnouncementPolicy 삭제
  kubectl --context "$CTX" delete ciliumloadbalancerippool --all --ignore-not-found 2>/dev/null || true
  kubectl --context "$CTX" delete ciliuml2announcementpolicy --all --ignore-not-found 2>/dev/null || true

  # Helm release 삭제
  if helm list -n kube-system --kube-context "$CTX" 2>/dev/null | grep -q cilium; then
    helm uninstall cilium -n kube-system --kube-context "$CTX" 2>&1 || warn "helm uninstall 실패 (계속 진행)"
    info "  Cilium Helm release 삭제 완료"
  else
    info "  Cilium Helm release 없음 (이미 삭제됨)"
  fi

  # Cilium CRD 삭제 (operator가 런타임에 생성한 것)
  CILIUM_CRDS=$(kubectl --context "$CTX" get crd -o name 2>/dev/null | grep cilium || true)
  if [[ -n "$CILIUM_CRDS" ]]; then
    echo "$CILIUM_CRDS" | xargs kubectl --context "$CTX" delete --ignore-not-found 2>/dev/null || true
    info "  Cilium CRD 삭제 완료"
  fi

  # Cilium namespace (cilium-secrets 등) 정리
  kubectl --context "$CTX" delete namespace cilium-secrets --ignore-not-found 2>/dev/null || true

else
  warn "  클러스터 접근 불가. k8s 리소스 정리 건너뜀 (etcd에 잔여물이 남을 수 있음)."
  warn "  복원 후 수동으로 Cilium CRD를 삭제해야 합니다."
fi

# ─── Step 2: 모든 노드에서 k3s 중지 ───
info "[2/7] 모든 노드에서 k3s 중지..."
cd "$ANSIBLE_DIR"
for i in "${!ALL_NAMES[@]}"; do
  name="${ALL_NAMES[$i]}"
  ansible -i inventory/hosts "$name" -m systemd -a "name=k3s state=stopped" --become 2>/dev/null \
    && info "  $name: k3s 중지됨" \
    || warn "  $name: k3s 중지 실패 (이미 중지되었을 수 있음)"
done

# ─── Step 3: 각 노드에서 Flannel 동작을 방해하는 Cilium 잔여물 제거 ───
info "[3/7] 각 노드에서 Cilium 잔여물 제거..."
info "  (Flannel/kube-proxy 동작에 영향을 주는 것만 제거. 나머지는 무해하므로 무시)"
for i in "${!ALL_SSH[@]}"; do
  ssh_target="${ALL_SSH[$i]}"
  name="${ALL_NAMES[$i]}"

  ssh "$ssh_target" "sudo bash -s" <<'CLEANUP' 2>/dev/null && info "  $name: 정리 완료" || warn "  $name: 일부 정리 실패"
    # [필수] Cilium CNI 설정 파일 삭제
    # 이유: kubelet이 CNI를 알파벳순으로 로드하므로 05-cilium이 10-flannel보다 먼저 선택됨
    # 이 파일이 남아있으면 Pod 생성 시 없는 Cilium CNI를 호출하여 실패함
    rm -f /etc/cni/net.d/05-cilium.conflist
    rm -f /etc/cni/net.d/*cilium*
CLEANUP
done

# ─── Step 4: Git 복원 ───
info "[4/7] Git을 원래 커밋으로 복원..."
cd "$REPO_DIR"
CURRENT_BRANCH=$(git branch --show-current 2>/dev/null || echo "detached")
git stash 2>/dev/null || true
git checkout "$ORIGINAL_COMMIT" 2>&1
info "  Git HEAD: $(git rev-parse HEAD)"

# ─── Step 5: 모든 노드 reboot ───
info "[5/7] 모든 노드 reboot..."
info "  이유: Cilium이 네트워크 인터페이스에 attach한 tc eBPF 프로그램은"
info "  파일 삭제로 제거되지 않음. 이 프로그램이 남아있으면 패킷 경로를"
info "  가로채서 Flannel의 host-gw 라우팅과 kube-proxy의 iptables 처리를 방해함."
info "  reboot이 이를 확실히 정리하는 유일한 방법."
ask "모든 노드를 reboot합니다."

cd "$ANSIBLE_DIR"
for i in "${!ALL_SSH[@]}"; do
  ssh_target="${ALL_SSH[$i]}"
  name="${ALL_NAMES[$i]}"
  ssh "$ssh_target" "sudo reboot" 2>/dev/null || true
  info "  $name: reboot 명령 전송"
done

info "  60초 대기 (노드 부팅 중)..."
sleep 60

# 노드가 SSH 응답할 때까지 대기
info "  노드 부팅 완료 대기..."
for i in "${!ALL_SSH[@]}"; do
  ssh_target="${ALL_SSH[$i]}"
  name="${ALL_NAMES[$i]}"
  for attempt in $(seq 1 30); do
    if ssh -o ConnectTimeout=5 "$ssh_target" "echo ok" &>/dev/null; then
      info "  $name: SSH 접속 가능 (${attempt}번째 시도)"
      break
    fi
    if [[ "$attempt" -eq 30 ]]; then
      error "  $name: 30회 시도 후에도 SSH 접속 불가. 수동 확인 필요."
    fi
    sleep 10
  done
done

# ─── Step 6: k3s 원래 설정으로 재설치 ───
info "[6/7] k3s를 원래 설정(flannel host-gw)으로 재설치..."
cd "$ANSIBLE_DIR"

# 마스터 순서대로
for name in "${MASTER_NAMES[@]}"; do
  info "  $name: ansible-playbook 실행 중..."
  ansible-playbook -i inventory/hosts k3s.yaml --limit "$name" 2>&1 | tail -3
  sleep 10
done

# 워커
for name in "${WORKER_NAMES[@]}"; do
  info "  $name: ansible-playbook 실행 중..."
  ansible-playbook -i inventory/hosts k3s.yaml --limit "$name" 2>&1 | tail -3
done

# 클러스터 안정화 대기
info "  클러스터 안정화 대기 (30초)..."
sleep 30

# ─── Step 7: iptables 복원 + Pod 재시작 ───
info "[7/7] iptables 복원 + Pod 재시작..."

# iptables
cd "$ANSIBLE_DIR"
ansible-playbook -i inventory/hosts firewall.yaml --limit backbone 2>&1 | tail -3

# Pod 재시작
info "  모든 Pod 재시작..."
for ns in $(kubectl --context "$CTX" get ns -o jsonpath='{.items[*].metadata.name}' 2>/dev/null \
  | tr ' ' '\n' | grep -v kube-system); do
  kubectl --context "$CTX" rollout restart deploy -n "$ns" 2>/dev/null || true
  kubectl --context "$CTX" rollout restart sts -n "$ns" 2>/dev/null || true
  kubectl --context "$CTX" rollout restart ds -n "$ns" 2>/dev/null || true
done

# Step 1에서 클러스터 접근이 불가능했던 경우, 이제 CRD 정리
CILIUM_CRDS=$(kubectl --context "$CTX" get crd -o name 2>/dev/null | grep cilium || true)
if [[ -n "$CILIUM_CRDS" ]]; then
  info "  잔여 Cilium CRD 삭제..."
  echo "$CILIUM_CRDS" | xargs kubectl --context "$CTX" delete --ignore-not-found 2>/dev/null || true
fi

# Cilium Helm release secret 정리 (helm uninstall 실패 시 남을 수 있음)
kubectl --context "$CTX" delete secret -n kube-system -l owner=helm,name=cilium --ignore-not-found 2>/dev/null || true

echo ""
echo "============================================"
echo "  복원 완료"
echo "============================================"
info "다음 명령으로 검증하세요:"
echo "  ./cilium-migration-verify.sh $BACKUP_DIR"
echo ""
info "Git을 원래 브랜치로 돌리려면:"
echo "  cd $REPO_DIR && git checkout $CURRENT_BRANCH && git stash pop"
