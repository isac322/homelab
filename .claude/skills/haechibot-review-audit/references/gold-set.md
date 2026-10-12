---
gold_version: g1.0
created: 2026-10-12
rubric_version: v2.2
collector_version: 2.0.0
files:
  gold-findings.jsonl: sha256 351ec3cb73d87c977e28e17f4af8ba6f4691a2a8e58066104002d7ccf896ef6d
  gold-misses.jsonl: sha256 4a8e79a6840b3b55173c629987923c8f8019af2c0de64aaa6d5395bf41071f8a
part_a_findings: {rows: 55, first_occurrence: 45, duplicate: 10, valid: 43, invalid: 12, severity: {P0: 1, P1: 7, P2: 18, P3: 17, none: 12}}
part_b_misses: {items: 30, rows: 53, important_in_R_imp: 13, coverage_only_items: 3}
irr_part_a:
  validity: {n: 56, kappa: 1.000, ci95: [1.000, 1.000]}
  severity_linear_weighted: {n: 44, kappa: 0.921, ci95: [0.745, 1.000]}
  p2_blocking_v2_1: {n: 15, kappa: 0.299, ci95: [-0.203, 0.801]}
  p2_blocking_v2_2: {n: 15, kappa: 1.000, ci95: [1.000, 1.000]}
---

# Gold set g1.0

Phase 2(rater 자격)과 판정 규칙 회귀 확인에 쓰는 동결 정답 집합이다. 측정 라운드 도중에는 바꾸지 않는다(HRA-02). 바꾸면 `gold_version`을 올리고 `versions.json`의 hash를 새로 적는다. 이 파일과 두 JSONL에는 공개 저장소의 PR 번호·SHA·`file:line`·공개 bot 리뷰의 요지만 있고, owner 세션 id·로컬 경로·비공개 텍스트는 없다(D2).

## Part A: bot finding 라벨(`gold-findings.jsonl`)

- **출처 창:** pre-baseline 주간 `[T0−14d, T0−7d)` = `[2026-09-27T20:13:52Z, 2026-10-04T20:13:52Z)`, 6개 저장소 전체. baseline 창 B와 after 창 A, pilot 창 `[T0−21d, T0−14d)` 어느 것과도 겹치지 않는다.
- `noise_codes`에는 rater 코드만 들어 있다. invalid 행의 `noise_codes`가 `[]`인 것은 `INVALID`(그리고 `SEVERITY_INFLATED`)를 metrics가 파생하기 때문이다.
- **재현:** `issue-agent-review-audit collect --since 2026-09-27T20:13:52Z --until 2026-10-04T20:13:52Z --out <DIR>`(collector 2.0.0, `--evidence-days 3`). 이 수집의 `findings.jsonl` id가 gold 행의 `id`다. 각 행의 `gold_id`(G01–G56)는 처음 라벨링할 때 쓴 번호다. G14와 G15는 collector 2.0.0의 body·inline twin 판정으로 한 finding으로 합쳐졌으므로 행은 55개다.
- **라벨 절차:**
  1. 같은 모델 계열(Claude)의 독립 labeler 두 명이 bot 심각도·섹션·판정을 가린 입력으로 따로 라벨했다.
  2. adjudicator가 두 사람의 라벨이 갈린 항목을 reviewed head에서 다시 확인해 `final`을 정했다. owner_tie는 없었다.
- **분포(첫 등장 45건):** valid 38, invalid 7, 그리고 DUPLICATE 10건. 첫 등장 finding에 붙은 rater 코드는 AUTOMATABLE 2건, LOW_VALUE 1건이다.
  - invalid 사례: GitHub Actions `needs.<id>`의 하이픈 해석, buildkit-cache-dance `skip-extraction`의 의미, release note의 issue/PR 번호, RUNBOOK이 명시한 metric 정의, 기존 문서가 이미 요구한 Docker 빌드, libtaskmanager의 group parent `IsWindow`.
- **bot 심각도 대 gold 심각도(valid만):**

| bot \ gold | P0 | P1 | P2 | P3 |
|---|---|---|---|---|
| P1 | 1 | 7 | 7 | 1 |
| P2 | 0 | 0 | 11 | 11 |
| 없음 | 0 | 0 | 0 | 5 |

