# n8n + HAPI Issue Agent 구현·운영 설계

## 상태와 변경 경계

이 문서는 구현 체크리스트이자 수용 기준이다. 체크되지 않은 항목은 완료·검증되지 않았다. 설계 작성만으로 배포나 검증이 완료되었다고 보고하지 않는다.

사용자가 선택한 구성은 n8n + HAPI다. 기존 Archon은 새 구성의 검증과 안전한 전환 전까지만 유지한다. 사용자의 후속 명시 지시로 **전환 후 Archon 전용 배포·도메인·ArgoCD 등록·코드·대화/worktree/상태 DB PVC와 데이터를 모두 삭제**한다. 앞선 Archon 기록 보존 결정은 폐기되었다. 실제 GitHub 이슈·PR과 새 시스템이 재사용하는 GitHub App·인증 원본은 삭제 대상이 아니다. 이 작업은 임의의 Git 커밋·푸시·PR 머지를 승인하지 않는다. 사용자는 `apps/objects/issue-agent/bridge.py`, `test_bridge.py`의 이벤트 검증·영속 상태·세션 연결·복구·결과 보고와 n8n 워크플로 구현을 명시적으로 승인했다. HAPI·n8n upstream 및 대상 레포 제품 코드의 임의 변경은 승인 범위에 포함하지 않는다.

v2는 코딩 에이전트의 GitHub 쓰기를 모두 없앴다. 에이전트는 읽기 전용 토큰으로 조사하고 구조화된 결과만 반환하며, n8n이 그 결과를 bridge op로 GitHub에 반영한다. 아래 설계·계약 절은 v2 기준이다. v1 수용 기록은 v1 동작(에이전트의 직접 push·PR 생성, n8n 모델 분류, 저장소별 라벨 매핑)에 대한 당시 증거이므로 고치지 않는다. v2 수용 항목은 `### v2 수용 기준`에 따로 둔다.

## 확정된 요구사항

- 공통 Issue Agent를 여러 GitHub 저장소에서 사용할 수 있게 구현한다. GitHub App `bulgasaribot`의 설치 범위가 곧 대상 범위이며, bridge는 설치된 모든 저장소의 이벤트를 받는다. 현재 설치·운영 대상은 사용자 선택에 따라 `isac322/cc-lb`, `isac322/pillar-csi`, `isac322/flareway`, `isac322/krema`다. 설치 범위 확장은 사용자 지정 후에만 한다.
- GitHub 이슈마다 독립 세션과 해당 저장소의 worktree(`issue-<n>`)를 만든다. 동일 이슈 후속 댓글은 같은 논리 세션으로 전달한다. PR 리뷰는 PR마다 별도 세션(`review-pr-<n>`)을 쓴다. 이슈별 Pod도 허용하지만 최소 조건은 세션·worktree 분리다.
- 웹에서 모든 이슈 세션을 찾고 실행 중 관찰·메시지 전달·중단·승인을 처리한다. UI 접속 때문에 자동화 구독이나 실행을 종료하지 않는다.
- Codex·Claude Code면 충분하다. 자동 학습 기능은 범위에서 제외한다.
- 하네스가 기록하는 대화·도구 호출·실행 기록을 영속 보존하고 외부 에이전트가 조회할 수 있게 한다. 저장소가 여러 곳이어도 된다. 하네스가 생략한 원시 stdout/stderr의 별도 무손실 수집은 요구하지 않는다.
- 지침·스킬은 외부에서 갱신할 수 있으며 새 세션·재시작·재빌드로 반영해도 된다.
- 커스텀 provider와 모델 설정을 독립적으로 관리한다. 자체 ARM64 이미지 빌드는 허용된다.
- 선호가 불명확한 경우 추측하지 않고 질문한다.
- 누구나 이슈를 열 수 있다. 명확한 요청은 triage(재현·원인·중복 판단)를 거친 뒤 자동으로 수정·검증·PR 생성까지 수행한다. 불명확한 요청은 질문하며 자동 머지는 하지 않는다. 저장소 collaborator·owner가 아닌 사용자의 새 이슈는 전체 저장소 합산 1시간(rolling)에 10개까지만 받는다.
- 설치된 저장소에서 Draft가 아닌 PR을 생성·재개하거나 Ready for review로 바꾸면 이슈와 다른 `review-pr-<n>` 세션에서 리뷰한다. 리뷰 App이 설정되어 있으면 push로 head가 바뀔 때도 head별로 한 번 리뷰하고, 명시적 `@haechibot review` 요청은 같은 head를 다시 리뷰할 수 있다. ruleset·branch protection이 merge 조건을 소유하며 bridge는 필수 check 목록이나 reviewer 수를 하드코딩하지 않는다.
- 코딩 에이전트는 GitHub에 쓰지 않는다. 댓글·라벨·push·PR·리뷰는 모두 n8n이 에이전트 결과를 검증된 bridge op로 적용한다.

## 책임 분리

| 구성 요소 | 책임 |
|---|---|
| n8n | GitHub 이벤트 처리 흐름, 모드별 단계(triage → implement, followup, review), 결과에 따른 분기, 모든 GitHub 반영(라벨·댓글·push·PR·리뷰)의 호출과 실패 처리. 에이전트에 보내는 메시지에는 대상 번호와 트리거 정보만 넣으며 GitHub 내용 조회는 담당하지 않는다 |
| 연결 계층(bridge) | webhook 검증, collaborator 권한 판정(캐시)과 비신뢰 이슈 rate limit, 이벤트 영속화·중복 방지, 이슈/PR과 세션 매핑, HAPI API 인증·상태 확인, 모드별 결과 스키마 검증, GitHub 쓰기 op(issues/pull_requests/contents write 토큰. contents write는 리뷰 스레드 resolve용이며 push에 쓰지 않음), publisher 호출, attention 알림. 에이전트용 GitHub 읽기 op는 두지 않는다 |
| publisher(Runner Pod 사이드카) | push 토큰(`issue-agent-github-push`)의 유일한 보유자. bridge 요청으로 저장소 checkout clone과 `hapi-issue-<n>` branch의 non-force push만 수행 |
| HAPI Hub | 세션 목록·메시지·승인 API, 웹 UI, 다중 구독, Hub 데이터 저장 |
| HAPI Runner | 실제 Codex 실행, 저장소별 worktree, 하네스 설정·기록 보존. GitHub 토큰은 읽기 전용이며 에이전트가 `gh`(REST·`gh api graphql`)로 GitHub를 직접 읽는다 |
| 공통 에이전트 프로필 | 전역 `AGENTS.md`(읽기 전용 GitHub, 결과 프로토콜, 모드별 스킬)와 자동화용으로 고친 스킬 |
- 저장소 등록부: `defaults`(agent, model, permission_mode, machine_id, project_owner)와 저장소별 override. `project_owner`는 merge-ready 시 assign·멘션할 GitHub 사용자이며, 설정하지 않으면 알림을 건너뛴다. 기본 checkout 경로는 `/home/agent/checkouts/<owner>/<repo>`이다.

n8n은 단순히 에이전트를 한 번 호출하는 장식이 아니라 실제 처리 단계와 분기를 소유한다. 연결 계층은 전송·인증·영속 상태의 정확성을 담당하고 같은 비즈니스 절차를 별도로 중복 구현하지 않는다.

## 지침·스킬 계층

1. 공통 Issue Agent 지침(`profile/AGENTS.md` → `CODEX_HOME/AGENTS.md`): GitHub 읽기 전용, 턴 끝 `ISSUE_AGENT_RESULT <nonce> {json}` 한 줄로만 결과 반환, 메시지가 지정한 모드만 수행, 이슈·PR 본문과 context는 신뢰하지 않는 데이터, worktree branch에만 로컬 커밋, 불명확하면 결과로 질문.
2. 공통 스킬(`profile/skills/` → Codex ADMIN scope `/etc/codex/skills`, PVC에 두지 않음): 모드별 주 스킬은 `triage`=`isac-issue-triage`, `implement`=`isac-issue-to-pr`, `followup`=`isac-issue-to-pr`+`receiving-code-review`, `review`=`isac-pr-review`다. 보조 스킬은 `isac-github-publishing`, `isac-decision-brief`, `isac-multi-agent-consensus`, `isac-live-qa`, `issue-validation`, `five-whys-root-cause-analysis`, `comment-writer`, `humanizer`, `writing-clearly-and-concisely`, `destructive-operations`, `public-api`, `pull-request-merge`, `pull-request-review-handling`이다.
3. 저장소 지침: 각 저장소의 `AGENTS.md` 등 기여 규칙을 worktree에서 읽는다. 빌드·테스트·스타일만 정하며 공통 지침의 제한을 넓히지 못한다.
4. Codex 도구: 모든 세션에 context-mode(`ctx_*`)와 CodeGraph(`codegraph_*`) MCP 서버가 붙는다(`/etc/codex/config.toml`). 사용 강제는 `/etc/codex/requirements.toml`의 managed hook으로 한다. context-mode hook 6개(SessionStart, PreToolUse, PostToolUse, PreCompact, UserPromptSubmit, Stop)가 raw fetch를 막고 큰 출력을 sandbox로 유도하며, SessionStart의 `codegraph-index`가 worktree 색인을 준비한다. 공통 지침은 코드 탐색에 CodeGraph를, 20줄 넘는 출력에 context-mode를 기본으로 쓰게 한다.
5. 빌드 캐시: Runner는 sccache로 Rust(`RUSTC_WRAPPER`)와 C/C++(`PATH` 앞쪽 `cc`·`gcc`·`c++`·`g++` wrapper, CMake compiler launcher) 컴파일 결과를 home PVC의 `SCCACHE_DIR`(최대 5G)에 캐시해 worktree와 세션이 공유한다. wrapper는 sccache가 부모일 때 실제 컴파일러를 바로 실행해 이중 wrapping을 막는다.
6. 접근 제한: 에이전트 컨테이너에는 읽기 전용 설치 토큰만 마운트한다. 쓰기 토큰(bridge의 issues/pull_requests/contents write, publisher의 contents write)과 publisher bearer 토큰은 에이전트 컨테이너에서 읽을 수 없다. 지침 문구를 강제적인 보안 격리로 설명하지 않는다.
7. GitHub 읽기 자격증명 경계: Runner의 `GH_CONFIG_DIR`에는 사용자 토큰이나 PAT가 아닌 rotating repository-scoped GitHub App installation token이 들어간다. `gh auth status`, `gh auth login`, `gh auth setup-git`, `gh api user`, `gh api /user`, GraphQL `viewer` 조회는 설치 토큰에 맞지 않는 사용자 identity probe이므로 인증·readiness 확인에 사용하지 않는다. 이 probe의 실패만으로 저장소 읽기 권한이 없다고 판단하지 않는다.
8. 운영 불변식과 incident lesson: readiness/auth는 실제 대상 이슈·PR·저장소 읽기(`gh issue view`, `gh pr view`, `gh api repos/{owner}/{repo}/...`)로만 확인한다. 대상 읽기는 일반 셸 또는 `ctx_execute`로 실행할 수 있다. `ctx_batch_execute`가 출력을 색인하면 `ctx_search`로 확인하며, 빈 직접 응답만으로 인증 실패로 처리하지 않는다. 대상 읽기가 401/403을 반환하거나, 대상 404 뒤 저장소 메타데이터 읽기(`gh api repos/{owner}/{repo}`)도 404일 때만 GitHub 인증·설치 접근 blocker로 보고한다. 단순 404 또는 리소스 부재는 저장소 접근을 확인하기 전까지 자격증명 실패로 바꾸지 않는다. bootstrap의 `gh auth token`은 로컬 설정 파싱일 뿐 API capability/health check가 아니다.

