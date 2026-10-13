# 바꿀 수 있는 기본값

에이전트 관례에서 온 기본값이다. 사용자 지시나 프로젝트 문서(`references/projects/<owner>__<repo>.md`)가 다르게 정하면 그쪽을 따른다. `[U]` 규칙과 전역 가드는 여기서 바꾸지 않는다.

## 리뷰어 관점 (PR 리뷰 프리셋)

트리거된 렌즈(SKILL.md PRR-43, `references/review-dimensions.md` §10)는 기본값이 아니라 필수다. 여기서 바꿀 수 있는 것은 그 위의 구성이다: 트리거가 없어도 변경이 크면 security, performance 렌즈를 더해 병렬로 돌리고, 렌즈마다 반박용 challenger를 따로 둔다(PRR-50). 역할 분리, 구성 규모, 수정 → 재리뷰 루프는 `isac-multi-agent-consensus`를 따르고, 이 자동화의 PR 리뷰에서 이벤트 판정(APPROVE 조건 포함)은 SKILL.md PRR-56을 따른다. GitHub 쓰기는 에이전트가 하지 않고, n8n이 ReviewResult를 받아 한다.

## claim 판정 어휘

PR 주장을 claim별로 판정할 때 `issue-validation`의 판정 토큰을 그대로 쓴다(정의는 그 스킬 소유).

- PR 설명의 주장에 근거가 없거나 사실과 다르면(예: 틀린 ABI 설명) 실행으로 반증됐으면 `NOT_REPRODUCED`, 가릴 수 없으면 `INCONCLUSIVE`로 판정하고 "PR claim unsupported" 메모를 붙인다.
- 등급 척도(evidence grade)는 PR 리뷰에서 생략해도 된다.

## 게시

- 재리뷰는 새 ReviewResult로 내고, `ReviewResult.body` 첫 섹션에 이전 finding의 Closed/Open을 둔다. 이 절이 라운드별 상태 기록이다. `ReviewResult.thread_replies`는 SKILL.md PRR-29 조건에 맞는 스레드(새 head에서 finding 상태가 바뀐 미해결 봇 스레드, 봇의 마지막 댓글 뒤에 사람이 댓글을 단 스레드)에만 내고, 해결된 스레드를 다시 확인하거나 상태가 그대로인 열린 스레드에 답하지 않는다. 해결된 스레드의 finding이 회귀하면 `ReviewResult.comments`에 새 인라인 finding으로 낸다. 현재 head에 대한 리뷰는 하나이고, bridge가 본문·새 인라인 finding·스레드 답글을 한 리뷰로 함께 게시한다. `open_items`는 상태가 그대로인 항목의 문구를 바꾸지 않는다(bridge 결정 요청 코멘트가 같은 집합에 다시 게시되지 않게).
- PR 수정 때문에 PR이 하는 일과 제목이 달라졌으면 고칠 제목을 `ReviewResult.body`에 제안한다. 리뷰어는 PR을 편집하지 않는다(PRR-03).

## 사용자 보고 형식 (`ReviewResult.summary`)

- 짧은 영어. 여러 PR이면 PR별 판정을 결정 단위로 묶는다: `| 판정 | PR | 핵심 근거 |`.
- main에 남은 문제(PRR-32), 검증 범위의 한계, 정리한 임시 자원을 적는다.
