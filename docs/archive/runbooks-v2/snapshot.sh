#!/usr/bin/env bash
# snapshot.sh — Phase 0: Cilium 마이그레이션 전 상태 캡처
#
# v1 개선점:
# - 모든 SSH/scp 명령 exit code 검증
# - 수집된 각 파일 크기 검증 (0바이트면 실패)
# - etcd 스냅샷 해시 기록
# - 실패 시 즉시 중단 (set -e)
#
# Usage: SSHPASS='<pw>' ./snapshot.sh [backup_dir]

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/_lib.sh"

require_sshpass

BACKUP_DIR="${1:-$HOME/backup/cilium-migration/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$BACKUP_DIR"

info "Cilium Migration Snapshot 시작"
info "Backup dir: $BACKUP_DIR"
echo

FAIL=0
fail_step() { error "[FAIL] $*"; FAIL=1; }

# ─── 1. etcd snapshot ───
step "[1/6] etcd snapshot 생성..."

SNAPSHOT_NAME="pre-cilium-$(date +%Y%m%d-%H%M%S)"
if _sudo "bhyoo@192.168.219.5" "k3s etcd-snapshot save --name $SNAPSHOT_NAME" > "$BACKUP_DIR/etcd-snapshot-create.log" 2>&1; then
  pass "etcd snapshot 명령 성공"
else
  fail_step "etcd snapshot 생성 실패"
  command cat "$BACKUP_DIR/etcd-snapshot-create.log"
fi

# 실제 파일 경로 찾기 및 로컬로 복사
SNAPSHOT_PATH=$(_sudo "bhyoo@192.168.219.5" "ls -t /var/lib/rancher/k3s/server/db/snapshots/${SNAPSHOT_NAME}* 2>/dev/null | head -1" | tail -1 | tr -d '\r')

if [[ -z "$SNAPSHOT_PATH" ]]; then
  fail_step "etcd snapshot 파일 경로 찾기 실패"
else
  # 원격 파일을 읽을 수 있는 권한으로 임시 복사 후 scp
  _sudo "bhyoo@192.168.219.5" "cp $SNAPSHOT_PATH /tmp/etcd-snapshot && chmod 644 /tmp/etcd-snapshot"

  if sshpass -e scp "${SSH_OPTS[@]}" "bhyoo@192.168.219.5:/tmp/etcd-snapshot" "$BACKUP_DIR/etcd-snapshot" 2>/dev/null; then
    if assert_nonempty_file "$BACKUP_DIR/etcd-snapshot" 1048576; then  # 최소 1MB
      pass "etcd snapshot 복사 ($(stat -c%s "$BACKUP_DIR/etcd-snapshot") bytes)"
      sha256sum "$BACKUP_DIR/etcd-snapshot" > "$BACKUP_DIR/etcd-snapshot.sha256"
    else
      fail_step "etcd snapshot 크기 비정상"
    fi
  else
    fail_step "etcd snapshot scp 실패"
  fi

  # 임시 파일 제거
  _sudo "bhyoo@192.168.219.5" "rm -f /tmp/etcd-snapshot" >/dev/null 2>&1 || true
fi

# ─── 2. 노드별 설정 백업 ───
step "[2/6] 노드별 설정 백업..."