스킬은 원본을 자동화용으로 기계적으로만 고쳤다. 각 `SKILL.md` 머리의 adaptation 절이 바꾼 점을 적는다. 공통 규칙은 다음과 같다.

- 원본의 GitHub 쓰기 단계(라벨 부착·교체, 댓글 게시·수정, push, `gh pr create/edit`, 리뷰 게시, 스레드 답글·resolve, 리뷰 재요청, 이슈 닫기, merge)는 결과 필드로 바뀐다. 예: triage 라벨·분석 댓글 → TriageResult `labels`·`comment`, PR 제목·본문 → ImplementResult `pr`, 리뷰·inline·스레드 답글 → ReviewResult `body`·`comments`·`thread_replies`.
- 게시/초안 모드 구분이 없다. 항상 결과에 초안을 담는다.
- 채팅으로 묻고 기다리는 단계(`isac-decision-brief` 포함)는 결과의 `questions`와 초안 댓글에 질문을 넣고 `await_info`/`await_decision`/`needs_info`로 턴을 끝낸다.
- 한국어 최종 보고는 짧은 영어 `summary`가 된다. GitHub에 게시될 텍스트는 `isac-github-publishing`에 따라 영어로 쓴다.
- `pull-request-merge`는 merge를 금지하고 merge 준비 상태 보고로 바뀌었다.

Codex의 공통 지침은 전용 `CODEX_HOME/AGENTS.md`에서 읽고 프로젝트 지침과 결합할 수 있다. 전용 프로필은 개인 설정과 분리한다. 레포 안의 지침이 공통 지침을 덮어쓸 수 있으므로 비밀 보호나 접근 제어의 유일한 장치로 사용하지 않는다.

공통 지침·스킬은 버전 관리한다. 이슈 worktree에서의 수정은 다른 worktree에 자동 전파되지 않는다. 공통 반영은 기준 브랜치나 공통 이미지·설정 배포를 통해 수행한다.

### 자동 머지와 실행 격리의 한계

워크플로는 PR 생성·갱신과 리뷰 제출까지 수행하고 **merge는 사람이 한다**. bridge는 GitHub가 현재 head를 merge-ready로 판정할 때만 설정된 project owner를 assign하고 멘션한다. 에이전트는 읽기 전용 GitHub 토큰으로 작업하며, bridge가 결과를 받아 GitHub 쓰기를 수행한다. push는 publisher가 checkout cwd에서 `hapi-issue-[0-9]+` branch에 non-force 방식으로 실행한다. push 토큰은 publisher 사이드카에만 마운트한다.

다만 publisher와 에이전트는 Runner home PVC를 공유하므로 에이전트는 push될 커밋 내용을 정한다. n8n은 결과의 `head_sha`와 일치하는 커밋만 push한다. 공유 Runner는 악성 코드에 대한 주제별 보안 샌드박스가 아니다.

### PR 자동 수정과 merge-ready 알림

- 같은 저장소의 `hapi-issue-<n>` head를 가진 PR은 원본 이슈에 연결한다. SQLite `prs`에 head, dirty/revision, repair delivery lease, 마지막 시도 fingerprint, 수동 요청, 알림 head를 보관한다. fork의 같은 이름 branch는 관리 대상으로 삼지 않는다.
- `pull_request` 상태 변경, `pull_request_review`, `pull_request_review_comment`, `check_run`, `check_suite`, `status`, 기본 branch `push`는 최신 상태 재조회를 예약한다. GitHub App webhook에 해당 이벤트를 구독해야 한다. 누락된 webhook과 재시작은 60초 주기의 reconciliation으로 보완한다.
- 첫 actionable blocker에서 원본 `issue-<n>` worktree로 `pr_repair` followup을 보낸다. freshly fetched 기본 branch를 먼저 merge하고, 현재 head의 CI 실패와 리뷰 finding을 한 턴에서 검증·수정한다. rebase·reset·force-push와 자동 PR merge는 하지 않는다.
- repair 중 새 이벤트는 두 번째 writer를 시작하지 않고 dirty/revision만 갱신한다. 끝난 턴은 push 이후 GitHub 상태를 다시 조회한다. 이전 head의 change request는 새 head의 repair 근거로 재사용하지 않고 재리뷰를 기다린다.
- 시작 시 일시적인 GitHub 조회 실패는 같은 delivery를 backoff 후 재시도한다. 성공한 push·PR 갱신 뒤 상태 조회만 실패하면 성공 결과를 유지하고 reconciliation을 예약한다. 해결 불가능한 repair는 `needs_attention`으로 보류하며 새 repair writer를 막지만, 별도 worktree의 리뷰는 진행할 수 있다.
- readiness는 일치하는 GraphQL/REST head·base에서 open, non-Draft, `MERGEABLE`, `CLEAN` 또는 `UNSTABLE`일 때만 인정한다. `UNSTABLE`은 비필수 check 실패를 포함할 수 있다. `UNKNOWN`이나 API 간 불일치는 기다리며, assign 전과 멘션 직전에 다시 확인한다.
- 알림은 `(repo, PR, head)`별 SQLite acknowledgement와 `pr-ready:<PR>:<head>` comment marker로 중복을 방지한다. 같은 수동 repair 댓글의 재전송도 comment ID로 중복 처리한다. 현재 owner 설정은 `isac322/cc-lb`와 `isac322/pillar-csi`에만 있다.

### 리뷰·repair 반복 상한

krema#63에서 리뷰 ↔ repair 조정이 약 12시간 동안 반복돼 토큰 약 1.21억 개를 썼다. 아래 세 상한으로 모든 반복이 유한하게 끝난다.

- 리뷰 중복 제거: 새 `pr_review`가 들어오면 같은 PR에서 아직 dispatch되지 않은(`accepted`) 이전 리뷰를 `coalesced`로 끝내고 detail에 새 delivery를 남긴다. PR마다 대기 리뷰는 최대 하나다. `begin` 시 리뷰 App이 현재 head에 이벤트 수신 시각 이후 제출한 리뷰가 있으면 세션 없이 `already_reviewed`로 끝낸다. 마지막 리뷰보다 나중에 온 명시적 요청은 그대로 실행한다.
- 재리뷰 차단 해제 상한: 멈춘 리뷰의 detail이 자격증명·권한 실패(HTTP 401·403, `Bad credentials`, 권한 관련 HTTP 422)이거나, 마지막 `reviewed` 이후 `superseded`된 리뷰가 `MAX_REVIEW_SUPERSEDES`(2)개 이상이면 새 리뷰 요청은 차단을 풀지 않고 대기한다. 이때 attention 댓글과 stale 리뷰 본문은 `@haechibot review` 안내를 빼고 운영자가 원인을 고친 뒤 `retry_event`해야 한다고 쓴다.
- 자동 repair 상한: `prs.repair_count`가 reconciliation이 자동으로 넣은 `pr_repair` 수를 센다. `MAX_PR_REPAIRS`(3)에 도달한 뒤 fingerprint가 바뀌고 수동 요청이 없으면 repair를 넣지 않고 `repair_limit`을 반환하며 dirty를 내린다. PR에는 `pr-repair-limit:<PR>:<last_manual_id>` marker 댓글을 한 번 남긴다. 사람의 `@bulgasaribot` repair 요청은 허용되며 카운터를 0으로 되돌린다. PR이 merge-ready가 되어도 0으로 되돌린다.


### 알려진 제한

