# Rubric v2.5 (`rubric_version: v2.5`)

모든 라벨의 정의다. 각 정의는 라벨러가 저장소와 GitHub 데이터에서 직접 확인할 수 있는 관찰 가능한 테스트로 끝난다. 괄호 안의 ID는 근거 claim이고 `sources.md`에 매핑돼 있다. **policy**라고 적힌 것은 출처가 아니라 owner·감사 설계의 선택이다.

pilot(SKILL Phase 2)에서 바꾼 내용은 `v2.x`로 올리고, 측정 라운드가 시작되면 `versions.json`에 동결한다. 라운드 도중 바꾸면 영향받은 항목을 모두 다시 라벨링한다(HRA-03, R4-22).

## 0. 단위

- **finding 단위**는 첫 등장이다. 같은 finding을 이후 head나 리뷰에서 다시 말한 것(이전 리뷰의 열린 finding 재진술, `Previous findings`의 `Open` 이월 포함)은 `DUPLICATE`를 붙이고 precision·noise·findings-per-PR 분모에서 뺀다. `duplicate_rate`로 따로 보고한다(policy, D3).
- **결함 단위**는 `(pr_id, dedup_key)`다. `dedup_key`는 근본 원인 하나에 붙이는 짧은 slug이며, 같은 PR 안에서 같은 결함을 가리키는 bot finding, 후보, panel 항목이 같은 key를 쓴다. finding은 PR 하나를 한 라벨러가 head 순서대로 라벨하므로 같은 PR 안의 key가 일관된다.
- **dedup_key 조정(Phase 5 뒤, PR마다 한 번):** matcher 결과 `final`의 `bot_match`가 `hit`이고 `matched_finding_id`가 있으면, 그 결함의 모든 miss 행이 matched finding의 `final` `dedup_key`를 받는다. 이렇게 해서 자동 `bot_finding` hit 행과 후보 행이 `R_imp`에서 한 결함으로 합쳐진다(D7). 조정 전 key는 `notes`에 `prev_key: <slug>`로 남긴다.
- **판정 단위**는 `(pr, reviewed_head)`다. 같은 head에 리뷰가 여럿이면 verdict 지표는 하나로 센다(D3).
- 라벨은 reviewed head를 checkout한 상태에서 정한다(HRA-01).

## 1. Validity (`validity`)

finding이 주장한 문제가 reviewed head에 실제로 있는가. 작성자가 고쳤는지는 보지 않는다. 관점은 "그럴듯한 실패 경로가 있는 fault"다(R1-09, R1-02, R4-13, R2-14).

| 값 | 관찰 가능한 테스트 |
|---|---|
| `valid` | reviewed head의 코드에서, finding이 지목한 위치(±3줄 또는 같은 함수)에 주장한 메커니즘이 성립한다. 라벨러가 `file:line` 인용, probe 출력, 또는 정상 사용 경로를 따라가는 코드 경로 논증으로 보일 수 있다. 실행 probe가 없어도 코드 경로 논증이 충분하면 `valid`다. |
| `invalid` | 다음 중 하나를 `file:line` 근거로 보일 수 있다: 메커니즘이 성립하지 않는다; 이미 다른 곳에서 처리된다; API·동작을 잘못 읽었다; 잘못된 파일·줄을 가리킨다; 사실이 아닌 전제에 기댄다(R2-15). 추측성 주장을 사실처럼 단정했는데 반박되면 `invalid`다(R4-05 CERTAINTY). |
| `unverifiable` | 판정에 런타임·외부 시스템·비공개 컨텍스트가 필요한데 감사 환경에서 얻을 수 없다. 무엇이 없었는지 `notes`에 적는다. |

`unverifiable`은 precision·noise 분모에서 빼고, `unverifiable`을 `invalid`로 친 최악값(`validity_precision_worst`)도 보고한다(D5). `judge_batch`만으로 `valid`/`invalid`를 확정하지 않는다(HRA-07).

**probe 충실도**(policy: pilot-kwin-20261012 T2): probe는 저장소의 잠긴 의존성 버전(lockfile)과 저장소가 대상으로 하는 플랫폼에서 돌린다. 다른 플랫폼에서 돌린 probe, 모듈을 stub한 probe, 기본값이 아닌 환경(예: `PYTHONUNBUFFERED`)에서 돌린 probe는 `code_path_only` 근거다. 그런 probe만으로는 항목을 `invalid`로 만들 수 없고, 다른 근거가 없으면 `unverifiable`이다. 실행 환경의 패키지 버전이 lockfile과 일부만 맞으면, probe한 코드 경로에 쓰이는 패키지가 모두 lockfile과 같을 때만 `probe`이고 다른 패키지의 차이는 근거에 적는다. 그렇지 않으면 `code_path_only`다(policy: pilot-kwin-20261012 PR3-5). scratch 안에서 로컬 패키지 캐시로 오프라인 설치하는 것은 되고, 네트워크 설치는 안 된다. 저장소별 런타임과 probe 방법은 `references/repos/<owner>__<repo>.md`에 있다.

## 2. Adjudicated severity (`adjudicated_severity`, `p2_blocking`)

라벨러는 bot이 매긴 심각도, 리뷰 섹션 이름(`Blocking`/`Non-blocking`), 판정을 보지 않는다(R4-18, R2-26). 척도는 bot의 정의(`isac-multi-agent-consensus/references/defaults.md`)와 PR 리뷰 보정(`isac-pr-review` PRR-22, `references/review-dimensions.md` §8)을 그대로 쓴다.

