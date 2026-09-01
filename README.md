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

## Migration progress

2026-09-01 기준 Linux host migration 진행 상태:

- Nix 관리 완료: `n2p1`, `n2p2`, `rpi4`, `rock5bp`, `macmini`, `rpi5`
- Ansible host 관리 잔여: 없음
- `macmini` migration 완료(2026-08-31): revision `17d97f8e32142e876b82d7c8634fb212947bfafa`에서 bootstrap, host-local age identity와 encrypted WireGuard bundle import, native aarch64 generation build/register, `prepare -> activate -> reboot -> reboot-verify -> commit` terminal receipt를 완료했다. 재부팅 후 `verify-host`와 `verify-legacy-cleanup`이 통과했고 systemd-networkd/resolved/sshd, native `iptables.service`, `wg0` 주소·public key·peer set을 확인했다. K3s/NAS/iSCSI 비관리 경계는 유지되며 rollback timer와 current recovery artifact는 제거됐다. 따라서 `macmini`는 `[nix_managed]`에 속한다.
- `rpi5` migration 완료(2026-09-01): revision `778c4c5447c1a60417ad97b033a8569fbcd2e8ff`에서 K3s server와 `wg0` edge gateway를 guarded `prepare -> activate -> reboot -> reboot-verify -> commit` 순서로 전환했다. 첫 activation은 WireGuard persistent keepalive 검증 파서 오류를 감지했고 watchdog가 legacy K3s와 network 상태를 자동 복구했다. 파서를 수정한 뒤 재실행한 전체 sequence는 성공했다. 재부팅 후 `verify-host`와 `verify-legacy-cleanup`이 통과했고 backbone node와 workload가 Ready 상태임을 확인했다. Migration 전후 storage inventory도 12개 PV, 12개 PVC, 10개 consumer pod, 12개 attached VolumeAttachment, 5개 iSCSI session으로 동일했다. `wg0`는 20개 peer와 최근 handshake를 유지했고 rollback artifact와 timer는 commit 후 제거됐다. 따라서 `rpi5`는 `[nix_managed]`에 속하며 `[ansible_managed]`에는 host가 남아 있지 않다.
- `rock5bp`는 host plane만 Nix가 관리한다. `[nas]` 역할과 ZFS, LIO/rtslib/targetcli, Samba/NFS, storage cron/listener, `democratic-csi` identity/access, native NAS firewall은 기존 외부 관리 경계에 남긴다.
- `rock5bp` migration 전후 live 검증에서 NAS baseline, ZFS pool health, democratic-csi PV/PVC binding, VolumeAttachment, iSCSI session이 모두 일치했다. Production restore는 필요하지 않았고, 2026-08-31에 migration 전용 off-host ZFS stream backup 약 226 GiB와 `pre-nix-migration-20260827T091229Z` snapshot/hold를 제거했다. 삭제 후 보존된 manifest를 기준으로 별도 read-only completeness audit을 수행해 17개 zvol stream을 live PV/PVC 및 kubelet mount 또는 VolumeAttachment/iSCSI session에 일대일 대응했고, root stream의 17개 child dataset도 모두 확인했다(18/18 PASS). 삭제 경로와 receipt-pinned recovery/baseline/storage inventory 및 NAS evidence 경로의 disjointness도 검증했다.
- 각 host는 `prepare -> activate -> reboot -> reboot-verify -> commit`이 terminal receipt로 끝나고 live verification이 통과한 뒤에만 `[ansible_managed]`에서 `[nix_managed]`로 옮긴다.

## Linux migration

일반 activation은 다음 다섯 단계다. K3s version과 rolling upgrade는 기존 Rancher `system-upgrade-controller`, `server-plan`, `agent-plan`, `backbone-k3s-upgrade` Application이 계속 소유한다. Host migration 중에는 Plan version을 변경하거나 별도 rollout을 시작하지 않는다.

