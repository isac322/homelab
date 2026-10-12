# Sources v2.3

근거는 2026-10-12 연구 4건(R1 유용성·noise, R2 AI reviewer 평가, R3 miss 탐지, R4 심각도·rater)의 claim 108개다. 각 claim은 다른 연구자가 원문을 다시 열어 교차 검증했다: VERIFIED 103, OVERSTATED 5, WRONG 0. 이 skill은 VERIFIED claim과, OVERSTATED claim의 교정된 형태만 쓴다. 원문 보고서는 세션 artifact(`R1ReviewUsefulness.md` 등)이고, 여기에는 규칙 점검에 필요한 만큼만 옮긴다. v2는 7개 비평과 orchestrator 결정 D1–D23(Round 1)을 반영했다.

**출처 표시 규칙.** 규칙과 임계값마다 근거가 claim인지 **policy**(owner·감사 설계의 선택, 출처 없음)인지 적는다. "policy by analogy to R…"는 출처의 수치를 다른 양에 빌려 쓴 policy다. Newcombe, Fisher, 조건부 binomial, McNemar, PABAK, Garwood 구간은 표준 통계 방법이며 claim에서 오지 않았다(D13 선택).

## 1. 반드시 지키는 교정

| claim | 교정 | 이 skill에서의 처리 |
|---|---|---|
| R1-06 | 사람 리뷰 유용성 "35% 하한"을 LLM reviewer에 옮기는 것은 출처가 뒷받침하지 않는다 | 35%를 쓰지 않는다. 크기·파일 유형 층화만 쓴다 |
| R1-14 | "evolvability만으로 낸 REQUEST_CHANGES = noise"는 출처에 없다 | verdict error는 adjudicated 심각도로 정한다(HRA-25) |
| R1-17 | (C1 비평) 10% effective FP는 Tricorder의 클릭 기반 비율과 수동 표본 기준이며, 침묵을 FP로 치는 `1 − addressed`에는 적용되지 않는다 | `effective_fp_rate`는 record-only. 10%는 명시적 신호만 쓰는 `explicit_not_useful_rate`에 적용(D12) |
| R1-25 | 거부 사유 코딩 κ는 0.71이 아니라 0.68 | 0.68로만 인용 |
| R2-02 | ClaimDisposition은 "최고 analyzer 0–3%가 본문에 없다"고 적었지만, R2 재확인으로 Tricorder 본문에 있음이 확인됐다("most successful analyzers have not-useful rate between 0-3%") | 서술용으로만 인용하고 target으로 쓰지 않는다(D14). 10% probation / 25% 끄기 선은 analyzer별 비율에만 적용 |
| R2-17 | SWR-Bench는 SZZ를 clean set 정리에만 썼다 | post-merge 수정을 miss 후보로 쓰는 것은 우리 확장이며, 모두 adjudication을 거친다 |
| R2-21 | "recall 없는 precision은 무의미"는 출처에 없다 | 정밀도는 조정 가능한 운영점이라는 교정 문장만 쓴다 |
| R2-31 | revert 비율 비교는 선택 편향으로 교란되고 사건이 드물다 | revert는 후보 채널로만 쓴다 |
| R3-07 | SZZ 범위는 골라낸 값이다. 기본 SZZ는 약 5건 중 3건이 틀린다 | SZZ·키워드 출력은 후보일 뿐이다 |
| R3-12 | da Costa의 "46% 수년 간격"은 SZZ 부정확성 신호이지 right-censoring 증거가 아니다 | 30/90일 재계산은 일반적인 censoring 우려로만 정당화한다 |
| R3-19 | singleton 상한은 리뷰 출처에 옮겨지지 않는다 | singleton 비율은 서술용 포화 지표로만 쓴다 |
| R3-27 | "사람 50%" 기준은 PSP 자기 리뷰 데이터다 | 사람 기준선으로 쓰지 않는다. 크기 층화만 쓴다 |
| R3 pitfalls | κ ≈ 0.75를 "4–5건 중 1건 불일치"로 읽은 것은 오독이다 | κ는 불일치율로 해석하지 않는다 |
| R4-11 | Chromium은 중대한 요인마다 "한 단계 이상" 내린다고 하며 총 상한은 없다. 비현실적 전제 조건은 보안 finding을 기능 finding으로 바꾼다 | 총 2단계 상한은 **audit policy**(rater 안정성)로 표시하고 R4-11에 귀속하지 않는다. 재분류 예외는 R4-11로 채택(D4) |
| R4-14 | Tricorder 90%/10%는 effective FP(개발자 행동) 기준이다 | `blocking_precision` ≥ 90%(validity)는 **policy by analogy to R4-14**(D14) |
| R4-17 | 0.667/0.80 기준은 Hallgren의 Krippendorff 인용을 통해서만 확인됐다 | "Krippendorff via Hallgren"으로 인용 |
| R4-21 | 76.6%는 벤치마크 split으로 fine-tune한 모델 수치다 | 범용 judge의 성능으로 인용하지 않는다 |

