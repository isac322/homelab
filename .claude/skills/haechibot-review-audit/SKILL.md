---
name: haechibot-review-audit
description: "Audit the review quality of haechibot, the homelab automated PR reviewer (`haechibot[bot]`), over a time window: count important escaped misses (significant defects present at a bot-reviewed head that the bot never reported) and noise (invalid, low-value, nitpicky, off-scope or severity-inflated findings), against a same-procedure baseline before the 2026-10-11 review-gate cutover. Use when the owner asks to evaluate, audit, measure or compare haechibot reviews, review noise, missed bugs, false positives or the effect of a review-prompt change, or says the week-after audit can start. Read-only: never changes the bot profile, GitHub state or the cluster."
---

# haechibot review audit

haechibot 리뷰가 한 기간 동안 **중요한 결함을 놓쳤는지(important escaped)**와 **쓸모없는 지적을 냈는지(noise)**를 같은 절차로 재는 방법이다. 규칙은 `HRA-xx`이고, 괄호 안은 근거 claim이다. **policy**는 출처 없이 owner·감사 설계가 정한 것이다. claim과 policy의 구분, 출처 충돌의 선택은 `references/sources.md` §3에 있다.

| 파일 | 내용 |
|---|---|
| `references/rubric.md` | 모든 라벨과 관찰 가능한 테스트, 라벨 파일 행 |
| `references/metrics.md` | 수치 표(공식, 분모, collector JSON key, CI, 임계값), 비교, pooling |
| `references/agent-prompts.md` | 역할별 동결 프롬프트 |
| `references/judge-questions.json` | `judge_batch` 1차 triage 질문, state builder, escalation |
| `references/report-template.md` | 보고서 형식 |
| `references/gold-set.md` | rater 자격 시험용 보정 세트로, 별도 단계에서 만든다. (A) 사전 baseline 주 `[T0−14d, T0−7d)`의 bot finding 40개 이상을 이중 라벨하고 adjudicate한 것, (B) kwin-mcp miss f00–f29를 비식별화한 것. frontmatter에는 version, part·등급별 항목 수, 만든 라벨러들의 κ 결과가 있다 |
| `references/sources.md` | 출처, 교정, 규칙 → claim 매핑 |

## 경계

- 읽기 전용이다. GitHub에는 GET과 GraphQL 조회만 한다. bot 프로필(`apps/objects/issue-agent/profile`), 저장소, 클러스터를 바꾸지 않는다. bot 개선안은 보고서의 제안으로만 적는다.
- 라운드 산출물은 모두 `$ROUND`에 있고, owner가 요청하기 전에는 아무것도 공개하지 않는다(HRA-04).

## 입력과 저장 위치

- `T0 = 2026-10-11T20:13:52Z`. after 창 `A = [T0, min(T0+7d, run_time − H))`, baseline 창 `B = [T0−7d, T0)`. evidence horizon `H` 기본값은 3일이고 두 창에 같은 값을 쓴다. 전체 창을 덮는 가장 이른 실행은 T0+10d(2026-10-21T20:14Z)다.
- `$ROUND = ~/.local/state/haechibot-review-audit/<round-id>/`(0700): `baseline/`, `after/`(collect DIR과 라벨 파일), `private/`(창별 owner 세션 후보 `private/<window>/`, runner transcript, 비공개 notes), `queue/`(섞인 라벨링 큐와 `map.jsonl`), `scratch/`(checkout), `versions.json`, `report.md`.
- 도구: `apps/objects/issue-agent/operations/issue-agent-review-audit`의 `collect --since --until --out --evidence-days H`, `panel-draw --dir --n --seed`, `metrics --format json [--labels-findings F] [--labels-misses F] [--labels-judge F] [--labels-matcher F] [--exclude-pr OWNER/REPO#N ...]`, `kappa --a --b [--rater-a --rater-b] [--all-items] [--field validity|severity|p2_blocking|bot_match|is_defect|verdict ...]`, `compare --before B.json --after A.json`; `issue-agent-records`; omp eval의 `archive`, `judge_batch`.

## 규칙