| 값 | 정의(bot 척도) | 관찰 가능한 테스트 |
|---|---|---|
| `P0` | 데이터 손실, 보안 결함, 비밀 유출, 광범위 장애 | 기본 설정에서 닿는 구체적 실패 시나리오(입력·상태 → 관찰 가능한 피해)를 적을 수 있다 |
| `P1` | 목적 달성 실패, 회귀, 주장한 문제를 해결하지 못하거나 일부만 해결 | 정상 사용 경로의 구체적 트리거와 잘못된 결과를 적을 수 있다 |
| `P2` | 결함이지만 목적은 유지되고 후속 처리 가능; 또는 코드 건강을 분명히 해치는 유지보수 문제 | 실패가 비기본 설정·드문 트리거를 요구하거나, 기능 영향 없이 명확한 유지보수 비용이 있다 |
| `P3` | 경미: 작은 명확성·견고성 개선, 선택적 강화 | 고치면 낫지만 안 고쳐도 결함이 배포되지 않는다 |
| `nit` | 취향 수준 다듬기: 이름 취향, 서식, 관용구, 문구 | 저장소 규칙(linter 설정, AGENTS.md, CONTRIBUTING, 일관된 기존 패턴)이 요구하지 않는다(R4-03) |
| `none` | `validity != valid`일 때만 | — |

`p2_blocking`은 다음 네 조건을 모두 만족할 때만 `true`다(**policy, bot 계약**: `isac-pr-review` PRR-22, `references/review-dimensions.md` §8).

1. `adjudicated_severity == P2`.
2. PR이 들여왔다: merge-base에는 결함이 없거나, PR이 그 결함을 새로 노출시켰다.
3. **제품의 정확성·보안 결함이다.** 실패 시나리오가 닿을 수 있는 입력·상태에서 출하된 코드나 배포·사용자 대상 산출물(런타임, chart, manifest, 공개 사이트·문서)의 잘못된 동작으로 끝나야 한다. 테스트, fixture, harness, lint, codegen, CI workflow, 개발 도구의 결함은 그 결과가 테스트·테스트 빌드·check·CI job의 실패, 건너뜀, 방어력 상실뿐이면 정확성 결함이 아니다. 실패가 결정적이고 merge를 막아도 같다(§8의 테스트 전용 결함, PRR-38의 CI gate). 그런 결함은 PR이 들여온 구체적인 제품 결함을 가리거나 통과시킬 때만 정확성 결함이며, 그때는 그 제품 결함으로 라벨한다. 타입 억제는 억제된 결함이 정확성 결함일 때만 blocking이다.
4. 증거: 재현, 또는 각 단계의 정확한 `file:line`을 인용한 코드 경로 논증. 근거 필드로는 `evidence_kind`가 `probe`나 `file_line`인 행만 `final`에서 `p2_blocking: true`일 수 있다. reviewer는 `p2_blocking`을 제안할 수 있지만, 트리거가 확인되지 않은 `code_path_only`·`unverified` 항목은 judge나 verifier가 probe나 `file_line`으로 확인하기 전까지 `false`다(policy: pilot-kwin-20261012 PR3-2).

그 밖에는 `false`다. CI가 잡는 실패는 심각도의 완화 요인(아래 절차 2단계)이지 `p2_blocking` 기준이 아니다. 비밀 유출은 심각도와 무관하게 blocking이다.

### 매기는 절차

1. **최악의 현실적 실패에서 시작한다.** bot이 보인 실패만이 아니라, rater가 코드 경로로 보일 수 있는 가장 나쁜 현실적 실패에서 시작한다. 실패 시나리오를 적는다. 적지 못하면 상한은 `P2`다(R4-10 FAILURE-ARGUMENT). 엉뚱한 대상에 파괴적 동작(창 닫기, 프로세스 종료, 삭제처럼 되돌릴 수 없는 동작)을 실행하는 결함은 `P1`에서 시작한다(policy: pilot-kwin-20261012 T4). 출력이 맞게 관찰한 값을 이미 함께 싣고 있거나 PR의 목적이 여전히 달성되면, 시작 등급은 위 표의 해당 행(`P2`/`P3`)에서 정한다. 호출자가 그 출력을 잘못 읽어 생길 수 있는 가장 나쁜 결과에서 시작하지 않는다(policy: pilot-kwin-20261012 N2).
2. **중대한 완화 요인을 적는다.** 비기본 설정 필요, 저장소에 없는 호출자 필요, 다른 곳에서 막힘, 개발 전용 경로, 비현실적 입력. 영향받는 사용자가 적다는 것은 완화 요인이 아니다(R4-11). 중대한 요인 하나는 한 단계 이상 내릴 수 있다(R4-11). 다음은 audit policy다(pilot-kwin-20261012 T4):
   - "best-effort by design", "cosmetic", "플랫폼이 의도한 동작", "되돌릴 수 있고 데이터 손실 없음"은 각각 많아야 완화 요인 하나다. 하나를 두 요인으로 나눠 세지 않는다.
   - 출하된 보조 진입점(CLI, REPL)이나 opt-in으로만 켜지는 진입점으로만 닿는 결함은 한 단계 내린다. 두 단계가 아니다.
   - 시작 등급을 고를 때 쓴 드묾(rarity)을 하향 단계로 다시 쓰지 않는다.
   - "비현실적 입력"은 문서화된 어떤 인터페이스나 tool schema도 받지 않는 입력이다. 호출자가 schema를 통해 보낼 수 있는 값은 현실적이다.
