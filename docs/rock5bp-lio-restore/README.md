# rock5bp LIO restore ordering

`rock5bp`의 NAS plane(ZFS, LIO/rtslib, Samba/NFS)은 Nix와 Ansible 어느 쪽도 소유하지 않는 외부 관리 영역이다(루트 `README.md`). 이 디렉터리는 그 영역에 수동으로 설치하는 LIO restore 보강 파일의 원본이다. Nix generation은 이 파일들을 선언하지 않으며, `homelab-host`의 preservation guard도 그대로 유지된다.

## 문제 (#363)

- `rtslib-fb-targetctl.service`는 `local-fs.target` 뒤에 `targetctl restore`로 `/etc/rtslib-fb-target/saveconfig.json`을 복원한다. zvol의 `/dev/zvol/...` udev link를 기다리는 순서는 없었고, `zfs-volume-wait.service`도 disabled였다.
- link가 아직 없거나 생성에 실패한 zvol은 `Could not create StorageObject ...: not a TYPE_DISK block device, skipped`로 빠지고, 그 LUN도 함께 빠진다.
- `targetctl restore`는 그래도 exit 0이므로 unit은 성공으로 끝나고, initiator는 LUN 없는 target에 붙어 I/O error를 낸다.

## 구성

| 파일 | 설치 위치 | 역할 |
|---|---|---|
| `50-homelab-zvol-wait.conf` | `/etc/systemd/system/rtslib-fb-targetctl.service.d/` | `Wants=`/`After=zfs-volumes.target`로 모든 zvol link를 기다린 뒤 restore한다. restore 뒤 아래 check를 실행한다. |
| `homelab-lio-restore-check` | `/usr/local/sbin/` (0755 root) | saveconfig의 storage object·LUN과 live configfs를 비교해 빠진 것이 있으면 목록을 journal에 남기고 exit 1로 unit을 실패시킨다. 읽기만 한다. |

`zfs-volumes.target`은 `zfs-volume-wait.service`(`zvol_wait`)를 `Requires=`한다. `zvol_wait`는 진척이 없으면 약 10분 뒤 실패한다. restore 쪽은 `Wants=`이므로 그 경우에도 restore는 실행되고, 빠진 object는 check가 unit 실패로 드러낸다.

ExecStartPost가 실패하면 systemd는 `ExecStop=`(`targetctl clear`)을 실행하지 않는다. 따라서 복원된 나머지 LUN은 계속 서비스된다.

## 설치

```sh
src=docs/rock5bp-lio-restore
scp "$src/homelab-lio-restore-check" "$src/50-homelab-zvol-wait.conf" rock5bp:/tmp/
ssh rock5bp '
  sudo install -m 0755 -o root -g root /tmp/homelab-lio-restore-check /usr/local/sbin/homelab-lio-restore-check
  sudo install -D -m 0644 -o root -g root /tmp/50-homelab-zvol-wait.conf /etc/systemd/system/rtslib-fb-targetctl.service.d/50-homelab-zvol-wait.conf
  rm -f /tmp/homelab-lio-restore-check /tmp/50-homelab-zvol-wait.conf
  sudo systemctl daemon-reload
  sudo systemctl enable zfs-volume-wait.service zfs-volumes.target
  sudo /usr/local/sbin/homelab-lio-restore-check
'
```

설치는 실행 중인 LIO 구성을 바꾸지 않는다. `rtslib-fb-targetctl.service`를 재시작하지 않아도 다음 부팅부터 적용된다.

Nix rollout의 NAS baseline은 `prepare`마다 새로 기록되므로 설치 뒤 첫 rollout은 바뀐 `zfs-volume-wait.service` enabled 상태를 baseline으로 받는다. 설치 이전 transaction의 receipt baseline과 비교하는 `verify-host`만 이 항목을 차이로 보고한다.

## 확인

```sh
systemctl show rtslib-fb-targetctl.service -p Wants -p After | tr ' ' '\n' | grep zfs-volumes
systemctl is-enabled zfs-volume-wait.service zfs-volumes.target
sudo /usr/local/sbin/homelab-lio-restore-check
# 부팅 뒤
systemctl is-failed rtslib-fb-targetctl.service
journalctl -b -u zfs-volume-wait.service -u rtslib-fb-targetctl.service
```

## restore가 실패했을 때

1. `journalctl -b -u rtslib-fb-targetctl.service`에서 빠진 storage object와 device 상태를 확인한다.
2. link가 없으면 `udevadm trigger --action=add --sysname-match=zdN`으로 다시 만든다.
3. 빠진 backstore와 LUN만 `saveconfig.json`의 WWN·LUN index로 rtslib에서 다시 만든다(2026-09-30 복구와 같은 방법). 살아 있는 LUN이 있는 상태에서 unit을 재시작하는 동작은 검증하지 않았으므로 쓰지 않는다.
4. `homelab-lio-restore-check`가 0으로 끝나면 `systemctl reset-failed rtslib-fb-targetctl.service`로 실패 상태를 지운다. 이 명령은 LIO 구성을 바꾸지 않는다.

## pillar-csi nvmet

pillar-csi의 NVMe/TCP export는 systemd가 아니라 pillar-agent가 복원한다. agent는 재시작 뒤 controller가 전체 export 상태를 보낼 때까지 subsystem을 link하지 않고, device마다 `/dev/zvol/...`을 최대 5초 기다린다. 실패한 volume은 `ExportReconciled` condition에 기록하고 backoff로 다시 시도한다(isac322/pillar-csi `internal/agent/server_export_restore.go`, `internal/csi/export_resync.go`). 조용히 빠지는 경로가 아니므로 systemd ordering을 추가하지 않는다.
