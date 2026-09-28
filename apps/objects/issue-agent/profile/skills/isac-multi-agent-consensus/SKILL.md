---
name: isac-multi-agent-consensus
description: Use inside the issue agent's triage, implement/followup, and review turns whenever a verdict, root cause, QA list, test tier, design choice, or review decision must come from several independent subagents (investigation angles, cross-critique, consensus or arbiter, fix-until-GREEN review loop, size gate), with unresolved user-level decisions returned as result questions instead of waiting.
---

## Automation adaptation

이 사본은 homelab issue agent(n8n + bridge + HAPI + Codex)용으로 원본 `isac-multi-agent-consensus`를 기계적으로 고친 것이다. 에이전트는 읽기 전용 GitHub 토큰으로 무인 실행되고, 턴 끝에 `ISSUE_AGENT_RESULT <nonce> {json}` 결과(TriageResult / ImplementResult / ReviewResult)를 낸다. GitHub 쓰기는 모두 n8n이 결과를 받아 bridge로 한다. 바뀐 것:

- 사용자에게 올리는 질문(`isac-decision-brief`)은 채팅으로 묻고 기다리지 않는다. 결과의 `questions`와 초안 GitHub 텍스트(TriageResult.comment, ImplementResult.issue_comment, ReviewResult.body)에 담고, 해당 next_action/status(`await_decision`, `await_info`, `needs_info`)로 턴을 끝낸다. ReviewResult에는 `questions` 필드가 없으므로 body에만 둔다.
- 한국어 최종 보고는 결과의 `summary`(짧은 영어)가 된다. 실질 내용은 다른 결과 필드에 담는다.
- 게시 주체는 n8n이다. 에이전트와 토론 역할은 GitHub에 쓰지 않는다.
- `isac-skill-correction` 안내 문장과 호출 목록 항목은 지웠다.

| 원본 단계 | 결과 필드 |
|---|---|
| 남은 쟁점·사용자 결정 올리기 (MAC-11, MAC-12, defaults §5) | `questions` + 초안 GitHub 텍스트, next_action/status로 턴 종료 |
| `P2` 잔여 위험 수용 요청 (MAC-16) | `questions` + 초안 GitHub 텍스트 |
| 최종 보고 (§5, defaults §6) | `summary`, 사용자 결정 항목은 `questions` |

고친 곳: MAC-11, MAC-12, MAC-16, §4 경계(게시 주체 줄, 호출 시점 줄), §5, `references/defaults.md` §3·§5·§6, `references/cases.md` 머리말.

# Multi-Agent Consensus

판정을 메인 에이전트 한 명의 의견이 아니라 독립 조사 → 상호 반박 → 합의/중재로 만든다. 다른 스킬은 "`isac-multi-agent-consensus`를 따른다"로 이 절차를 호출한다. 호출 스킬은 **언제·무엇을** 판정할지와 판정 결과 범주, 관점 목록을 소유하고, 이 스킬은 **어떻게** 판정할지만 소유한다.

`[U]` = 사용자 지시·교정·승인에서 온 규칙이다. 사용자 승인 없이 완화하거나 삭제하지 않는다. 태그 없음 = 바꿀 수 있는 기본값이다.

MAC-04와 MAC-06은 폐기했고 번호는 재사용하지 않는다(`references/cases.md`의 규칙 이력).

하네스가 이미 소유한 것은 재서술하지 않는다: 서브에이전트 위임 계약(Target/Change/Acceptance 브리프, 반환 스키마), 병렬 slice의 파일 소유권과 통합, 서브에이전트의 빌드·테스트 금지, `orchestrate`/`jevify` 키워드 처리.

## 1. 적용 조건과 역할

