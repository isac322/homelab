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

## 탐지 장치

### Canary

- Deployment `prometheus/storage-canary` (1 replica, `Recreate`)
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

### 1. rock5bp kernel log 즉시 확보

Node kernel log는 Loki로 가지 않고(Alloy는 pod log만 수집) `dmesg`는 ring buffer라 금방 덮어써진다. 가장 먼저 저장한다.

```bash
ssh rock5bp 'sudo dmesg -T' > rock5bp-dmesg-$(date -u +%Y%m%dT%H%M%SZ).log
```

불일치 시각 전후의 nvmet, nvme-tcp, ZFS, block layer 메시지를 본다.

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

## 수정 후 확인

Kernel 업그레이드, ZFS 버전 변경, `zvol_request_sync` 같은 zvol parameter 변경, digest 활성화 등 어떤 수정을 하든 canary를 계속 돌리고, 검증량 대비 불일치 비율을 수정 전후로 비교한다. 관측 빈도(90–150 GiB당 1건)를 생각하면 수정 후 최소 수백 GiB, 즉 며칠 분량을 검증해야 의미가 있다.

```promql
# 100 GiB당 불일치 수 (14일 window)
sum(increase(storage_canary_iterations_total{result="mismatch"}[14d]))
  / (sum(increase(storage_canary_verified_bytes_total[14d])) / 2^30) * 100
```

수정 시각 전후 구간을 Grafana에서 나란히 놓거나 `offset`으로 비교한다.