3. **총 하향 상한: 시작 등급에서 최대 2단계, valid한 기능 결함은 `P3` 아래로 내리지 않는다.** 이것은 rater 간 안정성을 위한 **audit policy**이며 Chromium 규칙이 아니다(D4). 6번의 경합 상한이 적용되면 그것을 먼저 적용하고, 2단계 상한은 상한으로 정해진 등급부터 센다(policy: pilot-kwin-20261012 T4).
4. **보안 예외(Chromium):** 공격에 비현실적인 전제 조건이 필요하면 보안 finding이 아니라 일반 기능 finding으로 다시 분류하고 1단계부터 다시 매긴다(R4-11). 보안 finding에는 저장소의 실제 배포 환경을 반영한다. 현실적 공격 벡터가 없으면 보안 라벨만으로 등급을 올리지 않는다(R4-12). 선택: 보안 finding의 `notes`에 대략의 CVSS-B 대역을 적는다.
5. **기본 설정에서 닿지 않는 경로**는 보안 민감이 아니면 최대 `P2`다(R4-11).
6. bot 규칙 §8 특례: 비밀 유출은 규모와 무관하게 blocking; 수정 없이도 통과하는 테스트만의 결함은 보통 `P2` non-blocking; 원자적 API가 없는 외부 상태 경합은 최대 `P2`.

important 여부(adjudicated `P0`/`P1`, 또는 `P2` ∧ `p2_blocking`)에서 rater가 갈려 adjudicator가 정한 항목은 모두 보고서의 사례 목록에 올린다(policy: pilot-kwin-20261012 T4).

## 3. Noise codes

### 3.1 rater가 붙이는 코드 (`noise_codes`)

| code | 관찰 가능한 테스트 | 근거 |
|---|---|---|
| `LOW_VALUE` | `valid`하고 크기도 맞지만, 라벨러가 고쳤을 때 얻는 구체적 결함 감소·관례 준수·유지보수 이득을 수정 비용보다 크게 적을 수 없다. | R2-07, R1-25 |
| `NON_ACTIONABLE` | 위치(`file:line` 또는 심볼), 메커니즘, 수정 방향 중 하나가 빠져 작성자가 무엇을 바꿔야 할지 정할 수 없거나, 결함을 주장하지 않고 코드를 설명만 한다(NONSPECIFIC 포함). | R1-18, R1-24, R2-15 |
| `OFF_SCOPE` | 지적한 결함이 merge-base에도 같은 형태로 있고 PR이 새로 노출시키지도 않았거나, PR이 바꾸지 않은 동작에 관한 것이다. bot 규칙 PRR-20은 이런 것을 finding이 아니라 관찰 사항으로 적게 한다. | R1-02, R2-15 |
| `STYLE_PREFERENCE` | 서식·이름·관용구 취향 지적인데, finding이 저장소 규칙을 인용하지 않고 라벨러도 그런 규칙을 찾지 못한다. | R4-03, R1-25 |
| `AUTOMATABLE` | 저장소에 설정된 linter·formatter·type checker가 같은 문제를 잡거나(convention·style 부분, R1-26), 컴파일러나 CI가 같은 결함을 결정적으로 잡는다(빌드 실패, 테스트 빌드 실패, CI check 실패). | R1-26(convention·style 부분만); 컴파일러·CI 확장은 **policy**: owner 결정 U1(reviewer는 CI와 무관하고, CI 실패는 새 커밋과 새 리뷰를 부른다, PRR-38)과 Sadowski CACM 2018(빌드 깨짐은 컴파일러·CI가 맡는다) |
| `DUPLICATE` | 같은 PR의 앞선 finding(같은 리뷰 또는 이전 리뷰)과 근본 원인이 같다. **noise가 아니라 단위 제외 표시다**(§0). | R1-16 (policy: 단위 규칙) |

### 3.2 metrics가 파생하는 코드 (rater는 쓰지 않는다)

| code | 파생 규칙 | 근거 |
|---|---|---|
| `INVALID` | `validity == invalid`. | R2-15, R2-14 |
| `SEVERITY_INFLATED` | `valid`이고, bot 심각도가 adjudicated보다 척도 `P0>P1>P2>P3>nit`에서 2단계 이상 높거나, adjudicated가 `nit`인데 bot이 `P0`–`P2`로 매겼다. bot 심각도는 collector가 finding에서 뽑은 값이다. severity가 없는 body finding은 파생하지 않는다. | R4-02, R1-03, R2-14 (2단계 경계는 policy, D4) |

rater는 bot 심각도를 보지 않으므로(§2) 이 두 코드를 직접 붙이지 않는다(D4).

### 3.3 noise 정의

finding은 `INVALID ∪ SEVERITY_INFLATED ∪ {LOW_VALUE, NON_ACTIONABLE, OFF_SCOPE, STYLE_PREFERENCE, AUTOMATABLE}` 중 하나라도 있으면 noise다. `DUPLICATE` 행은 noise 계산에서 빠진다(D5).

