#!/usr/bin/env bash
# restore-etcd.sh — Level 3 비상 복원 (etcd 스냅샷에서 재구성)
#
# 사용 시점: restore.sh가 실패했거나 etcd 자체가 손상된 경우
#
# Usage: SSHPASS='<pw>' ./restore-etcd.sh <backup_dir>
#   backup_dir: snapshot.sh로 생성된 디렉토리 (etcd-snapshot 파일 포함)

set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/_lib.sh"

require_sshpass

BACKUP_DIR="${1:-}"
if [[ -z "$BACKUP_DIR" || ! -d "$BACKUP_DIR" ]]; then
  error "Usage: $0 <backup_dir>"
  error "  backup_dir: snapshot.sh로 생성된 디렉토리 (예: ~/backup/cilium-migration/20260418-180000)"
  exit 1
fi

SNAPSHOT="$BACKUP_DIR/etcd-snapshot"
if [[ ! -s "$SNAPSHOT" ]]; then
  error "etcd snapshot 없음: $SNAPSHOT"
  exit 1
fi

# 체크섬 검증
if [[ -f "$BACKUP_DIR/etcd-snapshot.sha256" ]]; then
  if (cd "$BACKUP_DIR" && sha256sum -c etcd-snapshot.sha256 >/dev/null 2>&1); then
    pass "etcd snapshot 체크섬 유효"
  else
    error "etcd snapshot 체크섬 불일치 — 백업 손상"
    exit 1
  fi
fi

echo "========================================"
warn "Level 3 비상 복원 — etcd 스냅샷에서 재구성"
echo "========================================"
warn "etcd 클러스터가 완전히 재구성됩니다."
warn "backup 시점 이후의 모든 k8s 리소스 변경이 사라집니다."
ask "진행하시겠습니까?"

# ─── Step 1: snapshot을 rpi5로 복사 ───
step "[1/7] etcd snapshot을 rpi5에 복사..."

if ! sshpass -e scp "${SSH_OPTS[@]}" "$SNAPSHOT" "bhyoo@192.168.219.5:/tmp/etcd-restore-snapshot"; then
  error "snapshot scp 실패"
  exit 1
fi
# 원격 체크섬 재검증
LOCAL_SHA=$(sha256sum "$SNAPSHOT" | awk '{print $1}')
REMOTE_SHA=$(_ssh "bhyoo@192.168.219.5" "sha256sum /tmp/etcd-restore-snapshot" | awk '{print $1}')
if [[ "$LOCAL_SHA" != "$REMOTE_SHA" ]]; then
  error "원격 snapshot 체크섬 불일치 (local=$LOCAL_SHA remote=$REMOTE_SHA)"
  exit 1
fi
pass "snapshot 복사 + 체크섬 일치"

# ─── Step 2: 모든 노드 k3s/k3s-agent 중지 (role 기반) ───
step "[2/7] 모든 노드 k3s 중지 (role 기반)..."

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
if [[ "$STOP_FAIL" -eq 1 ]]; then
  error "일부 노드 중지 실패. 수동 확인 후 재실행"
  exit 1
fi
sleep 10

# ─── Step 3: rpi5에서 cluster-reset ───
step "[3/7] rpi5에서 k3s server --cluster-reset..."

_sudo "bhyoo@192.168.219.5" "k3s server --cluster-reset --cluster-reset-restore-path=/tmp/etcd-restore-snapshot" > /tmp/cluster-reset.log 2>&1 &
RESET_PID=$!
info "  cluster-reset 진행 중... (최대 180초)"

# 최대 180초 대기 (90초는 너무 짧을 수 있음)
for i in $(seq 1 36); do
  sleep 5
  if ! kill -0 $RESET_PID 2>/dev/null; then
    break
  fi
  if grep -q "Managed etcd cluster membership has been reset" /tmp/cluster-reset.log 2>/dev/null; then
    # 메시지 나왔으면 k3s가 곧 종료. 조금 더 대기
    sleep 5
    break
  fi
done

# PID 정리
if kill -0 $RESET_PID 2>/dev/null; then
  warn "cluster-reset이 스스로 종료하지 않음. SIGTERM 전송"
  kill $RESET_PID 2>/dev/null || true
  wait $RESET_PID 2>/dev/null || true