for entry in "${NODES[@]}"; do
  IFS=: read -r target name role <<< "$entry"
  dir="$BACKUP_DIR/nodes/$name"
  mkdir -p "$dir"

  # 각 파일별로 수집 + 크기 검증
  collect() {
    local filename="$1"; shift
    local expected_min="$1"; shift
    local cmd="$*"

    if _sudo "$target" "$cmd" > "$dir/$filename" 2>&1; then
      if assert_nonempty_file "$dir/$filename" "$expected_min" 2>/dev/null; then
        return 0
      else
        error "  $name/$filename: 크기 부족"
        return 1
      fi
    else
      error "  $name/$filename: 수집 실패"
      return 1
    fi
  }

  node_fail=0
  collect "config.yaml" 50   "cat /etc/rancher/k3s/config.yaml" || node_fail=1
  collect "iptables.txt" 500 "iptables-save" || node_fail=1
  collect "ip6tables.txt" 50 "ip6tables-save" || node_fail=1
  collect "cni-files.txt" 10 "ls -la /etc/cni/net.d/" || node_fail=1
  collect "cni-config.txt" 10 "cat /etc/cni/net.d/* 2>/dev/null || echo empty" || node_fail=1
  collect "cni-binaries.txt" 50 "ls -la /opt/cni/bin/" || node_fail=1
  collect "ip-addr.txt" 200 "ip -brief addr show" || node_fail=1
  collect "ip-route.txt" 50 "ip route show" || node_fail=1
  collect "interfaces-detail.txt" 200 "ip -details link show" || node_fail=1

  # BPF state (Cilium 전이므로 빈 결과 가능 - 크기 체크 없음)
  _sudo "$target" "ls /sys/fs/bpf/ 2>/dev/null || echo empty" > "$dir/bpf-fs.txt" 2>&1 || true

  # Kernel config (중요: XDP/netkit 지원 기록)
  _ssh "$target" 'KCONFIG=""; for p in /proc/config.gz /boot/config-$(uname -r); do [ -e "$p" ] && KCONFIG="$p" && break; done; if [ -z "$KCONFIG" ]; then echo "no kernel config"; exit 1; fi; if [ "${KCONFIG%.gz}" != "$KCONFIG" ]; then zcat "$KCONFIG"; else cat "$KCONFIG"; fi | grep -E "^CONFIG_(BPF|XDP|VXLAN|NETKIT|CGROUP_BPF|NF_TABLES|NET_CLS_BPF|TCP_CONG_BBR)=" | head -40' > "$dir/kernel-config.txt" 2>&1 || true

  if [[ "$node_fail" -eq 0 ]]; then
    pass "$name: 9/9 필수 파일 수집"
  else
    fail_step "$name: 일부 파일 수집 실패"
  fi
done

# ─── 3. 클러스터 리소스 백업 ───
step "[3/6] 클러스터 리소스 백업..."

CLUSTER="$BACKUP_DIR/cluster"
mkdir -p "$CLUSTER"

kubectl_or_fail() {
  local out="$1"; shift
  if kubectl --context "$CTX" "$@" > "$out" 2>&1; then
    if [[ -s "$out" ]]; then
      return 0
    else
      error "  빈 결과: $out"
      return 1
    fi
  else
    error "  kubectl 실패: $@"
    return 1
  fi
}

cluster_fail=0
kubectl_or_fail "$CLUSTER/nodes.txt"             get nodes -o wide || cluster_fail=1
kubectl_or_fail "$CLUSTER/nodes.json"            get nodes -o json || cluster_fail=1
kubectl_or_fail "$CLUSTER/namespaces.txt"        get ns || cluster_fail=1
kubectl_or_fail "$CLUSTER/pods.txt"              get pods -A -o wide || cluster_fail=1
kubectl_or_fail "$CLUSTER/services.txt"          get svc -A -o wide || cluster_fail=1
kubectl_or_fail "$CLUSTER/deployments.txt"       get deploy -A -o wide || cluster_fail=1
kubectl_or_fail "$CLUSTER/statefulsets.txt"      get sts -A -o wide || cluster_fail=1
kubectl_or_fail "$CLUSTER/daemonsets.txt"        get ds -A -o wide || cluster_fail=1
kubectl_or_fail "$CLUSTER/ingress.yaml"          get ingress -A -o yaml || cluster_fail=1
kubectl_or_fail "$CLUSTER/gateway.yaml"          get gateway -A -o yaml || cluster_fail=1
kubectl_or_fail "$CLUSTER/httproute.yaml"        get httproute -A -o yaml || cluster_fail=1
kubectl_or_fail "$CLUSTER/networkpolicies.yaml"  get networkpolicy -A -o yaml || cluster_fail=1
kubectl_or_fail "$CLUSTER/crds.txt"              get crd || cluster_fail=1
kubectl_or_fail "$CLUSTER/argocd-apps.yaml"      -n argocd get app -o yaml || cluster_fail=1
kubectl_or_fail "$CLUSTER/argocd-appsets.yaml"   -n argocd get appsets -o yaml 2>/dev/null || true

# 서비스 상세 (LB IP 포함) — 탭 구분
kubectl --context "$CTX" get svc -A -o json | python3 -c "
import json, sys
data = json.load(sys.stdin)
for svc in data['items']:
    ns = svc['metadata']['namespace']
    name = svc['metadata']['name']
    stype = svc['spec'].get('type', 'ClusterIP')
    cip = svc['spec'].get('clusterIP', '')
    lb = svc.get('status', {}).get('loadBalancer', {}).get('ingress', [])
    lb_ips = ','.join(i.get('ip', '') for i in lb if 'ip' in i)
    print(f'{ns}\t{name}\t{stype}\t{cip}\t{lb_ips}')