noise가 **아닌** 경우:
- evolvability(문서, 구조, 가독성) finding 자체. 리뷰 산출물의 대부분이 evolvability다(R1-07, R4-07, R1-15).
- `valid`하고 범위 안이며 실행 가능한 finding을 bot이 `P3`로 매겼고 adjudicated가 `P3`나 `nit`인 경우. `P3` 등급 자체는 noise가 아니다(R1-03, R4-02).
- 1단계 과대평가. `over_severity_rate`로만 보고한다(D4). 그것이 `REQUEST_CHANGES`를 만들었으면 verdict-level error로 따로 센다(HRA-25).
- bot 규칙 PRR-49 형식(`file:line`, 메커니즘, 구체적 트리거)을 갖춘 `P3` 질문. 그 형식이 없는 질문이나 막연한 의심은 `NON_ACTIONABLE`이다.
- 작성자가 고치지 않았다는 사실만으로는 noise가 아니다(R4-13, R2-04).
- 구현 봇(`bulgasaribot[bot]`) PR에서 지적이 반영됐다는 사실은 유용성의 증거가 아니고, 반영되지 않았다는 사실도 noise의 증거가 아니다.

## 4. Value (`value`)

| 값 | 테스트 |
|---|---|
| `high` | `valid`이고 adjudicated `P0`/`P1`, 또는 `P2`이면서 `p2_blocking == true`. |
| `normal` | `valid`이고 `high`도 `low`도 아니다. |
| `low` | `validity != valid`, 또는 adjudicated `nit`, 또는 `LOW_VALUE`. |

## 5. Author action (`author_action`, 보조 라벨)

Turzo & Bosu 정의다(R1-19). PR이 merge 또는 close될 때까지의 행동만 본다. 라벨러가 적으면 collector heuristic보다 우선한다(D12). 라벨러는 pass 1에서 `author_action: null`을 쓰고 pass 2에서 이 필드만 채운다(policy: pilot-kwin-20261012 T9).

| 값 | 테스트 |
|---|---|
| `addressed` | 작성자(owner 또는 owner의 에이전트 포함)가 (1) 명시적으로 수용했거나, (2) 제안한 변경을 했거나(later commit이 앵커 ±1줄을 바꿨고 그 변경이 finding과 관련 있음을 확인), (3) 후속 이슈·TODO로 명시적으로 미뤘다. |
| `rejected` | 작성자가 문제가 아니라거나 고치지 않겠다고 명시했다. |
| `ignored` | 위 어느 것도 없다. |
| `unknown` | PR이 아직 열려 있다. |
| `not_applicable` | 그 bot 리뷰가 PR merge 또는 close 뒤에 게시됐다(리뷰 `submitted_at` ≥ `merged_at`, merge되지 않았으면 `closed_at`). `addressed_rate` 분모에서 빠진다. 이 조건을 만족하지 않는 `final` 행은 metrics가 bad row로 돌려준다(policy: pilot-kwin-20261012 T9, N6). |

GitHub 스레드 resolved 상태와 bot 자신의 다음 리뷰가 적은 `Closed` 상태는 근거가 아니다(R1-22, R2-12, R2-28; D12). 구현 봇이 finding에 단 답글(`Fixed at ...`)은 miss 후보가 아니라 이 라벨의 근거로 쓴다. reviewer login(`haechibot[bot]`)으로 게시된 답글은 issue-agent가 쓴 `Fixed at <sha>`라도 작성자 근거가 아니다(policy: pilot-kwin-20261012 T9). pass 2의 입력은 사람·작성자 답글과 커밋이며, 오케스트레이터가 bot 코멘트 본문을 빼고 준다(bot 심각도는 계속 가린다).

## 6. Miss 후보 판정 (`verdict`)

collector 후보, owner 세션 후보, panel 항목에 같은 판정을 쓴다. "fix"·"revert" 키워드나 blame·SZZ 류 추적 결과는 후보일 뿐 증거가 아니다(R3-08, R3-07, R2-17).

| 값 | 관찰 가능한 테스트 |
|---|---|
| `defect_fix` | 결함이 bot이 리뷰한 head에 있고, PR이 들여왔거나(`exposed_by_pr: false`) merge-base의 결함을 새로 도달 가능하게 만들었으며(`exposed_by_pr: true`, D6), 고치면 동작·정확성이 바뀐다(또는 PR이 주장한 목적을 그제야 달성한다). 라벨러가 reviewed head의 `file:line`으로 보인다. |
| `not_defect` | 기능 추가, 리팩터링, 스타일, 리뷰 요구에 따른 범위 변경, 테스트 보강, 결함 없는 토론(R3-08). 결함 수정 커밋에 딸린 hunk는 여기가 아니라 아래 "딸린 hunk" 규칙을 따른다. |
| `external_cause` | 원인이 PR 코드 밖이다: 업스트림·외부 API 변경, 환경, CI 설정, 의존성. reviewer가 diff와 저장소에서 알 수 없었다(R3-09). |
| `pre_existing` | 결함이 merge-base에도 같은 형태로 있고 PR이 새로 노출시키지 않았다. PR 리뷰의 miss가 아니다(PRR-20). 건수만 보고한다. |
| `policy_risk` | 결함이 아니라 owner가 설계·보안 선택을 이유로 merge를 보류하거나 위험을 수용한 항목이다. important miss에 넣지 않고 따로 센다(policy). |