1. `prepare`: clean/pushed Git revision을 대상 Linux host가 native architecture로 build/register하고, 필수 distro package reconciliation, iptables-nft backend preflight, baseline/recovery archive, secret staging, legacy K3s preflight를 완료한다. macOS operator는 Linux generation을 로컬에서 build하지 않는다.
2. `activate`: runtime firewall snapshot과 recovery archive를 `/var/lib/homelab-host-rollback/current`에 복제하고 reboot 후에도 다시 시작되는 15분 rollback timer를 arm한 뒤, server datastore cold backup과 `prepare`가 등록한 정확한 system-manager generation activation을 수행한다. Armed 상태의 내부 runtime verification은 timer를 먼저 15분으로 rearm한 뒤 시작하며, 검증 완료 후 다음 operator 승인 대기 전에 다시 rearm한다.
3. `reboot`: 완료된 watchdog rollback을 local receipt에 먼저 동기화한 뒤 `activated` 또는 retry 가능한 `rebooting` phase를 확인한다. 그 다음 remote receipt/state/secret/store path/boot ID를 읽기 전에 timer를 15분으로 rearm한다. 최초 요청이면 현재 kernel boot ID를 receipt에 보존해 phase를 `rebooting`으로 기록한 뒤 non-blocking reboot를 요청한다. Watchdog rollback이 시작됐거나 완료돼 rearm이 실패하면 즉시 한 번 더 동기화해 completed rollback을 `rolled-back`으로 기록한다. Reboot 요청이 실패하고 boot ID가 그대로면 같은 `reboot` command가 다시 command-entry synchronization/rearm 후 요청을 재시도하며, boot ID가 이미 바뀌었으면 timer만 갱신된 상태로 재부팅하지 않고 `reboot-verify`를 요구한다.
4. `reboot-verify`: host가 다시 연결되면 완료된 watchdog rollback을 local receipt에 먼저 동기화하고 receipt가 `rebooting`인지 확인한 뒤, 다른 remote receipt/boot 검증보다 먼저 rollback timer를 15분으로 rearm한다. Rearm이 deadline과 경합해 실패하면 즉시 다시 동기화하고 검증을 중단한다. 그 뒤 remote receipt 조건과 pre-reboot boot ID를 검증하고 현재 boot ID가 달라졌는지 확인한다. 새 SSH session과 runtime contract 검증도 내부 armed verification entrypoint가 다시 rearm한 뒤 최대 12분 동안 수행하며, 성공한 경우에만 timer를 disarm한다. 검증 timeout/실패 시 timer를 armed 상태로 둔 채 즉시 restore를 시도하므로 SSH session이 끊겨도 persistent service가 복구를 계속할 수 있다. recovery archive/service는 `commit` 완료 전까지 유지한다.
5. `commit`: 대상 host가 commit generation을 native build/register한 뒤 persistent timer를 arm하고 destructive activation과 legacy systemd unit/drop-in/tuning wrapper/distro package 제거를 수행한다. 각 armed runtime verification은 시작 전에 timer를 다시 갱신한다. 검증된 terminal receipt를 local receipt directory에 먼저 stage한 뒤 최종 `accept`가 cleanup 전에 다시 rearm하며, `accept` 성공 후 atomic rename으로 receipt를 공개한다. Rancher upgrade가 사용하는 `/usr/local/bin/k3s` install layout은 유지하며, 전체 검증과 `accept`가 성공한 경우에만 rollback artifact와 timer를 삭제한다.

`rock5bp`의 NAS 표시는 이 host가 제공하는 device role을 설명하며, migration 전에 전체 pool을 별도로 backup해야 한다는 뜻이 아니다. `preserveNasState=true`는 ZFS pool/dataset/zvol과 data, target/iSCSI, Samba/NFS, 관련 configuration과 users, storage service ownership을 `system-manager` 전환 범위 밖에 둔다. 보존 정책을 평가하지 못하면 migration은 fail-closed한다.

`prepare`는 NAS baseline을 읽기 전용으로 기록한다. ZFS는 `zpool status -v`, `zpool get -H guid`, `zfs list -Hp -t filesystem,volume -o name,type,mountpoint,volsize` 결과를 기록한다. `zpool status -v`의 scrub/resilver `scan:` block은 진행률·속도·ETA가 바뀌므로 equality manifest에서 제외하지만 다음 labeled section부터 다시 기록해 pool state/status/action/see, remove/checkpoint, device topology, READ/WRITE/CKSUM error counters, 최종 `errors:` 결과는 유지한다. `volsize`는 zvol shrink를 검출하지만 live `used`/free capacity는 제외한다. `targetcli`는 one-shot 조회도 종료 시 auto-save할 수 있으므로 호출하지 않는다. Live target topology는 volatile session/statistics/ACL-info/action/control subtree를 제외한 `/sys/kernel/config/target` configfs path, metadata, readable value hash와 symlink target으로 캡처하고, persistent target state는 기존 `/etc/rtslib-fb-target/saveconfig.json`의 SHA-256 및 원문만 읽는다. Samba effective configuration은 `testparm -s`로 기록한다. 그 밖에 `democratic-csi` access, NFS/firewall/cron 파일의 hash와 stable stat(type/mode/uid/gid, regular-file size), storage service 상태, NAS listener를 `.host-state/baselines/rock5bp-nas-<timestamp>/`에 기록한다. Baseline, lifecycle gate, rollback verification은 `targetcli`, `targetcli saveconfig`, 또는 다른 NAS state writer를 실행하지 않는다.

