---
name: isac-live-qa
description: Use in the issue-agent automation when a triage or implementation turn needs live QA of a deployed environment the runner can reach (URL, service, cluster) to check the product behaves as intended, returning findings as drafted issue text in the ISSUE_AGENT_RESULT fields instead of filing issues.
---

## Automation adaptation

이 사본은 issue-agent 자동화(n8n + bridge + HAPI + Codex)용으로 기계적으로만 바꿨다. 에이전트는 읽기 전용 GitHub 토큰만 가지며 GitHub에 어떤 쓰기도 하지 않는다. 모든 결과는 턴 끝의 `ISSUE_AGENT_RESULT <nonce> {json}` 한 줄로 반환하고, n8n이 적용한다. 무인 실행이라 채팅으로 묻거나 기다릴 사용자가 없다.

바꾼 것:

- 이슈 등록·댓글 게시 → 이슈 초안(영어, `references/issue-template.md`)을 결과에 넣는다. 자동화에는 새 이슈 생성 op가 없으므로, 초안은 현재 모드의 댓글 필드에 finding마다 `Proposed issue` 절로 넣고 `summary`에 별도 이슈 등록을 권고한다. 사람이 판단해 등록한다(LQA-01, LQA-27, LQA-32, LQA-35, LQA-46).
- 게시/초안 모드, finding 담당자의 게시 주체 지정 → 항상 초안 모드. 담당자 subagent는 초안까지만 만들고, 메인 에이전트가 결과에 넣는다(LQA-46).
- 인터뷰·허용 범위 승인·자격증명 요청·인증벽 안내·중단 보고 → 질문과 필요한 조치를 결과 `questions`와 댓글 필드에 넣고, 해당 결과 상태로 턴을 끝낸다. 기다리지 않는다(LQA-02, LQA-03, LQA-05, LQA-06, LQA-08, LQA-09, LQA-12).
- 한국어 최종 보고 → 결과 `summary`(짧은 영어). 실질 내용(점검 범위, 이슈 초안 표, 정리 결과, live 변경, 검증 수준)은 댓글 필드에 영어로 넣는다(LQA-43).
- scratch·런타임 준비물 위치 → `/tmp/issue-agent/<worktree-name>/`(커밋하지 않음). HAPI 워크트리가 유일한 checkout이다(LQA-01).
- 러너에는 클라우드·클러스터·벤더 자격증명과 브라우저 로그인 세션이 없다. live QA는 러너가 실제로 닿는 대상(공개 URL, 러너 네트워크에서 접근 가능한 서비스, 러너 안의 일회용 컨테이너)으로만 할 수 있다. 그 밖의 대상이 필요하면 추측하지 않고 결과를 `status: blocked`와 구체적인 `blockers`(필요한 자격증명·접근 경로)로 반환한다.
- `isac-skill-correction` 관련 교정 루프 절은 삭제했다(설치되지 않음).

단계 → 결과 필드:

| 단계 | triage (TriageResult) | implement / followup (ImplementResult) |
|---|---|---|
| 인터뷰 질문·허용 범위 승인 요청 | `questions` + `comment`, `next_action: await_decision` 또는 `await_info` | `questions` (+ `issue_comment`), `status: needs_info` |
| 이슈 초안(finding별) | `comment`의 `Proposed issue` 절 | `issue_comment`의 `Proposed issue` 절 |
| 라벨(`bug`/`enhancement`) | 현재 이슈에 해당하면 `labels.add`; 새 이슈 초안에는 초안 안에 권장 라벨로 적는다 | 초안 안에 권장 라벨로 적는다 |
| 최종 보고 | `summary` + `comment` | `summary` + `issue_comment` |
| 자격증명·인프라 부재 | `status: blocked` + `blockers` | `status: blocked` + `blockers` |

# Live QA

지정된 배포 환경을 탐색해 제품이 의도대로 동작하는지(기능·성능·UX·로그)를 확인하고, 발견한 문제를 GitHub 이슈 초안으로 결과에 넣는다(등록은 자동화 밖에서 사람이 한다). 산출물은 **이슈 초안과 정리 증명**이다. 가장 중요한 단계는 시작 전 인터뷰다.