행 구조와 추가 필드:
- **결함 하나에 행이 여럿이다.** 같은 `(pr_id, dedup_key)` 결함이 있던 bot-reviewed head마다 행을 하나씩 쓴다. **행 id는 `<candidate-id>[.<k>]@<head12>`**이고, `head12`는 그 행 `reviewed_head_sha`의 앞 12자리 16진수다(policy, DEC). head 접미사는 id의 마지막 `@<hex>`다. 후보 id 안에 `@`가 있어도 그대로 둔다(policy: pilot-kwin-20261012 B5). 같은 결함의 행들은 `dedup_key`로 묶인다. 결함이 아닌 판정(`not_defect` 등)은 후보의 reviewed head에 행 하나를 쓴다. 모든 결함 행에 `latest_present_head`(결함이 있는 가장 늦은 bot-reviewed head)를 적는다. 필수다. "창 안 마지막 리뷰"로 대신하지 않는다(D3). 두 값 모두 bot이 실제로 리뷰한 head여야 하며, collector의 PR별 bot-reviewed head 목록(`coverage.jsonl`의 `bot_reviewed_heads`)에서 고른다.
- **`not_defect` 행의 null 필드**(policy: pilot-kwin-20261012 T6): `adjudicated_severity`, `present_at_reviewed_head`, `latest_present_head`, `defect_type`, `exposed_by_pr`는 null이다. `pre_existing`과 `policy_risk` 행은 심각도를 적는다.
- `exposed_by_pr`: PR이 들여온 결함은 `false`다. merge-base에 있던 결함을 PR이 새로 도달 가능하게 만들었으면 `true`다. PR이 새로 추가한 파라미터·입력·경로를 통해 base 버그에 닿는 경우도 `true`다. 값은 `defect_fix` 행에만 쓰고 다른 판정에서는 null이다(policy: pilot-kwin-20261012 T6). merge-base는 그 head의 `merge_base`를 쓴다. PR이 base branch를 다시 merge했으면 head마다 다르다.
- `present_at_reviewed_head`: 그 행의 head를 checkout해 확인한 결과(`yes`/`no`/`unknown`).
- 한 후보에 결함이 여럿이면 `@` 앞에서 `<candidate-id>.<k>`로 나눈다(D3). 두 검증자가 다르게 나누면 adjudicator는 labelerA의 번호를 유지하고 labelerB 행을 내용(위치와 메커니즘)으로 대응시킨다(policy: pilot-kwin-20261012 T15).
- **딸린 hunk**(policy: pilot-kwin-20261012 T7): 결함 수정 커밋에 함께 들어간 테스트, 주석, CHANGELOG, 목록 문서 hunk는 그것이 따르는 근본 원인과 같은 `dedup_key`와 판정을 받는다. 그 자체로 서는 테스트·문서 결함(문서화된 저장소 규칙을 어긴 문서, 수정 없이도 통과하는 테스트)은 자기 key를 가진다. 빠진 것 하나 때문에 여러 문서가 낡았으면 결함 하나다.
- `out_of_horizon`: 증거 시점이 anchor + H보다 늦으면 `true`이고 verdict는 비워 둔다. 수치에서 빠지고 깔때기에만 센다.
- `coverage_only`(§9): 다음 결함이면 `true`이고 verdict는 `defect_fix`다(R3-11; policy: pilot-kwin-20261012 T8). (a) bot 리뷰를 한 번도 받지 못한 PR의 결함; (b) 첫 bot-reviewed head 전에 들어왔다가 고쳐진 결함; (c) bot-reviewed head들 사이에만 있었던 결함(어느 reviewed head에도 없다); (d) 마지막 bot-reviewed head 뒤에 push된 커밋이 들여온 결함. id에는 `@<head12>`가 없거나 후보의 `@<head12>`가 붙는다. `reviewed_head_sha`·`latest_present_head`는 null이어도 된다. `R_imp`와 모든 miss 수치에서 빠지고 `coverage_unreviewed_defects`로만 센다.
- `is_defect`: `verdict ∈ {defect_fix, external_cause, pre_existing}`이고 결함이 실재하면 `true`.
- `repo_rule`: 결함이 저장소에 적힌 규칙(AGENTS.md, CONTRIBUTING, 문서 동기화 규칙, 테스트·프로세스 규칙)을 어긴 것이면 `true`. important가 아니어도 따로 센다(policy). base가 다른 파일에서 이미 같은 규칙을 어기고 있어도 PR이 새로 빠뜨린 것은 결함이며, 규칙이 달리 정하지 않으면 `P3`다. base에 이미 있던 누락은 보고하지 않는다(policy: pilot-kwin-20261012 PR3-3).
- **이미 있던 동작에 대한 새 주장**(policy: pilot-kwin-20261012 PR3-4): PR이 merge-base에 이미 있던 동작에 대해 새로 주장하는데(예: "SIGINT가 이제 세션을 멈춘다") 그 동작이 base에서부터 틀렸으면, 결함은 PR이 들여온 주장이다. verdict `defect_fix`, `defect_type: functional/claim_mismatch`, `exposed_by_pr: false`, `p2_blocking: false`(조건 2 불충족)이고 심각도는 §2 표에서 정한다. `pre_existing`이 아니다.
- `sources`: 그 결함을 드러낸 채널 이름의 목록이다(§9의 `channel` 값, 예: `["post_review_hunk", "panel"]`)(policy: pilot-kwin-20261012 T6).
- `irr_sample`: 무작위 IRR 층에 뽑힌 항목이면 `true`(HRA-11). panel 행은 `irr_sample: false`, `out_of_horizon: false`다(policy: pilot-kwin-20261012 T15).
- **근거 필드**(policy: pilot-kwin-20261012 T6): candidate verifier, panel reviewer, panel judge 행은 `path`, `line`, `mechanism`(한 문장 이상, 자르지 않음), `evidence_kind`(`file_line` | `probe` | `code_path_only` | `unverified`), `exposed_by_pr`를 가진다. matcher에 넘길 때 어떤 필드도 자르지 않는다.

