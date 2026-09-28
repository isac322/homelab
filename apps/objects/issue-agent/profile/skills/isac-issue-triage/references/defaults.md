# 바꿀 수 있는 기본값

이 파일의 항목은 에이전트 관행에서 온 기본값이다. 사용자 지시나 프로젝트 문서가 다르게 정하면 그쪽을 따른다. `[U]` 규칙(SKILL.md)을 완화하는 근거로 쓰지 않는다.

## 이슈별 담당 서브에이전트 브리프

자기완결적으로 쓴다. 담당자는 부모 대화를 모른다.

```text
# Target
<이슈 URL>. 한 문장 의심: <무엇이 잘못됐다고 보는지>.
# Evidence found by orchestrator
<중복 판정 결과, 연결 PR·커밋, 이미 실행된 증거 경로>
# Investigate
- Bug or intended behavior (standard contract / docs)?
- Code location (file:line), security·invariant impact.
- Reproduction via issue-validation; RCA via five-whys-root-cause-analysis.
# Acceptance
<반환 필드 전부 채움, verdict 하나>
# Write boundary
No GitHub writes. No edits to tracked files in the HAPI worktree. Scratch only: /tmp/issue-agent/<worktree-name>/<issue>/.
```

- 이슈 본문 전체, 댓글, 연결된 설계 문서를 먼저 읽게 한다.
- 저장소 규칙과 관련 스킬(불변식, 보안, 테스트 스킬)을 이름으로 알려 준다.

## 산출물 계약

이슈별 scratch 디렉터리(`/tmp/issue-agent/<worktree-name>/<issue>/`, 커밋하지 않음):

- `dossier.md`: `issue-validation`의 validation dossier + RCA 결과
- `result.json`: 아래 반환 필드
- `comment.md`: 영어 댓글 초안(`comment-template.md` 형식)
- 원본 아티팩트: 실행 로그, 재현 스크립트, 버전 매트릭스. 공개할 모든 숫자·버전이 이 로그로 추적되어야 한다.

반환 필드: `verdict`(`issue-validation` 어휘), `needs_approval`(boolean, 구조 변경 게이트 대상인지), `atomic_claims`, `commands_and_outputs`, `version_matrix`, `why_chain`, `root_cause`, `code_bug`(우리 코드인가), `affected_symbols`, `fix_design`, `regression_test_contract`, `labels_proposed`, `comment_draft`, `blockers`.

verdict에서 라벨·댓글·다음 단계로 가는 대응은 `labels.md`의 표 하나만 쓴다. 담당자 반환은 TriageResult로 옮긴다: `verdict`→`verdict`, 결함 영역→`fault_domain`, `labels_proposed`→`labels.add/remove`, `comment_draft`→`comment`, `fix_design`+`regression_test_contract`+범위→`implementation_brief`(`next_action: implement`일 때), `blockers`→`blockers`.

## 반환 전 주장 검토

- 댓글 초안과 dossier의 모든 주장을 원본 실행 로그와 대조하는 독립 검토자를 둔다. 판정 어휘는 `isac-multi-agent-consensus`의 것을 쓴다.
- 반환 계약: `verdict`(`isac-multi-agent-consensus`의 판정 어휘), `evidence_grade`, `supported_claims`, `unsupported_claims`, `comment_corrections`, `fix_design_corrections`, `implementation_readiness`.
- 과장된 원인, 실행하지 않은 증거, 범위를 넘는 일반화는 보수적으로 고친다. 반환 기준은 `isac-multi-agent-consensus`의 리뷰-GREEN 루프 종료 조건이다(GREEN 판정 한 번으로는 부족).
- 반환 직전 마지막 대조: 이슈마다 승인된 분석 댓글(`comment`)이 하나인지, `labels`가 댓글과 맞는지 확인한다.

## 근본 원인 조사 각도

RCA 관점 배정은 `isac-multi-agent-consensus`의 RCA 기본 관점을 쓴다. 이 스킬에서 따로 정하지 않는다.

## 증거 다루기

- 같은 모양의 로그·출력이 20줄 이상이면 눈으로 훑지 않는다. 파일로 저장해 경로와 개수를 보고하고 결정적으로 분류한다.
- 원격 API는 읽기 전용 요청으로 확인하고 개수·메타데이터만 보고한다. 자격증명은 이름이나 위치로만 부른다.
- 이슈·산출물이 어느 세션에서 만들어졌는지 추적할 때는 하위 에이전트 초안이 아니라 부모 세션의 실제 명령 실행 로그와 세션 메타데이터를 대조한다. 빈 검색 결과를 부재의 증거로 쓰지 않는다.
- 테스트 드라이버의 산물(드라이버 timeout 등)을 제품 동작으로 읽지 않는다. 적대적 변형(같은 식별자를 가진 항목 여러 개, 중복된 이름 등)으로 메커니즘을 확인한다.

## 심각도 표현

- 입증된 영향으로 쓴다. 예: "5 of 6 endpoints report Ready but return 5xx".
- 정책 위반을 입증된 침해로, 실행하지 않은 반사실 장애를 확정 장애로 쓰지 않는다.
- 지표 의미를 구분한다: wall vs CPU, 상관 vs 인과.
- 이슈마다 검증 수준을 하나 적는다: 운영 환경 재현 / 격리 재현 / mock 재현 / 정적 확인만.

## 재현 환경

- 재현은 scratch 컨테이너, 임시 복사본, 자체 임시 namespace 같은 일회용 격리 자원에서 한다.
- HAPI 워크트리의 추적 파일, 공유·라이브 환경의 기존 자원은 읽기만 한다. 끝나면 만든 자원을 정리했다는 증거(목록 조회 결과)를 남긴다.
- 라이브 변경이 필요한 판별은 코드 추론이라고 표시하거나 승인 요청을 `questions`에 넣고 `next_action: await_decision`으로 끝낸다(삭제·덮어쓰기는 `destructive-operations` 절차).
