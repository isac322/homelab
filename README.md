# Homelab GitOps and host management

Kubernetes desired state는 Argo CD가, Linux 호스트는 `system-manager`, macOS 호스트는 `nix-darwin`이 관리한다. 호스트와 WireGuard 권위 데이터는 `nix/lib/topology.nix`에 있으며 private key와 PSK는 Git/Nix store에 평문으로 저장하지 않는다.

## Active topology

```bash
nix run .#homelab-host -- inventory
```

- Linux: `n2p1`, `n2p2`, `rpi4`, `rpi5`, `rock5bp`, `macmini`
- macOS: `bhyoo-macbook-pro`
- `wg0`: 7-node full mesh 21개와 rpi5를 통하는 `/32` edge link 14개
- `wg1`: K3s backbone 5-node full mesh 10개
- 전체 required link: 45개. `linkId`는 immutable하다.
- MacBook이 한쪽 endpoint인 6개 link와 edge link는 `managed=false`다. 저장소가 양쪽 Linux bundle을 모두 소유하는 link만 PSK 생성·회전 대상이다.

## Secret model

WireGuard ciphertext는 `nix/secrets/wireguard/hosts/<nodeId>.sops.yaml`에 둔다. 각 bundle은 target host age recipient와 offline recovery recipient를 모두 포함한다. K3s node bundle에는 기존 cluster의 canonical server token을 byte-exact base64로 저장한다. `REPLACE_WITH_*` recipient는 배포를 의도적으로 막는 placeholder다.

```bash
nix run .#bootstrap-host -- n2p1
nix run .#bootstrap-age-identity -- n2p1
nix run .#import-wireguard-host -- n2p1
nix run .#import-wireguard-host -- n2p1 --write
nix run .#gen-psk -- --link wg0-n2p1-n2p2 --check
nix run .#gen-psk -- --link wg0-n2p1-n2p2 --write
nix run .#copy-k3s-token -- --from rock5bp --to n2p1 --write
nix run .#stage-secrets -- n2p1
nix run .#rotate-psk -- --link wg0-n2p1-n2p2
```

복호화 workspace와 machine-bound credential staging tree는 tmpfs에만 생성한다. 원격 host는 generation을 검증한 뒤 `systemd-creds encrypt --with-key=host`로 `/var/lib/homelab-secrets/generations/<generation>/*.cred`를 만들고 `active`/`previous` symlink를 원자 교체한다. systemd는 unit별 `LoadCredentialEncrypted=`로 `/run/credentials/<unit>/`에만 plaintext를 제공한다. Migration receipt는 Git revision과 secret generation을 함께 고정한다.

## Linux migration

일반 activation은 다음 네 단계다.

1. `prepare`: 필수 distro package reconciliation, iptables-nft backend preflight, baseline/recovery archive, secret staging, build/register, legacy K3s preflight
2. `activate`: 15분 rollback timer arm, server datastore cold backup, system-manager switch, host verification
3. `reboot-verify`: reboot 이후 새 SSH session과 runtime contract 재검증
4. `commit`: destructive cleanup이 포함된 commit generation 검증 후 legacy unit/binary/package 제거

```bash
nix run .#adopt-host -- n2p1
nix run .#deploy -- n2p1
nix run .#homelab-host -- activate n2p1
# 운영자가 재부팅
nix run .#homelab-host -- reboot-verify n2p1
nix run .#homelab-host -- commit n2p1
```

권장 순서: `n2p1` → `n2p2` → `rpi4` → `rock5bp` → `macmini` → `rpi5`. rpi5는 wg0 edge gateway이므로 마지막이다.

Rollback:

```bash
nix run .#homelab-host -- rollback n2p1 <system-manager-generation>
```

Recovery archive에는 hostname/hosts/resolver/network, passwd/group/shadow, 사용자 SSH key, systemd/WireGuard/K3s/sysctl/udev/modprobe/SSH/sudoers 설정, legacy K3s binaries, server etcd snapshot과 datastore cold backup을 보관한다.

## Service ownership

`system-manager`가 직접 관리할 수 있는 파일·사용자·tmpfs·mount·networkd·native loader 설정은 선언형 state로 둔다. Permanent custom unit은 장기 실행 daemon인 `homelab-k3s.service` 하나뿐이다.

- hostname, locale, timezone, hosts, resolver, SSH, sysctl, tmpfiles, zram-generator는 declarative file과 native generator가 소유한다.
- WireGuard는 networkd `.netdev`/`.network`와 encrypted systemd credentials를 사용한다. 첫 activation의 reload/reconfigure와 peer 검증은 migration command가 수행한다.
- Firewall은 distro-native `iptables.service`/`netfilter-persistent`가 Nix-rendered rules file을 boot에 적재한다. `iptables`, `iptables-save`, `iptables-restore`는 모두 `(nf_tables)`를 보고해야 하는 iptables-nft backend invariant다. Running host에서는 native loader를 restart하지 않고 migration command가 `iptables-restore --noflush`로 rules를 갱신한 뒤 기존 Cilium feeder chain 뒤에 HOMELAB jump를 재삽입한다. 실패 시 recovery archive의 runtime ruleset을 복구한다.
- Distro package 설치·삭제, native service enable/reload, legacy file 제거는 `prepare`/`activate`/`commit` migration command에서만 실행한다.
- iSCSI client는 K3s가 native `iscsid.service`와 `open-iscsi.service`를 직접 wants/after로 참조한다. sshd는 `/etc/ssh/authorized_keys.d/%u`를 직접 읽는다.