### 후보 위생 (blame과 add-only 수정)

- post-merge 커밋을 PR에 연결할 때는 `git blame -w -M -C`로 공백·이동·복사를 무시하고, 리팩터링만 한 hunk는 버린다(R3-06).
- 줄을 **추가만** 하는 수정(빠진 검증, guard, 권한 확인, 테스트)은 줄 겹침으로 찾을 수 없다. 파일·함수 이력을 따라 그 코드가 있어야 했던 PR을 직접 찾는다(R3-10).
- merge commit 중 first-parent diff가 설명하지 못하는 PR 파일 변경(evil merge)은 사람이 확인할 목록에 올린다.
- 여러 수정을 묶은 post-merge 커밋은 blame이 이 PR에 연결하는 부분만 `.k`로 나눠 판정하고, 나머지 부분은 `notes`에 적고 버린다(policy: pilot-kwin-20261012 T7).
- owner 세션이 나중에 main에서 찾은 결함(release QA 등)은 그 줄을 `git blame -w -M -C`로 따라가 이 PR의 squash 커밋에 닿을 때만 PR에 귀속한다. 닿지 않으면 버리고 버린 건수를 보고한다(policy: pilot-kwin-20261012 T12).

## 7. Important와 escaped

**Important**(D6): adjudicated `P0`/`P1`, 또는 `P2`이면서 `p2_blocking == true`. bot 자신의 계약(PRR-22)이 이 P2에서 `REQUEST_CHANGES`를 내게 하므로 포함한다(policy, bot 계약 기반). 문헌 비교용으로 `P0`/`P1` 소계를 항상 같이 보인다(R4-15, R4-06, R2-19).

reference 항목이 important로 들어가려면: `verdict == defect_fix`, `present_at_reviewed_head == yes`, important 심각도, 그리고 독립 확인(collector·owner 후보는 2번째 verifier와 adjudication, HRA-13; panel 항목은 panel과 분리된 panel judge, HRA-15).

- **`important_escaped`(헤드라인):** important 결함이 하나 이상의 bot-reviewed head에 있었고, 그 결함의 행들 중 어느 것도 `hit`이 아니다. 가장 좋은 판정이 `partial`이어도 escaped다(D3, D6, R2-18).
- **`first_exposure_miss`(보조):** 결함이 처음 있던 reviewed head의 행이 `hit`이 아니다.
- **`important_partial`:** escaped 중 가장 좋은 판정이 `partial`인 것. 소계로 보인다.
- **severity miss:** `hit`이지만 bot 심각도가 adjudicated보다 2단계 이상 낮다. escaped에는 넣지 않고 따로 센다(R3-23).

important 결함은 보통 functional이다. evolvability 항목은 owner가 명시적으로 중요하다고 올린 경우만 important다(R1-07).

## 8. Matching (`bot_match`, `matched_finding_id`)

reference 결함을 그 결함이 있던 각 reviewed head의 bot 리뷰 finding과 맞춘다(R2-18, R3-21, R3-22).

| 값 | 테스트 |
|---|---|
| `hit` | 위치가 맞고(같은 hunk 또는 같은 함수, 또는 앵커 ±3줄) 메커니즘과 영향을 맞게 설명한 bot finding이 있다. |
| `partial` | finding이나 리뷰 본문이 이 결함의 실패를 짚었지만 메커니즘이 틀리거나 막연하다; 또는 결함 앵커 ±3줄 안을 가리키며 관련된 메커니즘을 말한다. 같은 함수는 관련된 메커니즘을 말할 때만 위치가 맞는 것으로 친다. 위치 없는 요약·본문 언급과 `Not verified`/`Open items` 항목은 이 결함의 실패를 짚을 때만 `partial`이다. 언급이 `findings.jsonl` 행이 아니면 `matched_finding_id: null`과 그 리뷰의 `review_id`를 쓴다. |
| `miss` | 둘 다 아니다. 이 결함을 짚지 않는 `Not verified` 단서, 메커니즘이 다른 이웃 finding, 결함 동작을 옳다고 단정한 본문은 `miss`이고, 그 사실을 `notes`에 적는다. |

행 판정 규칙(policy: pilot-kwin-20261012 T5, A7):
- finding 하나는 그것이 말한 메커니즘 하나당 결함 하나에만 `hit`이나 `partial`을 준다.
- `review_id`: `hit`과 `partial`에는 판정에 쓴 리뷰의 id를 적고, `miss`에는 null이다. 한 head에 bot 리뷰가 여럿이면 그중 어느 것이든 쓸 수 있고 가장 좋은 값을 택한다.
- 매칭 대상: escape 수치가 쓰는 행, 곧 important `defect_fix` 행 중 bot-reviewed head에 있고(`present_at_reviewed_head: yes`) `coverage_only`가 아닌 행만 매칭한다(policy: pilot-kwin-20261012 N3).
- `final` miss 행의 `bot_match`가 `hit`이나 `partial`인데 그 `matched_finding_id`의 `final` validity가 `invalid`이면 metrics가 `conflicts`로 나열한다. bad row가 아니라 다시 adjudicate할 목록이다(finding 라벨이 있을 때만).
- 행마다 그 행의 head를 리뷰한 bot 리뷰와 비교해 `bot_match`를 정한다. 결함 단위 판정은 metrics가 행들 중 가장 좋은 값(`hit > partial > miss`)으로 정한다.
- 매처는 PR마다 두 번 독립 실행하며 rater id는 `matcher-defect_first`, `matcher-review_first`다. 두 실행이 같은 값이면 그 값을 `final`에 복사하고(`notes: matcher-copy`), 다르면 adjudicator가 rubric §8을 직접 적용해 `final`을 정한다. "낮은 값을 택한다" 규칙은 없다(DEC, R2-27, R4-19).
- match 표본(Phase 5): 사람이 확인한 행은 그 사람의 값으로 matcher-copy `final`을 **대체**하고 `match_sample: true`를 붙인다. `irr_sample`과는 별개다. `match_kappa`는 `match_sample` 행에서만, 순서별로 각 matcher rater 대 사람 `final`로 계산한다.
- 매처는 후보 판정자와 다른 실행이다(후보 판정자는 bot 출력을 보지 않는다).
- metrics는 valid important bot finding으로부터 `channel: bot_finding`, `bot_match: hit` 행을 자동으로 만든다. 그러려면 그 finding의 라벨에 `dedup_key`가 있어야 한다(D7).

