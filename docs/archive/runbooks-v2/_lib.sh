#!/usr/bin/env bash
# _lib.sh — 공통 함수 및 노드 정의

# 색상
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()   { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()   { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()  { echo -e "${RED}[ERROR]${NC} $*" >&2; }
step()   { echo -e "${BLUE}[STEP]${NC}  $*"; }
ask()    { echo -e "${YELLOW}[확인]${NC} $*"; read -r -p "  계속 Enter / 중단 Ctrl+C: "; }

# Cluster context
export CTX="${CTX:-private-backbone}"

# 노드 정의: "ssh_target:name:role"
# NOTE: ssh_target에 IPv6 주소(콜론 포함)는 지원하지 않음.
# 현재 환경은 IPv4 only이고, 필요 시 [::1] 형식 대신 /etc/hosts 별칭 사용 권장.
export NODES=(
  "bhyoo@192.168.219.5:rpi5:master"
  "bhyoo@192.168.219.6:rock5bp:master"
  "bhyoo@192.168.219.7:rpi4:master"
  "root@192.168.219.3:n2p1:worker"
  "root@192.168.219.4:n2p2:worker"
)

# NODES 엔트리 무결성 검증 (정확히 2개 콜론, user@host 형식)
_validate_nodes() {
  for entry in "${NODES[@]}"; do
    # 콜론 개수 = 2 필수
    local colons="${entry//[^:]/}"
    if [[ "${#colons}" -ne 2 ]]; then
      echo "ERROR: NODES entry malformed (IPv6 or extra colon?): $entry" >&2
      return 1
    fi
  done
  return 0
}
_validate_nodes || exit 1

# 편의 배열
export NODE_NAMES=(rpi5 rock5bp rpi4 n2p1 n2p2)
export MASTER_NAMES=(rpi5 rock5bp rpi4)
export WORKER_NAMES=(n2p1 n2p2)

# sshpass 확인
require_sshpass() {
  if ! command -v sshpass >/dev/null 2>&1; then
    error "sshpass가 설치되지 않았습니다. 설치: sudo pacman -S sshpass (Arch) / apt install sshpass (Debian)"
    return 1
  fi
  if [[ -z "${SSHPASS:-}" ]]; then
    error "SSHPASS 환경변수가 설정되지 않았습니다."
    error "실행 전: export SSHPASS='...'"
    return 1
  fi
}

# SSH 실행
SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR)

_ssh() {
  # _ssh <target> <command>
  local target="$1"; shift
  sshpass -e ssh "${SSH_OPTS[@]}" "$target" "$@"
}

_sudo() {
  # _sudo <target> <command> — 원격에서 sudo로 명령 실행
  # 비밀번호를 CLI에 노출하지 않기 위해 stdin으로 전달
  local target="$1"; shift
  local user="${target%@*}"
  local cmd="$*"
  if [[ "$user" == "root" ]]; then
    sshpass -e ssh "${SSH_OPTS[@]}" "$target" "$cmd"
  else
    # sudo -S가 stdin에서 비밀번호를 읽음. 원격 쉘이 stdin 읽어 sudo에 직접 넘김
    sshpass -e ssh "${SSH_OPTS[@]}" "$target" \
      "SUDO_PASS=\$(cat); echo \"\$SUDO_PASS\" | sudo -S -p '' $cmd" <<< "$SSHPASS"
  fi
}

# 노드 role에 따라 systemd 유닛 이름 반환
# Usage: unit=$(k3s_unit_for "master" or "worker")
k3s_unit_for() {
  case "$1" in
    master) echo "k3s" ;;
    worker) echo "k3s-agent" ;;
    *) echo "k3s"; return 1 ;;
  esac
}

# 노드 배열에서 role 조회: get_role <name>
get_role() {
  local want="$1"
  for entry in "${NODES[@]}"; do
    IFS=: read -r t n r <<< "$entry"
    if [[ "$n" == "$want" ]]; then echo "$r"; return 0; fi
  done
  return 1
}