## 경계

- 공개 게시 여부와 분석 전용 요청의 쓰기 금지는 전역 `task-intent-boundary`, 되돌릴 수 없는 삭제·변경 준비는 `destructive-operations`, 완료 주장은 `verification`, 비밀값 비노출은 `guardrails`를 따른다. 이 스킬은 재서술하지 않는다.
- 사용자에게 묻는 형식(현상 → 원인 → 선택지별 변화 → 권장, 자격증명 값별 설명)은 `isac-decision-brief` 스킬이 소유한다.
- 여러 에이전트의 토론·합의 절차는 `isac-multi-agent-consensus` 스킬이 소유한다. 사용자의 중지 지시는 전역 `task-intent-boundary` 가드를 따른다.
- 이슈 판정 dossier(bug/intended/duplicate)는 `issue-validation`, 깊은 근본 원인은 `five-whys-root-cause-analysis` 또는 등록 후 `isac-issue-triage`가 맡는다.
- 영어·공개 저장소 위생·중복 검색·기존 이슈 보강·라벨 선택은 `isac-github-publishing` 스킬이 소유한다. 이 자동화에서는 항상 초안 모드다: 이 스킬의 "이슈 등록"은 이슈 초안 작성으로 읽고, 초안을 결과 필드에 넣는다. 에이전트는 GitHub에 쓰지 않는다.
- 격리 단위: 기존 환경과 분리해 만들고 통째로 지울 수 있는 범위다(예: namespace, 테스트 계정·테넌트, 임시 프로젝트, 일회용 VM·컨테이너·가상 디스플레이). 아래 규칙의 namespace·finalizer 같은 용어는 Kubernetes 배포의 예이며, 다른 대상에서는 해당하는 격리 단위와 정리 신호로 읽는다.

## 0단계: 프로젝트 훅

brief나 cwd로 이슈 대상 저장소가 정해져 있으면 지금, 아니면 인터뷰 항목 i에서 확정한 직후 `gh repo view --json nameWithOwner,visibility`로 확인한다. 이 스킬의 `references/projects/<owner>__<repo>.md`가 있으면 먼저 읽는다(공개 저장소만 여기 둔다). 프로젝트 문서는 기본값을 좁히거나 구체화만 할 수 있고, `[U]` 규칙과 전역 가드를 완화하지 못한다. 비공개 저장소의 프로젝트 사실은 그 저장소의 자체 지침에 있다.

## 1. 인터뷰

- **LQA-01** [U] 목표는 "지정된 배포 환경의 대상 버전이 의도대로 동작하는지, 버그가 있는지"를 샅샅이 조사해 **GitHub 이슈 초안까지** 결과에 넣는 것이다. 발견한 문제를 고치지 않는다. 저장소는 건드리지 않는다(커밋·브랜치·PR·코드 수정 없음, 작업트리는 시작 상태 그대로). 런타임 준비물(컨테이너·디스플레이·설치·인증)은 저장소 밖 scratch(`/tmp/issue-agent/<worktree-name>/`)에서 구성한다.
- **LQA-02** [U] 시작 전에 `references/interview.md` 체크리스트를 확정한다. 배포 위치와 QA 범위는 프로젝트마다 다르므로 추정하지 않는다. 불확실한 항목이 하나라도 있으면 실행하지 않고, 질문을 결과 `questions`와 댓글 필드에 넣어 턴을 끝낸다.
- **LQA-03** [U] 사용자 brief가 이미 정한 경계(예: "기존 리소스는 R만, 임시 namespace에서 임시 리소스로 검사, 끝나면 제거")는 그대로 운영 규칙으로 옮긴다. 빠진 항목만 한 번의 구조화된 질문으로 묻는다. 이미 답한 항목은 다시 묻지 않는다.
- **LQA-04** [U] 설치·실행을 검증하면 사용자에게 안내된 설치 경로로 한다(규칙·보고 항목은 `isac-issue-to-pr` 소유).

## 2. 위험 고지와 허용 범위 승인

