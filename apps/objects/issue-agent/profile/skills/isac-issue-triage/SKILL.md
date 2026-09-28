---
name: isac-issue-triage
description: Use in the issue-agent `triage` mode (a new issue, or a new comment on an issue not yet in implementation) to deduplicate, reproduce by execution, classify the fault domain, find the root cause by multi-agent Five Whys, decide a fix direction or a structural-change brief, and return the repro/triage labels, one English analysis comment, and the next action as a TriageResult for n8n to publish.
---

## Automation adaptation

이 스킬은 homelab issue agent(n8n + bridge + HAPI + Codex)에서 무인으로 실행되도록 기계적으로만 바뀌었다. 규칙 ID·케이스·표·템플릿은 원본 그대로이며, 아래 대응만 적용한다. 바뀐 곳: frontmatter `description`, 도입 문장, `## 경계`의 GitHub 쓰기·인계 항목, §0 모드 문단, TRI-01, TRI-03, TRI-41, TRI-42, TRI-46, TRI-08, TRI-09, TRI-43, TRI-11, TRI-13, TRI-15, TRI-21, TRI-22, TRI-23, TRI-25, TRI-28, TRI-29, TRI-30, §8 제목·TRI-52·TRI-45, TRI-38, TRI-40, `## 완료 조건`, `## 교정`(삭제). references: `labels.md`(도입, `documentation` 행, 판정 표의 다음 단계 → `next_action`, 전이, 기존 라벨 매핑), `comment-template.md`(도입, ⑤→④ 제자리 수정), `defaults.md`(Write boundary, scratch 경로, 반환 필드 → TriageResult, 게시 전 검토 → 반환 전, 재현 환경), `design-research.md`(도입, Brief 단계), `cases.md`(`isac-skill-correction` 문장 삭제).

- **GitHub 쓰기 금지.** 에이전트는 GitHub에 아무것도 쓰지 않는다(읽기 전용 토큰). 라벨 부착·교체, 댓글 게시·제자리 수정, 이슈 닫기, 외부 저장소 이슈 등록을 시도하지 않는다. 원본의 모든 쓰기 단계는 턴 끝의 `ISSUE_AGENT_RESULT <nonce> {json}` 줄에 담는 TriageResult 필드로 바뀌고, n8n이 bridge ops로 적용한다.
- **게시/초안 모드 없음.** 항상 초안을 결과에 담는다. "게시"는 "결과 필드에 담아 반환"으로, "게시 전"은 "반환 전"으로 읽는다.
- **질문·승인 대기 없음.** 사용자에게 묻거나 승인을 기다리는 단계(`isac-decision-brief` 포함)는 질문을 `questions`와 `comment`에 함께 넣고 `next_action`을 `await_decision`(메인테이너 결정·TRI-25) 또는 `await_info`(제보자 정보)로 두고 턴을 끝낸다. 채팅 답을 기다리지 않는다.
- **최종 보고(한국어) → `summary`.** 사용자 보고·최종 보고는 짧은 영어 `summary`가 되고, 실질 내용은 다른 결과 필드가 담는다.
- **독립 검토·합의 유지.** 반환 전 독립 검토자와 `isac-multi-agent-consensus` 단계는 서브에이전트로 그대로 수행한다.
- **작업 위치.** HAPI 워크트리가 유일한 체크아웃이며 트리아지는 추적 파일을 수정·커밋하지 않는다. scratch 산출물(`dossier.md`, `result.json`, `comment.md`, 로그)은 `/tmp/issue-agent/<worktree-name>/` 아래에 두고 커밋하지 않는다.
- **삭제.** `isac-skill-correction`만 가리키던 `## 교정` 절을 지웠다.

단계 → TriageResult 필드:

