# Homelab GitOps and host management

Kubernetes 지속 상태는 Argo CD GitOps가 관리한다. Linux 호스트는 `system-manager`, macOS 호스트는 `nix-darwin`이 관리한다. 호스트·WireGuard 권위 데이터는 `nix/lib/topology.nix`이며 private key와 PSK는 Git/Nix store에 평문으로 넣지 않는다.

## Host catalog

```bash
nix run .#homelab-host -- inventory
```

현재 runtime topology:

- `wg0`: Linux 6대와 MacBook Pro(`10.222.0.7`)의 7-node full mesh, pairwise link 21개.
- `wg0` edge: rpi5를 통하는 `/32` 14개. 내부↔edge만 허용하고 모든 edge 간 lateral traffic은 차단한다.
- 전체 required link는 `wg0` 35개이며 immutable `linkId`로 식별한다.

## Secret model

암호문 위치는 `nix/secrets/`다. WireGuard bundle은 `nix/secrets/wireguard/hosts/<nodeId>.sops.yaml`이며 target host age recipient와 offline operator recovery recipient 둘 다 포함해야 한다. K3s role이 있는 host는 cluster의 canonical server token을 byte-exact base64로 같은 bundle에 보관한다. `nix/lib/topology.nix`의 `REPLACE_WITH_*` recipient는 배포를 막는 의도적 placeholder다.

```bash
# 대상 호스트에 age 설치 후 host-local identity/recipient 생성
nix run .#bootstrap-age-identity -- n2p1
# 기존 /etc/wireguard identity와 PSK가 topology와 일치하는지 읽기 전용 확인
nix run .#import-wireguard-host -- n2p1
# offline recovery recipient를 topology에 넣은 뒤에만 ciphertext 작성
nix run .#import-wireguard-host -- n2p1 --write
nix run .#gen-psk -- --link wg0-n2p1-n2p2 --check
nix run .#gen-psk -- --link wg0-n2p1-n2p2 --write
nix run .#rekey-secrets -- --recipient age1...
# agent import는 로컬 agent token을 신뢰하지 않는다. 기존 server에서 canonical token을 복사한다.
nix run .#copy-k3s-token -- --from rock5bp --to n2p1 --write
nix run .#copy-k3s-token -- --from rock5bp --to n2p1 --check
nix run .#stage-secrets -- n2p1
nix run .#rotate-psk -- --link wg0-n2p1-n2p2
```

`stage-secrets`의 복호화 workspace는 local tmpfs에만 만들고, 원격 `/run/homelab-secrets/generations/<id>`에 mode `0700`으로 staging한다. 검증 후 `active` symlink를 원자 교체하며 실패한 inactive generation은 제거한다. active/previous 두 세대만 보존한다. unmanaged edge PSK 회전은 전달 채널과 실제 적용 ACK가 없으면 실패한다.

## Linux four-stage migration

한 단계가 실패하면 다음 단계로 진행하지 않는다. `prepare`는 현재 K3s version, encrypted join token, legacy unit, WireGuard secret generation을 검증하고 backbone server의 etcd snapshot을 생성한다. `activate`는 legacy unit을 멈추기 전에 15분 rollback timer를 arm하고 server datastore를 cold backup한 뒤 Nix service로 전환한다. timer가 먼저 발화했거나 새 service 검증에 실패하면 성공 receipt를 쓰지 않고 legacy unit을 복원한다. installer unit과 `/usr/local/bin/k3s*` 제거는 reboot 검증 후 commit generation에서만 허용한다.

```bash
nix run .#adopt-host -- n2p1
nix run .#deploy -- n2p1          # prepare: baseline, secret stage, build/register
nix run .#homelab-host -- activate n2p1
# 운영자가 재부팅 후
nix run .#homelab-host -- reboot-verify n2p1
nix run .#homelab-host -- commit n2p1
```

권장 순서: `n2p1` → `n2p2` → `rpi4` → `rock5bp` → `macmini` → `rpi5`. rpi5는 wg0 edge gateway라 마지막이다. `deploy`는 K3s pin 변경을 감지하면 거부하고 `upgrade-k3s` 사용을 요구한다.
각 migration receipt는 `.host-state/recovery/<host>-<timestamp>`를 가리킨다. 여기에는 `/etc` launch/config backup, backbone server의 pre-cutover 또는 pre-upgrade etcd snapshot 기록과 datastore cold backup이 보관된다.

