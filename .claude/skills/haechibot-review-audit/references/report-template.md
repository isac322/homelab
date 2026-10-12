# haechibot review audit report: round `<round-id>`

> 이 보고서는 `$ROUND/report.md`에 둔다. owner가 요청하기 전에는 저장소나 GitHub에 올리지 않는다. 올릴 때도 `private/`, transcript, owner 세션, `notes`의 내용은 넣지 않는다(HRA-04).
> 비율은 `k/n (p̂, Wilson 95% [lo, hi])`로 적는다. `n < 10`이면 건수와 구간만 적는다. escape 기반 수치에는 `@<H>`를 붙인다. 각 수치 옆에 collector JSON key를 적는다.

## 0. 메타데이터

| 항목 | 값 |
|---|---|
| cutover T0 | 2026-10-11T20:13:52Z (image `0.30.7-codex0.160.0-20261012-review-gate`) |
| 창 A (after) | `[T0, <end>)`; 7일보다 짧으면 이유(실행 시각 − H) |
| 창 B (baseline) | `[2026-10-04T20:13:52Z, T0)` |
| evidence horizon H | `<H>`일(두 창 동일) |
| 실행 시각 | `<run_time>` (전체 창을 덮는 가장 이른 시각: 2026-10-21T20:14Z) |
| `versions.json` | homelab SHA, collector 버전, rubric/judge/gold-set/prompt hash, seed |
| 대상 repo, PR 수(창별) | |
| rater 구성 | labeler·adjudicator·verifier·matcher 모델 family; panel 모델 family; 사람 |
| `manifest.json` 잘림·API 오류, `bad_rows` | |
| pilot 결과 | rubric v2.x 변경 요약 |

## 1. 요약 (5줄 이내)

- important escaped `@H`:
- noise:
- verdict-level error:
- before/after(primary endpoint 4개):
- 이 결과로 말할 수 없는 것(metrics.md §6):

## 2. Rater 자격과 신뢰도

| 항목 | 값(κ, 95% CI, raw, PABAK, pos/neg) | n | gate | 상태 |
|---|---|---|---|---|
| gold set validity κ (rater별) | | | ≥ 0.80 | |
| gold set severity linear κ_w (rater별) | | | ≥ 0.667, CI 하한 ≥ 0.667 | |
| 감사 `irr.validity` (무작위 층, 누적 쌍) | | | ≥ 0.80 | |
| 감사 `irr.adjudicated_severity` | | | ≥ 0.667 | |
| `irr.is_defect`, `irr.verdict` | | | 기록 | |
| `match_kappa` (`match_sample` 행만, `matcher-defect_first`·`matcher-review_first` 순서별) | | | ≥ 0.80 definite / 0.667–0.80 tentative | |
| `judge_bias` (κ judge vs blind labelerB, irr_sample만; 길이 상관) | | | 기록 | |
| escalation 항목 κ (진단용) | | | — | |

CI 하한 ≥ 0.667 조건은 gold-set 자격 gate에만 적용한다. 감사 IRR은 점추정으로 판정하고 CI는 보고만 한다. 누적 IRR 쌍이 60 미만이면 그 사실을 적는다. gate 미달 라벨에 기대는 수치에는 아래 표에서 `tentative`를 붙인다. 첫 라운드에서는 gold gate의 CI 조건 때문에 tentative가 나올 수 있다고 적는다.

## 3. Noise

| 지표 | key | B | A | 선 | 상태 |
|---|---|---|---|---|---|
| validity precision | `validity_precision` | | | — | |
| 최악값(unverifiable = invalid) | `validity_precision_worst` | | | — | |
| blocking precision | `blocking_precision` | | | ≥ 90% (policy by analogy to R4-14) | |
| noise rate | `noise_rate` | | | — | |
| duplicate rate | `duplicate_rate` | | | — | |
| severity inflation / 1단계 | `severity_inflated_rate` / `over_severity_rate` | | | — | |
| nit share, 리뷰당 nit(miss 유무별) | `nit_share` | | | — | |
| findings per PR, valid blocking per PR | `findings_per_pr` / manual | | | — | |
| silent review share, verdict 분포 | `silent_review_share` | | | — | |
| addressed `@H` (보정값과 CI, 표본 n) | `addressed_rate` | | | — | |
| effective FP `@H` (record-only) | `effective_fp_rate` | | | — | |
| human addressed `@H` | `human_addressed_rate` | | | — | |
| implementer_bot PR addressed | `addressed_rate.implementer_bot` | | | — | |

추가 표: `code_rate.<CODE>`; `explicit_not_useful_rate.<coarse>.<bot_sev>`(n, pooling 수준, probation/suppress 상태); severity 혼동 행렬(bot × adjudicated); addressed 보정 표본(양성 n, PPV; 음성 n, FOR; null vicinity 수).

## 4. Miss `@H`