- **MAC-01** [U] 멀티 에이전트 모드(`orchestrate`)이거나 사용자가 토론·교차 검증을 요청한 작업에서, 판정(실제 문제인지, 근본 원인, QA 목록, 테스트 계층, 설계·구조·분류 결정)은 메인 혼자 내리지 않는다. 여러 에이전트가 독립적으로 조사하고, 토론과 교차 검증으로 합의한 결과를 쓴다. (기본값, 태그 없음) 호출 스킬이 이 절차를 지정한 판정도 같다.
- **MAC-02** [U] 사용자가 멀티 에이전트 모드를 요청하면(메시지 앞 `orchestrate`, `orchestrate jevify` 포함) 구현뿐 아니라 분석·질문 응답·감사·릴리스 요청에도 적용한다. 메인은 판단, 결정, 다음 단계 진입, 역할 재분배, 리뷰, 통합만 한다. 리서치·실험·구현·항목별 작업은 역할별 서브에이전트에게 맡긴다. 요청에서 사용자가 메인 역할을 따로 정하면 그것을 따른다(예: 메인은 문제 탐색만 하고 조사·이슈 작성은 서브에이전트).
- **MAC-03** [U] 항목(이슈, PR, 앱, 리소스)이 여러 개면 항목마다 owner 에이전트를 하나씩 두고 병렬로 처리한다. 순차 처리는 실제 의존성이 있을 때만 한다. 진행이 느리면 실제로 병렬로 돌고 있는지부터 확인한다.
- **MAC-05** 규모 게이트. 토론 규모는 판정의 무게에 비례한다. 축소해도 MAC-01은 유지한다(최소 2 에이전트, 그중 하나는 반론자).

  | 규모 | 조건 | 구성 |
  |---|---|---|
  | 사소 | 사실 한 건 확인, 되돌리기 쉬운 선택 | 조사자 1 + challenger 1 |
  | 표준 | 단일 항목의 근본 원인·QA 목록·설계 결정 | 고정 관점 조사자 3 + challenger(설계·구조 결정이면 입장별 advocate) |
  | 대량 | 항목 2개 이상 또는 멀티 에이전트 모드 | 항목별 owner. 판정 항목마다 사소/표준 중 해당 구성 |

  arbiter는 합의가 실패했을 때만 추가한다(MAC-11). 반박 라운드는 기본 2회다. 격리 가능한 작업은 병렬로 하고, 같은 원격 상태를 바꾸는 작업만 직렬로 한다.
- **MAC-07** 작업 도중 사용자가 새 규칙이나 정정을 주면 실행 중인 서브에이전트에 즉시 전파하고, 이후 위임에는 standing constraint로 넣는다.

## 2. 토론 절차

- **MAC-08** 시작 전에 판정 질문 한 문장, 판정 기준(무엇을 보면 참/거짓인지), 결과 범주를 고정한다. 결과 범주는 호출 스킬의 것을 쓴다(예: `issue-validation` verdict, 실제 문제/문제 아님).
- **MAC-09** 독립 조사: 조사자마다 서로 다른 고정 관점을 배정한다. 서로의 결과를 보기 전에 현재 코드·worktree·실제 상태를 직접 읽고, 주장마다 file:line이나 관측 증거를 붙인다. 오케스트레이터의 가설도 검증 대상이다. 관점 세트는 호출 스킬이 주고, 없으면 `references/defaults.md`를 쓴다.
- **MAC-10** 교차 반박: 조사자와 분리된 challenger가 반박하거나, 입장별 advocate가 가장 강한 논거와 `## Concessions`(상대 입장에서 인정하는 점)를 낸다. 반박에는 증거가 있어야 하고, 증거 없거나 실행하지 않은 반박과 제안은 기각한다.
- **MAC-11** 합의·중재: 합의되면 채택한다. 기술적 쟁점에서 합의가 실패하면 조사에 참여하지 않은 arbiter가 판정한다. MAC-12에 해당하는 쟁점은 arbiter에게 보내지 않는다. arbiter 뒤에도 남은 쟁점은 선택지와 권장안을 `isac-decision-brief` 형식으로 결과의 `questions`와 초안 GitHub 텍스트에 담고 턴을 끝낸다(기다리지 않는다). 결과는 채택·기각 매트릭스(근거 포함), 번복·철회 기록, 수용한 잔여 위험으로 남긴다. 이미 투입한 비용(매몰 비용)은 근거로 받지 않고, 기각한 비현행 대안을 최소 하나 근거와 함께 적는다.
- **MAC-12** [U] 목적·의도·기획 수준에서 사용자 입력이 있어야 하는 결정(의도가 불명확하거나 제품 방향을 가르는 선택)과 프로젝트 핵심을 바꾸는 근본 해결은 에이전트끼리 확정하지 않는다. 현상·원인·선택지·권장안을 갖춰 `isac-decision-brief` 형식으로 결과의 `questions`와 초안 GitHub 텍스트에 담고, `await_decision` 등 해당 next_action/status로 턴을 끝낸다. 절차·운영상의 선택(예: 머지 후 작업 브랜치 삭제)은 묻지 않는다.
- **MAC-13** [U] 설계·모델링 결정이 열려 있는 동안 사용자의 제안이나 가설을 그대로 수용하지 않고 근거로 반박을 시도한다. 사용자가 에이전트 안이 가장 나아 보인다고 해도 확정 전에 더 나은 모델링이 없는지 한 번 더 찾는다. 사용자가 결정한 뒤에는 다시 꺼내지 않는다. 반박 형식은 `references/defaults.md`.
- **MAC-14** [U] 사용자가 최선의 구조·구현을 물으면 현행 구현을 전제로 비교하지 않는다. 구현체 교체, 구조 변경, 안정적인 기존 도구·OSS 재사용까지 후보에 넣는다. "이미 그렇게 구현돼 있다"만으로 정당화하지 않고, 전환 비용은 비교 항목으로 적는다.
- **MAC-15** 성능·우위 주장은 측정 없이 단정하지 않는다. 추론이면 `[INFERENCE]`로 표시하고, 판정을 가르는 주장이면 동일 조건 scratch 실험으로 확인한다. 실행하지 않은 검증을 통과로 쓰지 않는 규칙은 전역 `verification` 규칙이 소유한다.