configfs의 `iblock_N` 번호는 target service 재시작마다 같은 storage object에 다르게 배정될 수 있으므로 baseline 비교에서 object 이름으로 정규화한다. 이 번호만 반영하는 HBA/object info, default LU group members, LUN symlink hash는 runtime-index marker로 비교하지만, storage object/LUN path set, persistent `saveconfig.json`, target attribute, ZFS, service, listener, Samba/NFS와 다른 file hash는 그대로 exact-match한다.

`prepare`는 `preserveNasState=true`인 NAS host와 `iscsiClient=true`인 storage consumer host에서 democratic-csi PV/PVC/pod/VolumeAttachment와 consuming node의 정규화한 iSCSI session inventory를 recovery directory에 저장한다. 현재 active storage consumer pod가 `Running/Ready`가 아니면 host state를 변경하기 전에 fail-closed하며, 먼저 workload를 복구해야 한다. `storage-impact`와 lifecycle recovery checks는 Kubernetes resource, PV/PVC, VolumeAttachment, pod, iSCSI session을 관찰하기만 한다. Cluster resource를 scale, patch, restart하거나 다른 방식으로 변경하지 않는다. `activate`, `reboot-verify`, `commit`이 성공 상태를 기록하기 전에 같은 recovery checks를 자동으로 다시 실행하며, NAS 보존 경계나 recovery 상태를 읽기 전용으로 확인할 수 없으면 진행하지 않는다.

```bash
nix run .#adopt-host -- n2p1
nix run .#deploy -- n2p1
nix run .#homelab-host -- activate n2p1
nix run .#homelab-host -- reboot n2p1
nix run .#homelab-host -- reboot-verify n2p1
nix run .#homelab-host -- commit n2p1
nix run .#homelab-host -- verify-host n2p1
nix run .#homelab-host -- verify-legacy-cleanup n2p1
```

`rock5bp`도 one-step `reconcile` 대신 표준 guarded lifecycle을 사용한다. 먼저 host age identity와 live WireGuard/K3s identity를 host bundle로 import하고, 생성된 ciphertext를 서명한 commit으로 push한다. `reconcile-distro-packages`는 이 NAS host에서 read-only prerequisite check로 동작하므로 missing package가 있으면 host에서 명시적으로 설치한 뒤 다시 실행한다. `deploy`가 `prepare`를 실행하며, 다음 순서로 migration한다.

```bash
nix run .#bootstrap-age-identity -- rock5bp
nix run .#import-wireguard-host -- rock5bp
nix run .#import-wireguard-host -- rock5bp --write
# commit and push nix/secrets/wireguard/hosts/node-rock5bp.sops.yaml
nix run .#reconcile-distro-packages -- rock5bp
nix run .#adopt-host -- rock5bp
nix run .#homelab-host -- storage-impact rock5bp
nix run .#deploy -- rock5bp
nix run .#homelab-host -- activate rock5bp
nix run .#homelab-host -- reboot rock5bp
nix run .#homelab-host -- reboot-verify rock5bp
nix run .#homelab-host -- commit rock5bp
```

`storage-impact`는 변경 전에 Kubernetes/PV/PVC/VolumeAttachment와 storage session 영향을 읽기 전용으로 보여 준다. `activate`, `reboot-verify`, `commit`은 성공 상태를 기록하기 전에 자동 read-only recovery checks를 실행한다. 이 checks는 cluster workload나 storage resource를 변경하지 않으며, `preserveNasState` ownership boundary와 recovery 상태를 확인할 수 있을 때만 다음 phase를 기록한다.

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