Rollback:

```bash
nix run .#homelab-host -- rollback n2p1 <system-manager-generation>
```

## macOS WireGuard

MacBook은 기존 private identity를 유지한 `10.222.0.7/24` 내부 노드다. 기존 비밀 config를 먼저 Git 제외 import 경로에 둔다.

```bash
install -d -m 0700 .host-state/import/bhyoo-macbook-pro
install -m 0600 /secure/source/wg0.conf .host-state/import/bhyoo-macbook-pro/wg0.conf
nix run .#render-macbook-wireguard
sudo install -d -m 0700 '/Library/Application Support/Homelab/WireGuard/generations'
# 검증된 generation을 복사하고 active symlink를 원자 교체한 뒤:
nix build .#darwinConfigurations.bhyoo-macbook-pro.system
sudo ./result/sw/bin/darwin-rebuild switch --flake .#bhyoo-macbook-pro
```

홈 LAN의 direct endpoints를 사용하는 profile이다. roaming profile이나 두 번째 identity는 만들지 않는다.

## K3s and Kubernetes bootstrap

기존 클러스터 상태 확인:

```bash
nix run .#homelab-host -- check-bootstrap
nix run .#verify-cluster -- backbone
```

신규 bootstrap 명령은 `ALLOW_NEW_CLUSTER_BOOTSTRAP=yes`가 없으면 기존 release를 소유하거나 생성하지 않는다.

```bash
ALLOW_NEW_CLUSTER_BOOTSTRAP=yes nix run .#bootstrap-k3s -- backbone
ALLOW_NEW_CLUSTER_BOOTSTRAP=yes nix run .#bootstrap-argocd -- backbone
nix run .#register-clusters -- prod
nix run .#issue-kubeconfig -- <identity>
```

신규 K3s node는 topology와 WireGuard ciphertext/PSK가 준비된 뒤 기존 healthy server의 join token을 대상 host bundle로 복사하고 일반 `prepare` 단계로 들어간다. 대상에 legacy K3s data directory나 active unit이 있으면 onboarding은 거부된다.

```bash
nix run .#onboard-k3s-node -- <new-node> --token-source rock5bp
nix run .#homelab-host -- activate <new-node>
```

`onboard-k3s-node`는 cluster를 새로 만들지 않는다. 기존 token과 선언된 `server`, role, labels, CNI 설정을 사용해 같은 cluster에 join한다.

Cilium chart pin은 `argocd/apps/cilium.yaml`의 `1.19.6`, Argo CD/argocd-apps pin은 `argocd/apps/argocd.yaml`의 `10.1.4`/`2.0.5`와 일치한다. AWS bootstrap credential 수명주기는 Terraform 소유이며 `sync-bootstrap-secret`만 stdout 노출 없이 SOPS copy를 갱신한다.

K3s pin 변경은 일반 deploy와 분리한다.

```bash
nix run .#upgrade-k3s -- backbone --to 1.36.2+k3s1
```

backbone server는 `rock5bp → rpi4 → rpi5`, 이후 worker `n2p1`, `n2p2` 순서다. 각 노드는 drain, activate, Ready 확인, uncordon을 거친다.

## Verification

```bash
nix flake check --all-systems --no-build
nix build .#checks.x86_64-linux.topology .#checks.x86_64-linux.migration-contracts --no-link
python nix/scripts/check-topology.py
python nix/scripts/check-migration.py
bash -n nix/scripts/homelab-host nix/scripts/k3s-handoff nix/scripts/wireguard-secrets
```

실호스트 activation과 재부팅 후 새 SSH session, WireGuard public key/peer/AllowedIPs/handshake, firewall INPUT/FORWARD policy와 Cilium chain 보존, K3s Ready/etcd와 iSCSI 경로를 검증한다. 기존 Ansible 경로는 모든 호스트의 cutover와 reboot 검증이 끝날 때까지 rollback 기준으로 유지하고, 최종 제거는 별도 변경으로 수행한다.