## 9. 채널 (`channel`)

| channel | 출처 | 비고 |
|---|---|---|
| `post_review_hunk` | collector | bot 리뷰 뒤 push된 non-merge PR 커밋 hunk(R1-10) |
| `human_comment` | collector | 사람 리뷰·코멘트. `implementer_bot` 답글은 제외하고 §5로 보낸다 |
| `post_merge_commit` | collector | 기본 브랜치의 merge 뒤 커밋. §6 위생 적용 |
| `cross_reference` | collector | PR을 참조한 이후 이슈·PR |
| `owner_session` | omp `archive` | `private/<window>/extra-candidates.jsonl`, 후보 id `<pr-id>/os<k>`, bot 텍스트 제거, `anchor_review_id`·`anchor_at` 포함(D17) |
| `panel` | blind 재리뷰 | 후보 id `<pr-id>/pA<k>`(reviewer A), `<pr-id>/pB<k>`(reviewer B). A·B 중복은 panel judge가 합친다 |
| `bot_finding` | metrics 자동 | valid important bot finding |

runner Codex transcript는 bot 자신의 추론이므로 진단에만 쓰고 miss 채널로 쓰지 않는다(D17). 사람 코멘트와 owner 판단은 oracle이 아니다. 사람 코멘트만으로 만든 기준은 실제 결함을 크게 덜 센다(R3-24).

모든 후보는 증거 시점 ≤ anchor + H일 때만 센다. anchor는 PR 안 채널이면 귀속된 bot 리뷰의 `submitted_at`, post-merge 커밋이면 `merged_at`이다(D1). owner 세션 후보의 anchor는 증거 시점 이전의 가장 늦은 bot 리뷰이고, 그런 리뷰가 없으면 그 PR의 첫 bot 리뷰다. collector 후보 행은 모두 `reviewed_head_sha`를 가진다: anchor 리뷰의 head이고, post-merge 커밋이면 마지막 bot-reviewed head, bot 리뷰 전에 달린 사람 코멘트이면 첫 bot-reviewed head다. PR에 bot 리뷰가 전혀 없거나 §6의 다른 `coverage_only` 경우이면 그 결함은 `coverage_only: true` miss 행으로 쓴다. 이 행은 `reviewed_head_sha`·`latest_present_head`가 null이어도 되고 id에 `@<head12>`가 없거나 후보의 `@<head12>`가 붙는다. `R_imp`와 모든 miss 수치에서 빠지고 `coverage_unreviewed_defects`로만 센다.

**bot-reviewed head 목록**(policy: pilot-kwin-20261012 K2, T15): 모든 역할은 head를 collector가 `coverage.jsonl`의 `bot_reviewed_heads`에 낸 목록에서만 읽는다. 이 목록은 답글 컨테이너 리뷰를 빼고, force-push로 사라진 head를 남기며(`in_commits: false`), 첫 리뷰 순서로 정렬된다. head마다 `sha`, `first_review_at`, `review_ids`, `commit_ids`(GitHub `commit_id`), `body_head`, `merge_base`, `merge_base_note`가 있다. 리뷰 본문에 적힌 head("reviewed at <sha>", "re-reviewed at <sha>")가 `commit_id`와 다르면 본문 head가 `sha`가 되고 `commit_ids`에 GitHub 값이 남는다. GitHub `commit_id`로 head를 적은 라벨 행(id의 `@<head12>` 포함)은 검증기가 받아들이고, metrics와 `kappa --dir`이 본문 head로 바꿔 맞춘다. `merge_base`는 PR이 base branch를 다시 merge했을 때만 채워지며, null이면 PR의 merge-base를 쓴다(compare가 실패하면 null과 `merge_base_note`). 오케스트레이터는 이 목록을 모든 역할의 입력에 넣고, 어떤 텍스트도 잘라서 넘기지 않는다.

## 10. Defect type (`defect_type`)

1차는 coarse class, subtype은 탐색용이다(R1-11, R4-08). 둘 다 맞으면 functional이다(R1-11). 그 결함을 고친 변경이 무엇을 바꾸는지로 정한다(R4-09).