## 3. 리뷰-GREEN 루프

- **MAC-16** [U] 우리 작업물은 직전 검증 절차(명령, 범위, 기준)를 기록해 두고, 수정 후 같은 절차를 그대로 다시 돌려 더 이상 틀린 것이 나오지 않을 때까지 반복한다. 틀린 것을 고칠지 사용자에게 묻지 않는다. 종료 기준(기본값, 태그 없음): `P0`–`P2`가 0이다. `P2`를 남기려면 사용자가 잔여 위험으로 수용해야 하고(수용 요청은 결과의 `questions`와 초안 GitHub 텍스트에 담는다) 그 사실을 `summary`에 보고한다. `GREEN`만으로는 종료하지 않는다. 다른 스킬이 우리 작업물에 대해 "리뷰 통과"나 "리뷰-GREEN 루프 종료"라고 쓰면 이 종료 기준을 뜻한다. 남의 PR을 판정만 하는 리뷰는 MAC-19의 라운드 판정을 쓴다.
- **MAC-17** 독립 리뷰어는 구현자와 분리된 read-only 에이전트다. 수정 요약을 믿지 않고 현재 worktree와 head를 직접 읽는다. 재리뷰마다 이전 finding이 실제로 닫혔는지 fix의 논리를 다시 도출해 확인하고, 새 테스트가 옛 코드에서 올바른 이유로 실패하는지 본다. 틀린 지적은 근거와 함께 철회한다. 재현이 필요하면 판정 리뷰어와 분리된 실행자가 격리 환경에서 돌린다.
- **MAC-18** [U] 멀티 에이전트 모드에서 서브에이전트들이 여러 이슈를 병렬로 고쳐 PR을 만들고 사용자가 메인에게 리뷰를 맡기면, 메인은 PR 코드를 한 줄씩 읽고 이슈와 대조해 리뷰한다. 기본값으로 독립 리뷰어(MAC-17)를 추가해 교차 확인할 수 있다. finding은 해당 항목의 owner 에이전트에게 돌려보내 고치게 하고, 메인이 직접 패치하지 않는다.
- **MAC-19** 리뷰 라운드의 판정 어휘는 하나의 닫힌 집합만 쓴다.
  - 라운드 판정: `GREEN`(blocking finding 0, 근거 첨부) 또는 `BLOCKING`(finding 목록).
  - finding: 심각도 `P0`–`P3`, file:line이나 관측 가능한 실패, 최소 수정안. `P0`/`P1`이 blocking이다. 여러 리뷰어가 같은 finding을 내면 한 번만 센다.
  - PR이 대상이면 `PR-ready: true|false`를 함께 낸다.
  - 모호한 요약, 조건부 승인, 빈 칭찬은 판정으로 인정하지 않는다. 심각도 정의는 `references/defaults.md`에 있다.
- **MAC-20** `GREEN`은 판정한 상태(head SHA, 배포 digest 등)에만 유효하다. 대상이 바뀌면 다시 판정한다. PR 리뷰 요청·재요청과 무효화 규칙은 전역 PR 리뷰 가드가 소유한다.

## 4. 경계

- 근본 원인 조사 방법: `five-whys-root-cause-analysis`. 재현, verdict 분류, fix provenance: `issue-validation`. 이 스킬은 그 결과를 여러 에이전트가 검증·합의하는 틀만 준다.
- 받은 리뷰 대응: `receiving-code-review`와 전역 PR 리뷰 가드.
- 질문 형식: `isac-decision-brief`. 질문 여부와 승인: 전역 task-intent, 애플리케이션 코드 승인, PR 생성·머지 가드.
- GitHub 게시: 에이전트는 GitHub에 쓰지 않고, n8n이 결과 필드를 받아 게시한다. 문체·위생은 `isac-github-publishing`. 토론 역할(조사자, challenger, advocate, arbiter, 판정 리뷰어)은 GitHub에 쓰지 않는다.
- 호출 시점: `isac-issue-triage`(근본 원인, 실제 문제 여부), `isac-issue-to-pr`(구현 전 QA 목록, 테스트 계층, 머지 전 리뷰), `isac-pr-review`(리뷰 판정), `isac-live-qa`(QA 목록, 후보별 실제 문제 판정).

## 5. 보고

최종 보고(결과의 `summary`, 짧은 영어)에는 판정, 채택·기각 요지, 수용한 잔여 위험을 적고, 사용자 결정이 필요한 항목은 `questions`에 적는다. 보고 형식은 `references/defaults.md`를 따른다.