| 지표 | key | B | B(kwin-mcp #90–#98 제외) | A |
|---|---|---|---|---|
| `|R_imp|`(채널별 기여) | — | | | |
| important escaped (P0 / P1 / P2-blocking; panel 단독은 `.panel_only`로 따로) | `important_escaped` | | | |
| escaped per PR | `important_escaped_per_pr` | | | |
| miss rate, 전체 PR·panel 제외 | `important_miss_rate_rel` | | | |
| miss rate, panel PR·panel 포함 | `important_miss_rate_rel.panel_prs` | | | |
| partial(소계) | `important_partial` | | | |
| P0/P1 소계 | `subtotal_p0p1` | | | |
| first-exposure miss | `first_exposure_miss` | | | |
| severity miss | `important_escaped.severity_miss` | | | |
| repo-rule miss | `important_escaped.repo_rule` | | | |
| capture–recapture (indicative only; panel 대상 head에 있는 결함만; 출처 수, panel family, m; "not estimable"은 정상 결과) | `capture_recapture` | | | |

miss rate는 union reference set에 대한 상대값이며 recall이 아니다. 짧은 H의 값은 bot 효과의 상한이다.

후보 깔때기(채널별): 후보 → horizon 안 → escalated → defect_fix → present → important → escaped. blame으로 연결한 post-merge 후보와 add-only 수동 추적은 각자 줄을 둔다.

escaped 결함마다 한 줄: PR 링크, latest_present_head, 채널, 심각도, defect type, 메커니즘 한 문장, 가장 가까운 bot finding과 판정. `P0`는 별도 사례 기록을 붙인다. 공개 정보만 쓴다.

## 5. Verdict-level error와 coverage

| 지표 | key | B | A |
|---|---|---|---|
| APPROVE with important miss, merged final head | `approve_with_important_miss.merged_final` | | |
| 같은 지표, superseded head | `approve_with_important_miss.superseded` | | |
| RC without valid blocking (prove-or-fix 분리, observe-only) | `rc_without_valid_blocking` | | |
| 리뷰 못 받은 head가 있는 PR | `coverage_unreviewed_heads` | | |
| bot 리뷰를 받지 못한 PR의 결함(important 소계) | `coverage_unreviewed_defects` | | |

사례마다 링크와 한 줄 근거.

## 6. Before/after (`compare` 출력)

| primary endpoint | key | 차이(A − B) | Newcombe 95% | 검정 p | 판단 |
|---|---|---|---|---|---|
| validity precision | `comparison.validity_precision` | | | Fisher | |
| noise rate | `comparison.noise_rate` | | | Fisher | |
| important escaped per PR `@H` | `comparison.important_escaped_per_pr` | rate ratio | — | 조건부 binomial | |
| APPROVE with important miss (PR 단위) | `comparison.approve_with_important_miss.per_pr` | | | Fisher | |

나머지는 `comparison.descriptive.*`로 서술만 한다. 구간이 겹쳐도 "변화 없음"의 증거가 아니다. gold-set replay를 돌렸으면 McNemar 결과를 붙인다.

## 7. 층화

repo, size bucket, verdict, author type, file type, defect type별로 validity precision, noise rate, addressed, escaped 건수. `n < 10` 칸은 건수만.

## 8. 해석과 한계

- 한 주로 말할 수 있는 것과 없는 것(metrics.md §6 목록 기준).
- 채널의 한계: H가 짧아 늦게 드러나는 결함이 빠진다; 사람 코멘트와 owner 판단은 oracle이 아니다; panel과 rater는 모두 Claude이고 gold set도 Claude가 찾은 항목이 많아 같은 맹점을 공유할 수 있다.
- 결정적 신호(change-in-vicinity 등)는 인과가 아니며 표본으로 보정했다.
- 비용: 실제 토큰·시간 대비 상한(약 35M 토큰, 약 7시간, owner 2–3시간).
- 선택: noise 비용(owner triage 분 × noise 건수).

## 9. 제안 (적용하지 않음)

- bot 규칙·프롬프트 개선안: 근거가 된 noise code와 miss 사례를 붙인다.
- rubric·질문·프롬프트 변경안: 다음 라운드용.
- 프로세스: 수정 커밋에 `Fixes: #<PR>` 또는 `Fixes: <sha>` trailer를 쓰면 이후 추적이 쉬워진다(R3-10, R3-07).

## 10. 재계산 예정

- `<A end + 30d>`: 같은 창을 `--evidence-days 30`으로 새 DIR에 다시 수집한다. 옛 DIR의 `final` 라벨 행을 새 DIR로 복사하고, 새 DIR에 없는 id만 라벨한다. 옛 DIR은 바꾸지 않는다.
- `<A end + 90d>`: 같은 절차를 `--evidence-days 90`으로.
- 결과는 이 보고서 끝에 날짜와 함께 덧붙이고, 비교는 같은 `@H`끼리만 한다.