- GitHub App은 PR reviewer로 요청할 수 없다. REST API로 `ironeater[bot]`(당시 이름, 현 `bulgasaribot[bot]`)을 reviewer로 요청하면 오류 없이 무시되는 것을 확인했다. 그래서 재리뷰 요청은 본문 어디든 `@haechibot` 멘션이 있는 PR 댓글(대소문자 무시)로 받되, PR 작성자 또는 저장소 collaborator·owner가 `User` sender로 남긴 댓글만 받는다.
- GitHub는 PR 작성자의 APPROVE/REQUEST_CHANGES를 금지한다. 그래서 리뷰는 작성용 `bulgasaribot`과 다른 App `haechibot`으로 제출하며, bulgasaribot이 연 PR에도 실제 승인·변경 요청이 달린다. 리뷰 App 자신이 연 PR만 `COMMENT`와 `**Verdict: <event>**` 접두로 downgrade한다(현재 그런 PR은 없다).
- 필수 승인 수에 GitHub App 승인이 포함되는지는 문서에 없어서, merge 강제는 특정 App이 남긴 상태만 인정하는 required status check(`issue-agent/review`, integration `5118831`)로 한다. 새 commit은 상태가 없으므로 재리뷰 전까지 merge되지 않는다.
- `isac322/cc-lb`는 GitHub Free의 private 저장소라 branch protection과 ruleset API가 403을 반환한다. 이 저장소는 bot 승인을 merge 조건으로 강제하지 않는다.

## 이벤트와 세션 계약

- 키는 저장소 식별자와 이슈/PR 번호의 조합이다. 서로 다른 저장소의 동일 번호를 충돌시키지 않는다.
- GitHub delivery 중복과 의미적으로 중복된 이슈를 구분한다. 전자는 영속 키로 처리하고 후자는 에이전트가 triage에서 읽기 전용 토큰으로 직접 검색·판단한다(`verdict: DUPLICATE`, `duplicate_of`).
- 이벤트는 수신 확인 전에 영속화한다. 허용하지 않은 사용자·이벤트는 모델에 전달하지 않는다. 저장소는 App 서명이 설치를 증명하므로 따로 거르지 않는다.
- 에이전트가 작성한 댓글이 재실행 루프를 만들지 않게 한다.
- 세션 생성과 메시지 전송은 결과가 불확실할 때 무조건 재전송하지 않는다. HAPI의 `localId`, queued-state와 세션 메타데이터를 사용해 확인 가능한 것만 복구한다.
- HAPI spawn 응답은 HTTP 200만으로 성공이라고 보지 않는다. `{type:'success', sessionId}`를 확인한다.
- resume/reopen 결과의 세션 ID는 기존과 다를 수 있다. 반환 ID와 superseded 매핑을 반영하여 같은 논리 이슈 대화를 유지한다.
- 운영 자동화는 일반 메시지를 queue로 전달한다. 사용자의 명시적 Steer·중단·승인은 UI를 통해 구분한다. Codex와 Claude의 중간 개입 기능이 같다고 가정하지 않는다.
- 결과는 제출 메시지의 `localId`와 `invokedAt`, 그 메시지 이후의 agent 결과에 포함된 작업별 nonce·결과 스키마를 함께 확인한다. 다른 UI 메시지가 중간에 실행되었거나 결과의 소속이 불확실하면 자동으로 다음 단계로 넘어가지 않는다. 이 경우 사람의 개입 기록은 보존하고 운영자 확인 상태로 전환한다. `/clear`를 기존 이슈의 자동 세션 이전으로 해석하지 않는다.
- 상태가 불확실하거나 권한·provider 오류가 나면 성공으로 처리하지 않는다. 운영자에게 근거를 남기고 중복 실행을 차단한다.

### 이벤트 분류(bridge `classify_event`)

- 신뢰 사용자는 저장소 collaborator·owner다. bridge가 이슈 App 토큰으로 `GET /repos/{repo}/collaborators/{login}/permission`을 호출해 `permission`이 `admin` 또는 `write`면 신뢰한다(`maintain`은 `write`, `triage`는 `read`로 매핑된다). 404는 비신뢰다. 결과는 신뢰·비신뢰 모두 SQLite `collaborators` 테이블에 600초 캐시한다. 조회는 규칙이 신뢰 여부를 필요로 할 때만 한다. 네트워크 오류·토큰 없음·그 외 HTTP 상태면 캐시하지 않고 HTTP 503 `permission_unavailable`로 응답하며 이벤트를 저장하지 않는다. GitHub가 재전달한다.
- `issues.opened`: 누구나(sender가 bot이 아닌 `User`이고 이슈 작성자와 같을 때) → `issue_opened`. 신뢰 사용자의 이슈는 항상 받는다. 비신뢰 사용자의 이슈는 전체 저장소 합산 최근 3600초(rolling) 안에 받은 비신뢰 `issue_opened`가 10개 미만일 때만 받고, 넘으면 `rate_limited`(202, 저장 안 함)다. 신뢰 사용자의 이슈는 한도에 세지 않는다.
- 예외: 저장소 owner(저장소 이름의 `<owner>`와 같은 login, 예: `isac322/*`의 `isac322`)가 연 이슈는 자동 처리하지 않는다(`owner_issue_ignored`, 저장 안 함). owner는 자기 에이전트 작업용 메모로 이슈를 여는 경우가 많기 때문이다. 이런 이슈도 신뢰 사용자가 `@bulgasaribot` 멘션 댓글을 달면 그 댓글이 `issue_comment`로 들어와 triage부터 시작한다. 조직 저장소는 login이 조직 이름과 같을 수 없으므로 해당이 없다.
- `issue_comment.created`(이슈): 이슈에 `agent:open-discussion` 라벨이 있으면 누구의 댓글이든 멘션 없이 `issue_comment`다(신뢰 조회·rate limit 없음). 누구나 의견과 자료를 보태 에이전트가 이슈를 더 잘 이해하게 하는 용도다. 라벨이 없으면 본문에 이슈 bot 멘션(`@bulgasaribot`, 대소문자 무시, `github_bot_login`에서 `[bot]` 제외)이 있어야 한다. 멘션이 없으면 `issue_comment_ignored`, 신뢰 사용자의 멘션은 `issue_comment`, 비신뢰 사용자의 멘션은 `actor_not_allowed`다. 에이전트가 처음 보는 이슈의 댓글도 같은 규칙으로 처리한다.
- `issue_comment.created` (PR): PR 작성자 또는 신뢰 사용자의 `@haechibot` 멘션은 재리뷰를 큐에 넣는다. 별도 리뷰 App이 있을 때 `@bulgasaribot` 멘션은 관리 PR의 원본 이슈 worktree에 수동 repair 요청을 기록한다. 그 외 댓글은 무시하며, 두 번째 App이 없으면 이슈 App 멘션으로 리뷰한다.
- `issues.edited`: `changes`에 `body`나 `title`이 있을 때만 본다(그 외 `edit_ignored`). sender는 bot이 아닌 `User`여야 하고, 이슈에 `agent:open-discussion` 라벨이 있거나 sender가 신뢰 사용자여야 한다(아니면 `actor_not_allowed`). 종류는 `issue_edited`, semantic key는 `repo#issue:<n>:edited:<delivery>`이며 새 제목·본문을 넘긴다. 이슈가 `phase: implementing`(PR을 만드는 중이거나 이미 있음)일 때만 큐에 넣고 그 외는 `edit_ignored`다.
- `pull_request.opened`/`reopened`/`ready_for_review`: Draft가 아닌 PR은 `pr_review`로 분류한다(`repo#pr:<n>:review:<head_sha>`). 리뷰 App이 설정된 non-Draft PR의 `synchronize`도 같은 head별 key로 리뷰하고, 관리 PR의 상태 재조회도 예약한다. dependabot·자기 App의 PR도 리뷰할 수 있다.
- bot·자기 댓글과 에이전트 marker가 있는 댓글은 `bot_sender`로 무시한다.
- 이벤트 행에는 신뢰 여부(`trusted`)를 함께 기록한다.

`agent:open-discussion` 라벨은 bridge `LABEL_CATALOG`에 없다. 공개 토론을 허용할 저장소마다 maintainer가 직접 만들고 이슈에 붙인다.

### 모드와 결과 계약

세션은 주제마다 하나이고 HAPI branch는 `hapi-<worktree>`다. 턴은 `(delivery_id, mode)`로 식별하며 HAPI 메시지 `localId`는 `issue-agent-<delivery_id>-<mode>`다. 한 delivery에서 triage 뒤 implement를 이어 실행할 수 있다. 메시지에는 대상 이슈·PR 번호와 트리거 정보만 싣는다. 이슈·댓글·PR·리뷰·스레드 같은 GitHub 내용은 에이전트가 읽기 전용 토큰으로 `gh`(REST·`gh api graphql`)를 직접 실행해 읽는다.

동시 실행: bridge dispatcher는 저장소와 무관하게 전체에서 최대 `MAX_ACTIVE_EVENTS`(5)개 이벤트에 슬롯(`dispatching`/`dispatched`)을 주고 n8n에 넘긴다. 같은 주제(이슈·PR 번호)의 이벤트는 세션·worktree를 공유하므로 앞선 이벤트가 끝날 때까지 기다린다. 응답이 불확실한 n8n POST는 그 이벤트의 슬롯만 유지한 채 같은 이벤트로만 재시도하고, 다른 주제는 막지 않는다. `begin`은 슬롯을 가진 이벤트만 시작시킨다. 세션 생성·재개는 bridge의 `session_lock`으로, 같은 저장소 checkout clone과 push는 publisher의 저장소별 잠금으로 직렬화된다. 모든 세션은 Runner Pod 하나의 메모리 한도를 함께 쓴다.

