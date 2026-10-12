# Metrics v2.4

`issue-agent-review-audit metrics`가 계산하는 수치의 정의다. 아래 §1 표의 `collector JSON key`가 collector 출력 키와 1:1로 대응한다. 표에 `manual`이라고 적힌 것은 collector가 내지 않으므로 감사자가 collector 출력과 라벨 파일에서 직접 계산한다.

입력: 창 하나의 collect DIR(`prs.jsonl`, `reviews.jsonl`, `findings.jsonl`, `candidates.jsonl`, `coverage.jsonl`, `manifest.json`)과 그 DIR의 `labels-findings.jsonl`, `labels-misses.jsonl`, `labels-judge.jsonl`, `labels-matcher.jsonl`, `panel.json`. 라벨 행 형식과 어휘는 `rubric.md` §12다. 같은 `id`에 행이 여럿이면 `rater == final`이 adjudicated 라벨이고, `labelerA`/`labelerB`는 IRR에만 쓰인다. `judge` 행(`labels-judge.jsonl`)은 `judge_bias`에만, `matcher` 행(`labels-matcher.jsonl`)은 order 불일치 처리에만 쓰이며 라벨 파일 검증 대상이 아니다. 후보 judge 행(`labels-judge-candidates.jsonl`)과 `panel-status.jsonl`은 metrics가 읽지 않는다. 모든 head 기반 수치(`coverage.jsonl`, panel 대상 head, 결함 행의 head)는 collector가 PR마다 내는 같은 `bot_reviewed_heads` 목록을 쓴다(rubric §9). `metrics --exclude-pr OWNER/REPO#N`(반복 가능)은 지정 PR을 모든 수치에서 뺀다(kwin-mcp #90–#98 제외 baseline용).

## 0. 기호와 집합

- `F` = 창 안 bot finding 중 `final` 라벨이 있는 것.
- `F*` = `F`에서 `DUPLICATE`(코드가 붙었거나 같은 PR의 앞선 finding과 `dedup_key`가 같은 것)와 `unverifiable`을 뺀 것.
- `bot(f)` = collector가 뽑은 bot 심각도, `adj(f)` = adjudicated 심각도. 순위는 `P0=0, P1=1, P2=2, P3=3, nit=4`.
- `noise(f)` = `validity = invalid` ∨ `SEVERITY_INFLATED(f)` ∨ `noise_codes ∩ {LOW_VALUE, NON_ACTIONABLE, OFF_SCOPE, STYLE_PREFERENCE, AUTOMATABLE} ≠ ∅`.
- `SEVERITY_INFLATED(f)` = `valid` ∧ (`adj(f) − bot(f) ≥ 2` ∨ (`adj(f) = nit` ∧ `bot(f) ∈ {P0,P1,P2}`)). rater는 이 코드를 쓰지 않는다. 라벨 행에 있으면 bad row다(D4).
- `F_closed` = merge 또는 close된 PR의 finding 중 `changed_in_vicinity_1`이 null이 아닌 것. null(force-push, LEFT side, diff 없음)은 건수만 보고하고 수동 표본으로 보낸다. `author_action = not_applicable`(PR merge·close 뒤에 게시된 리뷰의 finding)은 `F_closed`에서 뺀다(policy: pilot-kwin-20261012 T9).
- 결함 단위 = `(pr_id, dedup_key)`. miss 행 id는 `<candidate-id>[.<k>]@<head12>`(head12 = 그 행 `reviewed_head_sha`의 앞 12자리)이고, 같은 결함의 행은 `dedup_key`로 묶인다. `out_of_horizon: true` 행은 수치에서 빠진다. `R_imp` = important(adj `P0`/`P1`, 또는 `P2` ∧ `p2_blocking`), `verdict = defect_fix`, `present_at_reviewed_head = yes`인 결함과, valid important bot finding으로 metrics가 자동으로 만든 `bot_finding` hit 행의 union(D7). 둘은 Phase 5 뒤 dedup_key 조정(rubric §0)으로 같은 key를 가진다.
- **panel 단독 결함:** panel만 찾은 결함(`sources == ["panel"]`)은 panel 표본 PR에 대해서만 `R_imp`에 들어간다. 모든 PR 기준 수치(`important_escaped`, `important_escaped_per_pr`, `important_miss_rate_rel`)에서는 빼고 `important_escaped.panel_only`로 따로 보고하며, `important_miss_rate_rel.panel_prs`에만 들어간다. panel 단독 `P0` 결함도 P0 사례 기록 규칙을 따른다.
- 결함의 `best_match` = 그 결함 행들 중 `hit > partial > miss`로 가장 좋은 값.
- 판정 단위 = 서로 다른 `(pr, reviewed_head)`. verdict는 body의 `**Verdict: X**` 줄에서 온다.
- `@H` = evidence horizon(기본 3일, D1). escape 기반 수치(miss 쪽 전부, `addressed_rate`)는 `@H`를 붙여 적는다. 짧은 H의 값은 bot 효과의 **상한**이다(R3-01, R3-12).

## 1. 수치 표

| figure | formula | denominator | collector JSON key | CI method | threshold (source or 'policy') |
|---|---|---|---|---|---|
| Validity precision | `|{f∈F*: valid}| / |F*|` | `F*` | `validity_precision` | Wilson | 없음. D13 primary endpoint 1 |
| Validity precision, 최악값 | `valid / (valid + invalid + unverifiable)` | `F` − DUPLICATE | `validity_precision_worst` | Wilson | 없음 |
| Blocking precision | validity precision을 `bot(f) ∈ {P0,P1}`로 제한 | `F*` 중 bot P0/P1 | `blocking_precision` | Wilson | ≥ 90% valid: **policy by analogy to R4-14** (Tricorder 90% 기준은 effective FP이지 validity가 아니다) |
| Noise rate | `|{f∈F*: noise(f)}| / |F*|` | `F*` | `noise_rate` | Wilson | 없음. D13 primary endpoint 2 |
| Code rate | `|{f∈F*: c(f)}| / |F*|`, `c` ∈ INVALID, SEVERITY_INFLATED(파생), LOW_VALUE, NON_ACTIONABLE, OFF_SCOPE, STYLE_PREFERENCE, AUTOMATABLE | `F*` | `code_rate.<CODE>` | Wilson | 없음. Tricorder 10%/25%는 analyzer별 비율이라 여기 적용하지 않는다(R2-02) |
| Duplicate rate | `|DUPLICATE| / |F|`(unverifiable 포함) | `F` | `duplicate_rate` | Wilson | 없음(policy, D3) |
| Over-severity(1단계) | `|{f: valid, adj(f) − bot(f) = 1}|` / valid finding 중 bot 심각도 있음 | valid `F*` ∧ bot 심각도 | `over_severity_rate` | Wilson | 없음. noise 아님(D4) |
| Severity inflation | `|{f: SEVERITY_INFLATED(f)}|` / 같은 분모 | valid `F*` ∧ bot 심각도 | `severity_inflated_rate` | Wilson | 없음. 2단계 경계는 policy(D4) |
| Nit share | `|{f: adj = nit}| / |valid F*|`; 부속값 `per_review`: 리뷰당 nit 수를 escaped important 결함이 있는 head의 리뷰(`with_escaped`)와 없는 리뷰(`without_escaped`)로 나눠 표시 | valid `F*` | `nit_share` (`.per_review`) | Wilson; `per_review`는 CI 없음 | 없음. distraction index는 서술용(R1-13) |
| Findings per PR | `(|F*| + 라벨 없는 창 안 finding) / 리뷰된 PR 수` | 리뷰된 PR | `findings_per_pr` | 없음(서술) | 없음 |
| Valid blocking findings per PR | `blocking_precision.k / 리뷰된 PR 수` | 리뷰된 PR | manual | 없음 | 없음. rate와 volume을 짝짓는다(R2-22) |
| Silent review share | finding 0인 리뷰 / reply container를 뺀 bot 리뷰; 부속값 verdict 분포 | bot 리뷰 | `silent_review_share` (`.verdict_distribution`) | Wilson | 없음(R2-23) |
| Addressed rate | `|addressed| / |F_closed|`; addressed = `author_action`(있으면) 아니면 `changed_in_vicinity_1 ∨ author_reply_kind = ack`. implementer_bot PR은 빼고 sub-summary로 따로. `author_action = not_applicable`은 분모에 없고 그 건수는 `addressed_rate.not_applicable_excluded`에 나온다 | `F_closed` − implementer_bot PR | `addressed_rate` (`.not_applicable_excluded`) | Wilson(원값); 보정값은 §3 | 없음 |
| Effective FP | `1 − addressed_rate` | 같음 | `effective_fp_rate` | 같음 | **record-only**(D12). Tricorder `<10%`는 참고선일 뿐(R2-01, R4-14) |
| Human addressed rate | 같은 정의를 같은 PR의 사람 root inline 코멘트에 적용, PR 작성자 자신의 코멘트와 `bulgasaribot[bot]` 제외 | 사람 코멘트 `F_closed` | `human_addressed_rate` | Wilson | 없음. 같은 저장소 기준선(R2-10) |
| Explicit not-useful | `rejected / (rejected + addressed)`, family = `<coarse>.<bot severity>`(coarse = functional/evolvability). n < 10이면 `<coarse>.*`, 그다음 `*.*`로 합친다. 축별 값은 `.by_axis` | family별 | `explicit_not_useful_rate.<coarse>.<bot_sev>` | Wilson | probation: 점추정 ≥ 10% ∧ n ≥ 10 (R2-02 Tricorder 10% probation선, R1-17 교정); suppress 후보: Wilson 하한 > 10% (**policy**, D12) |
| Important escaped | `|{d∈R_imp: best_match ≠ hit}|` (partial 포함, panel 단독 제외) | — (건수) | `important_escaped`; panel 단독은 `important_escaped.panel_only` {`escaped`, `defects`, `panel_prs`, `outside_panel_prs`, `note`} | 건수 | `P0`: 0, panel 단독 포함 1건이라도 사례 기록(R4-15). 나머지 없음 |
| Important escaped per PR | `important_escaped / 리뷰된 PR 수`; 구간은 건수 x에 대한 정확 Poisson(Garwood) 95%: `[χ²(0.025; 2x)/2, χ²(0.975; 2x+2)/2]`를 PR 수로 나눈다 | 리뷰된 PR | `important_escaped_per_pr` (`.overall.ci95`, `.overall.ci_method`) | 정확 Poisson(Garwood) | 없음. D13 primary endpoint 3 |
| Important miss rate (relative) | `important_escaped / |R_imp|` = `1 − hit rate`; (a) 전체 PR·panel 제외 채널, (b) `panel_prs`: panel PR·panel 포함 | `|R_imp|` | `important_miss_rate_rel` (`.panel_prs`) | Wilson | 없음. recall이라고 부르지 않는다(R4-15, R3-24) |
| Important partial | `|{d: best_match = partial}| / |R_imp|` | `|R_imp|` | `important_partial` | Wilson | 없음 |
| P0/P1 소계 | important miss rate를 adj `P0`/`P1`로 제한 | `|R_imp ∩ {P0,P1}|` | `subtotal_p0p1` | Wilson | 없음 |
| First-exposure miss | 결함이 처음 있던 head의 행이 `hit`이 아닌 결함 / `|R_imp|` | `|R_imp|` | `first_exposure_miss` | Wilson | 없음(보조, D3) |
| Severity miss | `best_match = hit` ∧ `adj − bot ≤ −2`인 결함 수 | — (건수) | `important_escaped.severity_miss` | 건수 | 없음(R3-23) |
| Escaped by first source | important escaped 결함(panel 단독 제외)을 그 결함을 처음 독립적으로 드러낸 출처로 나눈 건수: `bot`(가장 좋은 판정이 `partial`), `human_review`(owner 세션, 또는 구현 봇이 아닌 사람의 코멘트), `panel`, `fix_evidence_only`(수정 커밋·post-merge 커밋·이후 이슈만). metrics는 증거 시각을 비교하지 않고 고정된 순서 bot > human_review > panel > fix_evidence_only를 "가장 이른 출처"의 대용으로 쓴다(bot은 리뷰 때, 사람 재리뷰는 PR 도중, panel은 감사 때 말하기 때문이다). 합은 `important_escaped`와 같다 | — (건수) | `important_escaped.by_first_source` | 건수 | 없음(policy: pilot-kwin-20261012 A4). 새 비율을 만들지 않는다. owner 재리뷰가 없는 주에는 panel만 독립 출처다 |
| Label conflicts | `final` miss 행의 `bot_match ∈ {hit, partial}`인데 그 `matched_finding_id`의 `final` validity가 `invalid`인 행 | — (목록) | `conflicts`(metrics 출력 최상위 키) | 없음 | 없음. bad row가 아니라 adjudicator에게 다시 보낼 목록이며 수치에는 그대로 들어간다. finding `final` 라벨이 있을 때만 계산한다(policy: pilot-kwin-20261012 A7) |
| Panel precision | panel judge가 confirmed로 판정한 항목 / A·B 병합 뒤 보고된 panel 항목; rejected와 unverifiable 건수를 같이 적는다 | 병합된 panel 항목 | manual(`panel-status.jsonl`) | Wilson | 없음(policy: pilot-kwin-20261012 T1) |
| Repo-rule miss | `repo_rule = true`이고 `best_match ≠ hit`인 결함 수(important 여부 무관) | — (건수) | `important_escaped.repo_rule` | 건수 | 없음(policy) |
| APPROVE with important miss | important 결함 묶음 중 그 head의 행이 `miss`나 `partial`인 것이 있는 APPROVE 단위 / APPROVE 단위; `per_pr`: 그런 APPROVE `(pr, head)` 단위가 하나 이상 있는 PR / APPROVE 단위가 하나 이상 있는 PR; `merged_final`: merge된 PR의 최종 head만(서술); `superseded`: 나머지. head는 리뷰 본문에 적힌 head다(rubric §9). 그래서 base branch만 merge한 커밋 위에 게시된 APPROVE는 그 리뷰가 적은 앞 head의 단위가 되어 `superseded`로 센다(gold g1.1의 `merged_final` 분모가 13에서 11로 준 이유, policy: pilot-kwin-20261012 N4) | 서로 다른 APPROVE `(pr, head)`; `per_pr`은 APPROVE가 있는 PR | `approve_with_important_miss` (`.per_pr`, `.merged_final`, `.superseded`) | Wilson; 비교는 Newcombe + Fisher | 0, 사례마다 기록(**policy**). `per_pr`이 D13 primary endpoint 4 |
| RC without valid blocking | 어떤 finding도 `valid ∧ (adj ∈ {P0,P1} ∨ (adj = P2 ∧ p2_blocking))`이 아닌 REQUEST_CHANGES 단위 / RC 단위; `prove_or_fix`(구현 봇 PR, 미반박 의심만) 분리; 자기 finding 없는 head는 `excluded_no_own_findings`로 나열 | 서로 다른 RC `(pr, head)` | `rc_without_valid_blocking` | Wilson | **observe-only**(D14). 심각도 기반(R4-06, R1-14 교정) |
| Review coverage | 수정 커밋이나 merge 전에 bot 리뷰를 받지 못한 head가 있는 PR, 그리고 실패·중단 코멘트만 받은 PR / `coverage.jsonl`의 PR | `coverage.jsonl` PR | `coverage_unreviewed_heads` | Wilson | 없음(D16). miss와 섞지 않는다 |
| Coverage-only defects | `coverage_only: true` miss 행의 결함 수(rubric §6: bot 리뷰를 한 번도 받지 못한 PR의 결함, 첫 bot-reviewed head 전에 들어왔다 고쳐진 결함, reviewed head들 사이에만 있던 결함, 마지막 reviewed head 뒤에 들어온 결함); `important` 소계; repo·author_type·adjudicated_severity별 | — (건수) | `coverage_unreviewed_defects` (`.important`); 행 수는 coverage의 `miss_rows_coverage_only` | 건수 | 없음(policy). `R_imp`와 모든 miss 수치에서 뺀다 |
| Capture–recapture | §4 | panel PR의 important 결함 | `capture_recapture` | 없음(범위) | 없음. indicative only |
| IRR | κ, 95% CI, raw agreement, PABAK, 범주별 positive/negative agreement. validity Cohen κ, severity **linear** κ_w(quadratic은 부속값), `is_defect`, `verdict`, `important`(finding)와 `important_miss`(miss 행): 파생값, adj `P0`/`P1` 또는 `P2` ∧ `p2_blocking`, null 심각도는 not important | `irr_sample: true` 항목의 labelerA·labelerB(둘 다 judge 제안을 보지 않음) | `irr.<field>` (`kappa` 서브커맨드로도) | κ CI(collector 구현) | 감사 IRR: 점추정 validity κ ≥ 0.80, severity κ_w ≥ 0.667(R4-17, Krippendorff via Hallgren). CI는 보고만 한다. **CI 하한 ≥ 0.667 조건은 gold-set 자격 gate(HRA-05)에만 적용**(policy, D10). `important`·`important_miss` κ는 문턱 없이 기록한다(policy: pilot-kwin-20261012 A5) |
| Matching κ | 순서별로 `κ(bot_match: matcher-defect_first vs 사람 final)`, `κ(bot_match: matcher-review_first vs 사람 final)` | `match_sample: true` 행만(사람 값이 final을 대체한 행) | `match_kappa.defect_first`, `match_kappa.review_first` | κ CI | 두 순서 모두 ≥ 0.80이면 definite, 0.667–0.80 tentative, 그 아래는 자동 매칭 불신(D11, R4-17) |
| Judge bias | `κ(validity: judge vs labelerB)`와 finding 길이 vs judge "valid" 제안의 point-biserial 상관 | `irr_sample: true` finding 중 judge 행과 blind labelerB 행이 모두 있는 것 | `judge_bias` | κ CI | 없음. 기록(R4-19, R4-20) |
| Before/after | §5 | 두 창의 `metrics --format json` 출력 | `comparison.<endpoint>`, 나머지 비율은 `comparison.descriptive.<key>` (`compare` 서브커맨드) | Newcombe / Fisher / 조건부 binomial | primary endpoint 4개만 검정 |

모든 수치는 해당하는 층(§7)별로도 나온다.

## 2. Wilson 구간

모든 비율에 Wilson 95% 구간을 붙인다. Wald 구간은 쓰지 않는다(R3-28).

```
p̂ = x/n, z = 1.96
center = (p̂ + z²/(2n)) / (1 + z²/n)
half   = z / (1 + z²/n) · sqrt(p̂(1 − p̂)/n + z²/(4n²))
CI     = [center − half, center + half]
```

참고값(R3-28 교차검증 재계산): 6/10 → 0.31–0.83, 12/20 → 0.39–0.78, 24/40 → 0.45–0.74, 48/80 → 0.49–0.70. `n < 10`이면 건수와 구간만 적고 헤드라인 점추정으로 쓰지 않는다.

finding은 PR 안에서 군집하므로 Wilson은 약간 낙관적이다(DUPLICATE 제거 후 design effect 약 1.1–1.2, StatsCritic 추정). 선택: PR 단위 cluster bootstrap 구간을 민감도로 붙인다.

## 3. Addressed 보정

자동 분류(`changed_in_vicinity_1 ∨ ack`)의 인과를 사람이 확인한다(R2-05, R1-04). 보조 민감도는 `changed_in_vicinity_5`로 바꾼 같은 계산이다. bot 자신의 다음 리뷰가 적은 `Closed`는 쓰지 않는다(D12, R2-28).

- 표본: 두 창을 합쳐 자동 양성에서 최대 40, 자동 음성에서 최대 20을 seed로 뽑는다. 양성이 40보다 적으면 전부 확인하고 달성한 n을 적는다.
- 확인자: owner, 또는 blind 에이전트(이 경우 결과를 tentative로 표시).

```
PPV = 양성 표본 중 실제 addressed 비율,  FOR = 음성 표본 중 실제 addressed 비율
addressed_corrected = (pos·PPV + neg·FOR) / N
Var = (pos/N)²·PPV(1−PPV)/n_pos + (neg/N)²·FOR(1−FOR)/n_neg
CI  = addressed_corrected ± 1.96·sqrt(Var)
```

이 값은 층화 추정량이라 Wilson을 쓰지 않는다(StatsCritic).

주의(보고서에 그대로 적는다): ±1줄 change trigger는 사람 리뷰에서 precision 88%, recall 78%였다(R1-04). 변경은 인과가 아니다(R2-09). thread resolved는 근거가 아니다(R1-22, R2-12). 수용은 싼 수정에 치우친다(R2-13). owner가 한 사람이라 분산이 크다(R4-13). 닫혔지만 merge되지 않은 PR은 따로 보인다. 구현 봇 PR의 addressed는 noise나 유용성의 증거가 아니다.

참고값(target 아님, D14): AutoCommenter는 개발자 피드백 54%, blind rater 60%를 관측했고 목표는 80%였다(R1-21, R2-07). Atlassian CRR은 bot 38.70%, 사람 44.45%였다(R2-10). Tricorder 최상위 analyzer의 not-useful 비율 0–3%는 서술용이다(R2-02, D14). Bosu의 사람 리뷰 유용성 약 65%는 nit를 useful로 접은 분류기 기반이라 직접 비교할 수 없다(R1-06).

## 4. Capture–recapture (indicative only)

- 모집단: `panel.json`의 panel PR에서, panel **대상 head에 있는**(그 head 행의 `present_at_reviewed_head = yes`) 확인된 important 결함만(D9, R3-14). 대상 head 전에 고쳐진 결함은 panel이 볼 수 없으므로 넣지 않는다.
- 출처와 포획: `bot` = 그 결함의 **대상 head 행**이 `bot_match = hit`. `panel` = panel 항목이 그 결함으로 확인됨(reviewer A·B는 한 family로 한 출처). `human_blind` = 사람 코멘트가 그 결함을 지적했고, 그 코멘트가 대상 head 시점(대상 head의 bot 리뷰 `submitted_at`) 이전 또는 같은 시각이며, 그 PR의 첫 bot 리뷰보다 먼저 달렸다. fix 기반 채널(`post_review_hunk`, `post_merge_commit`, `cross_reference`, `owner_session`)은 출처로 쓰지 않는다. in-PR 수정은 bot finding에 반응한 것이 많아 bot과 양의 상관이 있고, post-merge 채널은 닫힌 모집단 표본이 아니기 때문이다(R3-13, R3-18). panel PR이 10개라 m ≥ 7은 드물고, "not estimable"은 정상 결과다.

```
2 출처:  Chapman  N̂ = (n1 + 1)(n2 + 1)/(m + 1) − 1
≥3 출처: bias-corrected Chao2  N̂ = S_obs + ((k − 1)/k) · Q1(Q1 − 1) / (2(Q2 + 1))
```

`m` = 두 출처가 모두 찾은 수, `k` = 출처 수, `Q1`/`Q2` = 정확히 1개/2개 출처가 찾은 결함 수(R3-15, R3-17; Chao 1987의 원식은 `f1²/(2f2)`이고 여기서는 bias-corrected 형식을 쓴다). `m < 7`이면 "not estimable"이라고만 적는다(D9). 값은 출처 수, panel 모델 family와 함께 적는다. bot과 panel이 모두 LLM이라 포획이 양의 상관을 가지므로 N̂는 낮게 치우친다(R3-18). singleton 비율은 상한으로 쓰지 않는다(R3-19 교정).

## 5. Before/after 비교

- 창(D1): after `A = [T0, min(T0+7d, run_time − H))`, baseline `B = [T0−7d, T0)`, `T0 = 2026-10-11T20:13:52Z`. 두 창에 같은 H(기본 3일)를 쓴다. 후보는 증거 시점 ≤ anchor + H일 때만 센다. 전체 창을 덮는 가장 이른 실행은 T0+10d(2026-10-21T20:14Z)이며, 더 일찍 돌리면 A가 짧아지고 보고서에 그 사실을 적는다.
- 사전 등록한 primary endpoint 4개만 검정한다(D13): (1) `validity_precision`, (2) `noise_rate`, (3) `important_escaped_per_pr`, (4) `approve_with_important_miss.per_pr`. `merged_final`을 포함한 나머지는 서술이다. 계산은 `issue-agent-review-audit compare --before B.json --after A.json`이 한다(입력은 각 창의 `metrics --format json` 출력).
- 비율 차이(endpoint 1, 2, 4): after − baseline의 Newcombe hybrid score 구간과 Fisher exact p. 각 창의 Wilson 구간 `(l1,u1)`(baseline), `(l2,u2)`(after)로
  ```
  d = p2 − p1
  L = d − sqrt((p2 − l2)² + (u1 − p1)²)
  U = d + sqrt((u2 − p2)² + (p1 − l1)²)
  ```
  구간이 0을 빼면 "변했다"고 쓴다. 판정은 Newcombe 구간으로 하고, 어느 칸이든 5 미만이면 Fisher exact p로 판정한다.
- PR당 건수(endpoint 3): 조건부 binomial. 두 창의 합 `x1 + x2`가 주어졌을 때 `x2 ~ Binom(x1 + x2, n2/(n1 + n2))`로 검정한다(정확 Poisson 비율 검정과 같다).
- 겹치는 Wilson 구간은 변화가 없다는 증거가 아니다. 결정적 비교가 필요하면 gold-set replay를 쓴다(R3-22). replay는 같은 사례를 옛·새 bot에 똑같이 돌리고 사례별 paired 결과를 McNemar로 비교한다. 주입 결함 replay는 상대 비교만 한다(R3-20).
- repo·크기 구성이 주마다 다르므로, 선택적으로 repo별 Mantel–Haenszel 층화 비교를 민감도로 붙인다.
- kwin-mcp #90–#98은 gold set(f00–f29)의 출처이고 B 창에 있다. baseline은 그 PR을 넣은 값과 뺀 값을 모두 보고한다(D10).
- revert 비율이나 사고 비율로 before/after를 비교하지 않는다(R2-31 교정).
- 같은 H로 30일, 90일 뒤에 두 창을 모두 다시 계산한다(HRA-28). 비교는 같은 `@H`끼리만 한다.

## 6. Pooling과 임계값 판정

- 판정 상태: **alarm** = 나쁜 쪽 Wilson 구간 경계가 선을 넘음(좋은 쪽 비율이면 상한이 target 아래), **watch** = 점추정만 넘음, **met** = 구간 전체가 target 쪽, 그 밖은 `insufficient`(R3-28).
- family·code·severity 묶음 판단은 묶음당 `n ≥ 10`이 될 때까지 주를 합친다(R1-16, R2-02 교차검증).
- 합치는 조건: `versions.json`의 collector 버전, `rubric_version`, judge 질문 `version`, gold-set 버전, prompt hash, H가 모두 같다(R4-22).
- IRR은 무작위 층(`irr_sample: true`, 약 20%)에서만 계산하고, 60쌍이 될 때까지 라운드를 합친다. escalation 항목의 κ는 진단용이다(D10, R4-16, R4-18).
- gold-set 자격 gate(HRA-05)는 validity κ, severity κ_w와 함께 `p2_blocking` 일치도와 `important` 일치도도 보고한다. `p2_blocking`은 두 rater가 모두 P2로 매긴 항목에서 Cohen κ(와 raw agreement, n)다. 2026-10 gold 보정에서 두 blind 라벨러가 56개 중 7개에서 갈린 유일한 불안정 필드였다(validity κ 1.0, severity κ_w 0.921). pilot-kwin-20261012에서는 labelerA와 labelerB가 bot finding 8개 중 4개에서 important 여부를 바꿨다(하나는 validity, 셋은 심각도 차이). 두 κ에는 문턱을 두지 않고 기록하며, 낮으면 rubric §2를 다시 pilot한다(policy).
- κ gate 미달 라벨에 기대는 수치에는 `tentative`를 붙인다.

### 한 주로 말할 수 있는 것과 없는 것 (StatsCritic 시뮬레이션, 약 70 PR)

- 말할 수 있다: 전체 validity precision과 noise rate(약 ±8pp, 서술), noise code 구성(서술), important miss와 P0 miss의 존재와 사례 목록, APPROVE-with-miss 사례 목록, verdict error 사례 목록, duplicate rate, findings per PR.
- 말할 수 없다: recall 또는 recall 비슷한 수치, 90% target 대비 blocking precision 판정, 보정 전 effective FP 판정, code별 억제 결정, 층별 비율(대부분 칸이 n < 10), precision 약 12pp 미만의 before/after 변화, miss 건수의 변화, capture–recapture N, n=30에서 믿을 만한 κ gate 통과, P0 심각도 합의.

## 7. 층화 (D15)

헤드라인 비율은 다음으로도 나눈다. `n < 10` 칸은 건수만 적는다.

- `repo`
- `size_bucket`: `S` < 50 changed lines, `M` < 400, `L` ≥ 400 또는 ≥ 20 files. 줄 경계는 **owner policy**이고 ≥ 20 files 경계만 R1-14가 뒷받침한다. 크기가 커질수록 유용성이 떨어진다(R1-06, R1-14).
- `verdict`: body verdict(GitHub 상태가 아님)
- `author_type`: `owner`, `implementer_bot`, `automation`, `external`
- `file_type`: `code`, `test`, `build_config`, `docs`. 빌드·설정 파일 코멘트는 유용성이 낮다(R1-06)
- `defect_type`: functional / evolvability. addressed와 effective FP는 반드시 이 축으로도 본다. 수용은 리팩터링 쪽으로 치우친다(R2-13)

miss는 채널과 defect subtype으로도 센다(R4-09). 채널별 후보 깔때기(후보 → escalated → defect_fix → present → important → escaped)를 보고하고, blame으로 연결한 post-merge 후보는 자기 줄을 둔다(R3-07).

## 8. Target과 alarm 요약 (D14)

| 지표 | 선 | 출처 표시 |
|---|---|---|
| `blocking_precision` | ≥ 90% valid | policy by analogy to R4-14 |
| `explicit_not_useful_rate.<coarse>.<bot_sev>` | probation 점추정 ≥ 10%(n ≥ 10); suppress 후보 Wilson 하한 > 10% | probation: R2-02, R1-17 교정; suppress 규칙: policy |
| `important_escaped`, `P0` | 0, 사례마다 기록 | R4-15 ("P0 miss는 incident") |
| `approve_with_important_miss` | 0, 사례마다 기록 | policy |
| `rc_without_valid_blocking` | observe-only | policy (출처 없음, D14) |
| `effective_fp_rate` | record-only, `human_addressed_rate`와 비교 | D12; Tricorder 10%는 참고선(R2-01) |
| useful ratio | target 없음 | AutoCommenter 54%/60% 관측, 80% 목표는 맥락(R1-21, D14) |

사람 리뷰 35% 하한(R1-06 교정)과 vendor 벤치마크 수치는 쓰지 않는다.

## 9. 선택 지표

- noise 비용: owner가 noise finding 5–10개를 triage하는 시간을 재고 `noise 건수 × 중앙값 분`으로 적는다(R2-30). 서술용이다.
