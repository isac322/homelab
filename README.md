# Homelab GitOps and host management

Kubernetes desired state는 Argo CD가, Linux 호스트는 `system-manager`, macOS 호스트는 `nix-darwin`이 관리한다. 호스트와 WireGuard 권위 데이터는 `nix/lib/topology.nix`에 있으며 private key와 PSK는 Git/Nix store에 평문으로 저장하지 않는다.

## Active topology

```bash
nix run .#homelab-host -- inventory
```

- Linux: `n2p1`, `n2p2`, `rpi4`, `rpi5`, `rock5bp`, `macmini`
- macOS: `bhyoo-macbook-pro`
- `wg0`: 7-node full mesh 21개와 rpi5를 통하는 `/32` edge link 14개
- 전체 required link: 35개. `linkId`는 immutable하다.
- MacBook이 한쪽 endpoint인 6개 link와 edge link는 `managed=false`다. 저장소가 양쪽 Linux bundle을 모두 소유하는 link만 PSK 생성·회전 대상이다.

## Secret model

WireGuard ciphertext는 `nix/secrets/wireguard/hosts/<nodeId>.sops.yaml`에 둔다. 각 bundle은 세 recipient로 암호화한다: 해당 node의 host-local age identity, 일상적인 SOPS 작업에 사용하는 online operator identity, 비상 복구에만 쓰는 offline recovery identity. host identity는 node마다 하나씩 만들고, operator/recovery identity는 전체 host bundle에 공통으로 사용한다. K3s node bundle에는 기존 cluster의 canonical server token을 byte-exact base64로 저장한다. recipient의 `REPLACE_WITH_*` 값은 배포를 의도적으로 막는 placeholder다.
이 저장소의 secret app은 `SOPS_AGE_KEY_FILE`이 없으면 `${XDG_CONFIG_HOME:-$HOME/.config}/sops/age/keys.txt`를 online operator identity 경로로 사용한다. 다른 위치를 쓰려면 `HOMELAB_OPERATOR_AGE_KEY_FILE` 또는 `SOPS_AGE_KEY_FILE`을 명시한다.

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
`bootstrap-host`는 기존 SSH identity로 접속하며, 비-root host에서는 현재 sudo 암호를 TTY로 한 번 요구해 `/etc/sudoers.d/homelab-admin`을 검증·설치한다. 이후 migration command는 `sudo -n`만 사용하고 암호 prompt가 발생하면 실패한다.
복호화 workspace와 machine-bound credential staging tree는 Linux에서는 runtime tmpfs를 우선 사용하고, `/dev/shm`이 없는 macOS에서는 권한이 제한된 `${TMPDIR:-/tmp}` workspace를 사용한 뒤 trap으로 즉시 제거한다. 원격 host는 generation을 검증한 뒤 `systemd-creds encrypt --with-key=host`로 `/var/lib/homelab-secrets/generations/<generation>/*.cred`를 만들고 `active`/`previous` symlink를 원자 교체한다. systemd는 unit별 `LoadCredentialEncrypted=`로 `/run/credentials/<unit>/`에만 plaintext를 제공한다. Migration receipt는 Git revision, secret generation, 등록된 system-manager store path를 함께 고정한다.

## Linux migration

일반 activation은 다음 다섯 단계다. K3s version과 rolling upgrade는 기존 Rancher `system-upgrade-controller`, `server-plan`, `agent-plan`, `backbone-k3s-upgrade` Application이 계속 소유한다. Host migration 중에는 Plan version을 변경하거나 별도 rollout을 시작하지 않는다.