이벤트가 `finish`로 끝나면 bridge가 그 주제의 HAPI 세션을 `archive`해 Codex 프로세스와 MCP 서버를 멈춘다. 같은 주제의 다음 이벤트는 `ensure_session`의 resume 경로로 같은 세션 ID·같은 Codex 대화를 다시 띄운다(운영 HAPI 0.30.7에서 archive → resume이 1.2초에 같은 ID로 돌아오는 것을 확인). archive 실패는 이벤트 완료를 막지 않고 로그만 남긴다. 멈추지 않으면 끝난 세션이 Runner 재시작 전까지 세션마다 수백 MB를 계속 차지한다. `needs_attention`으로 멈춘 이벤트의 세션은 운영자 확인을 위해 archive하지 않는다.

닫힌 주제의 상태는 닫힌 시점에는 그대로 두고, 닫힌 지 30일이 지나면 지운다. n8n `IssueAgentMain01`의 `Daily cleanup`(매일 04:00 UTC)이 bridge `cleanup_closed` op(`older_than_days` 기본 30, `dry_run` 지원)를 부른다. bridge는 세션이나 worktree가 남은 `issues` 행마다 `accepted`/`dispatching`/`dispatched` 이벤트가 있으면 건너뛰고, 이슈 App 토큰으로 `GET /repos/{repo}/issues/{n}`을 읽어 `state == "closed"`이고 `closed_at`이 기준보다 오래된 주제만 정리한다(PR도 같은 API이며 merge도 closed다). 정리는 `session_lock`을 잡고 진행 중 이벤트를 다시 확인한 뒤 ① 현재·superseded HAPI 세션마다 `codexSessionId`를 모으고 archive → `DELETE /api/sessions/{id}`(운영 HAPI 0.30.7에서 이후 GET이 404임을 확인), ② publisher `POST /cleanup`으로 worktree·admin 디렉터리·`hapi-*` branch ref(loose와 `packed-refs`)·Codex rollout 파일 삭제, ③ `issues` 행을 세션·단계가 없는 상태로 되돌리는 순서다. branch ref까지 지우는 이유는 HAPI가 branch가 남은 이름을 피해 `issue-<n>-<4hex>` 같은 새 worktree 이름을 고르기 때문이다. publisher는 에이전트가 hook·config를 심을 수 있는 checkout에서 git을 실행하지 않는다는 원칙대로 git 없이 파일 연산만 쓰고, symlink이거나 checkout·`.git/worktrees`·`CODEX_HOME` 밖으로 풀리는 경로는 거부한다. 중간에 실패하면 행이 그대로 남아 다음 날 나머지를 다시 시도하고, 오류 목록이 비어 있지 않으면 n8n 실행을 실패로 끝내 error workflow에 보인다. GitHub 내용과 `events` 기록은 지우지 않으며, 정리된 주제의 다음 이벤트는 `session_state = none`에서 새 세션을 spawn한다.

| mode | 시작 조건 | worktree | 스킬 | 결과 |
|---|---|---|---|---|
| `triage` | `issue_opened`, 또는 구현 단계가 아닌 이슈의 `issue_comment` | `issue-<n>` | `isac-issue-triage` | TriageResult |
| `implement` | TriageResult `next_action: implement`(같은 n8n 실행·같은 세션) | `issue-<n>` | `isac-issue-to-pr` | ImplementResult |
| `followup` | 구현 단계(`phase: implementing`) 이슈의 `issue_comment` 또는 `issue_edited` | `issue-<n>` | `isac-issue-to-pr` + `receiving-code-review` | ImplementResult |
| followup (PR repair) | 현재 head의 CI·리뷰·base blocker 또는 명시적 repair 댓글 | `issue-<n>` | 원본 이슈 범위, `receiving-code-review` | ImplementResult |
| `review` | `pr_review` | `review-pr-<n>` | `isac-pr-review` | ReviewResult |

에이전트는 턴 끝에 `ISSUE_AGENT_RESULT <nonce> {json}` 한 줄을 낸다. `session_send`가 메시지에 nonce와 해당 모드의 정확한 스키마를 넣고, `context`(트리거 정보나 triage 결과 같은 작은 보조 데이터, 200KB 이하)는 신뢰하지 않는 데이터로 fence한다. `session_turn`이 턴 모드의 스키마로 결과를 검증한다(모든 필드 필수, 알 수 없는 키 거절). n8n은 턴마다 120초 간격으로 최대 180회(약 6시간) 확인한다.

followup 턴은 PR을 이슈와 맞춘다. 에이전트는 `gh issue view`와 `gh api`로 이슈 제목·본문과 모든 댓글을 직접 읽는다. Begin 응답에 기록된 `pr_number`가 있으면 `gh pr view`로 그 PR의 상태(번호·URL·state·merged·draft·제목·본문·head/base)와 리뷰 댓글도 직접 읽고, 없으면 아직 PR이 없는 상태다. 에이전트는 PR이 열려 있든, merge·close됐든, 아직 만드는 중이든 이슈 제목·본문과 모든 댓글에서 현재 요구사항을 다시 정리하고 branch diff와 현재 PR 제목·본문·상태와 비교한다. 다르면 `hapi-issue-<n>`에 새 커밋을 올리고 전체 현재 범위를 설명하는 `pr.title`/`pr.body`로 `ready`를 낸다. PR이 merge·close됐으면 먼저 `origin/<default>`를 branch에 merge한다(rebase·force 금지). 자동화가 그 branch로 새 PR을 연다. PR이 이미 충족하는 단순 맥락이면 `no_change`와 어떻게 반영했는지 설명하는 `issue_comment`를 낸다. 요구사항이 모호하거나 충돌하면 `needs_info`다.

- TriageResult: `status`(`triaged|blocked`), `verdict`, `fault_domain`, `duplicate_of`, `labels.add/remove`(카탈로그 이름), `comment`, `next_action`(`implement|await_info|await_decision|none`), `implementation_brief`(implement일 때 필수), `questions`, `summary`, `blockers`. n8n은 결과 기록 → 라벨 적용 → 분석 댓글 게시 후 `next_action`으로 분기한다. `implement`면 brief를 implement 턴으로 넘기고, 질문이면 `questioned`, 그 외는 `triaged`로 끝난다. `blocked`는 attention이다.
- ImplementResult: `status`(`ready|no_change|needs_info|blocked`), `head_sha`와 `pr{title, body}`(ready일 때 필수, 본문에 `Fixes #<n>` 또는 `Related to #<n>`), `issue_comment`, `questions`, `summary`, `blockers`. 에이전트는 `hapi-issue-<n>`에 로컬 커밋만 한다. `ready`면 n8n이 `git.push`(publisher `POST /push`, sha 일치·non-force) → `github.pr_upsert`(열린 PR이 없으면 기본 브랜치 대상 일반 PR 생성, 있으면 제목·본문 PATCH) → 이슈에 PR 링크 댓글 → `implemented`. `no_change`는 이슈 댓글, `needs_info`는 질문 댓글과 `triage:needs-info` 라벨, `blocked`는 attention이다. implement/followup 전송 시 이슈 phase는 `implementing`이 된다.
- ReviewResult: `status`(`reviewed|blocked`), `head_sha`, `event`(`APPROVE|REQUEST_CHANGES|COMMENT`), `body`, `comments`(새 inline 지적, 최대 50), `thread_replies`(기존 스레드 comment ID에 대한 답글과 `resolve`, 최대 100), `summary`, `blockers`. n8n은 context로 PR 번호와 이벤트 head(`head_sha`, 없으면 에이전트가 `gh`로 현재 head를 읽는다)만 넘긴다. 에이전트는 `gh`와 `gh api graphql`로 PR 제목·본문·파일·리뷰·댓글, 리뷰 스레드(스레드 comment `databaseId` 포함, `thread_replies`에 필요)와 연결 이슈·그 댓글을 직접 읽는다. Begin 응답의 `reviewer_login`이 남긴 이전 리뷰가 있으면 재리뷰다. `github.review`는 리뷰 App(`haechibot[bot]`) 토큰으로 동작하며, 스레드 답글 게시·resolve 후 `commit_id=head_sha`로 리뷰 하나를 제출하고 `issue-agent/review` 상태(APPROVE → success, 그 외 failure)를 남긴다. PR head가 `head_sha`와 다르면(리뷰 중 push) 리뷰는 그대로 `head_sha`에 제출하되 본문 첫머리에 stale 안내와 재리뷰 명령을 넣고 상태는 남기지 않는다. force-push로 `head_sha`가 PR에서 빠져 422가 나면 판정·지적을 marker 댓글로 남긴다. 둘 다 성공으로 끝나며 attention을 만들지 않는다. 모두 숨은 marker 또는 기존 상태 비교로 멱등이다. inline 지적이 422로 거절되면 본문의 "Findings outside the diff" 절로 옮겨 다시 제출한다. 재리뷰 본문의 첫 절은 이전 지적의 Closed/Open 상태다. bridge가 제출하는 리뷰 본문과 `pr_review` 이벤트의 attention 댓글 끝에는 항상 같은 footer 블록이 붙고 에이전트는 body에 footer를 쓰지 않는다:

  ```
  ---
  <sub>To request another review, comment `@haechibot review` on this pull request after pushing fixes or replying to the findings. The same comment restarts a review that stopped with an error. The pull request author or a maintainer can request it.</sub>
  ```

  footer의 bot login은 설정값(`GITHUB_REVIEW_BOT_LOGIN`의 `[bot]` 제외)이며 코드에 하드코딩하지 않는다.

