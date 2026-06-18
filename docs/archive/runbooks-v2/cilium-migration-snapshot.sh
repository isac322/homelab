#!/usr/bin/env bash
# cilium-migration-snapshot.sh
# Cilium 마이그레이션 전 클러스터 상태를 캡처합니다.
# 복원 후 cilium-migration-verify.sh로 비교 검증합니다.
#
# Usage: ./cilium-migration-snapshot.sh [backup_dir]

set -euo pipefail

CTX="private-backbone"
BACKUP_DIR="${1:-$HOME/backup/cilium-migration/$(date +%Y%m%d-%H%M%S)}"
MASTERS=("bhyoo@192.168.219.5:rpi5" "bhyoo@192.168.219.6:rock5bp" "bhyoo@192.168.219.7:rpi4")
WORKERS=("root@192.168.219.3:n2p1" "root@192.168.219.4:n2p2")
ALL_NODES=("${MASTERS[@]}" "${WORKERS[@]}")

mkdir -p "$BACKUP_DIR"

echo "=== Cilium Migration Snapshot ==="
echo "Backup dir: $BACKUP_DIR"
echo ""

# ─── 1. etcd 스냅샷 ───
echo "[1/7] etcd 스냅샷 생성..."
ssh bhyoo@192.168.219.5 "sudo k3s etcd-snapshot save --name pre-cilium-$(date +%Y%m%d-%H%M%S)" 2>&1
SNAPSHOT_FILE=$(ssh bhyoo@192.168.219.5 "sudo ls -t /var/lib/rancher/k3s/server/db/snapshots/pre-cilium-* 2>/dev/null | head -1")
if [[ -n "$SNAPSHOT_FILE" ]]; then
  scp "bhyoo@192.168.219.5:$SNAPSHOT_FILE" "$BACKUP_DIR/etcd-snapshot"
  echo "  etcd 스냅샷: $BACKUP_DIR/etcd-snapshot"
else
  echo "  WARNING: etcd 스냅샷 복사 실패. 수동 확인 필요."
fi

# ─── 2. 노드별 상태 캡처 ───
echo "[2/7] 노드별 설정 백업..."
for entry in "${ALL_NODES[@]}"; do
  IFS=: read -r ssh_target name <<< "$entry"
  dir="$BACKUP_DIR/nodes/$name"
  mkdir -p "$dir"

  # k3s config
  scp "$ssh_target:/etc/rancher/k3s/config.yaml" "$dir/config.yaml" 2>/dev/null || true

  # iptables
  ssh "$ssh_target" "sudo iptables-save 2>/dev/null || cat /etc/iptables/rules.v4 2>/dev/null" > "$dir/iptables.txt" 2>/dev/null || true

  # CNI 설정
  ssh "$ssh_target" "sudo ls -la /etc/cni/net.d/ 2>/dev/null" > "$dir/cni-ls.txt" 2>/dev/null || true
  ssh "$ssh_target" "sudo cat /etc/cni/net.d/* 2>/dev/null" > "$dir/cni-config.txt" 2>/dev/null || true

  # eBPF 상태 (Cilium 전이므로 비어있어야 정상)
  ssh "$ssh_target" "sudo ls /sys/fs/bpf/tc/globals/ 2>/dev/null" > "$dir/bpf-maps.txt" 2>/dev/null || true

  # 네트워크 인터페이스
  ssh "$ssh_target" "ip addr show 2>/dev/null" > "$dir/ip-addr.txt" 2>/dev/null || true

  # 라우팅 테이블
  ssh "$ssh_target" "ip route show 2>/dev/null" > "$dir/ip-route.txt" 2>/dev/null || true

  echo "  $name: OK"
done

# ─── 3. kubectl 클러스터 상태 ───
echo "[3/7] 클러스터 리소스 상태 캡처..."
KUBE_DIR="$BACKUP_DIR/cluster"
mkdir -p "$KUBE_DIR"