iptables frontend가 legacy backend를 보고하면 `prepare`, `activate`, `verify-host`, runtime capture/restore는 ruleset을 건드리기 전에 실패한다. Migration command는 `update-alternatives`를 실행하거나 backend를 자동 전환하지 않는다. x_tables와 nf_tables ruleset은 서로 보이지 않으므로 backend 전환은 이 migration의 범위가 아니다. 필요한 경우 두 backend를 각각 별도 보존하고 독립된 canary 절차로 전환해야 한다.

## macOS WireGuard

MacBook은 기존 private identity를 유지한 `10.222.0.7/24` 내부 노드다.

```bash
install -d -m 0700 .host-state/import/bhyoo-macbook-pro
install -m 0600 /secure/source/wg0.conf .host-state/import/bhyoo-macbook-pro/wg0.conf
nix run .#render-macbook-wireguard
nix build .#darwinConfigurations.bhyoo-macbook-pro.system
sudo ./result/sw/bin/darwin-rebuild switch --flake .#bhyoo-macbook-pro
```

## K3s and Kubernetes

```bash
nix run .#homelab-host -- check-bootstrap
nix run .#verify-cluster -- backbone
ALLOW_NEW_CLUSTER_BOOTSTRAP=yes nix run .#bootstrap-k3s -- backbone
ALLOW_NEW_CLUSTER_BOOTSTRAP=yes nix run .#bootstrap-argocd -- backbone
nix run .#issue-kubeconfig -- <identity>
```

새 node는 topology와 WireGuard ciphertext/PSK를 준비한 뒤 healthy server의 token을 복사하고 일반 migration 절차로 들어간다.

```bash
nix run .#onboard-k3s-node -- <new-node> --token-source rock5bp
nix run .#homelab-host -- activate <new-node>
```

K3s pin 변경은 일반 deploy와 분리한다.

```bash
nix run .#upgrade-k3s -- backbone --to 1.36.2+k3s1
```

Server 순서는 `rock5bp → rpi4 → rpi5`, 이후 agent `n2p1 → n2p2`다. 각 node는 drain, activate, Ready 확인, uncordon을 거친다.

`n2p1`, `n2p2`, `rpi4`, `rpi5`, `rock5bp`는 live iSCSI client dependency를 유지한다. `rock5bp`는 `democratic-csi` uid/gid 1001, `/etc/ssh/authorized_keys.d/democratic-csi`, NOPASSWD sudo와 targetcli를 추가로 유지한다.

### Graceful node shutdown

K3s node 5대는 priority별로 순차 종료한다. 일반 workload(priority 0)는 60초, ZFS CSI(priority 900000000 이상)는 45초, `system-cluster-critical`은 30초, `system-node-critical`은 45초다. 현재 일반 Pod의 표준 종료 예산은 최대 30초이고 ZFS 및 democratic-csi node Pod는 30초와 `preStop`/volume unmount 작업을 사용한다. 전체 kubelet 예산은 180초이며 logind `InhibitDelayMaxSec=195s`가 15초의 감지·해제 여유를 둔다.

CNPG의 1800초와 Prometheus의 600초 종료 예산은 일반 reboot에 그대로 반영하지 않는다. 이를 반영하면 모든 node의 machine-wide inhibitor가 30분 이상으로 늘어난다. 해당 workload가 있는 node의 계획 유지보수는 CNPG switchover와 `kubectl drain`으로 처리한다. `n2p1`, `n2p2`에서는 unattended-upgrades의 같은 이름 30초 drop-in을 `/dev/null`로 마스킹한다. `activate`는 logind를 먼저 재시작한 뒤 K3s를 재시작하며, `verify-host`는 merged logind 값, kubelet inhibitor, API의 active priority별 kubelet config를 확인한다.

구성 적용 후 일반 재부팅은 `systemctl reboot`를 사용한다. 이 경로는 kubelet의 정상 Pod 종료 기회를 제공하지만 PDB eviction, 대체 Pod의 Ready 완료, 단일 replica 무중단, local PV 이동을 보장하지 않는다. 먼저 `n2p1`, `n2p2`에서 검증하고 control-plane/etcd node는 quorum을 위해 항상 한 번에 하나씩 재부팅한다. `reboot -f`와 `systemctl reboot --force`는 사용하지 않는다.

## Verification

```bash
nix flake check --all-systems --no-build
nix build .#checks.x86_64-linux.topology .#checks.x86_64-linux.migration-contracts --no-link
python3 nix/scripts/check-topology.py
python3 nix/scripts/check-migration.py
bash -n nix/scripts/homelab-host nix/scripts/k3s-handoff nix/scripts/wireguard-secrets
```

실호스트에서는 새 SSH session, WireGuard public key/peer/AllowedIPs/handshake, firewall INPUT/FORWARD policy와 Cilium chain, K3s Ready/etcd, iSCSI path를 확인한다. 기존 Ansible host-management 경로는 모든 node cutover와 reboot 검증이 끝날 때까지 rollback 기준으로 유지한다.