라벨은 bridge `LABEL_CATALOG`의 이름만 허용한다(목록은 README `#### 라벨`). 저장소에 없으면 카탈로그 설명·색으로 만들고, 같은 그룹(`repro:*`, direction, kind) 라벨을 추가하면 나머지를 같은 op에서 제거한다. `agent:needs-attention`은 bridge만 다룬다.

### 오류 알림

에이전트를 실행하는 모든 경로는 GitHub에 보이는 상태로 끝난다. 실패는 bridge `mark_attention`으로 모인다. 입구는 워크플로의 `Mark needs attention`(`fail`), n8n 오류 워크플로 `IssueAgentError01`(Error Trigger → `fail_execution`, 메인 워크플로 `settings.errorWorkflow`), bridge 자체 포기(dispatch 8회 실패, stale dispatch, n8n 응답 없음)다. `mark_attention`은 이벤트를 `needs_attention`으로 두고 해당 이슈/PR을 block한 뒤, 멈춘 노드·단계, 이벤트 종류, delivery ID, n8n 실행 링크, HAPI 세션 링크, `retry_event` 방법을 담은 댓글과 `agent:needs-attention` 라벨을 붙인다. attention 댓글·라벨은 이벤트가 `pr_review`면 리뷰 App(`haechibot[bot]`)으로 게시하고 위의 재리뷰 footer도 붙이며, 그 외 이벤트는 작성 App(`bulgasaribot[bot]`)으로 게시한다. 둘 다 적용될 때까지 backoff 후 재시도한다. 자동 재실행은 하지 않는다. 운영자는 `retry_event`(기록된 단계부터 재개) 또는 `unblock_issue`(이후 이벤트만 진행)로 푼다. 성공한 `finish`는 `agent:needs-attention`을 제거한다.

## 데이터 보존

| 데이터 | 보존 방식 |
|---|---|
| n8n 워크플로·실행 기록·credential 암호화 키 | 지원되는 영속 DB/볼륨과 독립 Secret, 보존 정책을 명시 |
| 이벤트·이슈 매핑·전송 상태 | 영속 저장소, 재시작 후 이어짐 |
| HAPI 세션·메시지 | Hub SQLite와 WAL을 고려한 일관된 백업 |
| Codex 네이티브 기록·설정 | 영속 `CODEX_HOME` |
| Claude 네이티브 기록·설정 | 영속 하네스 사용자 디렉터리 |
| 소스·worktree·작업 산출물 | Runner 영속 볼륨 |

HAPI `v0.30.7`은 agent 메시지 내부의 65,536자 초과 문자열을 저장 전에 축약한다. Hub DB만으로 네이티브 기록 보존을 대체하지 않는다. UI 삭제·워크플로 정리·Pod 재생성 때문에 하네스 기록이 함께 삭제되지 않도록 수명주기를 분리한다. 백업에 포함된 자격증명은 일반 조회 경로로 노출하지 않는다.

## 배포·전환 제약

- 이미지는 검증한 버전과 digest로 고정한다. Hub·Runner·CLI의 프로토콜 호환성을 확인한다.
- 사설 UI는 기존 내부 HTTPS Gateway 패턴을 재사용한다. 공개 webhook 경로만 분리한다. HAPI/n8n 인증을 생략하는 fallback을 만들지 않는다.
- 기존 전용 GitHub App의 설치 범위를 임의로 확장하지 않는다. 추가 운영 레포는 사용자 지정과 설치 권한 확인 후 연결한다.
- 새 컨테이너별 tier와 자원 수치를 명시하고 14일 CPU/working-set 기록 및 클러스터 메모리 요청 비율을 확인한다. 이력이 없는 신규 서비스는 수치를 추측하지 않고 초기 측정·배포 기준을 사용자와 확정한다.
- 전환 전 미처리 작업을 확인하고, 단일 GitHub App webhook을 새 endpoint와 secret으로 변경한 뒤 실제 전달을 검증한다. 과거 Archon 대화의 HAPI 이전이나 legacy 댓글 전달 기능은 구현하지 않는다.
- 전환 검증 후 Archon 전용 리소스와 PVC 데이터를 삭제한다. 삭제 뒤 과거 Archon 세션을 재개할 수 없다는 결과를 사용자에게 고지했다. GitHub App과 SSM 인증 원본은 새 시스템의 공유 의존성이므로 유지하며, 삭제 전 새 namespace에서 독립적인 토큰 발급을 확인한다.

### 관리자 계정

n8n 관리자 이메일은 사용자 지정 `bhyoo@bhyoo.com`이다. 비밀번호는 암호학적으로 안전한 난수로 생성하여 Kubernetes Secret에 보관한다. 비밀번호·HAPI 접속 토큰·GitHub 자격증명은 채팅, 로그, 저장소, 이미지에 출력하거나 포함하지 않는다. 재시작 때 비밀번호를 재생성하거나 기존 계정을 임의로 초기화하지 않는다. 최종 운영 안내에는 로그인 주소와 Secret의 namespace·이름·키만 기록한다.

GitHub App 이름은 `bulgasaribot`(작성)·`haechibot`(리뷰)이지만 인증 인프라 식별자는 바꾸지 않는다. Terraform Cloud 변수 `github_app_private_key_ironeater`/`github_app_private_key_ironeater_reviewer`, SSM `/homelab/cluster/backbone/github-app/ironeater/private-key`와 `…/ironeater-reviewer/private-key`, 연결된 Secret·ExternalSecret 이름은 git-crypt로 잠긴 Terraform apply가 필요하므로 예전 `ironeater*` 이름을 유지한다.

### 승인된 초기 자원 예외

신규 n8n·HAPI·issue-agent namespace의 14일 working-set 쿼리는 빈 결과였다. 사용자는 14일 이력 없이 아래 초기 측정용 자원을 적용하는 예외를 명시적으로 승인했다. 이 수치는 14일 관측 기반 최종 산정값이 아니다.

| 컨테이너 | Tier | CPU 요청 | 메모리 요청 | 메모리 제한 |
|---|---|---|---|---|
| n8n | 3 | 100m | 512Mi | 2Gi |
| HAPI Hub | 3 | 100m | 256Mi | 1Gi |
| 연결 계층 | 3 | 25m | 64Mi | 256Mi |
| Codex Runner | 4 | 1 | 1Gi | 4Gi |

모든 CPU 제한은 생략한다. 자동 구현은 한 번에 한 건 실행하며 여러 독립 세션의 관찰은 허용한다. 측정 시 클러스터 allocatable 메모리 70,011,109,376 bytes 대비 요청 합계 45,570,306,048 bytes(65.09%)였다. 위 요청 1,856Mi 추가 시 약 67.9%다. 배포 직전에 실제 스케줄링 예산을 재계산한다. 추가 컨테이너·DB가 필요하면 이 예산에 숨겨 넣지 않고 별도로 검토한다.

배포 직전 재계산에서는 다른 workload가 증가하여 nonterminal Pod의 일반·init·restartable sidecar 및 overhead를 반영한 메모리 요청이 51.189GiB / 65.200GiB = 78.51%였다. 새 구성 포함 예상치는 81.29%다. 사용자는 이 수치를 안내받고 **이번 병행 배포에 한시적인 75% 상한 초과 예외**를 명시적으로 승인했다. 기존 CI나 서비스를 임의로 축소하지 않는다. 평상시 자원 정책이 변경된 것은 아니다.

v2는 Runner Pod에 publisher 사이드카를 추가했다. manifest의 값은 CPU 요청 10m, 메모리 요청 64Mi, 메모리 제한 256Mi이며 CPU 제한은 없다. 위 표의 승인 수치에는 포함되지 않은 추가분이다.

## 구현 체크리스트

- [x] 기존 n8n 유무, GitHub App, provider, 이미지 빌드, 저장소·Gateway·metrics 경로 조사
- [x] 연결 애플리케이션 코드의 구체적 파일·동작 승인
- [x] 추가 레포 대상과 자동 분류/승인/구현 정책 확정
- [x] 공통 Issue Agent 지침·스킬·저장소 등록부 구현
- [x] HAPI Hub·Runner·하네스 ARM64 이미지와 digest 고정
- [x] HAPI 영속 볼륨·인증·provider·내부 HTTPS 구성
- [x] n8n 영속 배포·인증·워크플로 가져오기/갱신 경로 구현
- [x] webhook 수신·검증·중복 방지·영속 상태 구현
- [x] n8n 중복 검사·분류·질문·승인·구현·PR 전달 흐름 구현
- [x] 이슈별 worktree·세션 생성·후속 댓글·결과 보고 연결
- [x] 기록 보존·외부 조회·백업·삭제 방지 운영 경로 구현
- [x] 검증 후 새 webhook으로 전환하고, 기존 Archon은 사용자 지시로 완전히 삭제했다. 기존 이슈 대화의 자동 이전·legacy forwarding은 하지 않는다.

### v2 구현

