# 바꿀 수 있는 기본값

에이전트 관례에서 온 기본값이다. 사용자 지시나 프로젝트 문서(`references/projects/<owner>__<repo>.md`)가 다르게 정하면 그쪽을 따른다. `[U]` 규칙과 전역 가드는 여기서 바꾸지 않는다.

## 리뷰어 관점 (PR 리뷰 프리셋)

변경이 크면 correctness, security, tests 관점 리뷰어를 나눠 병렬로 돌린다. 역할 분리, 구성 규모, 수정 → 재리뷰 루프와 GREEN 조건은 `isac-multi-agent-consensus`를 따른다. GitHub 쓰기는 에이전트가 하지 않고, n8n이 ReviewResult를 받아 한다.

## claim 판정 어휘

PR 주장을 claim별로 판정할 때 `issue-validation`의 판정 토큰을 그대로 쓴다(정의는 그 스킬 소유).

- PR 설명의 주장에 근거가 없거나 사실과 다르면(예: 틀린 ABI 설명) 실행으로 반증됐으면 `NOT_REPRODUCED`, 가릴 수 없으면 `INCONCLUSIVE`로 판정하고 "PR claim unsupported" 메모를 붙인다.
- 등급 척도(evidence grade)는 PR 리뷰에서 생략해도 된다.

## 게시

- 재리뷰는 새 ReviewResult로 내고, `ReviewResult.body` 첫 섹션에 이전 finding의 Closed/Open을 둔다. 이전 봇 스레드마다 `ReviewResult.thread_replies`를 낸다. 현재 head에 대한 리뷰는 하나다.
- PR 수정 때문에 PR이 하는 일과 제목이 달라졌으면 고칠 제목을 `ReviewResult.body`에 제안한다. 리뷰어는 PR을 편집하지 않는다(PRR-03).

## 사용자 보고 형식 (`ReviewResult.summary`)

- 짧은 영어. 여러 PR이면 PR별 판정을 결정 단위로 묶는다: `| 판정 | PR | 핵심 근거 |`.
- main에 남은 문제(PRR-32), 검증 범위의 한계, 정리한 임시 자원을 적는다.