| 원본 단계 | TriageResult 필드 |
|---|---|
| 판정(TRI-12, `issue-validation` verdict) | `verdict` |
| 결함 영역(TRI-51) | `fault_domain` |
| 중복 정본(TRI-41, `duplicate`) | `duplicate_of` (verdict DUPLICATE일 때만 정본 번호) |
| 라벨 부착·교체·제거(TRI-28/29, `references/labels.md`) | `labels.add` / `labels.remove` — 카탈로그 이름만. `agent:needs-attention`은 절대 넣지 않는다(bridge 전용). 같은 그룹 값을 넣으면 bridge가 그룹의 이전 값을 뗀다 |
| 분석·재현 안 됨·중복·상태 갱신 댓글(TRI-30/31, `references/comment-template.md`) | `comment` (영어 markdown 하나, 댓글이 없으면 `null`) |
| `references/labels.md`의 "다음 단계" 열 | `next_action` (아래 표) |
| `isac-issue-to-pr` 인계 내용(수정 설계 + 회귀 테스트 계약 + 범위) | `implementation_brief` (`next_action: implement`일 때만) |
| 사용자·제보자·메인테이너에게 묻는 것 | `questions` (`comment`에도 같은 질문을 넣는다) |
| 최종 보고(TRI-52/TRI-45) | `summary` |
| 합의 실패·실행 불가 블로커 | `blockers` (+ `status: blocked`) |

"다음 단계" → `next_action`:

| 원본 다음 단계 | `next_action` |
|---|---|
| `isac-issue-to-pr`로 인계(TRI-22 ∧ TRI-42 ∧ ④) | `implement` + `implementation_brief` |
| TRI-25 구조 변경 게이트, 메인테이너 결정 필요 | `await_decision` |
| needs-info, 재현 안 됨(TRI-09), 조건 부족(blocked) | `await_info` |
| 닫기 제안, 제외, 그 밖의 모든 경우 | `none` (닫기 제안은 `comment` 또는 `summary`에 적는다. 에이전트는 닫지 않는다) |

적응 규칙:

- **AD-01 (FEATURE_REQUEST).** 이 자동화에 도달한 이슈 작성자는 허용된 메인테이너다. 그가 올린 명확하고 범위 안의 기능·문서 요청은 사용자의 직접 수정 지시(`isac-issue-to-pr` I2P-01 진입 조건 "user directly instructs the fix")로 본다. 그때는 `labels.add`에 해당하는 `enhancement`/`documentation`을 넣고 `next_action: implement`와 `implementation_brief`를 채운다. 그렇지 않으면 TRI-03대로 라벨 없음, `comment: null`, `next_action: none`이며 제외 사유는 `summary`에 적는다.
- **AD-02 (재트리아지).** 메시지가 이미 트리아지된 이슈의 새 댓글이라고 하면, 기존 라벨·분석 댓글과 새 정보로 다시 판정한다. `references/labels.md`의 전이는 결과로 낸다: ③ 제거(제보자가 요청 정보를 줌 → `labels.remove: ["triage:needs-info"]` 후 재현 재시도), ⑤→④(댓글에서 메인테이너가 구조 변경 방향을 승인 → `labels.remove: ["triage:needs-structural-change"]`, `labels.add: ["triage:fix-direction-decided"]`, 승인된 방향 변형의 Fix direction을 담은 `comment`), ① 교체(같은 그룹 새 값을 `labels.add`에).
- **AD-03 (닫기).** 에이전트는 이슈를 닫지 않는다. 사용자가 닫기를 지시해도 닫기 제안과 근거를 `comment`·`summary`에 적을 뿐이다.

# GitHub Issue Triage

버그 이슈를 판독해 이슈별 **판정 라벨 + 사람이 읽는 영어 분석 댓글 + 영어 `summary`**를 TriageResult로 만든다. 적용(게시)은 n8n이 한다.

## 경계

- 재현·판정 분류·세 코드 상태 비교·수정 출처·증거 등급: `issue-validation` 스킬을 단계로 호출한다. 규칙을 여기서 다시 쓰지 않는다.
- 인과 그래프·반사실 검증·extent-of-condition sweep: `five-whys-root-cause-analysis` 스킬.
- 독립 조사·상호 반박·합의·판정 어휘: `isac-multi-agent-consensus` 스킬.
- 사용자에게 묻는 형식: `isac-decision-brief` 스킬.
- 모든 GitHub 쓰기 문안(영어·문체, 위생 처리, 실행 확인과 추론 구분, 댓글 제자리 수정 vs 새 댓글, 중복 확인): `isac-github-publishing` 스킬. 실제 쓰기(라벨 조회·생성 메커닉, 게시 주체)는 n8n이 TriageResult로 한다. 에이전트는 쓰지 않는다.
- 인계: `isac-live-qa`가 등록한 이슈를 받는다. `isac-issue-to-pr`로 넘기는 조건은 우리 코드 결함(TRI-22) ∧ 열린 PR 처리(TRI-42) ∧ `triage:fix-direction-decided`(또는 사용자 직접 지시, AD-01)다. 인계는 `next_action: implement` + `implementation_brief`로 한다. 머지로 인한 이슈 종결과 머지 후 상태 댓글은 `isac-issue-to-pr` 소관이다.
- 전역 가드 `task-intent-boundary`, `application-code-change-approval`, `destructive-operations`, `verification`, `guardrails`가 우선한다.