- [x] 에이전트 컨테이너를 읽기 전용 설치 토큰(`issue-agent-github-read`)으로 교체하고, push 토큰(`issue-agent-github-push`)은 publisher 사이드카에만, issues/pull_requests/contents write 토큰(`issue-agent-github-token`)은 bridge에만 마운트
- [x] publisher 사이드카(`/checkout`, `/push`, bearer `issue-agent-publisher`)와 Service `issue-agent-publisher` 구현
- [x] 저장소 등록부를 `defaults` + override로 바꾸고 설치된 모든 저장소 수용, 기본 브랜치는 payload, checkout은 필요 시 clone. `ISSUE_AGENT_REPOSITORIES`와 등록부 라벨 매핑 제거
- [x] bridge 모드별 결과 스키마(TriageResult/ImplementResult/ReviewResult)와 `(delivery_id, mode)` 턴, 라벨 카탈로그, `github.pr_context`·`github.review`·`git.push`·`github.pr_upsert`·`fail_execution` op 구현. `github.search` 제거. (이후 `github.pr_context`는 에이전트 직접 읽기로 대체)
- [x] n8n `IssueAgentMain01`을 triage → implement / followup / review 흐름으로 재작성. n8n 모델 분류 호출·중복 검색 노드·`issue-agent-n8n-model` Secret 제거
- [x] 오류 워크플로 `IssueAgentError01`과 attention 댓글·`agent:needs-attention` 라벨(전달될 때까지 재시도) 구현, bootstrap이 두 워크플로를 동기화
- [x] 전역 `AGENTS.md`와 스킬을 결과 필드 기반으로 수정하고 `/etc/codex/skills`에 설치
- [x] v2 이미지·manifest 배포 후 네 Deployment Ready, publisher `/healthz`, 세 GitHub 토큰 Secret 동기화 확인

## 수용 기준과 검증 기록

각 항목은 실행한 명령/시나리오, 대상 버전, 관찰 결과를 아래에 기록한 후 체크한다. 소스 조사나 단위 테스트만으로 종단 검증을 대체하지 않는다.

- [x] 서로 다른 두 이슈가 별도 세션·worktree로 생성되어 웹 목록에 각각 표시된다. #869(`00c0a41f…`, `hapi-issue-869`, PR #870)와 #873(`5f4f920a…`, `hapi-issue-873`, PR #874)의 독립 카드·경로·실제 결과를 브라우저에서 확인했다.
- [x] 서로 다른 두 저장소의 같은 이슈 번호가 충돌하지 않는다. 임시 로컬 저장소 owner-a/qa-repo와 owner-b/qa-repo의 `issue-1`에서 실제 native worktree와 파일 내용 분리를 검증했다.
- [x] 자동화 실행 중 웹 클라이언트 두 개를 연결하고 하나를 닫아도 남은 클라이언트와 에이전트 실행이 유지된다. #869 후속 작업의 실제 도구 실행과 PR #870 갱신 결과를 남은 탭에서 확인했다. 별도 SSE 동시 구독도 두 연결 모두 성공했다.
- [x] UI에서 승인·거절·후속 메시지·중단을 실제 실행에 반영한다. Codex Steer는 실행 중인 60초 대기 명령의 45.3초 시점에 queued message의 Steer 버튼을 눌러 검증했다. `Steered` 표시와 `Sleep canceled. HAPI_STEER_QA_20260926` 응답을 확인했다.
- [x] 공통 지침과 레포별 지침을 실제 작업이 읽고, 설치한 스킬을 실제로 사용한다. `qa-native-20260926` 세션의 실제 Codex 도구 호출과 응답에서 세 경로와 적용 규칙을 확인했다.
- [x] 의미적 중복 이슈와 webhook 중복 전달이 각각 의도한 방식으로 처리된다. #871은 표현이 다른 #869의 중복으로 판정해 기존 `duplicate` 라벨과 원본 이슈 안내만 남기고 세션/PR을 만들지 않았다. 동일 delivery 및 동일 이벤트의 별도 delivery ID도 새 실행 없이 거절됐다.
- [x] 기존 라벨 매핑만 적용하며 정보 부족·승인 필요 상황에서 임의 구현하지 않는다. #875는 대상 파일과 내용이 빠진 요청에 질문 두 개와 기존 `question` 라벨만 남겼고 세션/PR을 만들지 않았다. #872의 비실행 요청은 `unclear`로 보고하고 구현하지 않았다.
- [x] GitHub 이슈의 실제 수정·검증·PR 생성·후속 댓글 반영까지 수행한다. #869와 Draft PR #870에서 재시작 전 생성과 재시작 후 동일 세션의 후속 커밋·결과 댓글을 확인했다. webhook 입력은 명시적으로 구성한 서명 synthetic fixture이며 GitHub 실제 전송 경로 검증은 별도로 기록한다. 자동 merge하지 않는다.
- [x] Hub/Runner/연결 계층 재시작 후 논리 세션·worktree·기록을 유지한다. 네 Deployment를 모두 재시작한 뒤 로컬 A/B 세션의 기존 HAPI/Codex ID와 JSONL 파일, nonce를 유지하며 후속 실제 명령을 실행했다. 브리지의 완료 이벤트와 #869 매핑도 유지됐다. 진행 중 작업의 crash 복구는 이 idle-restart 시나리오의 증거에 포함하지 않는다.
- [x] 외부 읽기 전용 CLI가 Hub 메시지와 네이티브 하네스 기록을 조회한다. `operations/issue-agent-records issue isac322/cc-lb 869`는 Hub 세션 1개(46개 메시지), Codex 기록 1개, n8n 실행 2개의 연계 bundle을 생성했다. archive 후 A/B 네이티브 기록의 재조회와 동일 해시도 검증했다.
- [x] 커스텀 provider의 실제 모델 실행과 GitHub 토큰 갱신이 성공한다. 실제 Codex 응답을 확인했고 `issue-agent-github-token`의 배포 이후 갱신(`2026-09-25T16:53:32Z`, `SecretSynced=True`)을 확인했다.
- [x] 배포 후 Ready, 스케줄링, OOM, 클러스터 자원 예산을 확인한다. 최종 네 Deployment 1/1 Ready, 새 Pod 재시작 0, 전체 노드 6개 Ready, Pending 0. non-terminal Pod 105개의 유효 요청(일반/init/sidecar/overhead 포함)은 메모리 28.89/65.20GiB=44.31%, CPU 9.95/36=27.65%다.
- [x] webhook은 새 시스템으로만 전달되며 Archon 전용 리소스·코드·PVC 데이터를 제거했다. 새 시스템의 기록 보존은 유지한다.

### v2 수용 기준

각 항목은 당시 허용 목록 사용자의 실제 GitHub 이벤트로 실행하고, 이슈/PR 번호·delivery ID·n8n 실행 ID·관찰 결과를 함께 기록한 뒤 체크한다.