Recovery artifact에는 전체 `/etc`, root/사용자 SSH state, cron spool, reconciliation 전 distro package 설치/미설치 inventory, runtime firewall, K3s install-script binary/helper files, legacy K3s unit, server etcd snapshot과 datastore cold backup을 보관한다. 자동 rollback은 새 K3s/zram을 정지하고 previous secret generation, 이전 system-manager generation 또는 deactivate, recovery archive, native network/SSH/time synchronization, legacy K3s, runtime firewall, migration이 제거한 distro package 재설치와 새로 설치한 package 제거, tuning/iSCSI 순서로 복구한다. `rock5bp`의 full archive는 forensic recovery용으로 그대로 보존하지만 자동 rollback extraction은 ZFS, rtslib/targetcli, Samba/NFS, `democratic-csi` identity/access, native firewall, cron을 제외하며 runtime firewall restore와 firewall loader enable도 건너뛴다. systemd에서 실행되는 rollback script는 `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin`을 명시적으로 사용한다. Cilium이 재생성하는 nft set을 참조하는 captured ruleset은 legacy K3s가 먼저 시작된 뒤 `iptables-restore --test` bounded retry를 통과할 때만 적용한다. Full snapshot 적용 뒤 node-local Cilium agent container 하나를 재시작해 BPF와 restored nft state를 맞추고 Cilium health가 돌아와야 rollback을 완료한다.
`rock5bp` rollback artifact에는 hash-verified manifest와 같은 read-only capture script도 복사한다. 수동 restore와 15분 watchdog rollback은 첫 host mutation 전에 이 baseline을 확인하고, 복구 뒤 timer를 해제하기 전에 다시 확인한다. Drift가 있으면 NAS나 host state를 더 변경하지 않고 recovery를 armed 상태로 남긴다.

이 recovery artifact는 host configuration과 rollback을 위한 것이며, `preserveNasState`가 제외한 ZFS dataset/zvol data를 복사하거나 소유하지 않는다.

## Service ownership

`system-manager`가 직접 관리할 수 있는 파일·사용자·tmpfs·mount·networkd·native loader 설정은 선언형 state로 둔다. Permanent declarative custom unit은 장기 실행 daemon인 `homelab-k3s.service` 하나뿐이며, 15분 rollback service/timer는 activation 동안 `/etc/systemd/system`에만 임시 설치된다. `homelab-k3s.service`는 system-manager의 30초 activation job 한도와 K3s server의 초기 readiness 시간을 분리하기 위해 `Type=exec`로 process supervision만 시작하고, migration command가 local K3s `/readyz`, Cilium feeder chain, etcd와 Kubernetes Node Ready를 별도 bounded verification한다.

- hostname, locale, timezone, hosts, resolver, SSH, sysctl, tmpfiles, zram-generator는 declarative file과 native generator가 소유한다. zram 크기는 topology의 nominal RAM이 아니라 boot 시점의 실제 usable RAM 절반(`ram / 2`)으로 계산해 기존 Ansible `ansible_memtotal_mb // 2` 계약과 kernel-reserved memory를 보존한다. Native `systemd-timesyncd`는 activation과 rollback에서 enable/restart한다. 최초 clock recovery가 DNSSEC/DoT와 현재 시각에 의존하지 않도록 `/etc/systemd/timesyncd.conf`에는 numeric NTP endpoints만 선언하며 compiled hostname fallback은 비운다. Activation과 verification은 `NTPSynchronized=yes`를 bounded retry로 확인한 뒤 K3s 전환을 진행한다. DNS는 live-proven `DNSSEC=yes`, `DNSOverTLS=yes`를 사용하고 LAN link에 DoT hostname, `MulticastDNS=yes`, `LLMNR=no`를 명시한다.
- WireGuard는 networkd `.netdev`/`.network`와 encrypted systemd credentials를 사용한다. 첫 activation의 reload/reconfigure와 peer 검증은 migration command가 수행한다.
- Firewall은 기본적으로 distro-native `iptables.service`/`netfilter-persistent`가 Nix-rendered rules file을 boot에 적재한다. `iptables`, `iptables-save`, `iptables-restore`는 모두 `(nf_tables)`를 보고해야 하는 iptables-nft backend invariant다. Running host에서는 native loader를 restart하지 않고 migration command가 `iptables-restore --noflush`로 rules를 갱신한 뒤 기존 Cilium feeder chain 뒤에 HOMELAB jump를 재삽입한다. Reboot 뒤 Cilium이 feeder chain을 다시 만든 경우에는 `homelab-k3s.service`의 bounded `ExecStartPost` reconciliation이 완료될 때까지 unit activation을 유지하고 같은 ordering을 복구한다. Reboot verification도 K3s service와 Cilium/HOMELAB ordering을 bounded retry로 기다린다. INPUT/FORWARD jump 이동은 새 jump를 먼저 삽입하고 이전 duplicate를 뒤에서부터 제거해 DROP policy 아래에서도 관리 SSH 경로가 한 순간도 사라지지 않게 한다. 실패 시 persistent recovery service가 archive의 runtime ruleset을 복구한다. 예외로 `rock5bp`는 `homelab.firewall.manageRules=false`다. `/etc/iptables/rules.v4`와 runtime chain은 외부 소유이며 Nix와 migration/rollback 명령은 loader를 enable/restart하거나 `iptables-restore`, policy 변경, HOMELAB jump 추가·삭제를 실행하지 않는다. Manifest는 native rules hash와 NAS port runtime rules/listener만 equality 검증한다.
- Distro package 설치·삭제, native service enable/reload, legacy file 제거는 `prepare`/`activate`/`commit` migration command에서만 실행한다. 비대화형 remote verification도 distro별 admin binary 탐색이 login PATH에 의존하지 않도록 `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin`을 명시한다. `rock5bp`에서는 package reconciliation과 rollback package restore가 read-only이며 missing generic prerequisite가 있으면 외부에서 먼저 설치하도록 실패한다.
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