1. `prepare`: clean/pushed Git revision을 대상 Linux host가 native architecture로 build/register하고, 필수 distro package reconciliation, iptables-nft backend preflight, baseline/recovery archive, secret staging, legacy K3s preflight를 완료한다. macOS operator는 Linux generation을 로컬에서 build하지 않는다.
2. `activate`: runtime firewall snapshot과 recovery archive를 `/var/lib/homelab-host-rollback/current`에 복제하고 reboot 후에도 다시 시작되는 15분 rollback timer를 arm한 뒤, server datastore cold backup과 `prepare`가 등록한 정확한 system-manager generation activation을 수행한다. Armed 상태의 내부 runtime verification은 timer를 먼저 15분으로 rearm한 뒤 시작하며, 검증 완료 후 다음 operator 승인 대기 전에 다시 rearm한다.
3. `reboot`: 완료된 watchdog rollback을 local receipt에 먼저 동기화한 뒤 `activated` 또는 retry 가능한 `rebooting` phase를 확인한다. 그 다음 remote receipt/state/secret/store path/boot ID를 읽기 전에 timer를 15분으로 rearm한다. 최초 요청이면 현재 kernel boot ID를 receipt에 보존해 phase를 `rebooting`으로 기록한 뒤 non-blocking reboot를 요청한다. Watchdog rollback이 시작됐거나 완료돼 rearm이 실패하면 즉시 한 번 더 동기화해 completed rollback을 `rolled-back`으로 기록한다. Reboot 요청이 실패하고 boot ID가 그대로면 같은 `reboot` command가 다시 command-entry synchronization/rearm 후 요청을 재시도하며, boot ID가 이미 바뀌었으면 timer만 갱신된 상태로 재부팅하지 않고 `reboot-verify`를 요구한다.
4. `reboot-verify`: host가 다시 연결되면 완료된 watchdog rollback을 local receipt에 먼저 동기화하고 receipt가 `rebooting`인지 확인한 뒤, 다른 remote receipt/boot 검증보다 먼저 rollback timer를 15분으로 rearm한다. Rearm이 deadline과 경합해 실패하면 즉시 다시 동기화하고 검증을 중단한다. 그 뒤 remote receipt 조건과 pre-reboot boot ID를 검증하고 현재 boot ID가 달라졌는지 확인한다. 새 SSH session과 runtime contract 검증도 내부 armed verification entrypoint가 다시 rearm한 뒤 최대 12분 동안 수행하며, 성공한 경우에만 timer를 disarm한다. 검증 timeout/실패 시 timer를 armed 상태로 둔 채 즉시 restore를 시도하므로 SSH session이 끊겨도 persistent service가 복구를 계속할 수 있다. recovery archive/service는 `commit` 완료 전까지 유지한다.
5. `commit`: 대상 host가 commit generation을 native build/register한 뒤 persistent timer를 arm하고 destructive activation과 legacy systemd unit/drop-in/tuning wrapper/distro package 제거를 수행한다. 각 armed runtime verification은 시작 전에 timer를 다시 갱신하고, 최종 `accept`도 cleanup 전에 먼저 rearm하여 rollback이 이미 시작되거나 완료된 상태에서 artifact를 삭제하지 않는다. Rancher upgrade가 사용하는 `/usr/local/bin/k3s` install layout은 유지하며, 전체 검증과 `accept`가 성공한 경우에만 rollback artifact와 timer를 삭제한다.

```bash
nix run .#adopt-host -- n2p1
nix run .#deploy -- n2p1
nix run .#homelab-host -- activate n2p1
nix run .#homelab-host -- reboot n2p1
nix run .#homelab-host -- reboot-verify n2p1
nix run .#homelab-host -- commit n2p1
```

권장 순서: `n2p1` → `n2p2` → `rpi4` → `rock5bp` → `macmini` → `rpi5`. rpi5는 wg0 edge gateway이므로 마지막이다.

Rollback:

```bash
# activate 이후 commit 전: persistent full-host recovery
nix run .#homelab-host -- restore-host n2p1

# commit 이후: 이전 system-manager generation으로 전환
nix run .#homelab-host -- rollback n2p1 <system-manager-generation>
```

`restore-host`는 activation이 timer를 arm한 뒤 receipt 기록 전에 중단된 `prepared` 상태와 `activated`, `rebooting`, `reboot-verified` 상태를 모두 복구할 수 있다. Watchdog가 먼저 완료된 경우 다음 phase-gated command는 `restored` marker를 확인하고 `prepared` receipt를 포함한 local receipt를 먼저 `rolled-back`으로 동기화한 뒤 `cleanup-restored`로 rollback service/artifact cleanup을 시도한다. Remote recovery가 없는 `prepared` receipt는 정상적인 prepare 재실행 상태이므로 그대로 유지한다. `accept`는 아직 armed이고 rollback service가 inactive인 recovery만 대상으로 하며 command entry에서 먼저 rearm한다. Cleanup이 실패해도 `rolled-back` receipt와 recovery artifact를 유지해 다음 phase-gated command가 cleanup을 재시도한다. Restore가 진행 중이거나 실패한 상태는 완료로 기록하지 않으며 artifact와 timer를 보존한다.

`reboot`와 `reboot-verify`는 command entry에서 완료된 watchdog rollback을 먼저 local receipt에 동기화하고, `rearm` 실패 직후에도 다시 동기화한다. Deadline과 `rearm`이 경합해 rollback이 완료된 경우 receipt는 `rolled-back`으로 남으며 stale `rebooting` 상태를 유지하지 않는다.