- **LQA-05** [U] brief나 인터뷰가 이미 허용한 범위(LQA-03)가 아니면, 변경이 필요한 검증(임시 리소스 생성, 공유·운영 클러스터 배포, 외부 계정 리소스 생성)은 실행하지 않고 허용 범위 제안을 결과 `questions`와 댓글 필드에 넣어 명시 승인을 요청한다. 제안에는 격리 방식, 생성·삭제할 리소스 종류, 기존 서비스에 영향이 없다는 근거, 정리·복구 방법, 남는 위험을 담는다. 승인되지 않은 항목은 금지로 둔다. 형식은 `references/safety-and-isolation.md`의 제안 틀과 `isac-decision-brief`.
- **LQA-06** 자기 임시 객체에 대한 복구 조작(finalizer 제거 등)과 읽기 목적 토큰 발급도 변경으로 본다. 인터뷰에서 허용 여부를 묻고, 승인되지 않았으면 하지 않는다.
- **LQA-07** [U] 격리를 주장하려면 경계를 끝까지 따져 고지한다. 예: "전용 계정"이면 전용 도메인/zone 필요 여부까지 포함한다. run prefix는 충돌 방지일 뿐 보안 경계가 아니다. 공유 계정에서 전용 계정 수준의 안전을 주장하지 않는다.
- **LQA-08** [U] 자격증명 요청·전달·막힘 처리는 `isac-decision-brief` 스킬(DBR-15, DBR-16, DBR-18)을 따른다. 필요한 값은 인터뷰(항목 e·k)에서 한 번에 모아 요청한다.
- **LQA-09** [U] 브라우저가 인증벽(CAPTCHA·2FA)에 막히면 우회하지 않는다. 필요한 조치를 결과 `blockers`(또는 `questions`)와 댓글 필드에 정확히 적고 턴을 끝낸다.

## 3. 기본 경계와 준비

- **LQA-10** [U] 기존 리소스는 엄격히 읽기 전용이다(CUD 없이 R만). 기존 리소스를 생성·수정·삭제·재시작하지 않는다.
- **LQA-11** production과 "실제 사용 중"인 환경은 명시가 없어도 읽기 전용·무중단으로 운영하고, 그 전제를 인터뷰에서 확인한다. 허용 동작 세부(조회 동사, 진단 엔드포인트, provider API, probe 강도)는 `references/safety-and-isolation.md`.
- **LQA-12** live 환경에서 실제로 수행한 변경은 사소해도(토큰 발급 포함) 보고에 적는다. 경계를 위반했으면 숨기지 않고 즉시 중단하고, 결과 `summary`와 댓글 필드 첫머리에 적는다.
- **LQA-13** QA 전에 배포된 아티팩트가 대상 버전인지 확인한다(image digest ↔ release, 실행 인자 → commit). tag가 같다고 digest가 같다고 가정하지 않는다. 배포 버전과 현재 main을 구분한다.
- **LQA-14** [U] 실제 라우팅·DNS·상태를 바꾸지 않는 모의 검증을 요청받으면 server-side dry-run과 선언 수준 시뮬레이션으로 수행하고, "persisted 객체 0, 기존 상태 불변"을 증명해 보고한다. dry-run 통과와 실제 controller 수용을 구분한다.
- **LQA-15** [U] 제품의 상태 처리는 기존 리소스가 아니라 **임시 격리 단위와 임시 리소스**(예: 임시 namespace)로 검사한다. 임시 리소스 생성이 승인되지 않았으면(LQA-05) 해당 케이스를 원장에 BLOCKED로 남기고 보고한다. 다양한 파라미터를 쓰고, 대상에 리소스 간 참조가 있으면 적극 쓴다. 원격 객체를 만들지 않고 재현할 수 있으면 그 방법을 먼저 쓴다.
- **LQA-16** 임시 리소스에는 run prefix와 label을 달고, 생성 즉시 ledger(name+UID, 원격 type+id+name)에 기록한다. 삭제도 ledger의 name+UID로만 하고, prefix 전체를 지우는 janitor는 쓰지 않는다. 각 조사자는 자기 격리 단위·scratch만 쓰고 남의 것은 읽기만 한다.
- **LQA-17** 실행 전에 복구를 준비한다: 정리 경로(역순 teardown, 비상 정리, 실패 시 중단), 공유 fixture의 원래 값, 권한 범위 매핑. 정리 수단이 없는 생성은 하지 않는다. 절차는 `references/cleanup-and-recovery.md`.
- **LQA-18** 공유 계정·클러스터에서 위험한 케이스(계정 전역 설정 등)는 실행하지 않고 BLOCKED로 기록한다. BLOCKED는 PASS로 세지 않는다. 권한 부족은 permission-blocked로 분류하고 조용히 건너뛰지 않는다.