- **HRA-01** 단위를 고정한다. finding은 첫 등장 단위이고, 재진술은 `DUPLICATE`로 분모에서 뺀다. 결함은 `(pr_id, dedup_key)` 단위이며 결함이 있던 bot-reviewed head마다 id `<candidate-id>[.<k>]@<head12>`인 행을 쓴다. verdict 지표는 서로 다른 `(pr, head)` 단위로 센다. 판정은 그 head를 checkout해서 한다 (R2-16, R3-11, R2-06; 단위와 id 형식은 policy).
- **HRA-02** 창 A·B와 horizon H를 위와 같이 쓴다. 후보는 증거 시점 ≤ anchor + H일 때만 센다. escape 기반 수치에는 `@H`를 붙이고, 짧은 H의 값은 bot 효과의 상한이라고 적는다 (R3-01, R3-12; 창 경계와 H 값은 policy).
- **HRA-03** 측정 전에 pilot을 하고 버전을 동결한다. pilot은 `[T0−21d, T0−14d)`의 리뷰(모든 repo)로 해서 gold set 주와 창 B를 깨끗하게 둔다. 바뀐 rubric은 v2.x로 올리고, `versions.json`(homelab SHA, collector 버전, rubric·judge·gold·prompt hash, seed)을 라운드 동안 고정한다. 버전이 다른 결과는 합치지 않는다 (R4-22, R3-16; pilot 창은 policy).
- **HRA-04** `private/`, transcript, owner 세션, `notes`의 내용은 저장소, GitHub, 공개 보고서에 넣지 않는다. 저장소에 들어가는 gold set에는 공개 PR 번호, SHA, 공개 bot 리뷰 인용만 둔다 (policy).
- **HRA-05** 모든 rater 구성은 gold set을 통과해야 한다: validity Cohen κ ≥ 0.80, severity linear κ_w ≥ 0.667, 둘 다 95% CI 하한 ≥ 0.667. rater는 Part A 항목을 **전부** 라벨해야 하며, κ의 n은 gold 수와 같아야 한다(validity n = 55, severity n = 둘 다 valid로 본 항목). 완전 일치에서는 CI가 0 폭으로 줄어드므로 작은 n은 절대 통과시키지 않는다. CI 하한 조건은 이 자격 gate에만 쓴다. 미달 rater의 라벨은 tentative다. judge의 관대함을 사람과 비교해 기록한다 (R4-18, R4-17, R4-20, R2-11; 전수 라벨과 CI 하한 조건은 policy).
- **HRA-06** judge, 라벨러, panel은 bot(Codex, OpenAI 계열)과 다른 family인 Claude를 쓴다. bot 심각도, 섹션 이름, 판정은 숨긴다. 쌍 비교는 순서를 바꿔 따로 두 번 하고, 일치하면 채택하고 다르면 adjudicator가 정한다 (R4-21, R2-28, R2-26, R2-27, R4-19; adjudicator 처리는 policy).
- **HRA-07** `judge_batch`는 저장소 접근이 없으므로 triage만 한다. 최종 라벨은 reviewed head를 checkout한 에이전트가 `file:line` 근거로 정한다. judge 행은 `labels-judge.jsonl`에만 쓴다. 매 라운드 judge bias(길이 상관, irr_sample에서 judge와 blind labelerB의 κ)를 기록한다 (R1-20, R2-11, R2-29, R4-21, R4-19, R4-20).
- **HRA-08** 1차 noise 지표는 blind 기술적 validity다. effective FP는 기록만 하고, 같은 저장소의 사람 코멘트 addressed rate와 비교한다 (R4-13, R2-01, R1-01, R2-14, R2-04, R2-10).
- **HRA-09** 심각도는 bot의 P0–P3와 `nit`으로 매긴다. 최악의 현실적 실패에서 시작하고, 중대한 완화 요인으로 낮춘다. 비현실적 전제 조건이 필요한 보안 finding은 기능 finding으로 다시 매긴다. 총 2단계까지만 낮추고, 실패 시나리오를 적지 못하면 상한은 P2다 (R4-10, R4-11, R4-12, R4-02, R4-03; 2단계 상한은 policy).
- **HRA-10** noise는 `INVALID ∪ SEVERITY_INFLATED ∪ {LOW_VALUE, NON_ACTIONABLE, OFF_SCOPE, STYLE_PREFERENCE, AUTOMATABLE}`다. SEVERITY_INFLATED는 metrics가 파생한다. evolvability finding, 올바른 P3, 1단계 과대평가, DUPLICATE는 noise가 아니다 (R1-02, R1-03, R1-15, R4-07, R2-07, R2-15, R1-25, R1-26, R4-02, R1-18, R1-24).
- **HRA-11** IRR은 무작위 층(`irr_sample`, 약 20%)에서만 계산하고, 60쌍이 될 때까지 라운드를 합친다. labelerB는 judge 제안을 보지 않고, labelerA도 irr_sample 항목에서는 보지 않는다. 모든 P0/P1은 이중 라벨한다. 감사 IRR은 점추정으로 판정하고 κ와 CI, raw agreement, PABAK, positive/negative agreement를 보고한다. escalation 항목의 κ는 진단용이다 (R1-11, R4-16, R4-18, R2-29, R4-17; 층 비율과 60쌍은 policy).
- **HRA-12** addressed는 Turzo & Bosu 정의를 따른다. 신호는 `changed_in_vicinity_1` 또는 명시적 수용이고, 라벨러의 `author_action`이 있으면 그것이 우선한다. bot 자신의 `Closed` 표시와 thread resolved는 근거가 아니다. 분모는 `F_closed`다. 구현 봇 PR은 따로 보고한다. 표본으로 보정한다 (R1-19, R1-04, R1-05, R2-05, R2-09, R2-12, R1-22, R2-13, R2-28).
- **HRA-13** miss 후보는 collector 4채널과 owner 세션에서 온다. 키워드, blame, SZZ 류 신호는 후보일 뿐이다. 모든 후보는 rubric §6으로 판정하고 blame·add-only 위생을 적용한다. important `defect_fix`는 두 번째 독립 verifier(labelerB)와 adjudicator가 확인한다 (R1-10, R3-08, R3-07, R3-09, R2-17, R3-11, R3-06, R3-10, R4-15).
- **HRA-14** owner 세션은 `archive.sessions`와 세션 파일 grep으로 찾고 bot 텍스트를 제거한다. runner Codex transcript는 bot 자신의 추론이므로 진단에만 쓰고 miss 채널로 쓰지 않는다 (R3-24; 절차는 policy).
- **HRA-15** panel 재리뷰: 창당 10 PR을 seed로 층화 추출한다(repo × verdict, automation PR 제외). Claude reviewer A·B가 bot 출력과 대상 head 이후의 모든 것을 보지 않고 리뷰한다. 독립 panel judge가 A·B 중복을 합치고, 모든 functional 항목을 reviewer의 심각도와 상관없이 확인하거나 다시 매긴다 (R3-24, R3-18, R2-23, R4-21, R4-04, R3-25; 표본 크기·렌즈·예산은 policy).
- **HRA-16** reference set은 확인된 important 결함의 union이다. valid important bot finding, collector 채널, owner 세션, panel을 `(pr_id, dedup_key)`로 합친다. 매칭되지 않은 bot finding도 noise로 단정하지 않고 adjudication한다 (R3-24, R2-06, R2-19).
- **HRA-17** important는 adjudicated P0/P1, 또는 `p2_blocking` P2다. important escaped는 결함이 있던 어느 reviewed head에서도 `hit`이 없는 것이다. partial도 escaped에 들어간다. P0/P1 소계, partial 소계, first-exposure miss, severity miss를 따로 보인다 (R4-15, R4-06, R2-19, R1-07, R3-23, R2-18).
- **HRA-18** `hit`은 같은 hunk나 함수(또는 ±3줄)에 있고 메커니즘과 영향이 맞아야 한다. 요약에서만 언급했거나 메커니즘이 틀리면 `partial`이다. 매칭은 두 순서로 따로 실행하고, 두 순서가 다르면 adjudicator가 정한다 (R2-18, R3-21, R3-22, R3-23, R2-27; adjudicator 처리는 policy).
- **HRA-19** 자동 매칭은 사람이 확인한 `match_sample` 행에서 κ ≥ 0.80이면 definite, 0.667–0.80이면 tentative다. 그보다 낮으면 믿지 않는다 (R3-25, R4-17).
- **HRA-20** defect type은 functional과 evolvability를 1차로 나누고, ODC 류 subtype은 탐색용이다. 둘 다 맞으면 functional이다 (R1-07, R1-08, R1-11, R4-08, R4-09).
- **HRA-21** miss rate는 union에 대한 상대값으로만 보고한다. (a) 전체 PR에서 panel을 뺀 값과 (b) panel PR에서 panel을 넣은 값 두 가지다. recall이라고 부르지 않는다. 항상 precision, noise, volume과 함께 보고한다 (R4-15, R3-24, R3-26, R2-21, R3-01, R2-22).
- **HRA-22** capture–recapture는 panel PR 안에서, panel 대상 head에 있는 important 결함만으로 계산한다. bot 포획은 그 head 행의 `hit`이고, 사람 출처는 bot 리뷰를 보지 않은 대상 head 시점까지의 코멘트다. 2출처면 Chapman, 3출처 이상이면 Chao2를 쓴다. m < 7이면 not estimable이다. 결과는 indicative only다 (R3-13, R3-14, R3-15, R3-17, R3-18, R3-19).
- **HRA-23** 모든 비율에 Wilson 95% 구간을 붙이고, 임계값은 구간으로 판정한다. family 단위 판단은 n ≥ 10이 될 때까지 주를 합친다 (R3-28, R1-16, R2-02).
- **HRA-24** target은 metrics.md §8만 쓴다. blocking precision ≥ 90%는 policy by analogy to R4-14다. effective FP와 RC error는 기록만 한다. useful ratio target은 없다 (R4-15, R2-02, R1-17, R1-21, R2-07; 선은 policy).
- **HRA-25** verdict error는 심각도 기반이다. important miss나 partial이 있는 head의 APPROVE는 merged final과 superseded로 나눠 센다. valid blocking finding이 없는 REQUEST_CHANGES는 prove-or-fix를 분리해 센다. 리뷰를 받지 못한 head는 coverage로 따로 센다 (R4-06, R4-01, R1-14, R2-23; coverage는 policy).
- **HRA-26** repo, size bucket, body verdict, author type, file type, defect type으로 층화한다 (R1-06, R1-14, R3-27, R2-13, R4-09; size 줄 경계는 owner policy).
- **HRA-27** before/after는 사전 등록한 primary endpoint 4개(validity precision, noise rate, important escaped per PR, `approve_with_important_miss.per_pr`)만 Newcombe, Fisher, 조건부 binomial로 검정한다. 나머지는 서술이다. 두 창은 섞어서 blind로 라벨한다. revert 비율은 비교하지 않는다 (R3-28, R3-22, R3-20, R2-31; 검정 선택은 policy).
- **HRA-28** 같은 cohort를 H = 30일과 90일로 다시 계산한다. 비교는 같은 `@H`끼리만 한다 (R3-01, R3-12, R3-08).
- **HRA-29** 사람 코멘트, owner 판단, owner 세션은 증거 채널이지 oracle이 아니다 (R3-24, R1-01, R4-13, R2-04).
- **HRA-30** 비용 상한: 약 35M 토큰, concurrency 20에서 약 7시간, owner 2–3시간. 창 안의 finding은 모두 라벨하고, 표본은 panel만 뽑는다 (policy).