Recovery artifact에는 전체 `/etc`, root/사용자 SSH state, cron spool, purge 전 distro package inventory, runtime firewall, K3s install-script binary/helper files, legacy K3s unit, server etcd snapshot과 datastore cold backup을 보관한다. 자동 rollback은 새 K3s/zram을 정지하고 previous secret generation, 이전 system-manager generation 또는 deactivate, recovery archive, native network/SSH/time synchronization, legacy K3s, runtime firewall, 제거된 distro package와 tuning/iSCSI 순서로 복구한다. systemd에서 실행되는 rollback script는 `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin`을 명시적으로 사용한다. Cilium이 재생성하는 nft set을 참조하는 captured ruleset은 legacy K3s가 먼저 시작된 뒤 `iptables-restore --test` bounded retry를 통과할 때만 적용한다. Full snapshot 적용 뒤 node-local CRI로 `cilium-agent` container를 restart하고 새 container ID와 `127.0.0.1:9879/healthz`를 확인해 initial full reconciliation을 강제한다. NTP가 일시적으로 unavailable이면 package 복구만 보류하고 legacy K3s를 먼저 복구한 채 rollback timer를 유지한다. Restore는 한 번 재시도하며, 완료된 secret/system-manager/archive/firewall stage marker를 재사용해 destructive prefix와 Cilium restart를 반복하지 않는다. 두 번 모두 실패하면 `accept`를 실행하거나 recovery artifact와 `rollback.log`를 삭제하지 않는다. `status`는 rollback log와 service journal을 함께 출력한다. 복구가 끝날 때까지 timer는 enabled 상태로 남아 실패 후 reboot에서 다시 시도할 수 있다.

## Service ownership

`system-manager`가 직접 관리할 수 있는 파일·사용자·tmpfs·mount·networkd·native loader 설정은 선언형 state로 둔다. Permanent declarative custom unit은 장기 실행 daemon인 `homelab-k3s.service` 하나뿐이며, 15분 rollback service/timer는 activation 동안 `/etc/systemd/system`에만 임시 설치된다.

- hostname, locale, timezone, hosts, resolver, SSH, sysctl, tmpfiles, zram-generator는 declarative file과 native generator가 소유한다. Native `systemd-timesyncd`는 activation과 rollback에서 enable/restart한다. 최초 clock recovery가 DNSSEC/DoT와 현재 시각에 의존하지 않도록 `/etc/systemd/timesyncd.conf`에는 numeric NTP endpoints만 선언하며 compiled hostname fallback은 비운다. Activation과 verification은 `NTPSynchronized=yes`를 bounded retry로 확인한 뒤 K3s 전환을 진행한다. DNS는 live-proven `DNSSEC=yes`, `DNSOverTLS=yes`를 사용하고 LAN link에 DoT hostname, `MulticastDNS=yes`, `LLMNR=no`를 명시한다.
- WireGuard는 networkd `.netdev`/`.network`와 encrypted systemd credentials를 사용한다. 첫 activation의 reload/reconfigure와 peer 검증은 migration command가 수행한다.
- Firewall은 distro-native `iptables.service`/`netfilter-persistent`가 Nix-rendered rules file을 boot에 적재한다. `iptables`, `iptables-save`, `iptables-restore`는 모두 `(nf_tables)`를 보고해야 하는 iptables-nft backend invariant다. Running host에서는 native loader를 restart하지 않고 migration command가 `iptables-restore --noflush`로 rules를 갱신한 뒤 기존 Cilium feeder chain 뒤에 HOMELAB jump를 재삽입한다. 실패 시 persistent recovery service가 archive의 runtime ruleset을 복구한다. rock5bp의 active Samba client `192.168.219.139/32` TCP/445와 LAN NetBIOS UDP/137-138도 선언적으로 유지한다.
- Distro package 설치·삭제, native service enable/reload, legacy file 제거는 `prepare`/`activate`/`commit` migration command에서만 실행한다.
- iSCSI client는 K3s가 native `iscsid.service`와 `open-iscsi.service`를 직접 wants/after로 참조한다. sshd는 legacy main config가 drop-in을 include하지 않는 host도 있으므로 `/etc/ssh/sshd_config` 전체를 Nix가 소유하고 `/etc/ssh/authorized_keys.d/%u`를 실제 effective config에서 읽는지 검증한다. OpenSSH `StrictModes`가 absolute managed-key path를 거부하지 않도록 systemd-tmpfiles가 SSH reload 전에 `/etc`, `/etc/ssh`, `/etc/ssh/authorized_keys.d`를 모두 `root:root 0755`로 수렴시키며, migration command는 이 ancestor invariant와 managed admin key 존재를 확인한다. 비-root migration SSH 사용자의 NOPASSWD grant도 `/etc/sudoers.d/homelab-admin`으로 선언한다.

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