## 0. 프로젝트 훅과 모드

`gh repo view --json nameWithOwner,visibility`로 대상 저장소를 확인하고, 이 스킬의 `references/projects/<owner>__<repo>.md`가 있으면 먼저 읽는다(공개 저장소만 여기 둔다). 비공개 저장소의 프로젝트 사실은 그 저장소 자체 지침(AGENTS.md, `.agents/skills`)에 있다. 프로젝트 문서는 기본값을 좁히거나 구체화할 수 있지만 `[U]` 규칙과 전역 가드를 완화하지 못한다.

게시/초안 모드 판별은 하지 않는다. 라벨·댓글은 항상 TriageResult(`labels`, `comment`)에 초안으로 담고, scratch 사본은 `/tmp/issue-agent/<worktree-name>/`에 둔다.

- **TRI-01** [U] 산출물은 라벨(`labels.add/remove`), 분석 댓글(`comment`), 사용자 보고(`summary`)뿐이다. 코드 수정, PR 생성, 머지, 이슈 닫기는 하지 않는다. 트리아지 결과의 적용은 라벨·댓글에만 해당하며 n8n이 한다. 판정상 중복이거나 이미 수정됐으면 닫기를 `summary`(필요하면 `comment`)에서 제안만 한다. 사용자가 닫기를 직접 지시해도 판정 근거를 `comment`에 적고 닫기 제안을 `summary`에 적을 뿐 닫지 않는다(AD-03).

## 1. 인벤토리와 중복

- **TRI-02** 대상 저장소의 이슈를 open/closed 모두, 열린 PR과 함께 목록화한다. 작업 중 새로 등록된 이슈도 같은 파이프라인에 넣고, 완료 전에 목록을 다시 조회한다.
- **TRI-03** [U] 저장소 전체·여러 이슈를 일괄 트리아지할 때 사용자가 따로 지목하지 않은 재현 무관 이슈(기능 요청, 제안, 워크플로 제안, 철회된 보고, enabler)는 재현하지 않고 분류만 한다(지목된 기능 이슈 질문은 TRI-35). 이런 이슈에는 라벨·댓글을 쓰지 않고(`labels` 비움, `comment: null`, `next_action: none`) `summary`에 "제외(사유)"로만 둔다. 약속이 깨지지 않았는데 새 능력을 요구하는 이슈를 결함으로 부풀리지 않는다. 허용된 메인테이너가 올린 명확한 기능·문서 요청은 AD-01을 따른다.
- **TRI-04** [U] 여러 이슈를 다룰 때는 개별 작업 전에 전체를 훑어 중복부터 가리고 정본 하나만 작업한다. 이슈 하나만 맡았으면 그 이슈의 중복 후보만 확인한다.
- **TRI-41** 중복 판정은 제목·증상이 아니라 메커니즘 기준이며, `duplicate`는 그 이슈 자신의 경로를 실행해 같은 메커니즘을 확인했을 때만 `labels.add`에 넣고 정본 번호를 `duplicate_of`에 적는다.
- **TRI-05** [U] 이슈에 연결된 PR의 커밋이 다른 PR을 통해 이미 간접 머지됐는지 추적한다.
- **TRI-42** 열린 PR이 있는 이슈를 구현 인계에서 뺄지는 그 요청의 지시를 따르고, 지시가 없으면 빼고(`next_action`을 `implement`로 두지 않음) `summary`에 열린 PR과 미해결 부분을 적는다. 그런 이슈의 `comment`에는 그 PR이 해결하지 못하는 부분만 적는다. 포크에만 머지된 PR은 업스트림 수정이 아니다.
- **TRI-06** 외부·업스트림 의존성의 버그가 의심되면 업스트림 트래커부터 검색한다. "비슷한 이슈가 있다"와 "우리 재현과 정확히 같다"를 구분하고 환경·버전·모드 차이를 적는다.
- **TRI-46** 업스트림에 보고할 가치가 있으면 그 트래커가 요구하는 증거(정확한 버전, OS·모드, 대조군)를 준비한다. 제출(외부 저장소 이슈 등록)은 하지 않고, 준비한 증거와 제출 제안을 `summary`(필요하면 `comment`)에 적는다. 문안은 `isac-github-publishing`을 따른다.

