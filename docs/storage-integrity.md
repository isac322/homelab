# Storage integrity: 탐지와 디버깅 (#385)

## 목적

[#385](https://github.com/isac322/homelab/issues/385): rock5bp의 ZFS pool `hot-data` zvol에 kernel storage target 경로(과거 LIO iSCSI, 현재 pillar-csi StorageClass `ssd-ha`의 nvmet-tcp)로 쓴 데이터가 드물게 조용히 손상된다. 관측 빈도는 쓰기 약 90–150 GiB당 1건이다. ZFS checksum과 scrub은 깨끗하고, application CRC(Prometheus/Thanos TSDB)만 손상을 알아챈다.

손상 모양:

- 파일 길이는 그대로다.
- 2–20바이트 구간이 ±2/±4바이트 밀리고 빈 자리가 0으로 채워지거나, 같은 파일의 다른 위치 바이트가 복사되어 있다.

지금까지 확인한 것:

- lz4 압축은 필요조건이 아니다(`compression=off`에서도 발생).
- rock5bp에서 zvol에 직접 쓴 900 GiB(zvol 450 GiB + 비-ZFS 450 GiB, 2026-10-06)에서는 0건이다.
- rock5bp 안에서 nvmet target을 loopback으로 거친 경로도 0건이다(2026-10-07, arm마다 약 453 GiB: zvol 직접, nvmet digest 없음, nvmet header·data digest 사용). digest 오류도 없었다. 10-05 A/B의 `compression=off` 발생률이면 nvmet arm에서 약 5건이 나와야 하고, 0건일 확률은 0.6%다.
- 따라서 ZFS, nvmet target, rock5bp RAM/CPU만으로는 재현되지 않는다. 재현된 경로에만 있던 것은 원격 initiator(macmini 등)와 그 사이 네트워크(rock5bp의 vendor `r8125` NIC 포함)다. 3–5월 Prometheus가 rock5bp에 있을 때 난 손상은 iSCSI가 loopback으로 연결됐을 것이라는 추정에 기대고 있어 확인되지 않았다.

아래 장치는 기존 구조를 바꾸지 않고 손상을 상시 탐지하고 증거를 남기기 위한 것이다.

## 이어받기 (어느 세션이든 여기서 시작)

`StorageIntegrity*` 알림, Thanos/Prometheus 블록 손상, pillar-csi volume의 checksum 불일치를 보면 이 절부터 읽는다. #385의 최신 상태는 이 문서와 [#385 댓글](https://github.com/isac322/homelab/issues/385)에 있다.

**현재 상태 (2026-10-11):** 원인은 rock5bp의 NIC(RTL8125B, RK3588 PCIe) 수신 경로로 좁혀졌다. 2026-10-08..11 factorial 실험(driver 교체 r8125/r8169, Relaxed Ordering, rx checksum, 손실 유도, 수신자 교체)으로 확인했다.

- 손상 모양: full-size(1514바이트) frame의 마지막 10바이트(payload 1448바이트의 마지막 부분)가 같은 stream의 다른 데이터로 채워지고 TCP checksum이 달라진다("tail splice"). AF_PACKET 포착에서 이 모양이 우세했고(r8169 86개 중 14, r8125 12개 중 8) 세 sender 모두에서 나왔다.
- driver 무관: out-of-tree `r8125` 9.014.01과 in-tree `r8169`(6.1) 둘 다에서 나온다. PCIe Relaxed Ordering도 무관하다(꺼도 발생). 수신자를 macmini로 바꾸면 1503 GiB에 0건이므로 sender·스위치·공통 경로는 아니고 rock5bp 수신 경로 특정이다.
- 참고 사건: 2026-10-08 06:00 KST iSCSI(rpi5 `iscsi_tcp` → rock5bp LIO → `nas` HDD zvol) 경로에서도 같은 손상이 났다. versitygw가 받을 때 계산한 CRC64가 원본과 같았으므로 손상은 그 뒤 구간에서 생겼다. pool·프로토콜·initiator가 달라도 같은 모양이다.
- 정상 상태에서는 TCP checksum이 막는다. conntrack(`nf_conntrack_checksum=1`)이 CHECKSUM_UNNECESSARY가 아닌 packet의 checksum을 검증하고 INPUT의 `--ctstate INVALID -j DROP`이 TCP 전에 버리므로, application까지 오지 않고 `TcpInCsumErrors`는 0이다. Sender가 재전송한다. 1500바이트 frame 기준 실측 rate는 100 GiB당 r8169에서 약 280, r8125에서 약 406이다.
- Application까지 새는 것은 checksum-neutral 손상뿐으로 실측 100 GiB당 약 0.07–0.2다. 캠페인의 baseline 사건은 우연히 checksum이 유지된 10바이트 복사 2건과, checksum이 보존되는 짝수 바이트 shift(±2/4/6, 0 padding으로 이동) 8건이다. Shift 사건이 같은 기제인지는 미확증이다.
- 배제·불요(코드·증거 확인): ZFS 2.4.1 zvol 경로·ZFS 압축, nvme-tcp/nvmet-tcp와 LIO target 코드·DKMS patch, 6.1.84 TCP·GRO 경로, initiator 소프트웨어, 송신 측(macmini 수신자는 rock5bp sender 포함 같은 sender에서 clean), 케이블·PHY(FCS 오류 0), PCIe 링크(LCRC·RASDES 카운터 0)·Relaxed Ordering, arm64 DMA 코드, Cilium BPF, 온도·전원, rock5bp CPU/DRAM copy(9.7 TiB 검사 0건), TCP 손실 복구(1% 유도 손실에서 0건).
- 기제 추정 [INFERENCE]: RTL8125B + RK3588 PCIe의 non-coherent DMA에서 frame의 마지막 DMA write가 처리 시점에 CPU에 보이지 않는다. 2026-10-05 사건의 "정확히 256×1448바이트 전 데이터 복사"는 ring 한 바퀴 전 같은 RX buffer의 stale byte와 일치한다.
- 조치: pillar-csi v0.5.4부터 모든 pillar volume이 NVMe/TCP header·data digest를 쓴다. 캠페인 중 digest error 2건(실험 arm n1 1건, 운영 volume 1건 — rpi5 host, controller reset 후 write 재시도됨)을 잡았다. iSCSI(democratic-csi `hdd-ha-xfs`, versitygw-hdd-data)는 여전히 digest가 없다. TLS와 S3 SigV4 streaming도 본문 손상을 잡는다.
- 주의: rock5bp에서 r8169를 쓸 때 rx checksum을 끄지 않는다. r8169는 checksum이 꺼지면 모든 packet을 CHECKSUM_UNNECESSARY로 표시해 kernel이 아무것도 검증하지 않고, 실험에서 손상이 100 GiB당 약 282건으로 application까지 도달했다.
- 다음 실험(승인 필요): hardware isolation — PCIe MPS/MRRS 변경, PCIe Gen1 강제, RX buffer alignment 변경, 다른 NIC(USB 또는 M.2 i226) 장착.
- 상시 감시: `prometheus/storage-canary`가 rock5bp가 아닌 노드에서 `ssd-ha` volume에 하루 약 120 GiB를 쓰고 검증한다. Digest가 켜진 지금은 canary mismatch보다 `dmesg`의 `digest error`가 먼저 드러날 가능성이 크다.

**숨은 손상률 측정·실험 장비:**

- rock5bp에서 conntrack INVALID counter로 잰다: `iptables -L INPUT -v -x`의 `ctstate INVALID` DROP rule packet 수를 구간 전후로 읽고 `100 × Δpkts / Δ수신 GiB`를 계산하면 100 GiB당 rate가 나온다. `TcpInCsumErrors`는 0을 유지하므로 상시 신호는 이 counter다(AF_PACKET 캡처는 손상 모양을 확인하는 데 쓴다). Bulk 수신 중에는 drop이 full-size frame에서 나오는지 `pkts`와 `bytes` 증가분으로 확인한다.
- 2026-10-08..11 실험 harness는 rock5bp의 `/root/exp385`에 있다(검증 receiver, sender script, NVMe/TCP arm n0/n1). 제거할 것: nvmet subsystem `nqn.2026-10.io.exp385:n0`/`n1`, zvol `fast/exp385-n0`/`n1`, HOMELAB_PILLAR chain의 comment `exp385-armT` ACCEPT rule(tcp dport 39385), rock5bp·n2p2·rpi5·macmini의 `~/exp385`.

**알림을 받으면 순서대로:**

1. 커널 로그를 저장한다(아래 runbook 1). rock5bp의 journal은 nvmet 로그가 많아 약 6일 치만 남는다.
2. Loki에서 `MISMATCH` 줄을 찾고(runbook 2) evidence를 꺼낸다(runbook 3).
3. #385 signature와 비교한다(runbook 4). 같은 손상이면, 지금까지 나온 결론과 다른 점(node, digest 여부, 위치)이 무엇인지 본다.
4. #385에 결과를 댓글로 남기고(runbook 5), 결론이 바뀌면 이 절의 "현재 상태"를 고친다.

**접근 방법:**

| 대상 | 방법 |
|---|---|
| Cluster | `kubectl --context homelab-backbone` |
| Node SSH | `nix eval --raw .#topology.nodes.<host>.sshTarget`가 주는 `bhyoo@<IP>`(rock5bp `192.168.219.6`, rpi5 `.5`, rpi4 `.7`, macmini `.8`, n2p1 `.3`, n2p2 `.4`). Hostname은 해석되지 않는다. |
| Prometheus/Thanos | `kubectl --context homelab-backbone get --raw "/api/v1/namespaces/prometheus/services/thanos-query:9090/proxy/api/v1/query?query=<urlencoded>"`. Port-forward는 rock5bp kubelet이 불안정할 때 끊긴다. |
| Loki | `kubectl --context homelab-backbone get --raw "/api/v1/namespaces/loki/services/loki:3100/proxy/loki/api/v1/query_range?query=<urlencoded>&since=24h"` |
| Canary evidence | PVC `prometheus/storage-canary`의 `/data/evidence` (runbook 3) |
| 실험 script | rock5bp에서 `tools/storage-canary/zvol-path-experiment.sh` ("원인 좁히기 실험") |

rock5bp는 NAS 상태를 가진 storage node다. 운영 volume, ZFS 설정, nvmet port를 바꾸거나 module을 reload하는 일은 사용자 승인 없이 하지 않는다. 실험은 전용 scratch zvol·NQN·iptables rule(comment 표기)로만 하고 끝나면 지운다(이전: `hot-data/t385-*`·`nqn.2026-10.com.example:t385-*`, #385 캠페인: `fast/exp385-*`·`nqn.2026-10.io.exp385:*`·comment `exp385-armT`).

## 탐지 장치

### Canary

- Deployment `prometheus/storage-canary` (1 replica, `Recreate`). rock5bp에는 두지 않는다. rock5bp에서는 volume이 loopback으로 연결되는데, 이 경로는 2026-10-07 실험에서 재현되지 않았다. 원격 initiator와 네트워크를 거치는 경로를 감시해야 한다.
- Manifests: `apps/objects/storage-integrity/` (ArgoCD Application `argocd/apps/storage-integrity.yaml`)
- Source: `tools/storage-canary/`
- Image: `ghcr.io/isac322/storage-canary` (linux/arm64), `.github/workflows/storage-canary.yaml`가 빌드한다. Tag는 빌드한 commit SHA 앞 12자리이며 manifest는 `tag@sha256:digest`로 고정한다.

동작:

1. 시작 시 Thanos bucket에서 deletion/no-compact mark가 없는 최신 block의 chunk segment 중 256 MiB 이상인 것 6개를 고르고, S3에서 각각 두 번 받아 sha256을 계산해 manifest로 삼는다. 6시간마다, 그리고 download가 not-found를 반환하면 즉시 다시 고른다.
2. 반복마다 Thanos compactor와 같은 코드 경로인 objstore `DownloadFile`로 객체를 pillar-csi `ssd-ha` PVC(`storage-canary`, 4Gi, `/data`)의 `/data/work/<iter>/`에 받는다.
3. fsync, `fadvise(DONTNEED)` 후 `O_DIRECT`로 다시 읽어 sha256을 manifest와 비교한다.
4. 불일치하면 한 번 더 읽고, S3에서 새로 받은 stream을 다시 hash하고, 다른 byte 구간을 diff해 `/data/evidence`에 report와 1 MiB window를 저장한 뒤 `msg=MISMATCH` 로그를 남긴다.
5. iteration 디렉터리를 지운다.

Download와 검증 read가 rate limiter 하나(`-mbps 3`, 3 MB/s)를 공유하므로 하루 약 125 GiB를 검증한다. 관측 빈도대로라면 하루에 약 1건을 기대할 수 있다.

Metrics (`:9090/metrics`, port `metrics`, PodMonitor `storage-canary`):

| Metric | 의미 |
|---|---|
| `storage_canary_verified_bytes_total{arm}` | 검증 완료한 byte 수 |
| `storage_canary_iterations_total{arm,result}` | `result` = `ok` 또는 `mismatch` |
| `storage_canary_errors_total{arm,stage}` | `stage` = `select`, `download`, `fsync`, `verify` |
| `storage_canary_last_verified_timestamp_seconds{arm}` | 마지막 검증 성공 시각(unix seconds) |
| `storage_canary_last_mismatch_timestamp_seconds{arm}` | 마지막 불일치 시각 |
| `storage_canary_source_objects` | 현재 manifest의 객체 수 |

Go/process 기본 collector도 함께 노출한다.

```promql
# 하루 검증량(GiB)
sum by (arm) (increase(storage_canary_verified_bytes_total[1d])) / 2^30

# 최근 7일 불일치 횟수
sum by (arm) (increase(storage_canary_iterations_total{result="mismatch"}[7d]))
```

### Alerts

PrometheusRule `prometheus/storage-integrity`(`apps/objects/storage-integrity/prometheusrule.yaml`). Firing alert는 Grafana forwarding rule `infra-storage-integrity-alerts`(`ALERTS{alertname=~"StorageIntegrity.*", alertstate="firing"}`)를 통해 Telegram으로 간다.

| Alert | 조건과 의미 |
|---|---|
| `StorageIntegrityCanaryMismatch` | 6h 안에 `result="mismatch"` 증가(critical). canary가 읽은 데이터가 원본 sha256과 다르다. 아래 runbook 수행. |
| `StorageIntegrityCanaryStalled` | arm에서 2h 동안 검증 성공 없음. S3, PVC, 노드 상태 확인. |
| `StorageIntegrityCanaryAbsent` | `storage_canary_last_verified_timestamp_seconds`가 1h 동안 없음. Pod 미실행, scrape 실패, 또는 아직 한 번도 검증 못 함(시작 직후 object 선택에 약 30분 걸림). |
| `StorageIntegrityThanosCompactionFailures` | 1h 안에 `thanos_compact_group_compactions_failures_total` 증가. |
| `StorageIntegrityThanosBlockMarkedCorrupt` | 1h 안에 reason `block-index-out-of-order-chunk`인 no-compact mark 발생. compactor가 block을 읽다 이상을 발견한 것으로, 원인이 storage 손상인지는 따로 확인해야 한다. |
| `StorageIntegrityStoreBlockLoadFailures` | 1h 안에 `thanos_bucket_store_block_load_failures_total` 증가. store gateway가 block을 못 읽었다. |
| `StorageIntegrityPrometheusChunkCorruption` | 1h 안에 `prometheus_tsdb_mmap_chunk_corruptions_total` 증가. |
| `StorageIntegrityPrometheusCompactionFailures` | 1h 안에 `prometheus_tsdb_compactions_failed_total` 증가. |

같은 탐지 범위에 속하는 기존 Grafana rule도 있다.

- `infra-thanos-compactor-halted`: `thanos_compact_halted`(Thanos compactor halt).
- `infra-prometheus-wal-failure`: Prometheus WAL corruption.

## 손상이 잡혔을 때 (runbook)

### 1. kernel log 즉시 확보

Node kernel log는 Loki로 가지 않는다(Alloy는 pod log만 수집). Node journal은 영구 저장이지만 크기 제한으로 오래된 것부터 지워진다. rock5bp는 nvmet 로그가 많아 2026-10-07 기준 약 6일 치만 남았다. rock5bp(target)와 canary pod가 있던 node(initiator, Loki 줄의 `node` label) 둘 다 저장한다. `journalctl -k`는 현재 boot만 보므로 `_TRANSPORT=kernel`을 쓴다.

```bash
since="2026-10-07 09:00"  # 불일치 시각 2시간 전, KST
for t in 192.168.219.6 <initiator IP>; do
  ssh -o BatchMode=yes bhyoo@$t "sudo journalctl _TRANSPORT=kernel --since '$since' --no-pager -o short-iso" \
    > "kernel-$t-$(date -u +%Y%m%dT%H%M%SZ).log" </dev/null
done
```

불일치 시각 전후의 `nvmet`, `nvme_tcp`/`nvme`, `r8125`/`eth0`, ZFS, block layer 메시지를 본다. 특히 `digest error`, controller reset·reconnect, NIC link 변화를 찾는다.

### 2. 로그로 요약 확인

```logql
{namespace="prometheus", app="storage-canary"} |= "MISMATCH"
```

로그 줄에는 `arm`, `iter`, `object`, 다른 구간 수(`ranges`), `persistent`, `source_ok`, report 경로(`report`)가 있다. 구간 offset과 내용은 report 파일에만 있다.

### 3. Evidence 파일 회수

Image가 distroless라 `ls`나 `tar`가 없어 `kubectl exec ... ls`와 `kubectl cp`를 쓸 수 없다. PVC는 RWO이므로 canary를 멈추고 임시 pod에 붙여 꺼낸다.

1. ArgoCD Application `storage-integrity`의 auto-sync를 잠시 끈다(selfHeal이 replica를 되돌린다).
2. `kubectl -n prometheus scale deploy/storage-canary --replicas=0`
3. PVC `storage-canary`를 read-only로 mount하는 임시 pod를 띄운다.

   ```yaml
   apiVersion: v1
   kind: Pod
   metadata:
     name: storage-canary-evidence
     namespace: prometheus
   spec:
     restartPolicy: Never
     containers:
       - name: shell
         image: busybox:1.37.0@sha256:bdf57e528e45e4433820e045b29b4597825a1c9e38353532d90a01445013f82e
         command: ["sleep", "3600"]
         volumeMounts:
           - name: data
             mountPath: /data
             readOnly: true
     volumes:
       - name: data
         persistentVolumeClaim:
           claimName: storage-canary
           readOnly: true
   ```

4. `kubectl cp prometheus/storage-canary-evidence:/data/evidence ./evidence`
5. 임시 pod를 지우고 replica를 1로 되돌린 뒤 auto-sync를 다시 켠다.

파일은 `/data/evidence`에 평평하게 저장된다. Tag는 `<UTC 시각>-<arm>-<iter>-<object의 /를 _로 바꾼 이름>`이다.

- `<tag>.json`: report
- `<tag>-<rangeOffset>-src-<windowStart>.bin`, `<tag>-<rangeOffset>-local-<windowStart>.bin`: 다른 구간 최대 8개에 대한 원본/로컬 1 MiB window. Evidence 디렉터리가 512 MiB를 넘으면 window는 저장하지 않는다(`windows_saved=false`).

### 4. #385 signature와 비교

Report 주요 field:

- `manifest`, `first_read`, `second_read`, `fresh_s3`: 각 sha256.
- `persistent`: `second_read == first_read`. `true`면 다시 읽어도 같은 손상이 나오므로 disk에 기록된 손상이다. `false`면 read 경로에서 생긴 일시적 손상이다.
- `source_ok`: `fresh_s3 == manifest`. `false`면 S3 원본이 바뀐 것이므로 storage 손상으로 보지 않는다.
- `ranges[{offset,len,source,local}]`: 다른 구간(hex).
- `time`, `node`, `pod`, `kernel`, `mount_point`, `mount_source`, `mount_fstype`.

`local`이 `source`를 ±2/±4바이트 민 모양이고 빈 자리가 0이면, 또는 같은 파일의 거리 D만큼 떨어진 위치 바이트와 같으면 #385와 같은 현상이다. 거리 D는 window 파일에서 `local` 바이트를 검색해 구한다.

### 5. #385에 기록

시각, node, pod, `mount_source`/`mount_fstype`, ranges(offset, len, shift 또는 거리 D), `persistent`/`source_ok`, kernel 버전, ZFS 버전, pillar-csi 버전, 확보한 dmesg 발췌를 남긴다.

## 원인 좁히기 실험

Script `tools/storage-canary/zvol-path-experiment.sh`는 rock5bp에서 실행한다. Subcommand는 `setup`, `start`, `status`, `teardown`이고 환경변수는 `POOL`, `SIZE`, `DIR`, `MBPS`, `TARGET_GIB`, `MKFS`, `CANARY`다. 같은 `storage-canary` binary를 `-mode run`으로 arm 3개에 동시에 돌린다.

| Arm | 경로 |
|---|---|
| `direct` | zvol을 rock5bp에 직접 mount |
| `nvmet` | 기존 nvmet TCP port 4420으로 export, loopback 연결, digest 없음 |
| `digest` | `nvmet`과 같되 `hdr_digest`, `data_digest` 사용 |

결과 해석:

| 결과 | 결론 |
|---|---|
| `nvmet`만 손상 | target 경로가 필요조건 |
| `digest` arm에서 kernel `data digest error` 발생 | TCP 수신 측에서 손상 |
| `digest` arm은 digest error 없이 데이터만 손상 | initiator의 digest 계산 이전, 또는 target과 zvol 사이에서 손상 |

Digest가 실제로 협상됐는지는 ICResp PDU의 `dgst` byte가 `0x3`(header와 data digest 모두 사용)인지로 확인한다.

준비 사항:

- rock5bp에는 `mkfs.xfs`와 `nvme-cli`가 없다. `mkfs.xfs`는 `apt-get download xfsprogs libinih1 liburcu8`로 받은 deb를 `dpkg -x`로 풀고 `LD_LIBRARY_PATH`를 맞춰 `MKFS`로 지정한다.
- `CANARY` binary는 image에서 꺼내거나 `tools/storage-canary`에서 `CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build`로 만든다.
- Manifest는 `-mode select`로 만든다.
- `objstore.yml`은 Secret `prometheus/thanos-objstore-config`에서 꺼내되, host가 cluster DNS를 해석하지 못하므로 endpoint를 versitygw-hdd ClusterIP로 바꾼다.
- pillar-agent는 자기 것이 아닌 NQN과 `hot-data/k8s` 밖의 dataset을 무시한다. 그래서 scratch zvol `hot-data/t385-*`와 NQN `nqn.2026-10.com.example:t385-*`는 안전하다.
- 끝나면 반드시 `teardown`을 실행한다.

부하: 측정 시 arm당 약 12 MB/s였고 arm당 450 GiB에 약 10시간이 걸렸다. 실행 중에는 NAS HDD와 rock5bp `nvme0` 사용률을 지켜본다.

2026-10-07 실행 결과: 세 arm 모두 약 453 GiB에서 0건, digest 오류 0건이었다. rock5bp 안의 target 경로만으로는 재현되지 않으므로 다음 실험은 initiator를 원격 노드(예: macmini)로 옮긴다. rock5bp에서 같은 방식으로 scratch zvol과 NQN을 export하되, 원격 노드에서 `/dev/nvme-fabrics`에 `traddr=<rock5bp IP>`로 연결한다. 한 arm은 digest 없이, 다른 arm은 `hdr_digest,data_digest`로 연결하고 같은 `storage-canary -mode run`을 원격 노드에서 돌린다. 해석은 같다. digest arm에서 `data digest error`가 나면 원격 initiator와 rock5bp 사이 네트워크·NIC 구간이고, digest 오류 없이 digest arm 데이터도 손상되면 initiator 쪽(digest 계산 이전)이다. 원격 노드의 digest 오류는 그 노드의 `dmesg`(`nvme_tcp`)와 rock5bp의 `dmesg`(`nvmet_tcp`) 양쪽에서 확인한다.

이후 2026-10-08..11에 이 원격 접근 방식을 넓힌 factorial 캠페인이 손상을 rock5bp NIC 수신 경로로 좁혔다. 원격 NVMe/TCP arm(cell마다 sub-arm당 약 55 GiB)은 0건이었고, digest는 실험 arm에서 1건·운영 volume에서 1건을 잡았다. 결과와 측정 방법은 "이어받기"의 현재 상태를 본다.

## 수정 후 확인

Kernel 업그레이드, ZFS 버전 변경, `zvol_request_sync` 같은 zvol parameter 변경, digest 활성화 등 어떤 수정을 하든 canary를 계속 돌리고, 검증량 대비 불일치 비율을 수정 전후로 비교한다. 관측 빈도(90–150 GiB당 1건)를 생각하면 수정 후 최소 수백 GiB, 즉 며칠 분량을 검증해야 의미가 있다.

```promql
# 100 GiB당 불일치 수 (14일 window)
sum(increase(storage_canary_iterations_total{result="mismatch"}[14d]))
  / (sum(increase(storage_canary_verified_bytes_total[14d])) / 2^30) * 100
```

수정 시각 전후 구간을 Grafana에서 나란히 놓거나 `offset`으로 비교한다.