새 node 추가는 먼저 `nix/lib/topology.nix`에 `lifecycle = "provisioning"`과 LAN/WireGuard/K3s desired state를 선언하고, `nix/identities/wireguard/<node>.pub` 및 host SOPS bundle을 같은 변경으로 준비한다. 그 뒤 healthy server의 live K3s version을 읽어 standard install layout만 설치하고 service는 시작하지 않은 채 bootstrap, age credential staging, token copy, 일반 migration 절차를 원자적으로 준비한다.

```bash
nix run .#provision-host -- <new-node> --token-source rock5bp
nix run .#homelab-host -- activate <new-node>
nix run .#homelab-host -- reboot <new-node>
nix run .#homelab-host -- reboot-verify <new-node>
nix run .#homelab-host -- commit <new-node>
```

`provision-host`는 topology와 ciphertext가 준비되지 않았으면 실패하며, K3s state가 이미 있거나 service가 실행 중인 대상에는 설치하지 않는다.

노드 삭제는 먼저 topology의 lifecycle을 `decommissioning`으로 바꾼 별도 커밋에서 시작한다. 다음 명령은 active Linux peers만 새 generation으로 전환하고, K3s drain/delete와 물리 호스트 삭제는 자동화하지 않는다.

```bash
nix run .#decommission-host -- <old-node>
```

변경된 노드의 WireGuard peer만 갱신할 때는 `nix run .#rollout-peers -- <host>`를 사용한다. `onboard-k3s-node`는 이미 standard install layout이 있고 K3s state/service가 없는 대상에 대한 낮은 수준의 준비 명령으로 유지한다.

K3s version과 순차 rollout은 기존 Rancher `system-upgrade-controller`가 단독 소유한다. Nix topology는 K3s version을 선언하거나 binary를 Nix store에 고정하지 않는다. `homelab-k3s.service`는 install-script layout의 `/usr/local/bin/k3s`를 `exec`하고 `Restart=always`로 실행하므로, Rancher `k3s-upgrade`가 binary를 교체하고 기존 process를 종료하면 systemd가 동일 unit을 새 binary로 다시 시작한다. 기존 `k3s.service`/`k3s-agent.service` unit은 cutover 후 제거하지만 `/usr/local/bin/k3s`와 install helper는 유지한다.

`n2p1`, `n2p2`, `rpi4`, `rpi5`, `rock5bp`는 live iSCSI client dependency를 유지한다. `rock5bp`는 `democratic-csi` uid/gid 1001, `/etc/ssh/authorized_keys.d/democratic-csi`, NOPASSWD sudo와 targetcli를 추가로 유지한다.

## Ansible ownership boundary

`cluster-setup/inventory/hosts`의 `[ansible_managed]`만 legacy Ansible
host-management playbook의 대상이다. Commit까지 끝난 호스트는
`[nix_managed]`로 옮기며, 현재 `n2p1`과 `n2p2`가 여기에 속한다. 이 호스트들의
`backbone` membership은 topology 참조를 위해 유지하지만 Ansible은 접속하거나
변경하지 않는다.

부분 전환 이후 legacy WireGuard playbook은 Nix의 encrypted identity와 PSK를
읽을 수 없으므로 fail closed한다. Peer 변경은
`nix run .#rollout-peers -- <host>`로 수행한다. K3s binary/version rollout은 계속
Rancher `system-upgrade-controller`가 소유한다.

## Verification

```bash
nix flake check --all-systems --no-build
nix build .#checks.x86_64-linux.topology .#checks.x86_64-linux.migration-contracts --no-link
python3 nix/scripts/check-topology.py
python3 nix/scripts/check-migration.py
bash -n nix/scripts/adopt-host nix/scripts/decommission-host nix/scripts/homelab-host nix/scripts/k3s-handoff nix/scripts/provision-host nix/scripts/render-macbook-wireguard nix/scripts/rollout-peers nix/scripts/wireguard-secrets
```

실호스트에서는 새 SSH session, effective sshd config, synchronized system clock, WireGuard public key/peer/AllowedIPs/handshake, firewall INPUT/FORWARD policy와 Cilium/Samba/NetBIOS rules, K3s version/Ready/etcd, iSCSI path, persistent rollback timer 상태를 확인한다. 기존 Ansible 코드는 전환하지 않은 `[ansible_managed]` 호스트와 rollback 기준을 위해 유지하며, `[nix_managed]` 호스트에는 실행하지 않는다.