교차 검증과 비평에서 나온 추가 단서도 따른다: R2-05 보정은 음성 표본도 확인한다; R2-08의 "valid + outdated = 유용"은 인과가 아니다; R3-09는 "최소 37%가 틀리다"로 읽는다; R1-16 범주별 판단은 범주당 n ≥ 10이 필요하다; R3-04의 54%는 검증 안 된 SZZ 원출력이라 사람 리뷰 miss 기준선이 아니다; R3-25의 κ = 0.75는 벤치마크가 도달한 값이지 문턱이 아니다; R1-21의 60%는 AutoCommenter의 관측값이지 수용 수준이 아니다; R3-17은 Chao 원식 `f1²/(2f2)`이고 skill은 bias-corrected Chao2 형식을 쓴다.

## 2. 출처 목록 (claim ID → 문헌)

- **R1-01, R1-02, R1-03, R1-04, R1-05, R1-06**: Bosu, Greiler, Bird, "Characteristics of Useful Code Reviews", MSR 2015.
- **R1-07, R1-08, R1-09**: Mäntylä & Lassenius, "What Types of Defects Are Really Discovered in Code Reviews?", IEEE TSE 35(3), 2009.
- **R1-10, R1-11, R4-07, R4-08**: Beller, Bacchelli, Zaidman, Juergens, "Modern Code Reviews in Open-Source Projects: Which Problems Do They Fix?", MSR 2014.
- **R1-12, R1-13**: Bacchelli & Bird, "Expectations, Outcomes, and Challenges of Modern Code Review", ICSE 2013.
- **R1-14**: Czerwonka, Greiler, Tilford, "Code Reviews Do Not Find Bugs", ICSE SEIP 2015 (2쪽 초록).
- **R1-15, R1-16**: Sadowski et al., "Modern Code Review: A Case Study at Google", ICSE SEIP 2018.
- **R1-17, R1-18, R4-13, R4-14**: Sadowski, Aftandilian, Eagle, Miller-Cushon, Jaspan, "Lessons from Building Static Analysis Tools at Google", CACM 61(4), 2018.
- **R1-19**: Turzo & Bosu, "What Makes a Code Review Useful to OpenDev Developers?", EMSE 2023/24.
- **R1-20**: Rahman, Roy, Kula, "Predicting Usefulness of Code Review Comments", MSR 2017.
- **R1-21, R2-05, R2-06, R2-07**: Vijayvergiya et al., "AI-Assisted Assessment of Coding Practices in Modern Code Review" (AutoCommenter), AIware 2024.
- **R1-22, R2-12, R4-23**: Cihan et al., "Automated Code Review In Practice", ICSE SEIP 2025.
- **R1-23**: Egelman et al., "Predicting Developers' Negative Feelings about Code Review", ICSE 2020.
- **R1-24**: Gunawardena et al., "Destructive Criticism in Software Code Review Impacts Inclusion", CSCW 2022 (초록만).
- **R1-25**: Watanabe et al., "On the Use of ChatGPT for Code Review", EASE 2024.
- **R1-26**: Han et al., "Does code review really remove coding convention violations?", SCAM 2020.
- **R2-01, R2-02, R2-03, R2-04**: Sadowski et al., "Tricorder: Building a Program Analysis Ecosystem", ICSE 2015.
- **R2-08, R2-09**: Sun et al., "BitsAI-CR: Automated Code Review via LLM in Practice", FSE-IVR 2025.
- **R2-10, R2-11**: Tantithamthavorn et al., "RovoDev Code Reviewer" (ICSE SEIP 2026); "HalluJudge" (Atlassian, 2026).
- **R2-13**: Olewicz et al., "Impact of LLM-based Review Comment Generation in Practice", 2024.
- **R2-14**: "Using Agentic AI for contextualized and multifaceted code review at Ericsson", 2026.
- **R2-15**: Ramesh et al., "Automated Code Review Using Large Language Models at Ericsson", 2025.
- **R2-16, R2-17, R3-25(일부)**: "SWR-Bench: Assessing LLM Performance in Real-World Code Review Comment Generation", 2025.
- **R2-18, R3-22**: Greptile, "AI Code Review Benchmarks", 2025 (vendor).
- **R2-18, R2-20, R2-21, R3-21**: Qodo, "How we built a real-world benchmark for AI code review", 2026 (vendor).
- **R2-19**: Augment Code, "We benchmarked 7 AI code review tools", 2025/2026 (vendor).
- **R2-21**: Google Research blog, "Resolving code review comments with ML", 2023.
- **R2-22**: Cursor, "Building a better Bugbot" / "Bugbot now self-improves", 2026 (vendor).
- **R2-23**: GitHub Blog, "60 million Copilot code reviews and counting" (vendor).
- **R2-24**: Braintrust customer story, Graphite Diamond (vendor).
- **R2-25**: Naik et al., "CRScore", NAACL 2025.
- **R2-26, R4-19**: Zheng et al., "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena", NeurIPS 2023.
- **R2-27, R4-20(일부)**: Wang et al., "Large Language Models are not Fair Evaluators", ACL 2024.
- **R2-28, R4-21(일부)**: Panickssery, Bowman, Feng, "LLM Evaluators Recognize and Favor Their Own Generations", NeurIPS 2024.
- **R2-29**: Ahmed, Devanbu, Treude, Pradel, "Can LLMs Replace Manual Annotation of Software Engineering Artifacts?", MSR 2025.
- **R2-30**: Tencent, "Reducing False Positives in Static Bug Detection with LLMs", 2026.
- **R2-31**: Meta, "Automating Low-Risk Code Review at Meta: RADAR", 2026.
- **R3-01**: C. Jones, "Software defect-removal efficiency", IEEE Computer 29(4), 1996 (초록).
- **R3-02**: DORA metrics guide.
- **R3-03**: McIntosh, Kamei, Adams, Hassan, MSR 2014.
- **R3-04**: Kononenko et al., "Investigating code review quality", ICSME 2015.
- **R3-05**: Śliwerski, Zimmermann, Zeller, "When do changes induce fixes?", MSR 2005.
- **R3-06**: Kim et al., ASE 2006; Neto et al., SANER 2018.
- **R3-07**: Rosa et al., "Evaluating SZZ Implementations Through a Developer-informed Oracle", ICSE 2021.
- **R3-08**: Herbold et al., "Problems with SZZ and Features", EMSE 2022.
- **R3-09**: Rodríguez-Pérez et al., "How bugs are born", EMSE 25, 2020.
- **R3-10**: Lyu et al., "Evaluating SZZ Implementations: An Empirical Study on the Linux Kernel", 2023.
- **R3-11**: Bludau & Pretschner, "PR-SZZ", SANER 2022; Petrulio et al., "SZZ in the time of Pull Requests", 2022.
- **R3-12**: da Costa et al., "A Framework for Evaluating the Results of the SZZ Approach", IEEE TSE 2017.
- **R3-13**: Eick et al., "Estimating software fault content before coding", ICSE 1992.
- **R3-14**: Briand et al., "A comprehensive evaluation of capture-recapture models", IEEE TSE 26(6), 2000.
- **R3-15**: El Emam & Laitenberger, "Evaluating capture-recapture models with two inspectors", IEEE TSE 27(9), 2001.
- **R3-16**: Petersson et al., "Capture-recapture in software inspections after 10 years research", JSS 72(2), 2004 (초록).
- **R3-17**: Chao, "Estimating the Population Size for Capture-Recapture Data with Unequal Catchability", Biometrics 43, 1987.
- **R3-18**: Roper, "Estimating Fault Numbers Remaining After Testing", ICST 2013.
- **R3-19**: arXiv 2607.17061 (2026 preprint).
- **R3-20**: Just et al., "Are mutants a valid substitute for real faults in software testing?", FSE 2014.
- **R3-23**: "CRBugBench", arXiv 2610.13668, 2026.
- **R3-24**: "AACR-Bench", arXiv 2601.19494, 2026.
- **R3-25, R4-21(일부)**: "SWE-PRBench", arXiv 2603.26130, 2026.
- **R3-26**: "CR-Bench", arXiv 2603.11078, 2026.
- **R3-27**: Kemerer & Paulk, IEEE TSE 35(4), 2009.
- **R3-28**: Brown, Cai, DasGupta, "Interval Estimation for a Binomial Proportion", Statistical Science 16(2), 2001.
- **R4-01, R4-02, R4-03, R4-04**: Google Engineering Practices (reviewer standard, comments, looking-for).
- **R4-05**: Conventional Comments.
- **R4-06**: Gerrit Code Review, "Review Labels".
- **R4-09**: Chillarege et al., "Orthogonal Defect Classification", IEEE TSE 18(11), 1992.
- **R4-10**: IEEE Std 1044-2009 (초록·범위만).
- **R4-11**: Chromium, "Severity Guidelines for Security Issues".
- **R4-12**: FIRST CVSS v4.0 specification, v3.1 user guide.
- **R4-15**: Distefano et al., "Scaling Static Analyses at Facebook", CACM 62(8), 2019.
- **R4-16, R4-17, R4-18**: Hallgren, "Computing Inter-Rater Reliability for Observational Data", TQMP 8(1), 2012; McHugh, "Interrater reliability: the kappa statistic", 2012.
- **R4-20**: Bavaresco et al., "JUDGE-BENCH", 2024; Thakur et al., "Judging the Judges", 2024.
- **R4-21**: "CRJudgeBench", arXiv 2609.37216, 2026.
- **R4-22**: Shankar et al., "Who Validates the Validators?", UIST 2024.