- **기대 metrics 값(회귀 확인):** 위 수집 디렉터리에 `gold-findings.jsonl`을 `labels-findings.jsonl`로 두고 `rater`를 `final`로 바꾼 뒤 `metrics`를 돌리면 다음 값이 나와야 한다. 값이 다르면 collector 또는 metrics 정의가 바뀐 것이다.
  - `validity_precision` 38/45
  - `noise_rate` 11/45
  - `duplicate_rate` 10/55
  - `severity_inflated_rate` 1/36
  - `over_severity_rate` 17/36
  - `blocking_precision` 14/17
  - `findings_per_pr` 46/69

## Part B: 알려진 miss(`gold-misses.jsonl`)

- **출처:** isac322/kwin-mcp #90, #92–#98. owner가 bot 리뷰 뒤 사람과 에이전트로 다시 리뷰하고 고치면서 찾은 30건(f00–f29)이다. 이 PR들은 baseline 창 B 안에 있으므로, baseline은 `metrics --exclude-pr isac322/kwin-mcp#90 …#98`을 붙인 값과 붙이지 않은 값을 둘 다 보고한다(D10).
- **행 구성:** 결함이 있던 bot-reviewed head마다 한 행을 둔다(`gold-fNN@<head12>`). #90은 force-push로 사라진 e923117과 0848f633 두 head에 모두 행이 있다. f22·f23과 #96의 f29는 첫 bot 리뷰가 게시되기 전에 고쳐졌으므로 `coverage_only`다. f29는 같은 Semantic PR 실패가 #97·#98 head에도 있어 그 head들에 partial 행이 있다.
- **재현:** `collect --since 2026-10-05T00:00:00Z --until 2026-10-11T20:13:52Z --repo isac322/kwin-mcp --out <DIR>` 뒤 `metrics --dir <DIR> --labels-misses gold-misses.jsonl`(rater를 `final`로 바꿔서)을 돌린다.
  - 기대값: `R_imp` 13, `important_escaped` 12(이 창의 kwin-mcp PR 17개 기준, `important_escaped_per_pr` 12/17), `important_partial` 2, `first_exposure_miss` 12/13, `subtotal_p0p1` 1/2, `coverage_unreviewed_defects` 3, `bad_rows` 없음. APPROVE 단위로는 34개 중 11개가 important miss나 partial을 안고 있었고, merge된 최종 head 13개 중에는 0개였다. owner가 merge 전에 모두 고쳤기 때문이다.
  - f22는 봇이 공개 리뷰에서 "앞서 비공개로 둔 P1 보안 우려를 닫았다"고 적은 항목이다. 놓친 결함이 아니라 공개 규칙(PRR-19)으로 보류된 것으로 보이므로, coverage 수치를 읽을 때 coverage gap으로 해석하지 않는다.