# 노드 배열에서 ssh target 조회: get_target <name>
get_target() {
  local want="$1"
  for entry in "${NODES[@]}"; do
    IFS=: read -r t n r <<< "$entry"
    if [[ "$n" == "$want" ]]; then echo "$t"; return 0; fi
  done
  return 1
}

# 노드 k3s/k3s-agent 중지 (role 기반)
stop_k3s_on() {
  local name="$1"
  local role unit
  role=$(get_role "$name") || { error "unknown node: $name"; return 1; }
  unit=$(k3s_unit_for "$role")
  ansible -i inventory/hosts "$name" -m systemd -a "name=$unit state=stopped" --become 2>/dev/null
}

# 노드 SSH 응답 대기 (성공 시 0, 실패 시 1)
# timeout_sec: 절대 시간 기준 deadline (기본 600초 = 10분)
wait_for_ssh() {
  local target="$1"
  local timeout_sec="${2:-600}"
  local poll_sec="${3:-5}"
  local deadline=$(( $(date +%s) + timeout_sec ))
  while [[ $(date +%s) -lt "$deadline" ]]; do
    # ConnectTimeout=3으로 빠른 재시도
    if sshpass -e ssh -o ConnectTimeout=3 -o StrictHostKeyChecking=accept-new \
         -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
         "$target" "echo ok" &>/dev/null; then
      return 0
    fi
    sleep "$poll_sec"
  done
  return 1
}

# 단일 노드의 pre-reboot baseline 수집 (boot time 필수)
# 실패 시 1 반환 → 호출자가 abort 결정
collect_boot_baseline() {
  local target="$1"
  local boot_time
  boot_time=$(_ssh "$target" "stat -c %Y /proc/1" 2>/dev/null | tr -d '\r\n')
  if [[ -z "$boot_time" ]] || ! [[ "$boot_time" =~ ^[0-9]+$ ]] || [[ "$boot_time" -eq 0 ]]; then
    return 1
  fi
  echo "$boot_time"
  return 0
}