## 3. 규칙 → claim 매핑

`policy` 열은 그 규칙에서 출처 없이 owner·감사 설계가 정한 부분이다. `D<n>`은 Round 1 결정 번호다.

| rule | claims | policy 부분 | 출처 충돌과 선택 |
|---|---|---|---|
| HRA-01 단위 | R2-16, R3-11, R2-06 | finding 첫 등장, `(pr_id, dedup_key)`, `(pr, head)` 단위(D3) | — |
| HRA-02 창과 horizon | R3-01, R3-12 | 창 경계, H = 3일, 가장 이른 실행일(D1) | — |
| HRA-03 pilot과 버전 동결 | R4-22, R3-16 | pilot 약 20건을 `[T0−21d, T0−14d)`에서(D19를 고친 DEC), `versions.json` 항목 | — |
| HRA-04 저장과 비공개 | — | 전부 policy(D2) | — |
| HRA-05 gold set gate | R4-18, R4-17, R4-20, R2-11 | gold set 구성(A ≥ 40, B f00–f29), CI 하한 조건(D10), Part A 전수 라벨과 n = gold 수 요구(완전 일치에서 CI가 붕괴하므로) | R2(κ ≥ 0.6 예시)와 R4(0.80/0.667): 문턱이 있는 R4-17(Krippendorff via Hallgren)을 쓴다. R2-11은 "사람과 보정한다"만 뒷받침한다 |
| HRA-06 judge 독립성·blind | R4-21, R2-28, R2-26, R2-27, R4-19 | Claude 계열 지정 | — |
| HRA-07 judge_batch는 triage | R1-20, R2-11, R2-29, R4-21, R4-19, R4-20 | escalation 문턱 0.7, 0.85(D18) | — |
| HRA-08 validity 1차, effective FP record-only | R4-13, R2-01, R1-01, R2-14, R2-04, R2-10 | — | R1-01(작성자 유용성)과 R4-13(기술적 타당성): 단일 owner의 판단은 bot과 상관되고 분산이 크므로 blind validity를 1차로 한다 |
| HRA-09 심각도 | R4-10, R4-11, R4-12, R4-02, R4-03, R4-18 | 총 2단계 하향 상한(D4) | R4 원문 적용(요인마다 1단계)과 Chromium 원문(요인마다 1단계 이상, 상한 없음): 상한은 rater 안정성을 위한 policy로 두고 Chromium 재분류 예외를 채택한다 |
| HRA-09 (p2_blocking) | — | 네 조건 정의 전부(**policy, bot 계약**: `isac-pr-review` PRR-22, `references/review-dimensions.md` §8; gold 보정에서 라벨러 불일치 7/56 뒤 adjudicator 문구 채택) | — |
| HRA-10 noise | R1-02, R1-03, R1-15, R4-07, R2-07, R2-15, R1-25, R1-26(AUTOMATABLE의 convention·style 부분만), R4-02, R1-18, R1-24 | SEVERITY_INFLATED 2단계 경계와 파생 방식, DUPLICATE 제외(D4, D5); AUTOMATABLE을 컴파일러·CI가 결정적으로 잡는 결함으로 넓힌 것(owner 결정 U1: reviewer는 CI와 무관하고 CI 실패는 새 커밋과 새 리뷰를 부른다; Sadowski CACM 2018: 빌드 깨짐은 컴파일러·CI 몫) | R2-14/15는 `LOW_VALUE`를 noise로, R1-03/15는 올바른 nit를 허용으로 본다: `LOW_VALUE`는 "수정 이득 < 비용" 테스트를 통과할 때만 붙이고 올바른 P3/nit는 noise가 아니다 |
| HRA-11 IRR | R1-11, R4-16, R4-18, R2-29, R4-17 | 무작위 20% 층, 60쌍 pooling, linear κ_w(D10), irr_sample에서 judge 제안을 숨기는 것(R4-16의 독립 가정을 지키기 위한 절차) | — |
| HRA-12 addressed | R1-19, R1-04, R1-05, R2-05, R2-09, R2-12, R1-22, R2-13, R2-28, R2-10 | 구현 봇 PR 분리, probation/suppress 판정 방식(D12) | 창 크기: R2-08(범위 전체)과 R1-04(±1줄): 유일한 경험적 보정이 있는 ±1을 1차, ±5를 민감도로 쓴다. 10% 적용 대상: R1-17·R2-01은 행동 기반 비율, C1·C2 비평은 침묵 포함 비율에는 맞지 않는다고 지적: 명시적 신호만 쓰는 비율에 적용한다 |
| HRA-13 후보 판정과 위생 | R1-10, R3-08, R3-07, R3-09, R2-17, R3-11, R3-06, R3-10, R4-15 | `policy_risk` 판정, `exposed_by_pr`(D6) | — |
| HRA-14 owner 세션, runner transcript | R3-24 | 검색 절차, transcript를 채널에서 뺀 것(D17) | — |
| HRA-15 panel | R3-24, R3-18, R2-23, R4-21, R4-04, R3-25 | 10 PR, seed 층화, 대상 head 규칙, remote 없는 scratch clone과 `refs/audit/base`, 렌즈 구성, 250k 토큰, `pA<k>`/`pB<k>` id와 A·B 병합, 모든 functional 항목을 심각도와 무관하게 확인·재평가, judge 수(D8, R3 r2 #3) | — |
| HRA-16 union reference set | R3-24, R2-06, R2-19 | bot_finding 자동 행(D7) | — |
| HRA-17 important와 escaped | R4-15, R4-06, R2-19, R1-07, R3-23, R2-18 | `p2_blocking` 포함, escaped 정의(D3, D6) | R3(≥ P1), R4(P0/P1), bot 계약(P2도 blocking): bot 자신의 판정 기준을 재므로 `p2_blocking` P2를 넣고 P0/P1 소계를 따로 보인다 |
| HRA-18 matching | R2-18, R3-21, R3-22, R3-23, R2-27 | 순서 불일치는 adjudicator가 정한다(DEC), PR 단위 배치 | R2-18(요약 언급은 미포착)과 R3(심각도 미달은 따로 기록): partial은 escaped에 넣고, severity miss는 hit 안의 소계로 센다 |
| HRA-19 matching κ | R3-25, R4-17 | `match_sample` 행만 사용 | R2(0.6 예시), R3 v1(0.7), R4(0.80/0.667): 문턱이 있는 R4-17을 쓴다. R3-25의 0.75는 도달값이지 문턱이 아니다(D11) |
| HRA-20 defect type | R1-07, R1-08, R1-11, R4-08, R4-09 | `claim_mismatch` subtype | — |
| HRA-21 상대 miss rate | R4-15, R3-24, R3-26, R2-21, R3-01, R2-22 | 두 가지 계산(D7) | — |
| HRA-22 capture–recapture | R3-13, R3-14, R3-15, R3-17, R3-18, R3-19 | m < 7 → not estimable(D9); 모집단은 panel 대상 head에 있는 결함, bot 포획은 그 head 행의 `hit`, human_blind는 대상 head 시점까지(R3 r2 #1) | — |
| HRA-23 Wilson과 pooling | R3-28, R1-16, R2-02 | n ≥ 10 pooling 조건 | — |
| HRA-24 target | R4-15, R2-02, R1-17, R1-21, R2-07 | blocking precision 90%(by analogy to R4-14), APPROVE 0건, RC observe-only(D14) | — |
| HRA-25 verdict error와 coverage | R4-06, R4-01, R1-14, R2-23 | coverage 수치(D16), merged/superseded 분리 | R1-14(유형 기반)와 R4-06(심각도 기반): 교정에 따라 심각도 기반을 쓴다 |
| HRA-26 층화 | R1-06, R1-14, R3-27, R2-13, R4-09 | 크기 줄 경계(owner policy), 어휘(D15) | — |
| HRA-27 before/after | R3-28, R3-22, R3-20, R2-31 | primary endpoint 4개(4번은 `approve_with_important_miss.per_pr`, merged_final은 서술), 검정 방법(D13), panel 단독 결함을 전체 PR 수치에서 빼는 것 | v1의 "구간 비겹침" 규칙은 너무 보수적이다(C1-R2 비평): 차이 구간으로 판정하고 비겹침은 쓰지 않는다 |
| HRA-28 30/90일 재계산 | R3-01, R3-12, R3-08 | — | — |
| HRA-29 사람·owner 증거의 한계 | R3-24, R1-01, R4-13, R2-04 | — | R3-04의 54%는 검증 안 된 SZZ 원출력이라 사람 리뷰 miss 기준선으로 쓰지 않는다 |
| HRA-30 비용 상한 | — | 전부 policy(D20) | — |