## 워크플로

### Phase 0. 라운드 준비
1. `$ROUND`를 0700으로 만든다. 실행 시각이 T0+10d보다 이르면 A가 짧아진다는 것을 기록한다(HRA-02).
2. `versions.json` 초안을 쓴다: homelab SHA, collector 버전, `rubric_version`, judge-questions `version`과 hash, gold-set version과 hash, `agent-prompts.md` 역할별 hash, seed(`irr`, `closed`, `queue`, `panel`, `addressed_sample`).

### Phase 1. 수집
1. 창마다 `issue-agent-review-audit collect --since <ISO> --until <ISO> --out $ROUND/<baseline|after>/collect --evidence-days <H>`를 돌린다.
2. `manifest.json`의 잘림과 API 오류를 확인한다. 0이 아니면 다시 수집하거나 제외 사유를 적는다.
3. owner 세션 후보를 만든다: `owner_session_extractor` 프롬프트를 창마다 돌리고, 결과는 `private/<window>/extra-candidates.jsonl`이다. 각 항목에 `anchor_review_id`와 `anchor_at`이 있다. bot 리뷰가 하나도 없는 PR의 항목은 coverage에만 센다(HRA-14).
4. runner transcript(`issue-agent-records issue <repo> <n> --out $ROUND/private/runner/<owner>__<repo>__<n>`)는 진단용으로만 받는다. `issue-agent-records bridge events`는 coverage 교차 확인에만 쓴다.

