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

2026-09-02 기준 Linux host migration 진행 상태:

- Nix 관리 완료: `n2p1`, `n2p2`, `rpi4`, `rock5bp`, `macmini`, `rpi5`
- Ansible host 관리 잔여: 없음
- `macmini` host migration 완료(2026-08-31): revision `17d97f8e32142e876b82d7c8634fb212947bfafa`에서 bootstrap, host-local age identity와 encrypted WireGuard bundle import, native aarch64 generation build/register, `prepare -> activate -> reboot -> reboot-verify -> commit` terminal receipt를 완료해 `[nix_managed]`로 전환했다. 이어 2026-09-02 revision `92e2ea352760b41854cde46e92c66d501b06b2e9`에서 K3s agent 역할과 encrypted join token을 Nix desired state에 추가하고 동일한 guarded sequence로 재배포했다. 첫 activation의 DNS-over-TLS 검증 불일치와 신규 worker rollback의 stale Cilium state 문제는 watchdog rollback으로 안전하게 복구한 뒤 계약과 구현을 수정해 재검증했다. 최종 commit 후 `macmini` node는 K3s `v1.36.3+k3s1` Ready 상태이며 Cilium, Cilium Envoy, democratic-csi iSCSI node plugin, shared node exporter workload가 정상 실행 중이다. systemd-networkd/resolved/sshd, native `iptables.service`, `homelab-k3s.service`, `wg0` 6개 peer도 검증했고 rollback timer는 disarm했다. 따라서 host plane과 K3s agent service는 Nix가 소유하며 Kubernetes workload와 CNI lifecycle은 기존 cluster controller가 소유한다.
- `rpi5` migration 완료(2026-09-01): revision `778c4c5447c1a60417ad97b033a8569fbcd2e8ff`에서 K3s server와 `wg0` edge gateway를 guarded `prepare -> activate -> reboot -> reboot-verify -> commit` 순서로 전환했다. 첫 activation은 WireGuard persistent keepalive 검증 파서 오류를 감지했고 watchdog가 legacy K3s와 network 상태를 자동 복구했다. 파서를 수정한 뒤 재실행한 전체 sequence는 성공했다. 재부팅 후 `verify-host`와 `verify-legacy-cleanup`이 통과했고 backbone node와 workload가 Ready 상태임을 확인했다. Migration 전후 storage inventory도 12개 PV, 12개 PVC, 10개 consumer pod, 12개 attached VolumeAttachment, 5개 iSCSI session으로 동일했다. `wg0`는 20개 peer와 최근 handshake를 유지했고 rollback artifact와 timer는 commit 후 제거됐다. 따라서 `rpi5`는 `[nix_managed]`에 속하며 `[ansible_managed]`에는 host가 남아 있지 않다.
- `rock5bp`는 host plane만 Nix가 관리한다. `[nas]` 역할과 ZFS, LIO/rtslib/targetcli, Samba/NFS, storage cron/listener, `democratic-csi` identity/access, native NAS firewall은 기존 외부 관리 경계에 남긴다.
- `rock5bp` migration 전후 live 검증에서 NAS baseline, ZFS pool health, democratic-csi PV/PVC binding, VolumeAttachment, iSCSI session이 모두 일치했다. Production restore는 필요하지 않았고, 2026-08-31에 migration 전용 off-host ZFS stream backup 약 226 GiB와 `pre-nix-migration-20260827T091229Z` snapshot/hold를 제거했다. 삭제 후 보존된 manifest를 기준으로 별도 read-only completeness audit을 수행해 17개 zvol stream을 live PV/PVC 및 kubelet mount 또는 VolumeAttachment/iSCSI session에 일대일 대응했고, root stream의 17개 child dataset도 모두 확인했다(18/18 PASS). 삭제 경로와 receipt-pinned recovery/baseline/storage inventory 및 NAS evidence 경로의 disjointness도 검증했다.
- 각 host는 `prepare -> activate -> reboot -> reboot-verify -> commit`이 terminal receipt로 끝나고 live verification이 통과한 뒤에만 `[ansible_managed]`에서 `[nix_managed]`로 옮긴다.

## Linux package ownership

Linux 호스트의 전역 패키지는 한 관리자가 소유한다. 커널·DKMS·systemd/udev/initramfs 통합, bootstrap·복구, 호스트 네트워크·스토리지 도구는 apt 또는 pacman이 관리한다. 현재 공통 OS 패키지는 `curl`, `vim`, `wireguard-tools`, `nvme-cli`, `iptables`다. 배포판과 독립적인 사용자 공간 도구인 `age`, `htop`, `jq`, `kubectl`, Helm, `sops`는 Nix `environment.systemPackages`가 관리한다.
`bootstrap-host`는 Nix `age-keygen`이 아직 없을 때만 OS `age`를 임시 설치한다. 일반 호스트는 commit 단계에서 이 bootstrap 패키지를 제거한다. `preserveNasState=true`인 `rock5bp`는 package reconciliation이 읽기 전용이므로, Nix generation 활성화 후 OS `age`를 별도 유지보수로 제거한다.

Nix와 distro 전역 패키지 목록에 같은 이름을 선언하면 module evaluation이 실패한다. Nix app이나 systemd service의 `runtimeInputs`는 해당 프로그램의 `/nix/store` closure에만 고정되므로 전역 소유권 중복으로 보지 않는다. `rock5bp`의 `preserveNasState=true` 계약에서는 distro package reconciliation이 계속 읽기 전용이다.

### NVMe/TCP DKMS

vendor 커널에 없는 NVMe/TCP 모듈(`rpi4`, `rpi5`, `macmini`는 `nvme-fabrics`/`nvme-tcp`, `rock5bp`는 `nvmet-tcp`)은 Nix가 node별로 만든 DKMS 패키지로 설치한다. 선언은 `nix/lib/nvme-tcp-dkms.json`에 있다. 패키지는 같은 stable series(`baseline`의 major.minor) 커널이면 자동으로 DKMS 빌드되며, 빌드 직후 `nvme-tcp-abi-check`가 패키지의 private NVMe 헤더가 대상 커널과 ABI가 같은지 확인하고 다르면 빌드를 실패시킨다(MODVERSIONS 커널은 export 심볼 CRC 비교, CRC가 없는 커널(macmini)은 vmlinux BTF와 struct/enum 비교). 확인할 수 없거나 series가 바뀌면 실패하므로 `select`/`install`로 갱신한다. 공유 헤더는 node 커널의 upstream release(`baseline`)에서, transport 소스(`tcp.c`, `fabrics.c`)만 같은 stable series에서 node 커널과 컴파일·링크되는 가장 새 release(`transport`)에서 가져온다. node에서 DKMS가 빌드할 때 네트워크를 쓰지 않는다.

```bash
nix run .#nvme-tcp-dkms -- select rpi5   # node에서 후보를 scratch 빌드하고 선언을 갱신, 결과를 commit
nix run .#nvme-tcp-dkms -- install rpi5  # Nix로 deb/pkg.tar.zst를 빌드해 apt/pacman으로 설치
```

`reconcile-distro-packages`는 선언된 일반 host에 이 패키지를 설치하고, `rock5bp`에서는 설치하지 않으므로 `install`을 명시적으로 실행한다. `install`은 배포판 hook이 빠뜨린 커널(Debian은 실행 중·최신 커널만 빌드)까지 headers가 설치된 모든 커널에 DKMS 빌드를 수행한다. NVMe core(`CONFIG_NVME_CORE`, target은 `CONFIG_NVME_TARGET`)가 없는 커널(예: `rock5bp`의 vendor 6.1.84-8 rescue 커널)은 `BUILD_EXCLUSIVE_CONFIG`로 제외한다. 설치한 모듈은 재부팅하거나 모듈을 다시 load해야 적용된다. 실행 중인 커널의 series가 다르거나 headers가 설치된 커널(NVMe core가 없는 커널 제외) 중 하나라도 installed module이 없으면 pre-activation assertion이 다음 generation을 막으므로 `select`로 선언을 갱신하고 `install`한다.