중복 제거 뒤 §2–§5는 이슈별 담당 서브에이전트가 수행한다(TRI-38).

## 2. 재현 (`issue-validation`)

- **TRI-07** [U] 재현이 확정 판정의 필수 조건이다. 코드, 제보 로그, 글만 보고 결함을 확정하지 않는다. 어떤 방법을 쓰든 격리 환경에서 실행해 재현하고, 방법(실행 증거 게이트, 실제 진입 경로, 최소 통제 실험과 정상 대조군, 세 코드 상태 비교, 원자적 주장 분리)은 `issue-validation`을 따른다.
- **TRI-08** [U] 외부 의존성은 mock으로라도 재현한다. 단 mock이 실제와 동떨어지지 않고 계약을 지킨다는 공식 문서·스펙 근거가 있을 때만 재현으로 인정한다(세부 조건은 `issue-validation`의 contract-faithful mock). 이 경우 `labels.add`에 `repro:reproduced`를 넣고 `comment`에 mock 재현이며 실제 서비스는 관찰하지 않았다고 적는다.
- **TRI-09** [U] 재현이 안 되면 멈춘다. 시도한 버전·환경·절차와 관찰을 `comment`에 적고 `labels.add`에 `repro:not-reproduced`(조건이 없어 결론이 안 나면 `repro:blocked`)를 넣으며 `next_action: await_info`로 끝낸다. 원인 단정이나 수정 방향은 쓰지 않는다. "버그 아님"이나 제보자 반증으로 쓰지 않고 이슈를 열어 둔다.
- **TRI-43** 재현이 안 된 이슈에는 제보자에게 관찰 대상 상태를 바꾸지 않는 읽기 전용 진단 명령을 요청하고(`comment`와 `questions`) `labels.add`에 `triage:needs-info`를 넣는다.
- **TRI-10** 이미 실행된 증거(CI 실패 로그, 기록된 재현 실행)는 재실행 없이 증거로 쓴다. 제보자의 글·로그·스택 트레이스, 이슈 본문의 file:line 용의자, 이전 에이전트의 주장은 검증할 가설일 뿐이다. 제보자의 후속 댓글은 그가 실제로 실행한 범위만큼만 해석한다.
- **TRI-11** [U] 운영·배포 환경 로그가 증거일 때 주 로그에 흔적이 없어도 추측으로 메우지 않고 `isac-decision-brief`의 대체 경로·자격증명 블로커 절차(DBR-18)를 따르되, 필요한 접근·자격증명 요청은 `questions`·`blockers`와 `comment`에 넣는다.

## 3. 판정