### Phase 2. 자격 시험과 pilot
1. rater 구성(라벨러, adjudicator, verifier, matcher, judge 질문)마다 `references/gold-set.md`로 시험한다. 정답은 보여주지 않는다. rater는 Part A 55건을 모두 라벨한 뒤 `issue-agent-review-audit kappa --a <rater 라벨> --b gold-findings.jsonl --rater-b gold --all-items --field validity --field severity --field p2_blocking`을 돌린다. 출력의 n이 gold 수와 같지 않으면 통과가 아니다. gate는 HRA-05이고, `p2_blocking` κ(두 쪽이 모두 P2로 매긴 항목)는 기록만 한다(metrics.md §6).
2. `[T0−21d, T0−14d)`의 리뷰 약 20건(모든 repo, gold set에 없는 것)으로 pilot을 돌린다. rubric, 질문, 프롬프트 변경은 v2.x로 올린다. 바뀌면 1단계를 다시 한다.
3. `versions.json`을 동결한다(HRA-03). 이후 바뀌면 영향받은 라벨을 다시 만든다.

### Phase 3. Noise 감사 (창 안의 모든 bot finding)
1. `triage` 프롬프트로 두 창의 state를 만들고 `judge_batch`를 돌린다. judge 행은 `labels-judge.jsonl`에 쓰고, `irr_sample`과 escalation을 정하고, PR 단위로 큐를 섞는다(HRA-07).
2. PR마다 `labeler` 에이전트 하나(labelerA)가 bot-reviewed head를 순서대로 따라가며 그 PR의 finding을 모두 라벨한다. 앞선 head의 finding과 그 `dedup_key`를 알고 있으므로 재진술에 같은 key와 `DUPLICATE`를 붙인다. judge 제안은 irr_sample이 아닌 finding에서만 본다. pass 1은 결과를 보지 않고, pass 2에서 `author_action`을 정한다.
3. escalation 대상과 `irr_sample`은 labelerB가 judge 제안 없이 독립적으로 라벨하고, `adjudicator`가 `final`을 쓴다. 단일 라벨 항목은 labelerA 값을 `final`로 복사한다. 동점은 owner가 정한다(HRA-11).
4. addressed 보정 표본을 확인한다(metrics.md §3).
5. `queue/map.jsonl`로 각 창 DIR의 `labels-findings.jsonl`에 되돌려 쓴다.