선택 필드 `patches`는 `nix/pkgs/nvme-tcp-dkms-patches/<name>.patch`의 local backport를 나열한다(없으면 빈 목록). 패키지 빌드 때 transport 소스 위에 순서대로 적용하며, patch가 하나라도 적용되지 않으면 Nix 빌드가 실패한다. patch가 있으면 DKMS `version`에 patch 내용 hash인 `+p<hash>` 표시가 붙으므로(예: `6.1.186+6.1.84+p1a2b3c4d`) patch 집합이 바뀌면 source tree 버전도 바뀐다. 적용한 patch 이름은 `SOURCE_SELECTION`의 `patches=` 줄에 기록된다.

`rock5bp`의 vendor 6.1.84 `nvmet-tcp`에 남아 있는 allocation failure crash(upstream `5572a55a6f830ee3f3a994b6b962a5c327d28cb3`, nvmet-tcp: fix kernel crash if commands allocation fails)는 transport 소스(6.1.186)에 이미 포함되어 있으므로 이 fix에는 별도 patch가 필요 없다. 그러나 이 fix는 crash만 막을 뿐 queue command 배열의 order-6 `kcalloc` 실패(단편화된 메모리에서 `NVME_SC_INTERNAL`로 connect 실패, #359)는 그대로이므로, `rock5bp`는 `patches`로 upstream `5c8d134f0155`(nvmet-tcp: use kvcalloc for commands array) backport를 적용한다. 이 commit은 mainline v6.19에서 처음 들어갔고 어떤 stable branch에도 backport되지 않았으므로 transport release를 올려도 대체되지 않는다. 이미 설치된 module은 새 패키지를 `install`하고 다시 load하기 전까지 기존 상태 그대로다.

같은 이유로 `rock5bp`는 mainline v6.19까지 `drivers/nvme/target/tcp.c`에 들어갔지만 6.1 stable에는 없는 fix 중, 6.1.186 코드에 버그가 실제로 있고 transport 파일만으로 적용되는 것도 backport한다: `44aef3b85075`/`6fe240bc0d97`(modparam 값 검증), `bbacf79201a1`(softirq에서도 잡히는 `state_lock`을 `spin_lock_bh`로), `07a29b134ce8`(`install_queue()`의 `flush_workqueue` 순환 lock 제거), `2fa8961d3a6a`(`listen_data_ready()` hang). 나머지 미backport commit은 새 core·network API가 필요하거나 TLS·secure concat처럼 6.1.186에 없는 코드를 고치는 것이라 적용하지 않는다.

### Issue Agent Runner DRM 장치

Issue Agent Runner Pod의 Docker 작업(예: Krema E2E harness의 KWin)은 node에 이미 있는 native DRM 장치 한 쌍 `/dev/dri/card0`·`/dev/dri/renderD128`만 받는다(`macmini`는 `asahi`, `rock5bp`는 `rockchip-drm`). 렌더링은 지금처럼 Mesa CPU rasterizer(llvmpipe)가 맡는다. 따라서 이 그래픽 전환에는 host 커널 module, 배포판 패키지, Nix 선언이나 activation 변경이 필요 없다. 장치 전달 방식은 [Issue Agent 플랫폼 문서](docs/issue-agent-platform.md)의 `Runner Docker와 DRM 장치` 절에 있다.

dockerd 방화벽: Docker 29.4의 nftables firewall backend는 kernel FIB expression을 쓴다. `rock5bp`의 vendor 커널 `6.1.84-999-rk2410`은 `# CONFIG_NFT_FIB_IPV4 is not set`이라 `nft_fib_ipv4`·`nft_fib_inet` module이 없고, 이 backend로는 dockerd가 시작에 실패했다. 그래서 dockerd는 `--firewall-backend=iptables`로 실행하며, base 이미지의 iptables-nft(`nf_tables`)가 규칙을 적용한다. default bridge와 NAT, IPv4 forwarding은 Docker가 Pod network namespace 안에서만 관리하므로 host 커널 module, 커널 교체, host 방화벽, forwarding sysctl, Nix 선언은 바꾸지 않는다. 실제 entrypoint 검증 결과와 남은 배포 확인 항목은 같은 문서에 있다.

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
- Firewall은 기본적으로 distro-native `iptables.service`/`netfilter-persistent`가 Nix-rendered rules file을 boot에 적재한다. `iptables`, `iptables-save`, `iptables-restore`는 모두 `(nf_tables)`를 보고해야 하는 iptables-nft backend invariant다. Running host에서는 native loader를 restart하지 않고 migration command가 `iptables-restore --noflush`로 rules를 갱신한 뒤 기존 Cilium feeder chain 뒤에 HOMELAB jump를 재삽입한다. Reboot 뒤 Cilium이 feeder chain을 다시 만든 경우에는 `homelab-k3s.service`의 bounded `ExecStartPost` reconciliation이 완료될 때까지 unit activation을 유지하고 같은 ordering을 복구한다. Reboot verification도 K3s service와 Cilium/HOMELAB ordering을 bounded retry로 기다린다. INPUT/FORWARD jump 이동은 새 jump를 먼저 삽입하고 이전 duplicate를 뒤에서부터 제거해 DROP policy 아래에서도 관리 SSH 경로가 한 순간도 사라지지 않게 한다. 실패 시 persistent recovery service가 archive의 runtime ruleset을 복구한다. 예외로 `rock5bp`는 `homelab.firewall.manageRules=false`다. `/etc/iptables/rules.v4`와 runtime chain은 외부 소유이며 Nix와 migration/rollback 명령은 loader를 enable/restart하거나 `iptables-restore`, policy 변경, HOMELAB jump 추가·삭제를 실행하지 않는다. 아래 `HOMELAB_PILLAR` chain만 예외다. Manifest는 native rules hash와 NAS port runtime rules/listener만 equality 검증한다.
- `rock5bp`의 유일한 firewall 예외는 `homelab.firewall.pillar`다. `homelab-pillar-firewall.service`(oneshot)는 `rules.v4`와 native chain을 수정하지 않고 homelab 소유 `HOMELAB_PILLAR` chain과 native `TCP` chain 맨 앞의 marked jump 하나만 관리한다. TCP 4420(nvmet)은 topology의 다른 active K3s node LAN `/32`에서만, TCP 9500(pillar-agent gRPC)은 K3s pod network(`topology.k3s.podNetwork`)에서만 허용한다. Host 자신의 initiator 연결과 kubelet probe는 기존 `-i lo` rule이 허용한다. Unit은 boot 시 `netfilter-persistent.service` 뒤, `homelab-k3s.service` 앞에서 실행되고 `PartOf=netfilter-persistent.service`로 native loader가 재시작되어 filter table이 교체되면 다시 적용된다. Chain 교체와 jump 삽입은 `iptables-restore --noflush` transaction 하나로 수행하고 readback으로 검증하므로, system-manager가 변경된 unit을 `ExecReload`로 갱신할 때 허용 rule이 빠지는 구간이 없다. Unit stop/rollback은 marker가 붙은 owned rule만 제거한다. 같은 이름의 chain에 marker 없는 rule이 있거나 비어 있거나 다른 곳에서 참조되면 어떤 rule도 바꾸지 않고 실패한다. `netfilter-persistent reload`처럼 systemd를 거치지 않는 native loader 직접 실행 뒤에는 `systemctl reload homelab-pillar-firewall.service`가 필요하다.
- `rock5bp`에서 전체 generation activation 없이 `homelab-pillar-firewall.service`만 먼저 적용하는 interim install(#350)은 `/etc`가 아니라 system-manager가 관리하지 않는 systemd search path `/usr/local/lib/systemd/system`에 unit link와 `system-manager.target.wants/` link를 두고, reviewed unit closure를 `/nix/var/nix/gcroots/homelab-pillar-firewall-unit` GC root로 pin한 뒤 `daemon-reload`와 이 unit의 `start`만 실행한다. `/etc/systemd/system`에 수동 link를 만들면 안 된다: pinned system-manager는 unmanaged `.wants`/`.requires` link만 backup 후 교체하고, unmanaged top-level unit link는 경고만 남긴 채 old store path로 둔다. `/usr/local` layout에서는 첫 full activation이 `/etc/systemd/system`의 두 link를 충돌 없이 새로 만들어 state에 기록하고, `/etc` unit이 `/usr/local` 사본을 가린다.
- 그 첫 full activation은 이미 active인 이 unit을 reload하지 않는다(old state에 없던 service는 `system-manager.target` start만 받는다). Activation exit 0만으로는 handoff 증거가 아니므로 직후 순서대로 확인한다. (1) `jq` 등으로 `/var/lib/system-manager/state/system-manager-state.json`의 `.fileTree.files`에 `/etc/systemd/system/homelab-pillar-firewall.service`와 `/etc/systemd/system/system-manager.target.wants/homelab-pillar-firewall.service`가 있고 `.services["homelab-pillar-firewall.service"]`가 새 generation의 unit store path를 가리키는지 확인한다. (2) `systemctl show -p FragmentPath --value homelab-pillar-firewall.service`가 `/etc/systemd/system/homelab-pillar-firewall.service`인지 확인하고 `systemctl reload homelab-pillar-firewall.service`로 새 rules를 적용한 뒤, 그 fragment의 `ExecStart=<script> apply`에 있는 script로 `<script> verify`를 실행한다. (3) 모두 성공한 뒤에만 `/usr/local/lib/systemd/system/homelab-pillar-firewall.service`와 `/usr/local/lib/systemd/system/system-manager.target.wants/homelab-pillar-firewall.service`를 지우고 `daemon-reload`한 다음 GC root를 지운다. 하나라도 실패하면 `/usr/local` link와 GC root를 그대로 두고 조사한다. `/usr/local` link가 남아 있으면 이후 generation이 `homelab.firewall.pillar`를 끌 때 옛 unit이 되살아나므로 handoff는 첫 full activation에서 끝내야 한다.
- `rock5bp`의 ZFS pool `fast`는 HP EX950의 `nvme1n1p5`(614.8G) 한 파티션으로 된 비복제 SSD pool이며 pillar-csi(`argocd/apps/pillar-csi.yaml`)의 `ssd-single`(`reclaimPolicy: Delete`)과 `ssd-single-retain`(`Retain`) StorageClass가 쓴다. StorageClass는 storage와 protocol, 그리고 PVC가 바꿀 수 없는 StorageClass 필드만 정하고, volblocksize·compression·refreservation·NVMe queue·filesystem 같은 workload별 설정은 PVC의 `pillar-csi.bhyoo.com/backend`·`/protocol`·`/filesystem` annotation으로 준다. 같은 디스크의 `part4`가 `hot-data` raidz1 member이므로 이 디스크를 잃으면 `fast`의 데이터는 전부 사라지고 `hot-data`는 degraded가 된다. 다른 pool과 마찬가지로 `preserveNasState` 범위라 Nix가 만들지 않으며, 한 번만 host에서 만든다: `zpool create -o ashift=12 -o autotrim=on -O compression=lz4 -O atime=off -O xattr=sa -O mountpoint=none fast /dev/disk/by-id/nvme-HP_SSD_EX950_1TB_HBSE49202700542_1-part5 && zfs create fast/k8s`. Import는 기존 pool과 같은 `/etc/zfs/zpool.cache` 경로를 따른다. PillarStore와 chart `agent.backends`의 `pool`/`parentDataset`은 이 layout과 같아야 한다.
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

변경된 노드의 WireGuard peer만 갱신할 때는 `nix run .#rollout-peers -- <host>`를 사용한다. `onboard-k3s-node`는 K3s state와 active/enabled legacy service가 없는 대상에 대해 healthy server의 live version으로 standard install layout을 설치하되 service enable/start는 건너뛰고, canonical token을 host ciphertext에 복사한 뒤 guarded `prepare`까지 실행한다. 신규 provisioning host뿐 아니라 이미 Nix-managed인 active host에 K3s 역할을 추가할 때도 같은 명령을 사용한다.

`macmini`의 Runbear Cloudflare WARP client는 loopback DNS proxy(`127.0.2.2`, `127.0.2.3`)를 `systemd-resolved`에 동적으로 등록한다. 따라서 이 host의 global `DNSOverTLS`만 `opportunistic`으로 두어 local proxy에는 평문 loopback DNS를 허용하고, `end0` link는 계속 `DNSOverTLS=yes`와 DNSSEC를 강제한다. WARP가 연결되면 upstream DNS는 WARP의 DoH 정책을 따르며, WARP가 없는 다른 host의 strict DoT 계약은 바뀌지 않는다.

K3s version과 순차 rollout은 기존 Rancher `system-upgrade-controller`가 단독 소유한다. Nix topology는 K3s version을 선언하거나 binary를 Nix store에 고정하지 않는다. `homelab-k3s.service`는 install-script layout의 `/usr/local/bin/k3s`를 `exec`하고 `Restart=always`로 실행하므로, Rancher `k3s-upgrade`가 binary를 교체하고 기존 process를 종료하면 systemd가 동일 unit을 새 binary로 다시 시작한다. 기존 `k3s.service`/`k3s-agent.service` unit은 cutover 후 제거하지만 `/usr/local/bin/k3s`와 install helper는 유지한다.

`n2p1`, `n2p2`, `rpi4`, `rpi5`, `rock5bp`, `macmini`는 live iSCSI client dependency를 유지한다. Debian 계열은 `open-iscsi.service`, Arch Linux는 `iscsi.service`를 login unit으로 사용하며 두 계열 모두 `iscsid.service`를 먼저 기동한다. `rock5bp`의 NAS plane은 계속 외부 소유다. Nix는 ZFS pool/dataset/zvol, rtslib/targetcli, Samba/NFS, storage cron, `democratic-csi` uid/gid 1001 identity, `/home/democratic-csi/.ssh/authorized_keys`, `/etc/sudoers.d/democratic-csi`, native firewall file/runtime chain을 선언하거나 쓰지 않는다. Commit generation의 sshd는 기존 home key lookup과 managed admin-key lookup을 함께 유지한다.

외부 소유 영역의 LIO restore는 모든 zvol link를 기다린 뒤 실행하고, 저장된 storage object나 LUN이 빠지면 unit을 실패시킨다. 수동 설치 파일과 절차는 [`docs/rock5bp-lio-restore`](docs/rock5bp-lio-restore/README.md)에 있다.

### Kubernetes 차트 순차 업그레이드

- 한 workload의 GitOps revision을 push한 뒤 실제 목표 chart revision, 실행 중인 container image, readiness와 기능 smoke를 확인하고 다음 workload를 배포한다. `Synced/Healthy`만으로 새 Pod 생성·네트워크·데이터 경로 정상 여부를 판단하지 않는다.
- Cilium 1.20.2의 socket-LB helper는 kernel BTF를 사용하는 enum CO-RE relocation을 도입했다. 현재 BTF 없는 vendor kernel에서는 KPR/socketLB를 유지한 채 사용할 수 없어 1.20.1로 롤백했다. kernel/BTF 전제 또는 upstream 수정이 해결되기 전 재배포하지 않는다.
- ARC 0.15.0은 `AutoscalingRunnerSet.spec.listenerConfig`를 추가한다. controller image pin과 CRD를 먼저 올리고 새 schema의 server-side dry-run이 통과한 뒤 runner-set chart를 올린다.
- Loki·Alloy·VersityGW 변경은 기존 PVC UID와 PV 연결을 보존한다. Loki 실제 query, Alloy 재시작 이후 로그 전달, VersityGW 소비자 IAM read 및 별도 QA prefix의 multipart/checksum·정리를 검증한다.
- rock5bp 재부팅은 원격 NVMe-oF PVC의 I/O와 Pod 종료·재부착을 막을 수 있다. chart rollout과 NAS 호스트 maintenance를 겹치지 않으며, 경로가 복구되기 전 RWO Pod를 강제 삭제해 새 writer를 만들지 않는다.
- CNPG operator 업그레이드 전 두 DB의 새 백업 완료를 확인한다. instance manager 갱신으로 단일 DB Pod가 재생성될 수 있으므로 SQL 응답, PVC UID/PV 연결, PostgreSQL system ID가 유지되는지 검증한다.
- DB cluster chart 변경은 DB Pod를 바꾸지 않고 label이나 alert rule만 바꿀 수 있다. 전체 `Cluster.spec`을 비교하고 PostgreSQL image pin, resources, storage 설정을 보존한다.
- Hindsight는 chart와 API/UI image pin을 함께 갱신한다. image rollback은 forward migration을 되돌리지 않으므로 API version, 기존 기록 조회, migration head와 index 상태를 확인한다.
- 내장 `barmanObjectStore` 백업은 CNPG 1.31.0에서 제거된다. 그 전에 Barman Cloud Plugin으로 전환해야 하며, 이번 1.30.1 업그레이드에서는 기존 백업 설정을 유지한다.
- Hindsight 0.10.2는 corrective retry에서 parsed reply dict를 assistant text로 전달해 갱신이 실패할 수 있다([upstream PR #4903](https://github.com/vectorize-io/hindsight/pull/4903)). 데이터 보존 guard는 유지하고, 이 회귀의 source 수정은 별도 승인 범위로 다룬다. guard를 끄거나 provider를 바꾸지 않는다.
- 현재 배포 기준 버전은 Registry 3.1.2(두 mirror), BuildKit 0.33.1, cloudflared 2026.9.3, Alloy 1.20.1/reloader 0.94.1, Argo Redis 8.10.2, Hermes 2026.9.24와 Camofox 1.18.0(3개 인스턴스), n8n 2.41.6이다. Issue Agent는 Docker 29.8.2, Codex 0.160.0, GitHub CLI 2.102.0을 사용하며 HAPI 0.30.7은 유지한다.
- GHA source 업데이트와 실제 검증 범위는 구분한다. master에는 checkout 7.0.1, script 9.0.0, chart-releaser 1.8.1을 반영했다. master Terraform run 37031284951은 성공했다. 별도 비병합 QA PR #384는 머지 없이 close했고, Terraform run 37032502269에서 실제 plan·no-changes·github-script 9.0.0 실행과 GitHub Actions comment를 확인했으며 AMD64/ARM64 run 37032502295도 성공했다. Release Charts 실행은 `CHART_GITHUB_TOKEN` 누락으로 차단됐으며 다른 credential로 대체하지 않는다.
- 최소 운영 주의사항: Alpine base 변경 시 `util-linux-misc=2.42.3-r1` pin과 `nf_tables`·`unshare`·native DRM guard를 유지한다. 이번 n8n 업그레이드는 5개 forward migration(261→266)을 실행했으므로 downgrade 전 검증된 pre-upgrade SQLite backup restore가 선행돼야 한다. Alloy는 `image.tag`와 `image.digest`를 따로 설정하며, Running 상태의 이전 실패 revision retry를 종료할 때 `status.operationState.phase`를 `Terminating`으로 전환한 후 새 revision으로 동기화한다.
- cc-lb ARC runner Pod와 k8s hook이 만드는 `-workflow`/`-step-*` job Pod는 `kubernetes.io/hostname=macmini` required affinity로 고정한다(각 scale set의 `template.spec.affinity`와 `workflow-pod-templates` ConfigMap + `ACTIONS_RUNNER_CONTAINER_HOOK_TEMPLATE`). rock5bp는 NVMe/TCP storage host이고 n2p*/rpi*는 RAM이 부족해 CI 컴퓨팅을 둘 수 없다(2026-10-04 rock5bp load 48, jellyfin/hermes liveness 실패 사고). 새 workflow service를 추가하면 ConfigMap에 `$<service>` 항목을 같이 넣어 resource cap을 준다.

### Issue agent (n8n + HAPI)

`apps/objects/issue-agent/`는 GitHub App `bulgasaribot`이 설치된 저장소의 이슈·PR 자동화 중 hub·n8n·bridge를 `issue-agent` namespace에, `apps/objects/issue-agent-runner/`는 Runner Pod를 `issue-agent-runner` namespace에 배포한다. Runner 이미지는 계속 `apps/objects/issue-agent/`에서 빌드한다. 현재 운영 대상은 `isac322/cc-lb`다. 설계와 책임 경계는 `docs/issue-agent-platform.md`를 따른다. Argo CD 등록 파일은 `argocd/apps/issue-agent.yaml`, `argocd/apps/issue-agent-runner.yaml`, `argocd/appprojects/issue-agent.yaml`이다. 자동 merge는 하지 않는다.

- 구성: 각 Deployment는 단일 replica이며 `Recreate`로 교체한다.
  - `issue-agent-bridge`: 서명 검증을 마친 GitHub delivery의 내부 수신(intake)·중복 방지·상태 SQLite와 n8n용 `/ops` API를 담당한다. GitHub 이슈·PR 쓰기는 모두 bridge op로만 일어난다.
  - `issue-agent-n8n`: 수신 워크플로 `IssueAgentIntake01`이 GitHub webhook 서명을 검증해 bridge로 넘긴다. 워크플로 `IssueAgentMain01`이 triage·구현·후속 댓글·PR 리뷰 단계와 모든 GitHub 반영(라벨·댓글·push·PR·리뷰)을 소유하고, 모드별 HAPI 세션 루프는 하위 워크플로 `IssueAgentSession01`로 호출한다. 오류 워크플로는 `IssueAgentError01`이다.
  - `issue-agent-hub`: HAPI Hub로, 세션·메시지 SQLite와 웹 UI를 제공한다.
  - `issue-agent-runner`(`issue-agent-runner` namespace): HAPI Runner로, Codex를 실행하며 네이티브 `CODEX_HOME`, checkout, 주제별 worktree를 home PVC에 보존한다. 같은 Pod의 `publisher` 사이드카(Service `issue-agent-publisher.issue-agent-runner`, 포트 8090)가 checkout clone과 branch push만 담당하고, native sidecar `dockerd`가 Pod 전용 Docker daemon을 제공한다. Runner Pod는 replica 1과 `Recreate`를 유지하며 replica를 늘리지 않는다.

  Hub, n8n, runner home(20Gi), bridge 상태는 각각 `ssd-ha-xfs` PVC에 저장하고, Docker 이미지와 build cache는 `issue-agent-runner-docker`(50Gi) PVC에 둔다. `issue-agent` namespace는 Pod Security `restricted`를 enforce하며 hub·n8n·bridge는 non-root다. `issue-agent-runner` namespace만 `privileged`를 enforce하고 audit·warn은 `restricted`로 둔다. 그 안에서 root·privileged로 실행하는 컨테이너는 `dockerd`뿐이고 runner와 publisher는 UID 1000 non-root다. 어느 Pod도 Kubernetes API 토큰을 마운트하지 않는다.
- 흐름: 에이전트(Codex)는 GitHub에 아무것도 쓰지 않는다. 턴 끝에 `ISSUE_AGENT_RESULT <nonce> {json}` 한 줄로 구조화된 결과를 내고, bridge가 모드별 스키마로 검증한 뒤 n8n이 bridge op로 GitHub에 반영한다. 세션은 주제마다 하나다(이슈 `issue-<n>`, PR `review-pr-<n>`, HAPI branch는 `hapi-<worktree>`). bridge dispatcher는 저장소와 무관하게 전체에서 이벤트를 최대 5개(`MAX_ACTIVE_EVENTS`)까지 동시에 n8n에 넘기되, 같은 이슈·PR의 이벤트는 세션과 worktree를 공유하므로 한 번에 하나씩 들어온 순서대로 처리한다. 이벤트가 `finish`로 끝나면 bridge가 그 세션을 HAPI에서 archive해 Codex 프로세스를 멈추고, 같은 주제의 다음 이벤트가 같은 세션을 resume한다. 그래서 Runner에는 일하는 세션과 `needs_attention`으로 멈춘 세션만 떠 있다.
  - triage: 누구나 연 `issues.opened`(저장소 collaborator·owner가 아닌 사용자의 새 이슈는 전체 저장소 합산 1시간(rolling)에 10개까지, 넘으면 `rate_limited`), 또는 구현 단계가 아닌 이슈의 새 댓글. 에이전트가 `gh`로 이슈와 댓글을 직접 읽고(관련 이슈·PR은 `gh search`로 검색) `isac-issue-triage`로 분석해 TriageResult를 낸다. n8n이 카탈로그 라벨을 적용하고 분석 댓글을 게시한다. `next_action`이 `implement`면 같은 실행·같은 세션에서 구현으로 넘어가고, `await_info`/`await_decision`이면 질문 댓글에서 멈춘다.
    - 신뢰와 기능 요청: 신뢰 사용자(collaborator 권한 `admin`/`write`)가 연 명확한 기능·문서 요청은 직접 지시로 보고 `enhancement`/`documentation` 라벨과 함께 바로 implement로 넘긴다(구조 변경이 필요하면 `triage:needs-structural-change`로 멈춘다). 비신뢰 사용자의 기능 요청은 바로 구현하지 않고 제안 트랙으로 간다: 현재 계약 확인, 실현 가능성 조사, 방향과 기각한 대안을 담은 제안 평가 댓글을 `enhancement` 라벨과 함께 게시하고 `await_decision`으로 멈춘다. 이후 신뢰 사용자가 댓글로 방향을 승인하면 다시 triage해 `triage:fix-direction-decided`와 `## Direction` 댓글을 남기고 implement로 넘어간다. 비신뢰 사용자의 댓글은 멘션이든 `agent:open-discussion` 경로든 추가 정보일 뿐 승인이 아니다. bridge는 actor의 신뢰 여부를 `begin` 응답의 `event.trusted`로 n8n에 넘기고, 에이전트는 그 밖의 사람을 `gh api repos/<owner>/<repo>/collaborators/<login>/permission`으로 확인한다. 버그와 기능 요청이 섞인 이슈는 따로 판정하고, 버그만 고치는 PR은 `Fixes` 대신 `Related to #<n>`을 쓴다.
    - 보안 취약점: 확인되거나 의심되는 취약점은 공개 위치에 아무것도 남기지 않는다. 라벨·이슈 댓글·재현 페이로드 없이 TriageResult의 `security_advisory`로 write-up을 내면, n8n의 `github.security_advisory` op가 issue App으로 비공개 draft repository security advisory(GHSA)를 만들고 이벤트를 `triaged`로 끝낸다. advisory 생성은 이벤트마다 한 번이다(재시도 시 기존 draft를 찾아 재사용).
  - 저장소 owner(`isac322/*`의 `isac322`)가 연 이슈는 자동 처리하지 않는다(`owner_issue_ignored`). 나중에 그 이슈에 `@bulgasaribot` 멘션 댓글을 달면 그 댓글로 triage부터 시작한다.
  - implement: `isac-issue-to-pr`로 `hapi-issue-<n>` branch에 로컬 커밋만 하고 ImplementResult(`head_sha`, PR 제목·본문)를 낸다. n8n이 `git.push`(publisher 경유, force 없음)로 push하고 `github.pr_upsert`로 일반(비 Draft) PR을 열거나 제목·본문을 갱신한 뒤 이슈에 PR 링크를 남긴다. `no_change`는 이슈 댓글, `needs_info`는 질문 댓글과 `triage:needs-info` 라벨로 끝난다.
  - 후속: 구현 단계 이슈의 새 댓글과 제목·본문 수정(`issues.edited`)은 `followup` 모드로 같은 세션에 전달되며(`receiving-code-review` 포함) 결과 처리는 implement와 같다. 에이전트는 `gh`로 이슈 제목·본문과 모든 댓글을 직접 읽고, 기록된 `pr_number`가 있으면 그 PR의 상태도 `gh`로 읽어 비교한 뒤 달라졌으면 커밋과 PR 제목·본문을 고친다. 진행 중인 PR의 요구사항은 신뢰 사용자의 댓글·수정만 바꿀 수 있고, 비신뢰 사용자의 입력은 지시가 아니라 판단할 정보다(질문이나 `needs_info`로 이어질 수 있다). PR이 merge·close됐으면 기본 브랜치를 branch에 merge한 뒤 새 PR을 연다.
  - PR 리뷰: 설치된 저장소의 Draft가 아닌 모든 PR이 `pull_request` `opened`/`reopened`/`ready_for_review`로 자동 리뷰된다(작성자·sender 무관, dependabot·외부 기여자·bot PR 포함). 재요청은 PR 작성자 또는 저장소 collaborator·owner가 `User` sender로 남긴, 본문 어디든 `@haechibot` 멘션이 있는(대소문자 무시) PR 댓글뿐이다. 리뷰 세션은 구현 세션과 분리되어 있고(`review-pr-<n>`), PR head를 `git fetch origin pull/<n>/head`로 checkout해 base diff를 본다. 에이전트는 `gh`와 `gh api graphql`로 PR 제목·본문·파일·리뷰·댓글·리뷰 스레드와 연결 이슈(다른 저장소 포함)를 직접 읽는다. 에이전트가 `isac-pr-review`로 ReviewResult를 내면 n8n의 `github.review`가 리뷰 App(`haechibot[bot]`)으로 기존 스레드 답글·resolve를 먼저 게시하고 리뷰 하나를 제출한 뒤, 리뷰한 head에 commit status `issue-agent/review`를 남긴다(APPROVE → `success`, REQUEST_CHANGES·COMMENT → `failure`). 작성 App과 리뷰 App이 다르므로 bulgasaribot이 연 PR에도 실제 APPROVE/REQUEST_CHANGES가 달린다. 리뷰 본문과 리뷰 이벤트의 attention 댓글은 bridge가 단일 footer 블록(재리뷰 방법과 요청 자격 안내)을 덧붙여 게시하며 에이전트는 footer를 쓰지 않는다. PR 리뷰 이벤트의 attention 댓글과 `agent:needs-attention` 라벨도 리뷰 App이 게시한다. 리뷰 중 PR head가 바뀌면(결과의 `head_sha`와 다르면) 리뷰를 리뷰한 커밋(`commit_id=head_sha`)에 제출하고 본문 첫머리에 새 head가 리뷰되지 않았다는 안내와 재리뷰 명령을 넣으며, 새 head에는 `issue-agent/review` 상태를 남기지 않는다. force-push로 그 커밋이 PR에서 빠져 GitHub가 422로 거절하면 판정과 지적을 PR 댓글로 남긴다. 어느 경우든 attention으로 멈추지 않는다.
- 정리: n8n `IssueAgentMain01`의 `Daily cleanup` 트리거가 매일 04:00(UTC) bridge `cleanup_closed` op를 부른다. GitHub에서 닫힌 지(merge 포함) 30일이 지난 이슈·PR은 에이전트 상태를 지운다. 대상은 HAPI 세션(superseded 포함, archive 후 삭제), publisher가 지우는 worktree·`hapi-*` branch ref·Codex rollout 파일, 그리고 bridge의 세션·단계 기록이다. GitHub의 이슈·PR·댓글·리뷰와 bridge 이벤트 기록은 남는다. 진행 중인 이벤트가 있거나 다시 열린 주제는 건드리지 않는다. 정리된 주제에 새 이벤트가 오면 새 세션과 worktree로 시작한다. 실패한 주제는 상태를 남겨 다음 날 다시 시도하고, 실패가 있으면 n8n 실행이 실패로 표시된다.
- 이미지: HAPI Hub와 Runner는 공개 이미지 `ghcr.io/isac322/issue-agent-hapi`, `ghcr.io/isac322/issue-agent-runner`를 digest로 고정하며 pull Secret이 필요 없다. publisher는 Runner 이미지를 그대로 쓴다. 이미지에는 레포에 있는 지침(`profile/AGENTS.md`)·스킬(`profile/skills/` → `/etc/codex/skills`)·스크립트만 들어가고 자격증명은 넣지 않는다. n8n은 공식 이미지를 digest로 고정한다. dockerd 이미지(`Dockerfile.dockerd`)는 digest로 고정한 `docker:29.8.2-dind` 위에 `util-linux-misc=2.42.3-r1`만 빌드 때 설치하며, 실행 중에는 패키지를 설치하지 않는다. base 이미지의 `iptables`·`ip6tables`가 `nf_tables` backend인지는 빌드 때와 `dockerd-start` 실행 때 확인한다. Runner 이미지의 Docker CLI·buildx·compose도 digest로 고정한 `docker:29.8.2-cli`에서 복사한다.
- Codex 도구: Runner 이미지에 context-mode와 CodeGraph를 `runner/tools/package-lock.json`(npm integrity 고정)으로 설치한다. MCP 서버 두 개는 Codex 시스템 설정(`runner/codex/config.toml` → `/etc/codex/config.toml`)에, hook은 `runner/codex/requirements.toml` → `/etc/codex/requirements.toml`의 managed hook으로 둔다. managed hook은 정책상 신뢰되므로 무인 Runner에서도 `/hooks` 승인 없이 실행되고 사용자 설정으로 끌 수 없다. context-mode hook은 큰 출력과 `curl`/`wget` 같은 raw fetch를 `ctx_*` 도구로 돌리고(MCP 서버가 살아 있을 때), SessionStart hook `codegraph-index`는 세션 worktree에 CodeGraph 색인을 만들거나 동기화한다. `.codegraph/`는 전역 git exclude(`runner/gitignore`)로 커밋되지 않는다.
- 빌드 캐시: Runner 이미지에 sccache를 체크섬 고정으로 설치한다. Rust는 `RUSTC_WRAPPER=sccache`로, C/C++는 `PATH`에서 `/usr/bin`보다 앞선 `cc`·`gcc`·`c++`·`g++` wrapper(`runner/sccache-cc`)로 sccache를 거친다. CMake는 `CMAKE_C_COMPILER_LAUNCHER`·`CMAKE_CXX_COMPILER_LAUNCHER`도 sccache로 둔다. Rust `cc` crate나 CMake launcher처럼 sccache가 이미 감싼 호출에서는 wrapper가 부모 프로세스를 보고 실제 컴파일러를 바로 실행해 이중으로 감싸지 않는다. 캐시(`SCCACHE_DIR=/home/agent/.cache/sccache`, 최대 `5G`)는 기존 home PVC에 있어 worktree·세션·Pod 재시작을 넘어 공유된다. 의존성 crate와 C/C++ 오브젝트는 캐시되지만, incremental로 빌드되는 워크스페이스 자기 crate와 링크는 캐시되지 않는다.
- 툴체인: Runner 이미지에는 Rust(rustup, toolchain은 home PVC에 lazy 설치), Go(`/usr/local/go`, 체크섬 고정), gcc/g++, CMake, Python 3, Node가 있다. Go의 `GOPATH`(모듈 캐시, `go install` 도구)와 `GOCACHE`는 기본값인 `$HOME` 아래라 home PVC에 남는다. `go.mod`가 더 새 toolchain을 요구하면 `GOTOOLCHAIN=auto`로 받아 `GOPATH`에 둔다.
- Provider: `external-secret-provider.yaml`이 기존 CLIProxyAPI SSM 항목에서 Runner용 `issue-agent-provider` Secret(`OPENAI_API_KEY`, Codex `config.toml`)을 만든다. n8n은 모델을 호출하지 않는다. 값은 파일 마운트로만 전달하므로 변경 후 Runner Pod를 재시작한다.
- 저장소: `repo-registry.json`은 `defaults`(agent `codex`, model `gpt-6.1-sol`, permission `yolo`)와 저장소별 override만 가진다. model은 새 세션을 spawn할 때만 적용되고, 이미 만들어진 세션은 resume할 때 원래 모델을 유지한다. 사용자 목록은 없고, 신뢰 사용자는 collaborator 권한 API가 `admin`/`write`를 돌려주는 저장소 collaborator·owner다(SQLite 600초 캐시, 조회 실패면 HTTP 503 `permission_unavailable`). n8n 수신 워크플로가 검증한 App 서명이 설치를 증명하므로 설치된 모든 저장소의 이벤트를 받는다. 기본 브랜치는 webhook payload에서 읽고, checkout(`/home/agent/checkouts/<owner>/<name>`)은 첫 세션 생성 때 publisher가 clone한다. 대상 저장소를 늘리려면 App 설치 범위를 바꾼다.
- GitHub 인증: 작성용 App `bulgasaribot`(App ID `5063990`, installation `164533066`, bot `bulgasaribot[bot]`, user ID `333478113`)과 리뷰 전용 App `haechibot`(App ID `5118831`, installation `166063086`, bot `haechibot[bot]`, user ID `335401592`)을 쓴다. 두 App 모두 `isac322/cc-lb`, `isac322/flareway`, `isac322/krema`, `isac322/pillar-csi`, `isac322/kwin-mcp`, `isac322/rkmon`에 설치돼 있다. 리뷰 App은 webhook이 없고 이벤트는 bulgasaribot webhook으로만 받는다.
  - 개인키는 Terraform Cloud 민감 변수 `github_app_private_key_ironeater`/`github_app_private_key_ironeater_reviewer`와 SSM `/homelab/cluster/backbone/github-app/{ironeater,ironeater-reviewer}/private-key`가 소유한다. 이 식별자들은 git-crypt로 잠긴 Terraform apply가 필요해서 App 이름을 바꿔도 예전 `ironeater*` 이름을 유지한다.
  - ESO가 설치 토큰 네 개를 15분마다 갱신한다. 저장소 제한은 없고 App 설치 범위를 따른다. read·push 토큰은 `issue-agent-runner`에서 발급하므로, 이 namespace에도 같은 SSM 항목에서 만든 bulgasaribot App 개인키 Secret `issue-agent-github-app`이 있다.
    - `issue-agent-github-read`(`issue-agent-runner` namespace): Runner 에이전트 컨테이너용 읽기 전용(contents/issues/pull_requests read). Git과 `gh`는 디렉터리로 마운트한 `hosts.yml`을 읽는다.
    - `issue-agent-github-push`(`issue-agent-runner` namespace): contents write. publisher 컨테이너에만 마운트한다.
    - `issue-agent-github-token`: bridge용 issues/pull_requests/contents write와 repository_advisories write. GraphQL `resolveReviewThread`가 GitHub App에 contents write를 요구해서 넣었고, repository_advisories write는 취약점 이슈의 draft security advisory 생성에 쓴다(App 등록에도 같은 권한이 있어야 한다). bridge는 push하지 않는다.
    - `issue-agent-github-review`: 리뷰 App 토큰(pull_requests/statuses/contents write, issues read). bridge에만 마운트하며 리뷰 제출·스레드 답글·resolve·commit status에만 쓴다.
  - bridge는 `issue-agent-publisher` Secret의 bearer 토큰으로 publisher를 호출한다. 이 Secret과 push 토큰은 에이전트 컨테이너에 마운트하지 않는다.
  - `issue-agent`가 원본인 `issue-agent-hapi-auth`(`CLI_API_TOKEN`)와 `issue-agent-publisher`(`token`)는 `issue-agent-runner`의 ESO `SecretStore` `issue-agent`가 1시간마다 복제한다. 복제용 ServiceAccount는 `issue-agent`에서 이 두 Secret 이름에 대한 `get`만 가진다.
  - `GH_TOKEN`·`GITHUB_TOKEN` 환경변수나 `subPath` 마운트를 추가하지 않는다. Git 작성자와 bridge의 `GITHUB_BOT_LOGIN`은 `bulgasaribot[bot]`, 리뷰용 `GITHUB_REVIEW_BOT_LOGIN`은 `haechibot[bot]`으로 설정하며 재리뷰 명령 `@haechibot review`도 이 값에서 온다.
- 인터넷 공개 경로: `https://issue-agent-webhook.bhyoo.com/webhooks/github`만 Cloudflare tunnel로 노출하며, 이 경로는 n8n(Service `issue-agent-n8n`, 포트 5678)으로 간다. n8n webhook 경로 접두사는 `N8N_ENDPOINT_WEBHOOK=webhooks`라 운영 URL이 `/webhooks/<path>`다.
  - 수신 흐름: GitHub → n8n `IssueAgentIntake01`(Webhook `github`, Raw Body) → `Verify GitHub signature` 노드(`X-Hub-Signature-256` 검증) → bridge 내부 `POST /webhooks/github`. 서명이 틀리거나 없으면 n8n이 HTTP 401 `{"status":"bad_signature"}`로 답하고 bridge에는 아무것도 전달하지 않는다. 검증된 요청은 원본 바이트 그대로 `X-GitHub-Event`·`X-GitHub-Delivery`와 함께 bridge로 넘기고, bridge의 상태 코드와 JSON 본문을 GitHub에 그대로 돌려준다. bridge에 연결하지 못하면 503 `{"status":"bridge_unavailable"}`이다.
  - 서명 secret은 `issue-agent-webhook` Secret의 `secret` 키이며 App webhook secret과 일치해야 한다. n8n이 `/run/issue-agent-n8n/webhook`에 마운트하고 bootstrap이 자격증명 `iaWebhookSign001`(`webhookSigningSecretApi`)로 갱신한다. bridge는 이 Secret을 마운트하지 않는다.
  - bridge의 `/webhooks/github`와 `/ops`, n8n 내부 webhook(`/webhooks/issue-agent`)은 클러스터 내부 전용이다. bridge의 두 경로는 `issue-agent-bridge-ops` Secret의 `bridge-ops-token`(n8n 자격증명 `iaBridgeOps00001`)으로, n8n 내부 webhook은 같은 Secret의 `n8n-webhook-token`으로 bearer 인증한다. bridge는 토큰이 틀리거나 없으면 401 `{"status":"unauthorized"}`로 답하고 아무것도 저장하지 않는다.
  - 서명 검증 노드는 커뮤니티 패키지 `n8n-nodes-webhook-signature@0.1.2`다. `deployment-n8n.yaml`의 `N8N_COMMUNITY_PACKAGES`가 버전과 npm integrity(`sha512-...`)로 고정하고(`N8N_COMMUNITY_PACKAGES_MANAGED_BY_ENV=true`, `N8N_UNVERIFIED_PACKAGES_ENABLED=false`), `n8n start`가 시작할 때 npm에서 설치·갱신하며 목록에 없는 패키지는 제거한다. 올리려면 새 버전의 `npm view n8n-nodes-webhook-signature@<version> dist.integrity` 값과 변경 내역(노드 이름·매개변수·자격증명 필드)을 확인한 뒤 `version`과 `checksum`을 함께 바꾸고 n8n을 재시작한다. 노드 type·version이나 매개변수가 바뀌었으면 `n8n-intake-workflow.json`도 같이 고친다.
- 운영자 접근: WireGuard 연결 후 내부 `bhyoo-gateway`로 접속한다. 두 UI 모두 인증을 유지한다.
  - HAPI: `https://hapi.bhyoo.com`에 `issue-agent-hapi-auth` Secret의 `CLI_API_TOKEN`으로 로그인한다.
  - n8n: `https://n8n.bhyoo.com`에 `bhyoo@bhyoo.com`으로 로그인한다. 비밀번호는 `issue-agent-n8n-owner` Secret의 `password` 키에 있다. n8n에는 bcrypt 해시만 전달되며, 소유자 정보는 시작할 때마다 이 Secret으로 다시 적용된다.

  비밀값은 채팅·로그·문서에 남기지 않는다. 생성된 인증 값(HAPI 토큰, webhook secret, n8n 암호화 키와 소유자 비밀번호, bridge·n8n·publisher 토큰)은 ESO Password generator가 한 번 만들고 다시 생성하지 않는다.

```bash
kubectl --context homelab-backbone -n issue-agent get secret issue-agent-n8n-owner -o jsonpath='{.data.password}' | base64 -d
kubectl --context homelab-backbone -n issue-agent logs deployment/issue-agent-bridge
kubectl --context homelab-backbone -n issue-agent logs deployment/issue-agent-n8n
kubectl --context homelab-backbone -n issue-agent-runner logs deployment/issue-agent-runner -c publisher
kubectl --context homelab-backbone -n issue-agent-runner logs deployment/issue-agent-runner -c dockerd
```

#### 라벨

에이전트는 bridge의 라벨 카탈로그 이름만 요청할 수 있다. 저장소에 없는 라벨은 카탈로그의 설명·색으로 만들고, 있는 라벨은 그대로 쓴다. 같은 그룹의 라벨을 추가하면 그 그룹의 다른 라벨은 같은 op에서 제거된다.

| 라벨 | 그룹 | 의미 |
|---|---|---|
| `repro:reproduced` / `repro:not-reproduced` / `repro:blocked` | repro | 로컬 재현됨 / 재현 안 됨 / 조건 부족으로 판단 불가 |
| `triage:root-cause-identified` | — | 증거로 원인 확정 |
| `triage:needs-info` | — | 제보자 답변 대기 |
| `triage:fix-direction-decided` / `triage:needs-structural-change` | direction | 수정 방향 확정 / 구조 변경이라 메인테이너 결정 필요 |
| `bug` / `enhancement` | kind | 결함 / 기능 요청 |
| `documentation`, `duplicate` | — | 문서, 중복 |
| `agent:needs-attention` | — | 자동화가 오류로 멈춤. bridge만 붙이고 뗀다 |

#### 오류 알림과 재시도

에이전트를 실행하는 모든 경로는 GitHub에 보이는 상태로 끝난다. 성공은 결과 댓글·리뷰, 실패는 해당 이슈/PR의 attention 댓글과 `agent:needs-attention` 라벨이다. attention 댓글에는 멈춘 n8n 노드 또는 단계, 이벤트 종류, delivery ID, n8n 실행 링크(`https://n8n.bhyoo.com/workflow/IssueAgentMain01/executions/<id>`), HAPI 세션 링크, 재시도 방법이 들어간다. 댓글과 라벨 중 하나라도 실패하면 bridge가 backoff 후 둘 다 적용될 때까지 다시 시도한다(숨은 marker로 중복 게시 없음).

- 워크플로 노드 실패는 `Mark needs attention`(bridge `fail`)으로, 처리되지 않은 n8n 오류는 `settings.errorWorkflow`의 `IssueAgentError01`(Error Trigger → bridge `fail_execution`)로 들어온다. bridge 자신이 포기하는 경우(dispatch 8회 실패, stale dispatch, n8n 응답 없음)도 같은 경로다. 자동 재시도는 하지 않는다.
- attention 상태가 되면 그 이슈/PR은 block되고, 이후 이벤트는 쌓이기만 하고 dispatch되지 않는다.
- 원인을 고친 뒤 `retry_event`로 그 이벤트를 다시 큐에 넣는다. 기록된 단계는 유지되어 이어서 실행되고, 성공하면 `finish`가 `agent:needs-attention`을 제거한다. 그 이벤트를 다시 실행하지 않고 이후 이벤트만 진행하려면 `unblock_issue`(`{"op":"unblock_issue","repo":"owner/name","issue_number":N}`)를 쓴다. 이때 라벨은 다음 성공 실행이 제거한다. 상태 확인은 `issue-agent-records bridge events`로 한다.

```bash
kubectl --context homelab-backbone -n issue-agent exec deploy/issue-agent-bridge -c bridge -- python -B -c '
import json, sys, urllib.request
token = open("/run/issue-agent/ops/bridge-ops-token").read().strip()
req = urllib.request.Request("http://127.0.0.1:8080/ops", sys.argv[1].encode(),
                             {"Content-Type": "application/json", "Authorization": "Bearer " + token})
print(urllib.request.urlopen(req).read().decode())
' '{"op":"retry_event","delivery_id":"<delivery-id>"}'
```

#### PR 리뷰 재요청과 merge 제한

GitHub App은 PR reviewer로 지정할 수 없다. REST로 `ironeater[bot]`(현 `bulgasaribot[bot]`)을 reviewer로 요청하면 오류 없이 무시되는 것을 확인했다. 그래서 재리뷰는 PR 댓글 `@haechibot review`로 요청한다. 재리뷰 본문의 첫 절은 이전 지적의 Closed/Open 상태다. PR에 새 commit이 올라오면 새 head에는 상태가 없으므로 다시 리뷰를 요청해야 merge할 수 있다.

merge 강제는 ruleset `issue-agent review`가 맡는다: `isac322/flareway`(`main`)와 `isac322/krema`(`master`)에서 리뷰 App(integration `5118831`)이 남긴 `issue-agent/review` 상태가 `success`여야 merge·push할 수 있다. bypass는 없으므로 기본 브랜치에 직접 push할 수 없고 모든 변경은 PR과 봇 승인을 거친다. `isac322/cc-lb`는 GitHub Free의 private 저장소라 ruleset API가 403을 반환하므로 강제하지 않는다.

#### n8n UI 수정

n8n은 시작 전 `n8n-bootstrap.sh`로 자격증명을 고정 ID로 갱신하고, 오류 워크플로 `IssueAgentError01`, 세션 하위 워크플로 `IssueAgentSession01`, 메인 `IssueAgentMain01`, 수신 `IssueAgentIntake01` 순으로 Git 원본을 동기화한다. 워크플로별 마지막 가져오기 기록은 `/home/node/.n8n/issue-agent/workflow-import-<id>.json`(`sourceSha256`, `versionId`)이다. 규칙은 다음과 같다.

- n8n에 워크플로가 없으면 가져와 게시한다.
- Git 원본 sha256이 기록과 같으면 아무것도 하지 않는다. UI 수정본이 그대로 실행된다.
- Git 원본이 바뀌었고 저장된 `versionId`가 기록과 같으면(UI 미수정) 가져와 게시한다.
- Git 원본이 바뀌었는데 UI에서도 수정됐으면 가져오지 않고 로그에 `CONFLICT workflow <id> ...`를 남긴다. UI 수정본이 계속 실행된다.

UI에서 고쳤거나 `CONFLICT`가 나면 다음 순서로 조정한다.

1. `issue-agent-records n8n-workflows`로 현재 워크플로와 `versionId`를 export해 Git 원본과 비교한다.
2. UI 변경을 유지하려면 그 내용을 해당 Git 원본(`n8n-workflow.json`, `n8n-session-workflow.json`, `n8n-intake-workflow.json`, `n8n-error-workflow.json`)에 옮긴다. `id`와 `settings.errorWorkflow`(메인·수신은 `IssueAgentError01`, 세션·오류 워크플로는 없음)는 그대로 둔다. 버리려면 Git 원본을 그대로 둔다.
3. Git을 최종본으로 가져오려면 export한 현재 `versionId`를 `workflow-import-<id>.json`의 `versionId`에 기록하고 `sourceSha256`을 비운 뒤 n8n을 재시작한다. 다음 시작에서 Git 원본을 가져와 게시한다. `versionId`를 기록하지 않으면 Git 원본이 UI 수정본과 같아도 계속 `CONFLICT`이고, `sourceSha256`을 비우지 않으면 Git 원본이 바뀌지 않은 경우 UI 수정본이 남는다.

```bash
kubectl --context homelab-backbone -n issue-agent exec deploy/issue-agent-n8n -- cat /home/node/.n8n/issue-agent/workflow-import-IssueAgentMain01.json
kubectl --context homelab-backbone -n issue-agent exec deploy/issue-agent-n8n -- node -e '
const fs = require("fs"), [file, version] = process.argv.slice(1);
const state = JSON.parse(fs.readFileSync(file, "utf8"));
fs.writeFileSync(file, JSON.stringify({ ...state, sourceSha256: "", versionId: version }));
' /home/node/.n8n/issue-agent/workflow-import-IssueAgentMain01.json '<live-versionId>'
kubectl --context homelab-backbone -n issue-agent rollout restart deployment/issue-agent-n8n
```

n8n 실행 기록은 성공·실패 모두 저장하며 자동 정리하지 않는다. 단, 수신 워크플로 `IssueAgentIntake01`은 delivery마다 원본 본문을 담으므로 실패 실행만 저장한다(GitHub App의 Recent Deliveries에 모든 응답이 남는다).

이슈 댓글은 이슈에 `agent:open-discussion` 라벨이 있으면 누구의 것이든 멘션 없이 처리한다. 이 경로에서도 bridge가 댓글 작성자의 신뢰 여부를 계산해 넘기며(권한 조회 실패면 비신뢰로 보고 경고 로그만 남긴다), 비신뢰 사용자의 댓글은 정보로만 쓰고 승인이나 지시로 받지 않는다. 라벨이 없으면 `@bulgasaribot` 멘션이 있는 collaborator·owner 댓글만 처리한다(멘션 없음 `issue_comment_ignored`, 비신뢰 멘션 `actor_not_allowed`). 이 라벨은 저장소마다 maintainer가 만든다. 배포 전 bridge 회귀 검증은 `python3 -B -m unittest apps/objects/issue-agent/test_bridge.py`로 실행한다.

기록 조회·내보내기는 [`issue-agent-records`](apps/objects/issue-agent/operations/issue-agent-records), 온라인 SQLite 백업은 [`issue-agent-backup`](apps/objects/issue-agent/operations/issue-agent-backup)을 사용한다. 사용법·복원 전제조건은 [운영 절차](apps/objects/issue-agent/operations/README.md)에 있다. 네이티브 기록은 보관된 세션도 조회할 수 있다. 원본 DB 백업은 인증 자료가 포함될 수 있는 비공개 운영자 자료이며 외부 조회용 export와 구분한다.

두 스크립트는 hub·bridge·n8n을 `--namespace`(기본 `issue-agent`)에서, Runner를 `--runner-namespace`(기본 `issue-agent-runner`)에서 읽는다. [`issue-agent-runner-home-migrate`](apps/objects/issue-agent/operations/issue-agent-runner-home-migrate)는 namespace 전환 때 기존 `issue-agent/issue-agent-runner-home`을 새 `issue-agent-runner/issue-agent-runner-home`으로 한 번 복사·검증하고 ready marker를 쓴다. marker가 없으면 Runner Pod는 시작하지 않는다. 기존 claim은 PV `Retain`과 Argo CD `Prune=false,Delete=false`로 남기며 자동 삭제하지 않는다. 전환 중에는 Runner와 publisher가 멈추므로 무중단 전환이 아니다. Runner 안의 [`issue-agent-docker-smoke`](apps/objects/issue-agent/operations/issue-agent-docker-smoke)는 Pod 전용 Docker daemon의 build와 bind mount를 확인한다. 부작용과 실행 순서는 [운영 절차](apps/objects/issue-agent/operations/README.md)에 있다.

기존 Archon은 새 시스템 webhook 전환 검증 후 완전히 제거했다. 전용 코드·Kubernetes/ArgoCD 정의 19개, `archon` namespace와 두 PVC(20Gi+1Gi), rock5bp의 backing zvol, `archon.bhyoo.com`·`archon-webhook.bhyoo.com` DNS가 제거됐다. 재사용하는 GitHub App과 인증 경로는 `ironeater`로 이름을 바꿨다. GitHub의 기존 이슈·PR은 삭제하지 않았다.

## Ansible ownership boundary

Legacy host-management playbook은 `[ansible_managed]`만 target으로 삼는다. Commit까지
끝난 호스트는 `[nix_managed]`로 옮기며, 현재 `n2p1`, `n2p2`, `rpi4`, `rock5bp`, `macmini`, `rpi5`가 여기에 속한다.
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

### Graceful node shutdown

K3s node 6대(`n2p1`, `n2p2`, `rpi4`, `rpi5`, `rock5bp`, `macmini`)는 priority별로 순차 종료한다. 일반 workload(priority 0)는 60초, ZFS CSI(priority 900000000 이상)는 45초, `system-cluster-critical`은 30초, `system-node-critical`은 45초다. 현재 일반 Pod의 표준 종료 예산은 최대 30초이고 ZFS 및 democratic-csi node Pod는 30초와 `preStop`/volume unmount 작업을 사용한다. 전체 kubelet 예산은 180초이며 logind `InhibitDelayMaxSec=195s`가 15초의 감지·해제 여유를 둔다.

CNPG의 1800초와 Prometheus의 600초 종료 예산은 일반 reboot에 그대로 반영하지 않는다. 이를 반영하면 모든 node의 machine-wide inhibitor가 30분 이상으로 늘어난다. 해당 workload가 있는 node의 계획 유지보수는 CNPG switchover와 `kubectl drain`으로 처리한다. `n2p1`, `n2p2`에서는 unattended-upgrades의 같은 이름 30초 drop-in을 `/dev/null`로 마스킹한다. `activate`는 logind를 먼저 재시작한 뒤 K3s를 재시작하며, `verify-host`는 merged logind 값, kubelet inhibitor, API의 active priority별 kubelet config를 확인한다.

구성 적용 후 일반 재부팅은 `systemctl reboot`를 사용한다. 이 경로는 kubelet의 정상 Pod 종료 기회를 제공하지만 PDB eviction, 대체 Pod의 Ready 완료, 단일 replica 무중단, local PV 이동을 보장하지 않는다. 먼저 `n2p1`, `n2p2`에서 검증하고 control-plane/etcd node는 quorum을 위해 항상 한 번에 하나씩 재부팅한다. `reboot -f`와 `systemctl reboot --force`는 사용하지 않는다.

## Verification

```bash
nix flake check --all-systems --no-build
nix build .#checks.x86_64-linux.topology .#checks.x86_64-linux.migration-contracts --no-link
python3 nix/scripts/check-topology.py
python3 nix/scripts/check-migration.py
bash -n nix/scripts/adopt-host nix/scripts/decommission-host nix/scripts/homelab-host nix/scripts/k3s-handoff nix/scripts/provision-host nix/scripts/render-macbook-wireguard nix/scripts/rollout-peers nix/scripts/wireguard-secrets
```

실호스트에서는 새 SSH session, effective sshd config, synchronized system clock, WireGuard public key/peer/AllowedIPs/handshake, firewall INPUT/FORWARD policy와 Cilium/Samba/NetBIOS rules, K3s version/Ready/etcd, iSCSI path, persistent rollback timer 상태를 확인한다. 기존 Ansible 코드는 전체 topology를 inventory input으로 유지하되, `[nix_managed]` 호스트에는 remote task를 실행하지 않는다.