- **TRI-12** [U] 검증을 끝내 판정을 단정하고, 무엇을 고쳐야 하는지(없으면 없다고) 평이하게 말한다. 판정 어휘는 `issue-validation`의 것을 쓴다.
- **TRI-51** 판정은 bug/not-bug가 아니라 결함 영역 분류다: 제품 결함, 테스트·오라클 결함, 환경 결함, 의도된·문서화된 동작, 기능 요청, 재현 불가. 먼저 프레임워크·플랫폼 표준 계약상 의도된 동작인지 판별한다. 결함 영역은 `result.json`의 별도 필드(`references/defaults.md`)로 적고, 영역별 라벨은 `references/labels.md`.
- **TRI-13** [U] 판정 근거가 특정 배포(사용자 운영 환경)의 관측일 때, 의도된 동작이라도 그 배포에서 불필요한 작업·소음(예: 쓰지 않는 대상을 계속 스캔)이 비례에 맞지 않으면 개선 후보로 `comment`와 `summary`에 알린다. 개선 제안에는 현재 동작, 제안 변경, 효과, 필요한 테스트, 제안이 기존 불변식을 깨는지 여부를 적는다.
- **TRI-14** 판정이 테스트·오라클 결함이면 수정 대상은 오라클이나 모델이고 제품 코드는 그대로 둔다. 수정 확인은 실패했던 구성(같은 seed, 설정, 단계)으로 한다. 새 입력에서 나온 새 실패는 별개 원인으로 보고하고 이전 판정과 합치지 않는다.
- **TRI-15** 복합 이슈는 원자적 주장으로 나눠 주장별로 판정하고 댓글은 하나(`comment`)로 묶는다. 일부만 해결됐으면 전체 해결로 쓰지 않고 남은 증상을 라벨·댓글에 적는다. 버그와 함께 발견한 하네스·테스트 전용 불일치는 제품 결함에 섞지 않는다.
- **TRI-16** 심각도는 입증된 영향에 비례하게 쓰고, 이슈마다 검증 수준(운영 환경 재현 / 격리 재현 / mock 재현 / 정적 확인만)을 명시한다. 표현 기본값은 `references/defaults.md`.

## 4. 근본 원인 (`five-whys-root-cause-analysis` + `isac-multi-agent-consensus`)

- **TRI-17** [U] 근본 원인은 증상이 나타난 곳이 아니다. 다른 곳이나 구조적 한계에 있을 수 있다. 여러 방면으로 파고들어 최소 5 Whys를 쓰고, 구조 전체나 프로젝트 핵심을 바꿔야 하더라도 끝까지 찾는다. 얕게 판단하지 않는다.
- **TRI-18** [U] "진짜 문제인가"와 근본 원인은 한 에이전트가 정하지 않는다. 이슈마다 여러 에이전트가 독립 조사한 뒤 토론해 합의한다(`isac-multi-agent-consensus`의 RCA 관점 기본값).
- **TRI-19** [U] 증상을 억누르는 수정(로그 레벨 강등, 고정 지연, timeout 증가, 재시도, 테스트 입력 특수 처리, 단언 약화)은 근본 해결로 받지 않는다.
- **TRI-20** 결함을 확인하면 같은 결함 유형이 대칭·형제 경로(다른 리소스 종류, 모듈)에도 있는지 `five-whys-root-cause-analysis`의 extent-of-condition sweep으로 전수 조사한다.
- **TRI-21** 원인을 완전히 입증하지 못해도 기록은 남긴다. 확정 사실, 가설, 가설을 가를 판별 증거를 나눠 쓰고 수정을 약속하지 않는다. 이때 `triage:root-cause-identified`는 `labels.add`에 넣지 않는다.
- **TRI-22** [U] 근본 원인이 우리 코드인지 명시적으로 판정한다. 우리 코드일 때만 `isac-issue-to-pr`로 넘기고(`next_action: implement` + `implementation_brief`), 업스트림·환경 원인은 우리 쪽 대응(명확한 오류, 정확한 보고)과 업스트림 기록으로 분리한다.
- **TRI-23** 반환 전 독립 검토(`isac-github-publishing`)의 대상은 dossier와 댓글 초안 전체다. 반환 기준은 `isac-multi-agent-consensus`의 리뷰-GREEN 루프 종료 조건이며(GREEN 판정만으로는 부족), 라운드 상한·교착도 그 스킬을 따른다. 합의하지 못한 이슈는 `comment`·`labels`를 내지 않고 `blockers`에 올려 `status: blocked`로 반환한다. 반환 계약은 `references/defaults.md`.

## 5. 수정 방향과 구조 변경 게이트