### Phase 4. Miss 감사
1. 후보(collector 4채널 + 창별 owner 세션)에 judge 질문을 돌리고 escalation 규칙대로 큐를 만든다. triage로 닫은 후보는 `<candidate-id>@<head12>` `final` 행으로 쓴다.
2. PR마다 `candidate_verifier` 에이전트 하나(labelerA)가 escalated 후보를 판정하고, 결함이 있던 head마다 `<candidate-id>[.<k>]@<head12>` 행을 쓴다. bot 출력은 보지 않는다. horizon 밖 후보는 `out_of_horizon: true`로 남긴다. important `defect_fix`는 두 번째 verifier(labelerB)가 judge 제안 없이 독립적으로 확인하고, `adjudicator`가 `final`을 쓴다. verifier가 하나면 그 행을 `final`로 복사한다(HRA-13).
3. panel(HRA-15): `issue-agent-review-audit panel-draw --dir <DIR> --n 10 --seed <SEED_PANEL>`이 `panel.json`을 쓴다. 대상 head는 다음 순서로 정한다: PR 작성자가 아닌 사람의 첫 수정 커밋 직전의 마지막 bot-reviewed head; 그런 커밋이 없으면 body verdict 기준 첫 GREEN head; 그것도 없으면 최종 bot-reviewed head. 오케스트레이터가 remote 없는 scratch clone을 만든다: 대상 head를 detach하고, base branch를 대상 head 커밋 시각까지 자른 `refs/audit/base`를 넣는다(B의 merge-skew 렌즈용). PR마다 `panel_reviewer_a`(id `<pr-id>/pA<k>`)와 `panel_reviewer_b`(id `<pr-id>/pB<k>`)를 그 clone과 merge-base diff만 주고 돌린다. reviewer당 약 250k 토큰이다. PR마다 `panel_judge` 한 번(labelerA)이 A·B 중복을 합치고, 모든 functional 항목을 reviewer 심각도와 상관없이 확인하거나 다시 매기고, 결함이 있던 head마다 행을 쓴다. P0/P1 여부에서 judge와 reviewer가 갈릴 때만 두 번째 judge(labelerB)와 adjudicator를 쓰고, important 동점은 owner가 정한다. judge가 하나면 그 행을 `final`로 복사한다.
4. 같은 근본 원인을 `dedup_key`로 묶고, `sources`에 드러낸 채널을 모두 적는다(HRA-16).