| item | PR | gold 심각도 | important | 최선 bot_match | 비고 |
|---|---|---|---|---|---|
| f00 | 90 | P1 | yes | miss | signal → AnyIO TaskGroup 예외 경로 |
| f01 | 90 | P2 (blocking) | yes | miss | 락 해제 틈의 reap. 원래 P1이었으나 SIGTERM 무시 자식이 필요해 한 단계 내림 |
| f02 | 90 | P2 (blocking) | yes | miss | close 뒤 temp dir 등록 누수 |
| f03 | 90 | P2 (blocking) | yes | miss | launch와 등록 사이 signal |
| f04 | 90 | P3 | no | miss | 새 `ty: ignore` |
| f05 | 90 | P2 | no | miss | PR 본문 주장 불일치(SIGINT) |
| f06 | 90 | P3 | no | miss | 문서·테스트 목록(repo_rule) |
| f07 | 90 | P2 | no | miss | 수정 없이도 통과하는 테스트 |
| f08 | 92 | P2 (blocking) | yes | miss | 축소 좌표의 픽셀 중심 |
| f09 | 92 | P3 | no | miss | 가장자리 색 번짐. 원래 P2였으나 영향 범위가 작아 내림 |
| f10 | 92 | P2 (blocking) | yes | miss | 이름 예약 race. bot은 Verified 섹션에서 "괜찮다"고 적었다 |
| f11 | 92 | P3 | no | miss | 중복 CLI flag. 원래 P2였으나 운영자 오용 경로라 내림 |
| f12 | 92 | P2 (blocking) | yes | miss | 기존 결함을 이 PR이 노출함(`exposed_by_pr`) |
| f13 | 92 | P3 | no | miss | 문서(repo_rule) |
| f14 | 93 | P2 (blocking) | yes | partial | D-Bus 전체 deadline. 원래 P1이었으나 지연에 상한이 있어 내림 |
| f15 | 93 | P2 (blocking) | yes | partial | enable-before-record. bot은 같은 hunk의 다른 race를 짚었다 |
| f16 | 93 | P3 | no | miss | 문서(repo_rule) |
| f17 | 94 | P2 (blocking) | yes | miss | 같은 크기 sibling 오매칭 |
| f18 | 94 | nit | no | miss | 테스트의 `type: ignore`. 문서화된 규칙이 없음 |
| f19 | 94 | P3 | no | miss | 낡은 주석·문서(repo_rule) |
| f20 | 95 | P2 (blocking) | yes | miss | Exec= 파싱 불일치 |
| f21 | 95 | P2 | no | partial | SELinux 우회(`policy_risk`). bot은 Not verified에만 남겼다 |
| f22 | 96 | P1 | yes | coverage_only | 게시된 리뷰 전 수정. bot이 공개하지 않은 P1을 가졌던 흔적만 있다 |
| f23 | 96 | P3 | no | coverage_only | 문서(repo_rule) |
| f24 | 97 | P2 (blocking) | yes | miss | 숫자 geometry 검증 |
| f25 | 97 | P3 | no | partial | requested 대 observed 보고 |
| f26 | 97 | P3 | no | miss | tool 수 문서(repo_rule) |
| f27 | 98 | P1 | yes | hit | 불완전 탐색에서 invoke |
| f28 | 98 | P3 | no | miss | 문서(repo_rule) |
| f29 | 96–98 | P3 | no | coverage_only / partial | Conventional Commits 제목(repo_rule) |

원래 세션 기록과 달리 판정한 항목은 위 표의 비고에 이유를 적었다(f01, f09, f10, f11, f14, f15, f25, f26, f29). f12는 `pre_existing`이 아니라 `defect_fix`이고 `exposed_by_pr`다.

## 사용법(Phase 2)

1. **Part A:** 새 rater(labeler 프롬프트, judge 설정 포함)가 위 수집을 입력으로 받아 bot 심각도를 가린 채 55건 **전부**를 라벨한다. 그런 다음 `issue-agent-review-audit kappa --a <rater 라벨> --b gold-findings.jsonl --rater-b gold --all-items --field validity --field severity --field p2_blocking`을 돌린다. 출력의 validity `n`은 55여야 하고, severity `n`은 두 쪽 모두 valid로 본 항목 수여야 한다. 일치가 완벽하면 CI가 [1, 1]로 줄어들므로 일부만 라벨한 rater는 n 조건으로 떨어뜨린다. 합격 기준은 validity κ ≥ 0.80, severity 선형가중 κ ≥ 0.667, 그리고 CI 하한 ≥ 0.667이다(HRA-05). p2_blocking κ는 기록만 한다.
2. **Part B:** candidate verifier와 matcher 프롬프트를 kwin-mcp 수집에 돌려 같은 13개 important 결함과 bot_match를 다시 만드는지 본다. 결과를 `metrics`의 기대값과 비교한다.
3. 합격하지 못한 rater의 라벨은 그 라운드에서 `tentative`로 표시한다.

## 알려진 한계

- **두 labeler가 같은 모델 계열이었다.** validity κ 1.0은 독립된 사람 둘의 합의보다 낙관적일 수 있다. 첫 측정 라운드에서 owner가 무작위 10건을 직접 확인해 이 값을 보정한다.
- **p2_blocking 정의를 한 번 고쳤다.**
  - v2.1 정의에서는 κ가 0.299였다. 테스트·CI만 깨지는 결함을 blocking으로 볼지에서 갈렸다.
  - adjudicator가 v2.2 정의를 제안했고, 같은 labeler들이 그 정의로 P2 항목만 다시 판정해 κ 1.0(n=15)을 얻었다. 다시 판정할 때 labeler들은 자기 첫 라벨을 알고 있었다.
- **Part B의 miss는 한 builder가 정했다.** 세션 기록과 적대적 비평 표를 대조해 정했고, 갈린 항목은 위 표에 적었다.