" > "$CLUSTER/service-details.tsv" 2>&1 || cluster_fail=1

if [[ "$cluster_fail" -eq 0 ]]; then
  pass "클러스터 리소스 백업 완료"
else
  fail_step "클러스터 리소스 일부 실패"
fi

# ─── 4. Git 상태 기록 ───
step "[4/6] Git 상태 기록..."

cd "$REPO_ROOT"
git rev-parse HEAD > "$BACKUP_DIR/git-head.txt"
git log --oneline -20 >> "$BACKUP_DIR/git-head.txt"
git status --short > "$BACKUP_DIR/git-status.txt"
git diff --stat > "$BACKUP_DIR/git-diff-stat.txt" 2>/dev/null || true

if assert_nonempty_file "$BACKUP_DIR/git-head.txt"; then
  pass "Git 상태 기록 ($(head -1 $BACKUP_DIR/git-head.txt))"
else
  fail_step "Git 상태 기록 실패"
fi

# ─── 5. ArgoCD app sync policy 기록 (롤백 시 필요) ───
step "[5/6] ArgoCD auto-sync 상태 기록..."

kubectl --context "$CTX" -n argocd get app -o json | python3 -c "
import json, sys
data = json.load(sys.stdin)
for app in data['items']:
    name = app['metadata']['name']
    auto = app['spec'].get('syncPolicy', {}).get('automated', None)
    print(f'{name}\t{\"automated\" if auto else \"manual\"}')
" > "$BACKUP_DIR/argocd-sync-policy.tsv"

if assert_nonempty_file "$BACKUP_DIR/argocd-sync-policy.tsv"; then
  pass "ArgoCD sync policy 기록 완료 ($(wc -l < $BACKUP_DIR/argocd-sync-policy.tsv) apps)"
else
  fail_step "ArgoCD sync policy 기록 실패"
fi

# ─── 6. 요약 생성 및 전체 검증 ───
step "[6/6] 요약 생성..."

cat > "$BACKUP_DIR/SUMMARY.txt" <<SUMMARY
Cilium Migration Snapshot
=========================
Date: $(date -Iseconds)
Repo: $REPO_ROOT
Git commit: $(head -1 "$BACKUP_DIR/git-head.txt")

Cluster stats:
  Nodes:           $(kubectl --context "$CTX" get nodes --no-headers 2>/dev/null | wc -l)
  Namespaces:      $(kubectl --context "$CTX" get ns --no-headers 2>/dev/null | wc -l)
  Pods:            $(kubectl --context "$CTX" get pods -A --no-headers 2>/dev/null | wc -l)
  Services:        $(kubectl --context "$CTX" get svc -A --no-headers 2>/dev/null | wc -l)
  LB Services:     $(kubectl --context "$CTX" get svc -A --field-selector spec.type=LoadBalancer --no-headers 2>/dev/null | wc -l)
  Ingresses:       $(kubectl --context "$CTX" get ingress -A --no-headers 2>/dev/null | wc -l)
  HTTPRoutes:      $(kubectl --context "$CTX" get httproute -A --no-headers 2>/dev/null | wc -l)
  NetworkPolicies: $(kubectl --context "$CTX" get networkpolicy -A --no-headers 2>/dev/null | wc -l)
  DaemonSets:      $(kubectl --context "$CTX" get ds -A --no-headers 2>/dev/null | wc -l)

Backup contents:
  etcd snapshot:            $([[ -s "$BACKUP_DIR/etcd-snapshot" ]] && stat -c%s "$BACKUP_DIR/etcd-snapshot" || echo MISSING) bytes
  Node configs backed up:   $(ls -1d "$BACKUP_DIR/nodes"/*/ 2>/dev/null | wc -l)
  Cluster files:            $(ls "$CLUSTER" 2>/dev/null | wc -l)
SUMMARY

command cat "$BACKUP_DIR/SUMMARY.txt"
echo

# ─── 최종 결과 ───
if [[ "$FAIL" -eq 0 ]]; then
  info "백업 성공: $BACKUP_DIR"
  echo
  echo "다음 단계:"
  echo "  Phase 2: ./dry-run.sh '$BACKUP_DIR'"
  exit 0
else
  error "백업 중 실패가 발생했습니다. 위 로그를 확인하고 다시 시도하세요."
  echo "  (부분 백업이 '$BACKUP_DIR'에 있으나 사용하면 안 됩니다)"
  exit 1
fi