## 4. QA 계획과 실행

- **LQA-19** [U] 임시 리소스를 만들어 능동 테스트(파라미터·조합·상호 참조 탐색)할 때는 실행 전에 여러 에이전트가 QA list를 다양하게 뽑는다(`isac-multi-agent-consensus`). 케이스마다 "의도된 바"와 "실제 관측된 바"를 나눠 기록한다. 의도된 바와 문제 기준은 6절과 `references/problem-criteria.md`로 정한다. 실행 중 케이스 추가는 허용한다. 실사용 배포의 읽기 전용 스캔은 LQA-28 경로(스캔 분할 + 후보별 토론)를 따른다.
- **LQA-20** QA 원장의 분모는 고정하고, sub-variant는 추적하되 다시 더하지 않는다. 안전한 위험 등급부터 실행한다(등급·열 구성은 `references/safety-and-isolation.md`).
- **LQA-21** 실제 계정 대상 탐색은 무제한 무작위 생성이 아니라 미리 정한 경계 있는 campaign으로 한다. 평균 성공률보다 최악의 누출(보호 경로의 2xx 한 번)을 본다. coverage는 리소스·전이·fault·timing·격리 축의 조합으로 재고, 실행하지 못한 조합을 보고한다.
- **LQA-22** 대규모·공유 계정 run에는 실행 게이트를 둔다: runbook·매트릭스·증거 정책 작성 → 독립 실행 검토와 보안 검토가 모두 `GREEN`(`isac-multi-agent-consensus`) → 실행. 수정하면 재검토한다. 소규모·격리 run은 생략한다.
- **LQA-23** 격리 가능한 QA 케이스는 병렬로 돌린다(병렬 원칙은 `isac-multi-agent-consensus` MAC-03). 계획·리뷰 루프가 케이스 실행을 지연시키지 않게 한다.
- **LQA-45** 직렬 구간(같은 원격 리소스를 바꾸는 케이스)과 예상 소요는 미리 알린다. 병렬·직렬·토론 규모 기준은 `isac-multi-agent-consensus`를 따른다.
- **LQA-24** [U] 조사 범위에는 상태 점검뿐 아니라 기능·성능·개선점이 들어간다. 가용한 로그(debug 수준 포함)를 주요 증거원으로 쓴다. 로그·자격증명 공백은 추측하지 않고 `isac-decision-brief` DBR-18을 따른다.
- **LQA-25** [U] 제품이 트래픽 경로(노출·라우팅·인증)를 만들면 실제 end-to-end 경로로 요청을 보내 응답 본문까지 확인한다.
- **LQA-48** 인증 계약은 무인증 / 잘못된 자격증명 / 정상 자격증명 세 경우를 실측한다.
- **LQA-26** [U] 외부 계정의 준비 상태나 설정을 알아야 하면 사용자에게 묻거나 기다리기 전에 읽기 전용으로 직접 확인한다(대시보드 로그인 포함, LQA-09).
- **LQA-49** 외부 벤더 쪽 상태는 제품 status나 에이전트 보고에만 의존하지 않고 벤더 대시보드·API로 교차 확인한다.

## 5. 탐색자와 finding 담당자