`n2p1`, `n2p2`, `rpi4`, `rpi5`, `rock5bp`는 live iSCSI client dependency를 유지한다. `rock5bp`의 NAS plane은 계속 외부 소유다. Nix는 ZFS pool/dataset/zvol, rtslib/targetcli, Samba/NFS, storage cron, `democratic-csi` uid/gid 1001 identity, `/home/democratic-csi/.ssh/authorized_keys`, `/etc/sudoers.d/democratic-csi`, native firewall file/runtime chain을 선언하거나 쓰지 않는다. Commit generation의 sshd는 기존 home key lookup과 managed admin-key lookup을 함께 유지한다.

## Ansible ownership boundary

Legacy host-management playbook은 `[ansible_managed]`만 target으로 삼는다. Commit까지
끝난 호스트는 `[nix_managed]`로 옮기며, 현재 `n2p1`, `n2p2`, `rpi4`, `rock5bp`, `macmini`가 여기에 속한다.
두 ownership group은 `homelab`의 child로 남고 `backbone` 같은 topology group도
유지하지만, Nix-managed host에는 Ansible SSH 연결이나 remote task를 실행하지 않는다.

`etc-hosts`는 모든 Ansible-managed host가 포함된 실행만 허용하고 `--limit`을
거부한다. Managed host 하나라도 fact gathering에 실패하면 어떤 `/etc/hosts`도
쓰기 전에 전체 play를 중단한다. Nix-managed host entry는 연결이나 facts 없이
inventory의 `[nix_managed]`와 `ansible_host`에서 `hosts_dns_hostname`으로 정적으로
추가한다. Legacy WireGuard playbook은 Nix의 encrypted identity와 PSK를 읽을 수
없으므로 fact gathering이나 remote mutation 전에 전체 play를 fail closed한다.
Peer 변경은 `nix run .#rollout-peers -- <host>`로 수행한다. K3s binary/version
rollout은 계속 Rancher `system-upgrade-controller`가 소유한다.

## Verification

```bash
nix flake check --all-systems --no-build
nix build .#checks.x86_64-linux.topology .#checks.x86_64-linux.migration-contracts --no-link
python3 nix/scripts/check-topology.py
python3 nix/scripts/check-migration.py
bash -n nix/scripts/adopt-host nix/scripts/decommission-host nix/scripts/homelab-host nix/scripts/k3s-handoff nix/scripts/provision-host nix/scripts/render-macbook-wireguard nix/scripts/rollout-peers nix/scripts/wireguard-secrets
```

실호스트에서는 새 SSH session, effective sshd config, synchronized system clock, WireGuard public key/peer/AllowedIPs/handshake, firewall INPUT/FORWARD policy와 Cilium/Samba/NetBIOS rules, K3s version/Ready/etcd, iSCSI path, persistent rollback timer 상태를 확인한다. 기존 Ansible 코드는 전체 topology를 inventory input으로 유지하되, `[nix_managed]` 호스트에는 remote task를 실행하지 않는다.