- `functional/*`: 고치면 런타임 동작이나 빌드·배포·설정 동작이 바뀐다(R1-07, R1-08).
  - `resource`: 데이터·변수·자원 초기화, 조작, 해제
  - `check`: 입력·값 검증, 잘못된 값 감지
  - `interface`: 라이브러리, OS, DB, 하드웨어, 외부 API와의 상호작용
  - `logic`: 비교, 제어 흐름, 계산
  - `timing`: 동시성, 공유 자원, 순서
  - `support`: 빌드 시스템, 버전, 의존성, 설정(Helm/Kustomize/Terraform/Nix 포함)
  - `larger`: 몇 줄로 집을 수 없는 빠지거나 잘못 구현된 기능
  - `claim_mismatch`: PR 본문이 주장한 동작을 코드가 내지 않는다. 주장한 동작이 base에서부터 없던 경우도 포함한다(§6). (policy; bot 규칙상 전체 해결을 주장하며 일부만 해결하면 P1)
- `evolvability/*`: 고쳐도 동작은 같고 이해·수정이 쉬워진다(R1-07).
  - `documentation`: 주석, 이름, 메시지, 문서 동기화
  - `visual`: 서식, 공백
  - `structure`: 구성, 해결 방식, 죽은 코드, 중복

## 11. 층화 어휘

collector가 정한다(D15).
- `author_type`: `owner`(isac322), `implementer_bot`(`bulgasaribot[bot]`), `automation`(dependabot, github-actions 등), `external`(그 밖).
- `file_type`: finding·결함 앵커 파일 기준 `code`, `test`, `build_config`(Helm, YAML manifest, Terraform, Nix, Dockerfile, CI, Makefile), `docs`.
- `verdict`: body의 `**Verdict: X**` 줄(GitHub 상태가 아님). superseded 리뷰는 GitHub에서 `DISMISSED`로 바뀌므로 body를 쓴다.
- `size_bucket`: `S` < 50 changed lines, `M` < 400, `L` ≥ 400 또는 ≥ 20 files. 줄 경계는 owner policy이고, ≥ 20 files 경계만 R1-14가 뒷받침한다.

## 12. 라벨 파일 행

어휘는 collector의 `VOCAB` 표가 강제한다. 어긋난 행은 metrics가 `bad_rows`로 돌려준다.

- `labels-findings.jsonl`: `id`, `rater`(`labelerA`/`labelerB`/`final`), `irr_sample`, `validity`, `adjudicated_severity`, `p2_blocking`, `noise_codes`(§3.1 코드만), `value`, `author_action`(선택; §5 값, pass 1 행은 null), `defect_type`, `dedup_key`(valid important이면 필수), `file_type`(선택, 없으면 collector 값), `notes`.
- `labels-misses.jsonl`: `id`(`<candidate-id>[.<k>]@<head12>`; `coverage_only` 행은 `@` 없음 또는 후보의 `@<head12>`), `rater`(`labelerA`/`labelerB`/`final`), `irr_sample`, `match_sample`, `out_of_horizon`, `coverage_only`(§6, §9), `channel`(`bot_finding` 제외), `verdict`, `exposed_by_pr`(`defect_fix` 밖에서는 null), `is_defect`, `reviewed_head_sha`, `latest_present_head`(`coverage_only`·`not_defect` 행이면 null 허용), `present_at_reviewed_head`(`not_defect`이면 null), `adjudicated_severity`(`not_defect`이면 null), `p2_blocking`, `bot_match`(`final` 행에만 필수), `matched_finding_id`, `review_id`(`hit`·`partial`에 적고 `miss`에는 null; `partial`이고 `matched_finding_id`가 null이면 필수), `defect_type`(`not_defect`이면 null), `repo_rule`, `dedup_key`, `sources`(채널 이름 목록), `path`, `line`, `mechanism`, `evidence_kind`(§6 근거 필드; 검증기는 검사하지 않는다), `file_type`(선택), `notes`.
- `labels-judge.jsonl`(rater `judge`, finding에 대한 `judge_batch` 제안), `labels-judge-candidates.jsonl`(rater `judge`, 후보에 대한 `judge_batch` 제안: verdict와 `p_not_defect`), `labels-matcher.jsonl`(rater `matcher-defect_first` / `matcher-review_first`)은 **별도 파일**이다. 라벨 파일 검증 대상이 아니다. `labels-judge.jsonl`은 `judge_bias`, `labels-matcher.jsonl`은 `match_kappa`와 match disagreement 처리에만 쓴다. `labels-judge-candidates.jsonl`은 metrics가 읽지 않으며 triage 닫기와 감사 표본의 기록이다(policy: pilot-kwin-20261012 B2).
- 누가 무엇을 쓰나: finding은 labeler(labelerA/B)와 adjudicator; miss 행은 candidate verifier와 panel judge가 `labelerA`(두 번째는 `labelerB`)로 쓰고, 검증자가 하나면 그 행을 `final`로 복사하며, 둘이면 adjudicator가 `final`을 쓴다. 그 뒤 `dedup_reconciler`가 PR마다 `final` 행의 `dedup_key`와 `sources`를 채널 사이에서 맞추고(SKILL Phase 4.4), matcher 결과는 위 §8대로 `final`의 `bot_match`에 들어간다.
- triage로 닫은 후보는 `rater: final`, id `<candidate-id>@<head12>`(후보의 reviewed head), `verdict: not_defect`, `is_defect: false`, `notes: "judge-triage p=<P(not_defect)>"`로 쓴다.
- `notes`, `evidence`, `mechanism`에는 공개 저장소의 `file:line`과 채널 이름만 쓴다. owner 세션 id, 로컬 경로(scratch 경로 포함), 비공개 텍스트는 `$ROUND/private/`에만 둔다(D2; policy: pilot-kwin-20261012 PR3-6).