fi

if grep -q "Managed etcd cluster membership has been reset" /tmp/cluster-reset.log; then
  pass "cluster-reset 성공"
else
  tail -20 /tmp/cluster-reset.log
  error "cluster-reset 메시지 없음. 수동 확인 필요"
  exit 1
fi

# ─── Step 4: 다른 마스터의 etcd 데이터 삭제 ───
step "[4/7] 다른 마스터의 etcd 데이터 삭제 (재합류 준비)..."

for name in rock5bp rpi4; do
  target=$(get_target "$name") || { error "unknown node: $name"; exit 1; }
  if _sudo "$target" "rm -rf /var/lib/rancher/k3s/server/db/etcd"; then
    pass "$name: etcd 데이터 삭제"
  else
    error "$name: etcd 데이터 삭제 실패"
    exit 1
  fi
done

# ─── Step 5: 모든 노드 reboot (per-node pairing) ───
step "[5/7] 모든 노드 reboot..."

if ! reboot_all_nodes_safely; then
  error "reboot 실패"
  exit 1
fi
pass "모든 노드 재부팅 완료"

# ─── Step 6: k3s.yaml 재실행 (master 순차, worker 병렬) ───
step "[6/7] ansible-playbook k3s.yaml..."

cd "$ANSIBLE_DIR"

# 마스터 순차: rpi5 먼저(cluster-init 상태) → rock5bp → rpi4
# 각 단계에서 (1) k8s Ready + (2) etcd 멤버로 합류했는지 함께 확인
for name in "${MASTER_NAMES[@]}"; do
  info "  master $name: 기동 중..."
  if ! ansible-playbook -i inventory/hosts k3s.yaml --limit "$name" 2>&1 | tail -5; then
    error "$name: k3s.yaml 실패"
    exit 1
  fi

  # (1) Kubernetes node Ready
  info "  $name k8s Ready 대기..."
  if ! kubectl --context "$CTX" wait node "$name" --for=condition=Ready --timeout=6m 2>/dev/null; then
    fail "$name k8s Ready 타임아웃"
    exit 1
  fi

  # (2) etcd 건강성: kubectl --raw /readyz?verbose 에서 [+]etcd ok 확인
  # k3s는 etcdctl wrapper를 기본 포함하지 않으므로 API server /readyz를 통해 검증.
  # --request-timeout=10s: API server가 hang 되어도 10초 후 다음 retry로 진행
  info "  $name etcd 건강성 확인 (/readyz)..."
  ETCD_OK=0
  for i in $(seq 1 30); do  # 최대 5분
    READYZ=$(kubectl --context "$CTX" --request-timeout=10s \
      get --raw "/readyz?verbose" 2>/dev/null || echo "")
    if echo "$READYZ" | grep -q '^\[+\]etcd ok$' && \
       echo "$READYZ" | grep -q '^\[+\]etcd-readiness ok$'; then
      ETCD_OK=1
      break
    fi
    sleep 10
  done
  if [[ "$ETCD_OK" -eq 1 ]]; then
    pass "  $name: etcd OK (/readyz)"
  else
    fail "$name join 후 etcd 건강성 5분 내 확인 실패"
    error "수동 확인: kubectl get --raw /readyz?verbose"
    error "예상: [+]etcd ok / [+]etcd-readiness ok"
    exit 1
  fi
done

# 워커는 병렬 가능
info "  workers 병렬 실행..."
if ! ansible-playbook -i inventory/hosts k3s.yaml --limit "$(IFS=,; echo "${WORKER_NAMES[*]}")" 2>&1 | tail -5; then
  error "worker k3s.yaml 실패"
  exit 1
fi

sleep 30

# ─── Step 7: 검증 ───
step "[7/7] 검증..."

if [[ -x "$SCRIPT_DIR/verify.sh" ]]; then
  "$SCRIPT_DIR/verify.sh" "$BACKUP_DIR" || {
    error "verify.sh FAIL"
    exit 1
  }
else
  warn "verify.sh 없음. 수동 검증 필요"
fi

echo
info "Level 3 비상 복원 완료"