# 단일 노드 reboot dispatch
# systemd-run을 우선 사용하여 SSH 세션이 정상 종료되도록 함
# 실패 시 1 반환
dispatch_reboot() {
  local target="$1"
  if _sudo "$target" "systemd-run --no-block --unit=cilium-restore-reboot-$$ /sbin/reboot" >/dev/null 2>&1; then
    return 0
  fi
  if _sudo "$target" "shutdown -r +0" >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

# 단일 노드가 SSH 응답을 멈출 때까지 대기 (reboot 실제 발생 확인)
# timeout_sec 내에 SSH 불가 상태가 되면 0, 아니면 1
wait_for_ssh_down() {
  local target="$1"
  local timeout_sec="${2:-180}"
  local poll_sec="${3:-3}"
  local deadline=$(( $(date +%s) + timeout_sec ))
  while [[ $(date +%s) -lt "$deadline" ]]; do
    if ! sshpass -e ssh -o ConnectTimeout=3 -o StrictHostKeyChecking=accept-new \
         -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
         "$target" "echo" &>/dev/null; then
      return 0
    fi
    sleep "$poll_sec"
  done
  return 1
}

# 전 노드 simultaneous reboot: 동시 dispatch + 모든 노드 down 확인 + 모든 노드 up 확인
# 용도: Pre-stop 마이그레이션 — 이미 k3s가 전부 중지된 상태에서만 사용
# (HA etcd quorum 손실 걱정 없음, 어차피 서비스 전부 내려간 상태)
# 실패 시 1 반환
reboot_all_nodes_parallel_safely() {
  declare -A _BT_BEFORE

  # 1) baseline 수집 (필수)
  for entry in "${NODES[@]}"; do
    IFS=: read -r target name _ <<< "$entry"
    local bt
    if ! bt=$(collect_boot_baseline "$target"); then
      error "$name: pre-reboot boot time 수집 실패"
      return 1
    fi
    _BT_BEFORE[$name]="$bt"
  done

  # 2) 병렬 dispatch — 전 노드 동시에 reboot 명령
  for entry in "${NODES[@]}"; do
    IFS=: read -r target name _ <<< "$entry"
    if ! dispatch_reboot "$target"; then
      error "$name: reboot dispatch 실패"
      return 1
    fi
    info "  $name: reboot dispatched"
  done

  # 3) 모든 노드 SSH down 대기 (동시 감시, polling loop)
  info "  모든 노드 SSH down 대기 (최대 5분)..."
  declare -A _DOWN=()
  local deadline_down=$(( $(date +%s) + 300 ))
  while [[ $(date +%s) -lt "$deadline_down" ]]; do
    local all_down=1
    for entry in "${NODES[@]}"; do
      IFS=: read -r target name _ <<< "$entry"
      [[ "${_DOWN[$name]:-0}" -eq 1 ]] && continue
      if ! sshpass -e ssh -o ConnectTimeout=3 -o StrictHostKeyChecking=accept-new \
           -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
           "$target" "echo" &>/dev/null; then
        _DOWN[$name]=1
        info "  $name: down"
      else
        all_down=0
      fi
    done
    [[ "$all_down" -eq 1 ]] && break
    sleep 3
  done
  for entry in "${NODES[@]}"; do
    IFS=: read -r target name _ <<< "$entry"
    if [[ "${_DOWN[$name]:-0}" -ne 1 ]]; then
      error "$name: 5분 내 내려가지 않음 (reboot 실행 안 됨)"
      return 1
    fi
  done

  # 4) 모든 노드 SSH up 대기 (동시 감시)
  info "  모든 노드 SSH 복구 대기 (최대 15분)..."
  declare -A _UP=()
  local deadline_up=$(( $(date +%s) + 900 ))
  while [[ $(date +%s) -lt "$deadline_up" ]]; do
    local all_up=1
    for entry in "${NODES[@]}"; do
      IFS=: read -r target name _ <<< "$entry"
      [[ "${_UP[$name]:-0}" -eq 1 ]] && continue
      if sshpass -e ssh -o ConnectTimeout=3 -o StrictHostKeyChecking=accept-new \
           -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
           "$target" "echo" &>/dev/null; then
        _UP[$name]=1
        info "  $name: up"
      else
        all_up=0
      fi
    done
    [[ "$all_up" -eq 1 ]] && break
    sleep 5
  done

  # 5) 모든 노드 up + boot time 변경 확인
  for entry in "${NODES[@]}"; do
    IFS=: read -r target name _ <<< "$entry"
    if [[ "${_UP[$name]:-0}" -ne 1 ]]; then
      error "$name: 15분 내 SSH 복구 실패"
      return 1
    fi
    local boot_after
    boot_after=$(_ssh "$target" "stat -c %Y /proc/1" 2>/dev/null | tr -d '\r\n')
    if [[ -z "$boot_after" ]] || ! [[ "$boot_after" =~ ^[0-9]+$ ]]; then
      error "$name: post-reboot boot time 읽기 실패"
      return 1
    fi
    if [[ "$boot_after" == "${_BT_BEFORE[$name]}" ]]; then
      error "$name: boot time 변경 없음 (재부팅 흔적 없음)"
      return 1
    fi
    info "  $name: 재부팅 완료 (${_BT_BEFORE[$name]} → $boot_after)"
  done

  return 0
}

# 전 노드 rolling reboot: per-node pairing (dispatch → down → 다음 노드 dispatch)
# 각 노드가 내려간 것을 확인한 뒤 다음 노드 dispatch
# 모든 노드 dispatch+down 확인 후, 각 노드가 다시 올라올 때까지 대기 + boot time 변경 검증
# 용도: 롤백(restore.sh) — Cilium이 깨지긴 했지만 완전히 죽지 않은 상태에서 안전하게 순차 복원
# 실패 시 1 반환
reboot_all_nodes_safely() {
  declare -A BOOT_BEFORE

  # 1) baseline 수집 (필수, 실패 시 abort)
  for entry in "${NODES[@]}"; do
    IFS=: read -r target name _ <<< "$entry"
    local bt
    if ! bt=$(collect_boot_baseline "$target"); then
      error "$name: pre-reboot boot time 수집 실패"
      return 1
    fi
    BOOT_BEFORE[$name]="$bt"
  done

  # 2) per-node dispatch → down (pair) — race 방지
  for entry in "${NODES[@]}"; do
    IFS=: read -r target name _ <<< "$entry"
    if ! dispatch_reboot "$target"; then
      error "$name: reboot dispatch 실패"
      return 1
    fi
    info "  $name: reboot dispatched, SSH down 대기..."
    if ! wait_for_ssh_down "$target" 180 3; then
      error "$name: 3분 내 내려가지 않음 (reboot 실행 안 됨)"
      return 1
    fi
    info "  $name: 내려감 확인"
  done

  # 3) 모든 노드 SSH 복구 대기 + boot time 변경 검증
  for entry in "${NODES[@]}"; do
    IFS=: read -r target name _ <<< "$entry"
    info "  $name: SSH 복구 대기 (최대 10분)..."
    if ! wait_for_ssh "$target" 600 5; then
      error "$name: SSH 복구 실패"
      return 1
    fi
    local boot_after
    boot_after=$(_ssh "$target" "stat -c %Y /proc/1" 2>/dev/null | tr -d '\r\n')
    if [[ -z "$boot_after" ]] || ! [[ "$boot_after" =~ ^[0-9]+$ ]]; then
      error "$name: post-reboot boot time 읽기 실패"
      return 1
    fi
    if [[ "$boot_after" == "${BOOT_BEFORE[$name]}" ]]; then
      error "$name: boot time 변경 없음 (재부팅 흔적 없음)"
      return 1
    fi
    info "  $name: 재부팅 완료 (boot time: ${BOOT_BEFORE[$name]} → $boot_after)"
  done

  return 0
}

# ArgoCD app이 Synced + Healthy 될 때까지 대기
wait_argocd_app() {
  local app="$1"
  local timeout="${2:-5m}"
  kubectl --context "$CTX" -n argocd wait "app/$app" \
    --for=jsonpath='{.status.sync.status}=Synced' --timeout="$timeout" 2>/dev/null \
  && kubectl --context "$CTX" -n argocd wait "app/$app" \
    --for=jsonpath='{.status.health.status}=Healthy' --timeout="$timeout" 2>/dev/null
}

# 파일 크기 검증 (byte 단위)
assert_nonempty_file() {
  local path="$1"
  local min_bytes="${2:-1}"
  if [[ ! -f "$path" ]]; then
    error "파일 없음: $path"
    return 1
  fi
  local size
  size=$(stat -c%s "$path" 2>/dev/null || stat -f%z "$path" 2>/dev/null)
  if [[ -z "$size" || "$size" -lt "$min_bytes" ]]; then
    error "파일 크기 부족: $path ($size bytes, 최소 $min_bytes)"
    return 1
  fi
  return 0
}

# PASS/FAIL/WARN 카운터
declare -g PASS_COUNT=0
declare -g FAIL_COUNT=0
declare -g WARN_COUNT=0

pass() { echo -e "  ${GREEN}PASS${NC}  $*"; ((PASS_COUNT++)); }
fail() { echo -e "  ${RED}FAIL${NC}  $*"; ((FAIL_COUNT++)); }
note() { echo -e "  ${YELLOW}WARN${NC}  $*"; ((WARN_COUNT++)); }

summary() {
  echo
  echo "========================================"
  echo -e "  ${GREEN}PASS${NC}: $PASS_COUNT"
  echo -e "  ${YELLOW}WARN${NC}: $WARN_COUNT"
  echo -e "  ${RED}FAIL${NC}: $FAIL_COUNT"
  echo "========================================"
}

# Repo root 자동 감지
detect_repo_root() {
  local dir="$(cd "$(dirname "${BASH_SOURCE[1]}")" && pwd)"
  while [[ "$dir" != "/" ]]; do
    [[ -d "$dir/.git" ]] && echo "$dir" && return 0
    dir="$(dirname "$dir")"
  done
  error "Git repo root 찾기 실패"
  return 1
}
export REPO_ROOT="${REPO_ROOT:-$(detect_repo_root)}"
export ANSIBLE_DIR="$REPO_ROOT/cluster-setup"