- **LQA-27** [U] 메인(orchestrator)은 문제 탐색만 계속한다. 문제를 찾으면 그 finding을 전담하는 subagent를 새로 띄워 구체 조사부터 이슈 초안 작성, 자기 임시 리소스 정리까지 맡긴다. 메인은 finding별 구체 조사를 직접 하지 않는다. brief 필드는 `references/issue-template.md`.
- **LQA-46** 순서: 메인은 후보를 기존 담당자 목록·열린 이슈와 대조해 같은 문제면 기존 담당자에게 넘기고, 아니면 담당자를 띄운다 → 담당자가 LQA-28로 판정 → 초안 반환. 담당자는 초안까지만 만들고, 메인이 초안을 결과 필드에 넣는다(`isac-github-publishing` GHP-15: 게시 주체는 n8n뿐).
- **LQA-28** [U] 후보가 실제 문제인지 혼자 판단하지 않는다. 스캔은 나눠서 빠르게 하고, 후보마다 여러 에이전트가 토론해 판정한다(`isac-multi-agent-consensus`). 판정 근거는 `issue-validation` dossier로 남긴다.

## 6. 무엇을 문제로 볼 것인가

- **LQA-29** [U] 의도된 동작이 이 배포에서 관측 가능한 비용(에러·노이즈·지표 오염·불필요한 외부 호출)을 만들면 "의도된/문서화된 동작"이라는 이유로 조사를 닫지 않는다. not-a-bug면 bug 이슈는 만들지 않되, 비례하지 않는 설계상 낭비는 `isac-issue-triage` TRI-13 기준으로 enhancement 후보로 올린다.
- **LQA-30** 결함과 개선 요청은 구분해 등록·보고한다. 문제 주장에는 관측된 live 증거나 결정적 재현이 필요하다. 심각도는 이론이 아니라 현재 live 영향으로 매긴다. 성능은 측정한 뒤 판단한다. 표면 상태(Ready 등)만으로 정상이라 판정하지 않는다. 세부 기준과 측정 규칙은 `references/problem-criteria.md`.

## 7. 이슈 초안

- **LQA-32** [U] 외부 보고자가 없는 내부 QA finding도 이슈 초안으로 만든다.
- **LQA-33** [U] 이슈에는 관측 현상(구체 증거·수치)과 단계별 최소 재현을 반드시 적는다. 원인·해결은 추가 노력 없이 알 수 있을 때만 적고, 증명되지 않은 원인은 hypothesis로 표시한다. brief가 근본 원인·근본 해결 방향까지 요구하면 `five-whys-root-cause-analysis`로 원인을 확정하고 해결 방향(구조 변경이 필요해도, 그 필요 여부 포함)을 이슈에 적는다. 구조 변경 결정은 `isac-issue-triage`와 `isac-decision-brief` 몫이다. 요구가 없으면 깊은 분석은 `isac-issue-triage`로 넘긴다. 배포 버전을 명시한다. 템플릿은 `references/issue-template.md`.
- **LQA-34** [U] 개선 이슈는 "개선하라"로 끝내지 않는다. 제안 내용(현재 동작, 제안 변경, 효과, 테스트, 사례별 현재 vs 제안, 남는 공백·완화책)은 `isac-issue-triage` TRI-13·TRI-26을 따른다.
- **LQA-35** finding 하나에 이슈 초안 하나를 만든다. 초안 절차(영어, 위생, 중복 검색과 기존 이슈 처리)는 `isac-github-publishing`을 따른다. 각 담당자의 이슈 초안은 결과에 넣기 전에 LQA-28 토론 참여자나 별도 read-only 에이전트 하나가 `isac-github-publishing`의 독립 검토자로 확인한다(담당자 단독 검토 금지). 결과에 넣기 전 모든 file:line을 배포 tag 기준으로 재확인하고 틀린 주장은 정정한다. 권장 라벨은 `bug`/`enhancement`만 적고 `repro:*`·`triage:*`는 적지 않는다. upstream 결함은 문서화와 보고 초안까지만 한다.
- **LQA-36** [U] QA에서 확인한 계약은 나중에 주기적으로 돌릴 수 있게 재현 가능한 형태(명령, 기대값)로 보고·이슈에 남긴다. 대상이 사용자가 유지하는 제품이면 적합한 테스트 tier도 제안한다. 테스트 코드화는 `isac-issue-to-pr`가 한다.
- **LQA-37** [U] 사용자가 이미 만든 수정의 live 검증을 이 스킬로 요청한 경우, 검증은 릴리스 전에 한다. "릴리스해서 검증"하지 않는다. 현재 main으로 만든 검증용 아티팩트를 격리 환경(전용 클러스터 + 외부 서비스의 전용 리소스)에 배포하고 기존 운영 배포는 건드리지 않는다. 수정 PR 흐름 안의 검증은 `isac-issue-to-pr`가 소유한다.