- [x] triage 결과를 n8n이 적용한다: #887(delivery `768d455a…`, n8n 실행 12)에서 에이전트가 TriageResult만 반환했고, `bug`·`repro:reproduced`·`triage:root-cause-identified`·`triage:fix-direction-decided` 라벨과 분석 댓글이 `github.labels`·`github.comment`로 게시됐다. Runner 컨테이너에서 `gh api -X POST …/comments`와 `git push --dry-run`은 모두 403이다.
- [x] 구현 PR이 publisher로 만들어진다: #887의 `next_action: implement`에서 에이전트는 로컬 커밋만 했고, n8n이 publisher로 `hapi-issue-887`을 push한 뒤 일반 PR #888을 열고 이슈에 PR 링크를 남겼다. 후속 댓글(delivery `74d2ce60…`)은 ADR 4개 파일의 링크를 같은 PR에 추가(`e53b11e`)하고 PR 제목·본문을 갱신했다. 이 과정에서 push 직후 PR head 반영 지연으로 한 번 멈췄고, `pr_upsert`가 branch ref를 확인한 뒤 PR head 반영을 기다리도록 고친 다음 `retry_event`로 완료했다.
- [x] PR 리뷰가 게시된다: bot이 연 #888은 `pull_request.opened`로 리뷰가 시작돼 `COMMENT`와 `**Verdict: APPROVE**` 본문으로 제출됐다. 사용자 명의 QA PR #889에는 실제 `CHANGES_REQUESTED`와 128행 인라인 지적이 head `b24e8aa`에 제출됐다.
- [x] 재리뷰 요청이 스레드 답글과 새 리뷰를 만든다: #889에서 수정 push, 제목·본문 변경, 사용자 스레드 답글 뒤 `@ironeater review`를 달자, 봇이 기존 스레드에 답글을 달고 resolve했으며 새 head `ab5bc4d`에 `Previous findings`의 Closed 절을 담은 `APPROVED` 리뷰를 제출했다. 세션 메시지에 수정된 제목·본문, 사용자 답글, 기존 스레드 ID가 들어 있음을 확인했다. 첫 시도는 `resolveReviewThread` 권한 부족으로 멈췄고, bridge 토큰에 contents write를 추가한 뒤 `retry_event`로 완료했다.
- [x] 오류가 알려진다: 실제 실패 세 건(#889 `Review submitted?` 권한 오류, #889 실행 중 HAPI abort 후 `Turn state (review)`의 결과 없음, #887 `Pull request upserted?`)에서 노드·delivery·n8n 실행 링크·HAPI 세션 링크·재시도 방법을 담은 attention 댓글과 `agent:needs-attention` 라벨이 붙었고, `retry_event` 뒤 성공한 이벤트는 라벨이 제거됐다. n8n 오류 워크플로 `IssueAgentError01`은 알 수 없는 delivery로 실패시킨 실행에서 실제로 기동해 bridge `fail_execution`을 호출함을 확인했다(`unknown_execution` 응답). 실제 이벤트의 실행이 비정상 종료되는 경우의 댓글·라벨은 단위 테스트로만 확인했다.
- [x] attention 알림은 이벤트당 하나다: #887에서 n8n `fail` 요청 스레드와 dispatcher의 재시도 tick이 같은 알림을 동시에 보내 같은 marker 댓글이 1초 간격으로 두 번 게시됐다(중복 하나는 삭제). 알림 전송을 delivery별로 직렬화하고, park할 때 재시도 시각을 미래로 잡으며, marker 확인과 댓글 POST를 한 잠금 안에서 하도록 고쳤다. 동시 경로를 재현하는 테스트는 수정 전 `2 != 1`로 실패하고 수정 후 통과한다.

### 리뷰 App 분리와 merge 강제 수용 기준

- [x] 리뷰 App `ironeater-reviewer`(App ID `5118831`, installation `166063086`)가 flareway·krema·cc-lb에 설치되고, 키가 TFC → SSM → ESO(`issue-agent-github-review`)로 bridge에 전달된다. JWT로 App 권한(contents/pull_requests/statuses write, issues/metadata read)과 설치 저장소 세 개를 확인했고, ExternalSecret 두 개가 `SecretSynced`다.
- [x] ironeater가 연 PR에 리뷰 App이 실제 `APPROVED` 리뷰와 `issue-agent/review=success` 상태를 남기고 merge가 가능해진다: krema#48(README 배경 스타일 불일치)을 triage·구현한 ironeater PR krema#49에 `ironeater-reviewer[bot]`이 head `0e3fff4`로 `APPROVED`와 `success` 상태를 남겼고 GraphQL `mergeable=MERGEABLE`이다.
- [x] 변경 요청이면 `CHANGES_REQUESTED`와 `failure` 상태가 남고 ruleset이 merge를 막는다: 사용자 QA PR krema#50에 inline 지적과 `CHANGES_REQUESTED`, `failure` 상태가 남았고 `mergeStateStatus=BLOCKED`였다(PR은 닫고 브랜치 삭제). 두 저장소의 활성 규칙은 `pull_request`와 `required_status_checks: issue-agent/review@5118831`이다.
- [x] triage 질문이 댓글에 그대로 없어도 거절하지 않고 `## Questions` 절로 덧붙인다: 거절돼 멈췄던 cc-lb#891을 `retry_event`로 다시 돌리자 `questioned`로 끝났고, 게시된 댓글 끝에 `## Questions` 절이 붙었으며 attention 라벨이 제거됐다.
- [x] 턴 도중 세션이 죽으면(runner eviction 등) `lost`로 판정하고 새 localId로 재전송한다(cc-lb#890 실패 원인: 2Gi `/tmp` 초과로 runner eviction). 재전송이 거절돼도 새 localId를 유지한다. 단위 테스트로만 확인했다. 빌드 산출물은 `/tmp`가 아닌 worktree 기본 위치에 두도록 지침을 바꿨다.
- [x] 멈춘 리뷰가 있는 PR에 새 리뷰 요청이 오면 멈춘 리뷰를 `superseded`로 끝내고 PR 차단을 푼다. cc-lb#890에서 `@ironeater review` 댓글이 차단 때문에 `accepted`에 머문 것을 발견해 고쳤다(단위 테스트). 이미 쌓였던 요청은 `unblock_issue`로 풀었고, `ironeater-reviewer[bot]`이 head `3e483a4`에 `CHANGES_REQUESTED`를 남겼다.

### 이름 변경과 전체 PR 리뷰 수용 기준

- [x] 설치된 저장소의 Draft가 아닌 모든 PR이 작성자·sender와 무관하게 자동 리뷰된다. dependabot이나 외부 기여자 등 당시 허용 목록·bot이 아닌 작성자의 PR이 `pull_request` `opened`/`reopened`/`ready_for_review`에서 `pr_review`로 분류되고 리뷰가 게시된다. Draft는 리뷰하지 않는다. QA: 허용 목록 밖의 Bot 작성자(`haechibot[bot]`, 설치 토큰으로 직접 연 QA PR krema#51)의 PR이 이전 코드라면 `bot_sender`로 버려졌을 텐데 자동으로 리뷰됐고, 리뷰 본문이 footer로 끝났다(PR은 닫고 브랜치 삭제).
- [x] 재리뷰는 PR 작성자 또는 등록부 허용 목록의 `User` sender 댓글 `@haechibot review`(본문 시작, 앞 공백·대소문자 무시)로만 시작된다. 그 외 사용자의 동일 댓글과 `@bulgasaribot review`는 리뷰를 시작하지 않는다. QA: krema#51에서 `@bulgasaribot review`는 `pull_request_comment_ignored`, `@haechibot review`는 `pr_review: queued` 후 재리뷰가 게시됐다. PR 작성자 경로와 허용 목록 밖 사용자 거절은 단위 테스트로 확인했다. 등록부 허용 목록은 트리거 규칙 v3에서 폐지되고 저장소 collaborator·owner 규칙으로 대체됐다.
- [x] `pr_review` 이벤트가 park되면 리뷰 App(`haechibot[bot]`)이 attention 댓글과 `agent:needs-attention` 라벨을 게시하고, 댓글 끝에는 bridge가 붙이는 재리뷰 footer 블록이 있다. 리뷰 본문도 같은 footer로 끝나며 에이전트 결과의 `body`에는 footer가 없다. QA: krema#51 재리뷰 턴을 HAPI abort로 멈추자 `haechibot[bot]`이 footer가 붙은 attention 댓글과 라벨을 게시했고, footer대로 `@haechibot review`를 달자 멈춘 이벤트는 `superseded`로 끝나고 새 리뷰가 게시되며 라벨이 제거됐다.
- [x] 두 GitHub App이 `bulgasaribot`과 `haechibot`으로 이름이 바뀌었고, 각각 직접 그린 한국 캐릭터 브랜드풍 마스코트 로고가 설정됐다(불가사리: 회색 곰 머리·코끼리 코·쇠 가시, 겨자색 배경 / 해치: 곱슬 갈기·외뿔·방울, 청록 배경). 둘 다 손으로 쓴 SVG를 렌더링한 원본이라 출처 표기 의무가 없다. App ID·installation·bot user ID와 infra 식별자(TFC 변수, SSM 경로, Secret 이름)는 바뀌지 않았다. `GET /user/333478113`과 `/user/335401592`가 각각 `bulgasaribot[bot]`, `haechibot[bot]`과 App 로고 아바타(`avatars.githubusercontent.com/in/<app id>`)를 반환한다. `bulgasari`와 `haechi`는 이미 GitHub 사용자 이름이라 App 이름에 `bot`을 붙였다.

### 트리거 규칙 v3 수용 기준

- [ ] 등록부와 bridge 설정에 사용자 목록이 없고, `defaults`는 agent, model, permission mode, machine만 가진다.
- [ ] 신뢰 판정은 collaborator 권한 API의 `admin`/`write`만 신뢰하고, 404는 비신뢰다. 결과는 SQLite에 600초 캐시되며, 조회 실패면 HTTP 503 `permission_unavailable`로 응답하고 이벤트를 저장하지 않는다.
- [ ] 비신뢰 사용자의 새 이슈는 전체 저장소 합산 1시간(rolling)에 10개까지 `issue_opened`로 받고, 11번째부터 `rate_limited`로 거절한다. 신뢰 사용자의 이슈는 한도와 무관하게 받는다.
- [ ] `agent:open-discussion` 라벨이 있는 이슈에는 누구의 댓글이든 멘션 없이 에이전트가 반응한다.
- [ ] 라벨이 없는 이슈에서는 `@bulgasaribot` 멘션이 있는 신뢰 사용자 댓글만 받는다. 멘션이 없으면 `issue_comment_ignored`, 비신뢰 사용자의 멘션은 `actor_not_allowed`다. 에이전트가 처음 보는 이슈의 댓글도 같은 규칙을 따른다.
- [ ] 재리뷰 `@haechibot review`는 PR 작성자 또는 저장소 collaborator·owner의 댓글로만 시작된다.
- [ ] 구현 단계 이슈의 제목·본문 수정(라벨이 있거나 신뢰 사용자)은 `issue_edited` followup을 실행한다. 구현 단계가 아니거나 제목·본문 외 수정이면 `edit_ignored`다.
- [ ] followup은 이슈 요구사항과 PR을 비교해 PR 커밋과 제목·본문을 고치고, merge·close된 PR이면 기본 브랜치를 merge한 뒤 새 PR을 연다. 이미 충족하면 `no_change` 댓글, 모호하면 `needs_info`다.
- [ ] 공개 토론을 쓰는 저장소마다 maintainer가 `agent:open-discussion` 라벨을 만들었다.

### GitHub 읽기 에이전트 이관 수용 기준

- [ ] 에이전트가 읽기 전용 설치 토큰으로 `gh`(REST·`gh api graphql`)를 직접 실행해 이슈·댓글·PR·리뷰·스레드·연결 이슈를 읽는다. 세션 메시지에는 대상 번호와 트리거·결과 맥락만 들어가고 GitHub 본문은 들어가지 않는다.
- [ ] bridge의 `github.issue`·`github.pr_context` op와 그 전용 헬퍼가 제거됐고, `op_begin` 응답이 `bot_login`·`reviewer_login`을 반환한다.
- [ ] n8n `IssueAgentMain01`에서 `Load issue`·`Issue loaded?`·`Load PR context`·`PR context loaded?` 노드가 제거됐고, `Route by mode`의 triage·followup 출력은 `Issue step`으로, review 출력은 `Prepare review step`으로 직접 연결된다. Prepare 노드는 제거된 노드를 참조하지 않는다.
- [ ] GitHub 쓰기 경로(bridge `github.comment`·`github.labels`·`github.review`·`git.push`·`github.pr_upsert`와 attention 알림)는 바뀌지 않았다.

### 현재 실행 증거

- 관리자 Secret `issue-agent/issue-agent-n8n-owner` 생성 및 ESO Ready 확인. 이메일 일치, 무작위 비밀번호 복잡도, bcrypt 해시 형식 검증. 평문 미출력. `https://n8n.bhyoo.com/rest/login`에 저장된 자격증명으로 실제 로그인하여 HTTP 200, 이메일 `bhyoo@bhyoo.com`, 역할 `global:owner`를 확인했다.
- HAPI ARM64 이미지 빌드·push 완료: `ghcr.io/isac322/issue-agent-hapi:0.30.7-20260926@sha256:936f5569c8c143fef9250785c339657e1c443f2be4aaa79771c8c7e96ab53b6e`. 컨테이너에서 `hapi --version` → `0.30.7`.
- Runner ARM64 이미지 빌드·push 완료. 초기 이미지의 비루트 지침 디렉터리 접근 오류를 수정한 현재 버전: `ghcr.io/isac322/issue-agent-runner:0.30.7-codex0.157.0-20260926-r2@sha256:359285ea165f65ff826b4f396a99237ed3baa5d63456fb806cfe3af73af4345c`. 실제 컨테이너에서 HAPI `0.30.7`, Codex `0.157.0`, gh `2.101.0`, rustup `1.29.1` 실행 및 비루트 프로필·스킬 접근 확인. Rust compiler toolchain은 아직 설치되지 않은 상태.
- 리뷰에서 발견한 불확실한 n8n 전달의 전역 동시성, HAPI invocation 순서, tool/reasoning 결과 오인 문제 수정 후 bridge 회귀 테스트 **33개 통과**. 모의 외부 서버를 사용한 테스트이며 실제 HAPI/n8n 종단 증거를 대체하지 않는다.
- 실제 파일로 Kustomize 렌더링 및 Kubernetes server-side dry-run 성공. 네 Deployment의 승인된 자원·CPU 제한 없음·이미지 digest 고정을 확인.
- `issue-agent` namespace의 네 Deployment가 Ready이며 HAPI 사설 HTTPS `/health`, 인증 교환, Runner 등록과 Codex availability를 확인했다. GitHub App webhook을 새 수신기로 전환하고 Archon 전용 코드/정의 19개, namespace, 20Gi+1Gi PVC, 두 backing zvol과 두 DNS 이름을 제거했다. Kubernetes NotFound와 rock5bp ZFS 조회, DNS 조회로 삭제 결과를 확인했다.
- n8n 실제 인증 API로 `IssueAgentMain01`의 51개 노드, `active=true`, `activeVersionId=versionId`를 확인했다. 실제 브라우저에서 Owner 계정과 Published 워크플로 캔버스도 확인했다. 여섯 QA 이벤트가 `implemented/replied/duplicate/unclear/implemented/questioned`로 완료됐다.
- HAPI 브라우저 두 탭의 동시 세션 관찰, 단일 명령 승인, pending 명령 Abort, 실행 중 Codex Steer를 실제 UI에서 확인했다. 부모 프로세스의 동시 인증 SSE 구독 두 개도 각각 HTTP 200과 `connection-changed`를 수신했다. 최초 175초 SSE 관찰에서 최종 응답을 수신하지 못했으므로 이를 최종 응답 수신 증거로 사용하지 않는다.
- GitHub QA #869는 bot 작성 실제 이슈와 서명된 synthetic webhook fixture를 사용했다. fixture의 sender/issue.user를 당시 허용 목록 사용자로 구성했으며 실제 GitHub delivery로 간주하지 않는다. n8n execution 1이 완료되고 실제 Draft PR #870(`master ← hapi-issue-869`)에 QA Markdown 한 파일을 생성한 뒤 브리지가 이슈에 결과를 보고했다. 동일 delivery와 동일 이벤트의 새 delivery ID 모두 중복으로 거절되고 새 실행은 생성되지 않았다.
- Hub·Runner·bridge·n8n의 동시 재시작 후 모두 rollout 성공. 새 Pod 네 개가 Running/Ready, 재시작 횟수 0, 이전 OOM 종료 없음이었다. 로컬 A/B는 명시적 resume 후 같은 native ID/JSONL에서 기존 nonce를 기억하고 후속 읽기 명령을 수행했다. 재시작 직후 idle 세션이 inactive로 보이는 것은 자동 재개가 아닌 명시적 resume 방식이다.
- `operations/issue-agent-backup create`와 `verify`를 실제 실행해 4개 component archive의 체크섬과 SQLite DB 9개의 `integrity_check`를 검증했다. 재시작이나 신규 binary 없이 온라인 snapshot을 사용한다. component 간 원자성은 보장하지 않는다. 원본 DB backup은 인증 자료가 포함될 수 있는 **비공개 운영자 자료**이며 외부 transcript export와 다르다. 파일 0600/디렉터리 0700으로 보호한다. restore 절차는 문서화했으며 빈 클러스터에 전체 복원하는 재해복구 실험은 수행하지 않았다.
- 로컬 A/B QA worktree는 export 검증 후 제거했다. Hub 메시지 23개씩과 `archived_sessions`의 원본 Codex JSONL은 보존했다. 운영 #869 worktree와 GitHub 기록은 이 정리에서 변경하지 않았다.
- GitHub App `5063990`의 webhook URL과 secret을 새 수신기로 전환했다. 실제 GitHub 재전달 ID `3844760011376959488`, GUID `97969f60-b902-11f1-8a2a-4e579a1bc4e6`이 `2026-09-25T17:04:56Z` 새 endpoint에서 HTTP 202를 받았다. bridge는 새 서명을 검증한 뒤 bot 작성 #871의 이벤트를 `bot_sender`로 제외했다. 이는 실제 전송·서명 검증 증거이며 신뢰 사용자의 실제 이슈 생성부터 이어진 end-to-end 실행 증거는 아니다. App identity/권한/설치 범위와 공유 SSM/TFC 인증 원본은 변경하지 않았다.
- 최종 QA export 후 `qa-native-20260926`, #869, #873 세션을 archive하고 깨끗한 임시 worktree 세 개와 로컬 QA branch를 제거했다. Hub 메시지 63/49/28개와 native JSONL, bridge/n8n 실행 기록은 보존했다. #869와 #873의 최종 bundle에서 Hub↔Codex ID와 n8n 실행(1·2 및 5)의 연결을 검증했다.
- 종료 점검 중 rock5bp가 재부팅되어 일시적으로 NotReady가 됐다. 호스트 journal의 `bhyoo /usr/sbin/reboot` 실행은 `17:10:39Z`이며 실행 세션은 확인되지 않았다. 이 작업의 제거 담당 transcript에는 재부팅 명령이 없었다. `17:16:30Z` Ready 복귀 뒤 Pending 0과 네 서비스 Ready를 확인했다. Runner의 macmini 이동 후에도 native 기록 해시가 유지됐다. 별도의 노드 복구·설정 변경은 수행하지 않았다.
- 최종 n8n 재가져오기 후 published workflow `fd9604c3-f292-43a2-8941-69d935b4489c`의 51개 노드·연결·자격증명 참조가 source와 일치했다. 배포된 `Compose report` 코드를 실제 실행하여 후속 댓글은 `Updated pull request`/`replied`, 새 이슈는 `Opened pull request`/`implemented`를 반환함을 확인했다.
- QA 정리 중 담당 agent가 `isac322` 계정으로 종료 댓글을 달아 의도하지 않은 실제 후속 이벤트 다섯 개(seq 7–11)를 만들었다. #873에는 native 메시지가 전달됐으나 도구 호출 없이 `no_change`로 응답했고 새 코드·PR·branch 변경은 없었다. 부모가 HAPI abort를 실행하고 기존 operator API로 남은 이벤트를 terminal 처리했다. 최초 여섯 QA 이벤트는 변경하지 않았으며 전체 11개 중 non-terminal은 0이다. 종료한 QA #869·#873·#875만 격리 상태로 유지한다. 정리 시에는 종료 댓글 없이 close하거나 bot 자격증명을 사용해야 한다.
- `no_change` 응답에 `pr_number`를 포함하면 현재 계약 검증이 거절한다. issue block은 이미 시작한 dispatch를 취소하지 않는다. 이번 QA 사고는 기존 abort/fail API로 처리했으며 이 두 런타임 동작을 임의로 변경하지 않았다.
- QA 이슈 #869·#871·#872·#873·#875와 Draft PR #870·#874는 종료했고 머지하지 않았다. 원격 QA branch 두 개와 모든 임시 worktree/빈 디렉터리를 제거했다. 최종 Hub 기록은 manual QA 63개, #869 49개, #873 32개이며 native JSONL과 전체 이벤트 기록을 보존했다. 별도 검증용 `/tmp` export·backup 복사본은 검증 후 제거했다.
- homelab 변경은 커밋·푸시하지 않았다. 실행 중인 구성은 직접 적용한 상태다. 공유 SSM 인증 원본의 Terraform wiring도 로컬 변경에 포함되므로, 이를 포함하지 않은 이전 checkout에서 Terraform apply하면 인증 원본을 다시 삭제할 위험이 있다. 향후 커밋할 때 공유 인증 wiring과 새 Issue Agent 정의를 함께 보존해야 한다.

## 핵심 upstream 근거

- HAPI client REST: https://github.com/tiann/hapi/blob/v0.30.7/docs/api/client-contract/rest.md
- HAPI SSE: https://github.com/tiann/hapi/blob/v0.30.7/docs/api/client-contract/sse.md
- Codex 공유 세션: https://github.com/tiann/hapi/blob/v0.30.7/docs/guide/codex-shared-sessions.md
- HAPI 기록 codec: https://github.com/tiann/hapi/blob/v0.30.7/hub/src/store/contentCodec.ts
- Codex 지침 계층: https://developers.openai.com/codex/guides/agents-md