kubectl --context "$CTX" get nodes -o wide > "$KUBE_DIR/nodes.txt" 2>&1
kubectl --context "$CTX" get nodes -o json > "$KUBE_DIR/nodes.json" 2>&1
kubectl --context "$CTX" get pods -A -o wide > "$KUBE_DIR/pods.txt" 2>&1
kubectl --context "$CTX" get svc -A > "$KUBE_DIR/services.txt" 2>&1
kubectl --context "$CTX" get ingress -A > "$KUBE_DIR/ingress.txt" 2>&1
kubectl --context "$CTX" get ds -A > "$KUBE_DIR/daemonsets.txt" 2>&1
kubectl --context "$CTX" get deploy -A > "$KUBE_DIR/deployments.txt" 2>&1
kubectl --context "$CTX" get networkpolicy -A > "$KUBE_DIR/networkpolicies.txt" 2>&1

# ─── 4. 노드 annotation/label (flannel 상태 포함) ───
echo "[4/7] 노드 annotation 캡처..."
kubectl --context "$CTX" get nodes -o json | \
  python3 -c "
import json, sys
data = json.load(sys.stdin)
for node in data['items']:
    name = node['metadata']['name']
    ann = node['metadata'].get('annotations', {})
    labels = node['metadata'].get('labels', {})
    print(f'=== {name} ===')
    print('annotations:')
    for k, v in sorted(ann.items()):
        print(f'  {k}: {v[:100]}')
    print('labels:')
    for k, v in sorted(labels.items()):
        print(f'  {k}: {v}')
    print()
" > "$KUBE_DIR/node-annotations.txt" 2>&1

# ─── 5. 서비스 엔드포인트 + LB IP ───
echo "[5/7] 서비스/엔드포인트 캡처..."
kubectl --context "$CTX" get svc -A -o json | \
  python3 -c "
import json, sys
data = json.load(sys.stdin)
for svc in data['items']:
    ns = svc['metadata']['namespace']
    name = svc['metadata']['name']
    stype = svc['spec'].get('type', 'ClusterIP')
    cip = svc['spec'].get('clusterIP', '')
    lb = svc.get('status', {}).get('loadBalancer', {}).get('ingress', [])
    lb_ips = ','.join(i.get('ip', '') for i in lb)
    print(f'{ns}/{name}\t{stype}\t{cip}\t{lb_ips}')
" > "$KUBE_DIR/service-details.txt" 2>&1

# ─── 6. Git 상태 ───
echo "[6/7] Git 상태 기록..."
cd "$(dirname "$0")/../.."
git rev-parse HEAD > "$BACKUP_DIR/git-head.txt"
git log --oneline -10 >> "$BACKUP_DIR/git-head.txt"
git diff --stat > "$BACKUP_DIR/git-diff-stat.txt" 2>/dev/null || true

# ─── 7. 요약 ───
echo "[7/7] 요약 생성..."
cat > "$BACKUP_DIR/SUMMARY.txt" <<SUMMARY
Cilium Migration Snapshot
=========================
Date: $(date -Iseconds)
Git commit: $(git rev-parse HEAD)
Nodes: $(kubectl --context "$CTX" get nodes --no-headers 2>/dev/null | wc -l)
Pods: $(kubectl --context "$CTX" get pods -A --no-headers 2>/dev/null | wc -l)
Services: $(kubectl --context "$CTX" get svc -A --no-headers 2>/dev/null | wc -l)
Ingress: $(kubectl --context "$CTX" get ingress -A --no-headers 2>/dev/null | wc -l)
NetworkPolicies: $(kubectl --context "$CTX" get networkpolicy -A --no-headers 2>/dev/null | wc -l)
DaemonSets: $(kubectl --context "$CTX" get ds -A --no-headers 2>/dev/null | wc -l)
etcd snapshot: $(ls "$BACKUP_DIR/etcd-snapshot" 2>/dev/null && echo "YES" || echo "NO")
SUMMARY

echo ""
echo "=== 스냅샷 완료 ==="
cat "$BACKUP_DIR/SUMMARY.txt"
echo ""
echo "Backup directory: $BACKUP_DIR"
echo ""
echo "다음 단계: Cilium 마이그레이션 후 복원 시"
echo "  ./cilium-migration-verify.sh $BACKUP_DIR"