## 8. 정리

- **LQA-38** [U] 모든 임시 리소스는 테스트가 끝나면 제거하고, 정리를 검증까지 한다: 삭제 완료 신호(예: finalizer 완료)와 원격 잔여 0을 read-only 조회로 확인한다.
- **LQA-39** [U] IaC가 관리하는 리소스는 수동으로 지우지 않고 IaC로 회수한다. plan에 정리 대상 외 변경이 보이면 적용하지 않고 멈춰 보고한다.
- **LQA-50** teardown은 생성·소유권의 역순이다.
- **LQA-40** [U] run ledger 밖까지 포함한 전체 흔적 정리(여러 표면·공유 계정)를 요청받으면 먼저 모든 표면(원격·클러스터·클라우드·GitHub·로컬)을 조사해 목록을 결과에 보고하고, 삭제는 별도 지시 후 한다. GitHub 표면의 삭제는 에이전트가 하지 않고 목록과 권고만 결과에 넣는다. 사용자가 지정한 보존 예외는 지우지 않고 정리 후 살아 있는지 재확인한다. 사용자가 요청하면 조사 결과를 `/tmp/issue-agent/<worktree-name>/`에 redacted 백업으로 남긴다. ledger 안의 임시 리소스는 LQA-38대로 목록 보고 없이 정리한다. 세부는 `references/cleanup-and-recovery.md`.
- **LQA-47** 작업이 중지되면(예: 사용자의 중지 지시, 전역 `task-intent-boundary` 가드) 새 케이스는 멈추되, 이 run이 만든 ledger 리소스의 teardown과 잔여 확인은 마친 뒤 멈춘다. 사용자가 아무것도 건드리지 말라고 하면 ledger와 잔여 목록을 넘기고 멈춘다.

## 9. 사용자 가시성과 최종 보고

- **LQA-41** [U] 사용자가 결과를 직접 보고 싶어 하면 보고만 하지 않고 실행 중인 화면을 노출한다(가상 디스플레이·원격 뷰 URL). 데모는 실제 end-user 경로를 쓰고, 결과는 독립 채널로 교차 확인한다.
- **LQA-42** [U] 남은 문제 요약을 사용자가 지정한 주소의 페이지로 달라고 하면 가독성을 최우선으로 하고 재현 정보(환경, 횟수, 로그 위치)를 함께 적는다. 세션이 끝나도 유지되게(detached) 띄우고, 다른 기기에서 HTTP 200과 레이아웃을 확인한다.
- **LQA-43** 최종 보고는 결과 `summary`에 짧은 영어로 쓰고, 상세 보고는 영어로 댓글 필드에 넣는다. 첫 줄은 한 줄 판정(N개 문제, 이슈 초안 수, 임시 리소스 제거, 코드 변경 없음)이다. 이어서 아티팩트 확인, 점검 범위, 이슈 초안 표(#, 한 줄 증상, 결함/개선, 심각도), 초안을 만들지 않은 후보와 이유, 영향 대상(개수가 아니라 식별자, 공개 댓글에는 넣지 않음), **정리 결과**, 수행한 live 변경, 검증됨/추론/미측정 구분, 커버리지 한계("이 이슈의 검증"과 "전체 릴리스 게이트 통과" 구분 포함), 소요 시간을 둔다. 틀은 `references/issue-template.md`.
- **LQA-44** 결과 페이지 프로세스는 ledger에 보존 대상으로 기록하고, 최종 보고에 중지 방법을 적는다. 사용자가 지정한 주소 외에는 노출하지 않는다.