- **TRI-24** [U] 분석 댓글에는 증상 패치가 아닌 근본 수정 방향을 적는다.
- **TRI-44** 수정 방향의 기본 구성: 입증된 불변식을 복구하는 가장 작은 안전한 시스템적 변경, 누락된 회귀 테스트가 단언해야 할 관찰 가능한 동작, 검토 후 기각한 대안과 이유 한 줄. 제안 범위는 입증된 공통 메커니즘에 맞춘다.
- **TRI-25** [U] 근본 수정이 구조 변경(`references/design-research.md`의 정의)을 요구하면 `labels.add`에 `triage:needs-structural-change`를 넣고, `references/design-research.md` 절차로 선택지를 조사한 뒤 `isac-decision-brief` 형식의 brief를 `comment`의 `## Fix direction (needs a maintainer decision)` 절과 `questions`에 넣어 `next_action: await_decision`으로 승인을 요청한다(실행 중 멈춰 묻지 않고, 교체는 메인테이너 답 이후 재트리아지에서, AD-02). 승인되면 `references/labels.md`의 ⑤→④ 전이(`labels.remove`/`labels.add` + 승인된 방향 변형을 담은 `comment`)를 결과로 낸다. 승인 댓글 작성자에게 대상 저장소의 maintain·admin 권한이 없으면(`gh api repos/<o>/<r>/collaborators/<login>/permission`, 읽기) 그 선택은 결정이 아니라 권고다: ⑤를 유지하고 `comment`의 `Recommended:` 줄로만 반영한다. 승인이 필요 없는 부분 집합은 그것만으로 완전한 수정일 때만 먼저 방향 확정으로 넘긴다.
- **TRI-47** [U] 구조 변경 방향 조사는 추측으로 세우지 않는다. 실측할 수 있는 것은 실측하고 API 스펙·공식 문서를 조사하며, 비교 대상 프로젝트들이 같은 문제를 어떻게 모델링했는지도 조사한다. 결과 표기(제품 표면 이름)는 `references/design-research.md`.
- **TRI-48** [U] 호환성·마이그레이션 평가("기존 N개를 새 구조가 다룰 수 있나")는 항목마다 분석 에이전트를 둔다.
- **TRI-49** 다른 OSS 코드는 작은 순수 함수만 파일 단위로 복사하고 attribution(NOTICE)을 남긴다. fork하거나 아키텍처·컨트롤러를 통째로 복사하지 않는다.
- **TRI-26** [U] 수정·개선 제안이 기존 보장(예: 고아 자원 탐지, fail-closed 인가)의 범위를 바꾸면 영향받는 사례별 현재 vs 제안 동작, 남는 공백, 완화책을 적고, 불변식을 약화시키는 선택지는 그 사실을 먼저 적는다.
- **TRI-27** [U] 원래 지시가 이미 허락한 것은 다시 묻지 않는다. 사용자 가시 계약이나 구조를 바꾸는 선택만 TRI-25 게이트를 거치고, 내부 구현 선택은 에이전트가 정한다.

## 6. 라벨

- **TRI-28** [U] 재현 여부와 사용자의 5축을 `labels.add`/`labels.remove`로 낸다: ① `repro:reproduced` / `repro:not-reproduced` / `repro:blocked`(상호배타) ② `triage:root-cause-identified` ③ `triage:needs-info` ④ `triage:fix-direction-decided` ⑤ `triage:needs-structural-change`(④와 배타). 각 라벨은 `references/labels.md`의 기준을 증거가 충족할 때만 넣는다. 기존 `bug`/`enhancement`/`duplicate`를 재사용하고 `invalid`/`wontfix`/`question`은 넣지 않는다. `agent:needs-attention`은 넣지도 빼지도 않는다.
- **TRI-29** 라벨과 댓글은 서로 맞아야 한다(`references/labels.md`의 일치 규칙). 라벨은 bridge 카탈로그 이름만 쓰며, 조회·생성은 n8n bridge가 한다.

## 7. 댓글

- **TRI-30** [U] 합의된 분석 결과(근본 원인 포함)는 이슈 댓글로 기록하도록 `comment`에 담는다. 영어, 핵심만, 사족 없이 쓰며 문체는 `isac-github-publishing`을 따르고 게시는 n8n이 한다.
- **TRI-31** [U] 분석 댓글에는 보이는 현상, 실제 근본 원인, 근본 해결 방향, 복사해 바로 실행할 수 있는 최소 재현(명령, 설정, 코드)을 넣는다. 절 구성과 길이 예산은 `references/comment-template.md`의 기본값을 따른다.
- **TRI-32** [U] 이미 수정된 이슈를 판정하면 수정 상태를 `issue-validation`의 수정 출처 어휘(fixed-in-PR / merged / released / deployed) 중 하나로 섞지 않고 적는다. 수정 PR·커밋, 수정이 포함된 첫 릴리스(또는 미릴리스), 검증 범위, 사용자가 쓸 버전을 적는다. main에만 있을 때의 릴리스 필요 안내는 `isac-issue-to-pr`를 따른다.
- **TRI-33** [U] "실제로 해결된 거야?"에 답하기 전에 수정 자체를 다시 검증한다. 어떤 PR이 main에 들어갔는지(간접 머지 포함) 확인하고 재현을 다시 돌린다. 답에서는 결함이 남았는지와 검증 범위만 남았는지를 분리한다.