### Phase 5. 매칭
1. PR마다 `matcher`를 두 번 따로 돌린다. 각 실행은 그 PR의 모든 결함 행을 그 head의 bot 리뷰와 비교하고, 결과를 `labels-matcher.jsonl`에 rater `matcher-defect_first` 또는 `matcher-review_first`로 쓴다. 두 순서가 같으면 그 값을 `final`의 `bot_match`, `matched_finding_id`(summary-only `partial`이면 null과 `review_id`)에 복사한다(`notes: matcher-copy`). 두 순서가 다르면 `adjudicator`가 rubric §8로 `final`을 정한다. "낮은 값" 규칙은 없다(HRA-18).
2. match 20–30건(두 창 합산, seed)을 사람이 확인한다. 사람 값이 그 행의 matcher-copy `final`을 대체하고 `match_sample: true`를 붙인다(`irr_sample`과 별개). `match_kappa`는 이 행에서만, 순서별로(`matcher-defect_first` 대 사람 `final`, `matcher-review_first` 대 사람 `final`) 계산하며 gate는 HRA-19다.
3. dedup_key 조정(PR마다 한 번): `final` `bot_match`가 `hit`인 결함은 모든 miss 행이 matched finding의 `final` `dedup_key`를 받는다. 옛 key는 `notes`에 `prev_key`로 남긴다. 이렇게 해서 `R_imp`에서 bot_finding 행과 후보 행이 한 결함으로 센다(rubric §0, HRA-16).

### Phase 6. 계산
1. 창마다 `issue-agent-review-audit metrics --format json`을 돌린다. `bad_rows`가 비어 있어야 한다. baseline은 `--exclude-pr isac322/kwin-mcp#90 … --exclude-pr isac322/kwin-mcp#98`을 붙인 실행도 한다(gold set 출처 PR 제외본).
2. `issue-agent-review-audit kappa --a <labels> --b <labels> [--field validity|severity|p2_blocking|bot_match|is_defect|verdict]`로 IRR을 확인한다(기본은 irr_sample 행만, 누적 60쌍까지 라운드 합산).
3. `issue-agent-review-audit compare --before <B.json> --after <A.json>`로 primary endpoint를 검정한다(HRA-27). 제외본 baseline으로도 한 번 더 돌린다.
4. gate 미달 라벨에 기대는 수치에 `tentative`를 붙이고, 임계값은 Wilson 구간으로 판정한다(HRA-23, HRA-24).

### Phase 7. 보고와 재계산
1. `references/report-template.md`로 `$ROUND/report.md`를 쓴다. miss는 상대값과 `@H`로, capture–recapture는 indicative로 적는다(HRA-21, HRA-22).
2. 30일·90일 재계산 날짜를 적는다. 그때 같은 창을 `--evidence-days 30`/`90`으로 새 DIR에 다시 수집하고, 옛 DIR의 `final` 라벨 행을 새 DIR로 복사한 뒤 새 DIR에 없는 id만 라벨한다. 옛 DIR은 바꾸지 않는다(HRA-28).

## 완료 조건

- `versions.json`이 동결돼 있고 모든 산출물이 그 버전으로 만들어졌다.
- 두 창 모두 collect DIR, `labels-findings.jsonl`, `labels-misses.jsonl`, `panel.json`, `metrics` JSON(`bad_rows: []`)이 있고, `compare` 출력이 있다.
- 창 안의 모든 bot finding에 에이전트가 정한 `final` 라벨이 있고, `judge_batch`만으로 확정된 validity가 없다.
- 모든 important 결함에 reviewed head 기준 `file:line` 근거, 독립 확인, 매칭 판정이 있다.
- 보고서에 gate 결과, κ와 CI, 모든 비율의 Wilson 구간, 층화 표, `@H` 표시, 30/90일 계획이 있다.
- 비공개 내용이 저장소나 GitHub에 없고, bot 프로필, GitHub, 클러스터에 변경이 없다.