## 8. 사용자 보고(`summary`)

- **TRI-34** [U] 남은·열린 이슈 요약을 요청받으면 이슈마다 무엇이 문제인지, 해결할 수 있는지, 추가 정보가 필요한지를 담는다.
- **TRI-52** `summary` 형식 기본값(짧은 영어): ① 이슈 표(이슈 / 판정 / 라벨 / 다음 단계 / 게시 여부) ② 이슈로 등록되지 않은 발견(확인된 사실 + 권장 처리) ③ 권장 우선순위 ④ main에 머지됐지만 미릴리스인 수정.
- **TRI-45** `summary`에는 검증 수준과 한계, 해결되지 않은 블로커(없으면 "0"; 블로커 자체는 `blockers`)를 적는다. 범위 밖 인접 결함은 흡수하지 않고 담당을 적어 넘긴다.
- **TRI-35** 기능·enabler 이슈에 대해 물으면 이 순서로 답한다: 도입하는 기능, 장점, 해소되는 블로커, 그 자체가 enabler인지, 핵심 난점·불확실성, 현재 수정 범위에 드는지. 실현 가능성이 입증되지 않았으면 바로 고치자고 하지 않고 feasibility 조사를 먼저 권한다.
- **TRI-36** [U] 트리아지 보고는 판정을 먼저, 간결하게 쓴다. 구체 사실(예: "어느 대상에서 오류가 나?")을 물으면 검증 방법과 함께 구체 목록으로 답하고, "확인해봐"에는 대상을 직접 열어 관찰한 사실로 답한다.
- **TRI-37** 트리아지 결과나 재현 실패에 대해 사용자가 실패 출력을 붙이며 "니 잘못이야?", "왜 이렇게 동작해?"라고 물으면 실제 코드 경로와 히스토리로 메커니즘을 설명하고, 에이전트 변경 탓인 것과 아닌 것을 표로 나눈다. 자기 잘못이면 인정한다.
- **TRI-50** 사용자의 불확실한 기술 기억("~라고 알고 있는데 맞아?")은 단정하지 않고 실측·코드 검색·공식 문서로 확인해, 확인된 부분과 아닌 부분을 구분한 결론을 준다.

## 9. 위임과 안전

- **TRI-38** [U] 여러 이슈를 다루면 중복 제거 이후 이슈별 과정(재현, 판정, 원인, 방향, 초안)은 `isac-multi-agent-consensus`의 항목별 담당 방식으로 이슈마다 병렬 위임한다. 게시 주체는 n8n이다.
- **TRI-39** 담당자 브리프, 산출물 계약(`dossier.md`, `result.json`, `comment.md`), 반환 필드와 verdict는 `references/defaults.md` 기본값을 쓴다.
- **TRI-40** 재현은 일회용 격리 자원에서만 하고, HAPI 워크트리의 추적 파일과 공유·라이브 환경의 기존 자원은 읽기만 한다. 끝나면 만든 자원을 정리했다는 증거를 남긴다. 라이브 변경이 필요한 판별은 코드 추론으로 표시하거나 승인 요청을 `questions`에 넣고 `next_action: await_decision`으로 끝낸다.

## 완료 조건

모든 대상 이슈가 분류(제외/중복/판정)됐고, 이슈마다 기준을 충족한 `labels`와 검토 승인된 `comment` 하나(또는 TRI-03·TRI-23에 따른 `null`)가 결과에 있으며, `next_action`이 "다음 단계" 표와 맞고, `summary`가 TRI-52 형식을 갖췄다.
