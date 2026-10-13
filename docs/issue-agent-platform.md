# n8n + HAPI Issue Agent 구현·운영 설계

## 상태와 변경 경계

이 문서는 구현 체크리스트이자 수용 기준이다. 체크되지 않은 항목은 완료·검증되지 않았다. 설계 작성만으로 배포나 검증이 완료되었다고 보고하지 않는다.

사용자가 선택한 구성은 n8n + HAPI다. 기존 Archon은 새 구성의 검증과 안전한 전환 전까지만 유지한다. 사용자의 후속 명시 지시로 **전환 후 Archon 전용 배포·도메인·ArgoCD 등록·코드·대화/worktree/상태 DB PVC와 데이터를 모두 삭제**한다. 앞선 Archon 기록 보존 결정은 폐기되었다. 실제 GitHub 이슈·PR과 새 시스템이 재사용하는 GitHub App·인증 원본은 삭제 대상이 아니다. 이 작업은 임의의 Git 커밋·푸시·PR 머지를 승인하지 않는다. 사용자는 `apps/objects/issue-agent/bridge.py`, `test_bridge.py`의 이벤트 검증·영속 상태·세션 연결·복구·결과 보고와 n8n 워크플로 구현을 명시적으로 승인했다. HAPI·n8n upstream 및 대상 레포 제품 코드의 임의 변경은 승인 범위에 포함하지 않는다.

v2는 코딩 에이전트의 GitHub 쓰기를 모두 없앴다. 에이전트는 읽기 전용 토큰으로 조사하고 구조화된 결과만 반환하며, n8n이 그 결과를 bridge op로 GitHub에 반영한다. 아래 설계·계약 절은 v2 기준이다. v1 수용 기록은 v1 동작(에이전트의 직접 push·PR 생성, n8n 모델 분류, 저장소별 라벨 매핑)에 대한 당시 증거이므로 고치지 않는다. v2 수용 항목은 `### v2 수용 기준`에 따로 둔다.

2026-10-11 리뷰 게이트·실행 경계 변경: kwin-mcp review-gap 분석(PR #90·#92–#98에서 사람의 리뷰 세션이 찾은 신호 처리·잠금·D-Bus timeout·좌표 계산·주입·SELinux 우회 결함 대부분을 haechibot이 놓쳤고, #95는 사람이 보류한 상태에서 APPROVE됐다)과 리뷰 실행 기록 감사(kwin-mcp 리뷰 실행 24회 중 17회가 PR 코드를 Runner 셸에서 직접 실행)를 근거로 리뷰 게시 신뢰성, 리뷰 판정 정책, Runner·Codex 설정, 신뢰하지 않는 코드의 실행 경계, Runner 자원을 함께 바꾼다. 사용자 결정은 다음과 같다. 리뷰 판정은 CI 결과에 의존하지 않고 봇은 lint·type·test 결과를 보고하지 않는다(U1). 모든 모드와 하위 에이전트의 reasoning effort는 `high`다(U2). 동시 실행을 제한하고 Runner 메모리를 늘린다(U3). PR이 새로 들인 취약점은 리뷰에 위치·메커니즘·수정안을 적는다(U4). 실행 경계는 E1–E4를 지금 적용하고 hub 토큰의 컨테이너 분리는 다음 단계로 미룬다(U6). 설계는 아래 각 절에 반영했고 수용 항목은 `### 리뷰 게이트·실행 경계 수용 기준(2026-10-11)`에 둔다. 체크되지 않은 항목은 아직 배포·검증되지 않았다.

2026-10-13 정체 복구 변경: krema#99 implement 턴이 `isac-issue-to-pr`의 당시 규칙대로 직렬 distro E2E를 로컬에서 돌리다 6시간 넘게 걸려 턴 예산에 걸렸다. 같은 조사에서 마감 뒤 결과 유실, 매시 정리 실패, Docker 데이터 증가, 대체된 세션 잔류, 닫을 방법이 없는 멈춘 이벤트가 함께 드러났다. 사용자 결정에 따라 e2e 같은 오래 걸리는 테스트는 CI의 일로 두고 로컬에서는 필요할 때만 돌린다(`### 리뷰·repair 반복 상한`의 로컬 CI 게이트). 그 밖에 bridge가 모드별 턴 마감을 정해 에이전트에게 알리고(`### 모드와 결과 계약`), 마감 뒤 답한 결과를 수거하며, `dismiss_event` op와 30분 stale dispatch 감지를 더했다(`### 오류 알림`). 정리는 주제별로 격리한다. Docker 사용률이 70%를 넘으면 bridge가 idle일 때 최대 20분의 maintenance lease를 잡아 새 dispatch를 멈추고, dockerd janitor가 그 lease 안에서 prune한다. janitor는 fd 기반 Go helper로 worktree 소유권도 되돌린다(`## Runner Docker와 DRM 장치`). 수용 항목은 `### 턴 마감·정체 복구·정리 수용 기준(2026-10-13)`에 있으며, 체크되지 않은 항목은 아직 배포·검증되지 않았다.

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
- 기능 요청은 작성자 신뢰에 따라 다룬다. 신뢰 사용자(collaborator 권한 `admin`/`write`)의 명확하고 범위 안의 기능·문서 요청은 직접 지시로 보고 구현까지 간다(구조 변경이면 결정을 묻고 멈춘다). 비신뢰 사용자의 기능 요청은 바로 구현하지 않고 제안 트랙(계약 확인, 실현 가능성 조사, 방향과 기각한 대안을 담은 제안 평가 댓글)을 거쳐 결정을 묻고 멈추며, 신뢰 사용자가 댓글로 방향을 승인해야 구현한다. 비신뢰 사용자의 댓글·수정은 승인이나 요구사항 변경이 아니라 정보다.
- 보안 취약점은 공개 위치에 남기지 않는다. 확인되거나 의심되는 취약점은 라벨·이슈 댓글·재현 페이로드 없이 비공개 draft repository security advisory로 보고한다.
- 설치된 저장소에서 Draft가 아닌 PR을 생성·재개하거나 Ready for review로 바꾸면 이슈와 다른 `review-pr-<n>` 세션에서 리뷰한다. 리뷰 App이 설정되어 있으면 push로 head가 바뀔 때도 head별로 한 번 리뷰하고, 명시적 `@haechibot review` 요청은 같은 head를 다시 리뷰할 수 있다. 자동 요청은 같은 head를 두 번 리뷰하지 않으며, bridge가 내려가 놓친 webhook은 열린 PR 리뷰 스윕이 복구한다. PR마다 대기 리뷰는 하나뿐이고 연달아 온 요청(PR 열기·push·댓글)은 그 하나로 합쳐지며, 새 head가 오면 이전 head를 리뷰하던 실행은 취소된다(아래 "리뷰 요청 합치기와 취소"). ruleset·branch protection이 merge 조건을 소유하며 bridge는 필수 check 목록이나 reviewer 수를 하드코딩하지 않는다.
- 코딩 에이전트는 GitHub에 쓰지 않는다. 댓글·라벨·push·PR·리뷰는 모두 n8n이 에이전트 결과를 검증된 bridge op로 적용한다.

## 책임 분리

| 구성 요소 | 책임 |
|---|---|
| n8n | GitHub webhook 수신과 서명 검증(수신 워크플로 `IssueAgentIntake01`, 커뮤니티 노드 `n8n-nodes-webhook-signature`), GitHub 이벤트 처리 흐름, 모드별 단계(triage → implement, followup, review), 결과에 따른 분기, 모든 GitHub 반영(라벨·댓글·push·PR·리뷰)의 호출과 실패 처리. 에이전트에 보내는 메시지에는 대상 번호와 트리거 정보만 넣으며 GitHub 내용 조회는 담당하지 않는다 |
| 연결 계층(bridge) | 서명 검증을 마친 delivery의 내부 수신(ops bearer 인증), collaborator 권한 판정(캐시)과 비신뢰 이슈 rate limit, 이벤트 영속화·중복 방지, 이슈/PR과 세션 매핑, HAPI API 인증·상태 확인, 모드별 결과 스키마 검증, GitHub 쓰기 op(issues/pull_requests/contents/repository_advisories write 토큰. contents write는 리뷰 스레드 resolve용이며 push에 쓰지 않고, repository_advisories write는 draft security advisory 생성용), publisher 호출, attention 알림. 에이전트용 GitHub 읽기 op는 두지 않는다 |
| publisher(Runner Pod 사이드카) | push 토큰(`issue-agent-github-push`)의 유일한 보유자. bridge 요청으로 저장소 checkout clone, `hapi-issue-<n>` branch head 조회(`/resolve`), 그 branch의 non-force push만 수행. `POST /worktree/restore {repo, worktree, branch}`는 사라진 worktree를 남은 branch(push 안 된 commit 포함) 위에 다시 만든다. 에이전트 checkout에서 git을 돌리지 않고 private mirror에서 꺼낸 tree와 linked-worktree 메타데이터 파일로 만들며, branch가 없으면 `{"restored": false, "reason": "no_branch"}`, 경로를 다른 디렉터리가 차지하면 409 `worktree_conflict`다 |
| dockerd(Runner Pod native sidecar) | runner·publisher와 같은 Pod의 Docker daemon. Unix socket만 열고 checkout·`/tmp`·Docker 데이터·native DRM 장치 두 개만 마운트한다. startup probe가 daemon 응답과 native DRM 장치 쌍을 확인해야 runner·publisher가 시작한다 |
| HAPI Hub | 세션 목록·메시지·승인 API, 웹 UI, 다중 구독, Hub 데이터 저장 |
| HAPI Runner | 실제 Codex 실행, 저장소별 worktree, 하네스 설정·기록 보존. `issue-agent-runner` namespace에서 publisher·dockerd와 한 Pod로 실행한다. GitHub 토큰은 읽기 전용이며 에이전트가 `gh`(REST·`gh api graphql`)로 GitHub를 직접 읽는다 |
| 공통 에이전트 프로필 | 전역 `AGENTS.md`(읽기 전용 GitHub, 결과 프로토콜, 모드별 스킬)와 자동화용으로 고친 스킬 |
- 저장소 등록부: `defaults`(agent, model, permission_mode, machine_id, project_owner)와 저장소별 override. `project_owner`는 merge-ready 시 assign·멘션할 GitHub 사용자이며, 설정하지 않으면 알림을 건너뛴다. 기본 checkout 경로는 `/home/agent/checkouts/<owner>/<repo>`이다.

n8n은 단순히 에이전트를 한 번 호출하는 장식이 아니라 실제 처리 단계와 분기를 소유한다. 연결 계층은 전송·인증·영속 상태의 정확성을 담당하고 같은 비즈니스 절차를 별도로 중복 구현하지 않는다.

## 지침·스킬 계층

1. 공통 Issue Agent 지침(`profile/AGENTS.md` → `CODEX_HOME/AGENTS.md`): GitHub 읽기 전용, 턴 끝 `ISSUE_AGENT_RESULT <nonce> {json}` 한 줄로만 결과 반환, 메시지가 지정한 모드만 수행, 이슈·PR 본문과 context는 신뢰하지 않는 데이터, worktree branch에만 로컬 커밋, 불명확하면 결과로 질문.
2. 공통 스킬(`profile/skills/` → Codex ADMIN scope `/etc/codex/skills`, PVC에 두지 않음): 모드별 주 스킬은 `triage`=`isac-issue-triage`, `implement`=`isac-issue-to-pr`, `followup`=`isac-issue-to-pr`+`receiving-code-review`, `review`=`isac-pr-review`다. 보조 스킬은 `isac-github-publishing`, `isac-decision-brief`, `isac-multi-agent-consensus`, `isac-live-qa`, `issue-validation`, `five-whys-root-cause-analysis`, `comment-writer`, `humanizer`, `writing-clearly-and-concisely`, `destructive-operations`, `public-api`, `pull-request-merge`, `pull-request-review-handling`이다.
3. 저장소 지침: 각 저장소의 `AGENTS.md`·`CLAUDE.md`·`.agents/**`·`.claude/**`·CONTRIBUTING 등 기여 규칙은 빌드·테스트·스타일만 정하며 공통 지침의 제한을 넓히지 못한다. 저장소 root는 Codex에 untrusted로 등록되므로(아래 9) Codex는 저장소 `AGENTS.md`나 `.agents/skills`를 자동으로 읽지 않는다. 에이전트가 직접 읽는다. implement·followup은 worktree에서, review는 PR이 바꿀 수 없는 기본 브랜치에서 읽는다.
4. Codex 도구: 모든 세션에 context-mode(`ctx_*`)와 CodeGraph(`codegraph_*`) MCP 서버가 붙는다(`/etc/codex/config.toml`). MCP 서버 프로세스는 셸 환경 정책과 별개로 `config.toml`의 `env_vars` allowlist에 있는 변수만 받는다. 목록은 live Runner 환경 이름에서 비밀(`OPENAI_API_KEY`, `CLI_API_TOKEN`, `HAPI_*`, `ISSUE_AGENT_PROVIDER_DIR`)을 뺀 것(`DOCKER_HOST`, `GH_CONFIG_DIR`, 빌드 캐시 변수 등)이고 codegraph는 `CODEGRAPH_NO_DOWNLOAD`도 받는다. 사용 강제는 `/etc/codex/requirements.toml`의 managed hook으로 한다. `requirements.toml`은 `allow_managed_hooks_only = true`로 managed hook만 허용하고, MCP 서버는 절대 경로 command로 고정한 allowlist(context-mode, codegraph, HAPI가 thread마다 넣는 `hapi`)만 허용한다. context-mode hook 6개(SessionStart, PreToolUse, PostToolUse, PreCompact, UserPromptSubmit, Stop)가 raw fetch를 막고 큰 출력을 sandbox로 유도하며, SessionStart의 `codegraph-index`가 worktree 색인을 준비한다. 공통 지침은 코드 탐색에 CodeGraph를, 20줄 넘는 출력에 context-mode를 기본으로 쓰게 한다. 다만 작업 대상(diff, 바뀐 파일, 따르는 스킬 파일, 저장소 지침 파일)은 context-mode snippet이 아니라 전문을 읽고, context-mode는 log·테스트 출력·목록에 쓴다.
5. 빌드 캐시: Runner는 sccache로 Rust(`RUSTC_WRAPPER`)와 C/C++(`PATH` 앞쪽 `cc`·`gcc`·`c++`·`g++` wrapper, CMake compiler launcher) 컴파일 결과를 home PVC의 `SCCACHE_DIR`(최대 5G)에 캐시해 worktree와 세션이 공유한다. wrapper는 sccache가 부모일 때 실제 컴파일러를 바로 실행해 이중 wrapping을 막는다.
6. 접근 제한: 에이전트 컨테이너에는 읽기 전용 설치 토큰만 마운트한다. 쓰기 토큰(bridge의 issues/pull_requests/contents/repository_advisories write, publisher의 contents write)과 publisher bearer 토큰은 에이전트 컨테이너에서 읽을 수 없다. 지침 문구를 강제적인 보안 격리로 설명하지 않는다.
7. GitHub 읽기 자격증명 경계: Runner의 `GH_CONFIG_DIR`에는 사용자 토큰이나 PAT가 아닌 rotating repository-scoped GitHub App installation token이 들어간다. `gh auth status`, `gh auth login`, `gh auth setup-git`, `gh api user`, `gh api /user`, GraphQL `viewer` 조회는 설치 토큰에 맞지 않는 사용자 identity probe이므로 인증·readiness 확인에 사용하지 않는다. 이 probe의 실패만으로 저장소 읽기 권한이 없다고 판단하지 않는다.
8. 운영 불변식과 incident lesson: readiness/auth는 실제 대상 이슈·PR·저장소 읽기(`gh issue view`, `gh pr view`, `gh api repos/{owner}/{repo}/...`)로만 확인한다. 대상 읽기는 일반 셸 또는 `ctx_execute`로 실행할 수 있다. `ctx_batch_execute`가 출력을 색인하면 `ctx_search`로 확인하며, 빈 직접 응답만으로 인증 실패로 처리하지 않는다. 대상 읽기가 401/403을 반환하거나, 대상 404 뒤 저장소 메타데이터 읽기(`gh api repos/{owner}/{repo}`)도 404일 때만 GitHub 인증·설치 접근 blocker로 보고한다. 단순 404 또는 리소스 부재는 저장소 접근을 확인하기 전까지 자격증명 실패로 바꾸지 않는다. bootstrap의 `gh auth token`은 로컬 설정 파싱일 뿐 API capability/health check가 아니다.
9. Codex 실행 설정: `/etc/codex/managed_config.toml`은 `model_reasoning_effort = "high"`, `[agents] default_subagent_reasoning_effort = "high"`·`max_threads = 2`, `shell_environment_policy`(`include_only` allowlist, 비밀·내부 변수 없음)를 둔다. Codex app-server는 thread 시작 때 cwd의 git root를 자동으로 trusted로 기록하므로, 전에는 PR이 넣은 `.codex/config.toml`(MCP 서버, hook, env, `developer_instructions`, effort)이 로드될 수 있었다. 이제 `codex-untrust` helper(`/opt/issue-agent/bin/codex-untrust`)가 `CODEX_HOME/config.toml`에 경로별 `trust_level = "untrusted"` 항목을 쓴다. bootstrap은 provider config를 `codex-untrust --install`로 같은 lock 아래 설치하고 모든 기본 클론을 등록하며, publisher `/checkout`은 매 호출마다(즉 매 spawn 전) checkout과 그 worktree를 등록한다. untrusted root에서는 프로젝트 `.codex/` 설정 계층이 꺼지고 저장소 `AGENTS.md`도 자동으로 읽히지 않는다(위 3). `include_only`는 같은 uid의 `/proc/<pid>/environ` 읽기를 막지 못하는 보조 장치다.

스킬은 원본을 자동화용으로 기계적으로만 고쳤다. 각 `SKILL.md` 머리의 adaptation 절이 바꾼 점을 적는다. 공통 규칙은 다음과 같다.

- 원본의 GitHub 쓰기 단계(라벨 부착·교체, 댓글 게시·수정, push, `gh pr create/edit`, 리뷰 게시, 스레드 답글·resolve, 리뷰 재요청, 이슈 닫기, merge)는 결과 필드로 바뀐다. 예: triage 라벨·분석 댓글 → TriageResult `labels`·`comment`, PR 제목·본문 → ImplementResult `pr`, 리뷰·inline·스레드 답글 → ReviewResult `body`·`comments`·`thread_replies`.
- 게시/초안 모드 구분이 없다. 항상 결과에 초안을 담는다.
- 채팅으로 묻고 기다리는 단계(`isac-decision-brief` 포함)는 결과의 `questions`와 초안 댓글에 질문을 넣고 `await_info`/`await_decision`/`needs_info`로 턴을 끝낸다.
- 한국어 최종 보고는 짧은 영어 `summary`가 된다. GitHub에 게시될 텍스트는 `isac-github-publishing`에 따라 영어로 쓴다.
- `pull-request-merge`는 merge를 금지하고 merge 준비 상태 보고로 바뀌었다.
- 신뢰 규칙(triage AD-01·AD-02, implement followup): 신뢰 사용자의 명확한 기능·문서 요청만 직접 지시이고, 그 밖의 기능 요청은 제안 트랙(TRI-54)으로 결정을 묻는다. 제안·구조 변경 승인과 진행 중인 PR의 요구사항 변경은 신뢰 사용자의 댓글·수정만 할 수 있다. actor의 신뢰는 메시지의 신뢰 사실(`context.actor_trusted`)로 받고, 다른 사람은 에이전트가 `gh api repos/<owner>/<repo>/collaborators/<login>/permission`으로 확인한다.
- 취약점(TRI-53, triage AD-04): 원본의 "공개 댓글·라벨 없이 GitHub Security Advisory로 옮기기 제안"은 TriageResult `security_advisory` 필드가 된다. 이때 `comment`는 `null`, 라벨 변경은 없고 `next_action`은 `none`이며, 재현 페이로드는 advisory 본문에만 둔다.

Codex의 공통 지침은 전용 `CODEX_HOME/AGENTS.md`에서 읽는다. 저장소 root를 untrusted로 두므로 Codex는 프로젝트 지침과 프로젝트 `.codex/` 설정을 자동으로 결합하지 않고, 에이전트가 저장소 지침을 명시적으로 읽는다. 전용 프로필은 개인 설정과 분리한다. 에이전트가 읽은 레포 지침은 신뢰하지 않는 입력이므로 비밀 보호나 접근 제어의 유일한 장치로 사용하지 않는다.

공통 지침·스킬은 버전 관리한다. 이슈 worktree에서의 수정은 다른 worktree에 자동 전파되지 않는다. 공통 반영은 기준 브랜치나 공통 이미지·설정 배포를 통해 수행한다.

### 리뷰 판정 정책

리뷰 규칙의 원본은 `isac-pr-review` 스킬(`SKILL.md`와 `references/`)이며 세부 규칙 ID와 문구는 스킬이 정한다. 2026-10-11 변경의 요지는 다음과 같다.

- CI 독립(U1): 판정은 CI·check 결과(성공이든 실패든)에 의존하지 않는다. CI 상태를 정확성이나 결함의 근거로 인용하지 않고, verdict 줄에서 `PR-ready`를 뺐으며, lint·type·test 결과를 리뷰 지적으로 보고하지 않는다. 리뷰어는 자기 판단에 필요하면 테스트·빌드·probe를 직접 돌릴 수 있고(아래 실행 경계와 로컬 실행 범위 안에서) 돌린 것은 자기 증거로 적는다. CI 실패는 새 commit을 요구하고 새 commit은 새 리뷰를 부른다. 이 전제를 위해 저장소 ruleset에 CI job을 required check로 넣는 일은 봇 변경이 아니며 따로 진행한다. krema의 CI job은 모두 paths filter가 있어 그대로는 required로 만들 수 없고, 항상 도는 gate job 같은 workflow 변경이 필요하다.
- 로컬 실행 범위(PRR-57, 2026-10-13): 구현 쪽 로컬 게이트와 같은 사용자 결정(e2e 같은 오래 걸리는 테스트는 CI의 일)을 리뷰에도 적용한다. 오래 걸리는 suite(e2e, GUI·Appium, multi-distro·패키지 matrix, 컨테이너 이미지 build, envtest, integration·soak)는 CI가 돌리고 리뷰어는 로컬에서 돌리지 않는다. 그 suite의 CI 결과는 판정 근거가 아니라 입력으로만 읽는다(U1). 로컬에서는 특정 claim 확인에 필요한 빠른 targeted check(단일 unit test, lint, 바뀐 모듈 하나의 빠른 build)만 돌리고, 오래 걸리는 suite로만 확인할 수 있는 claim은 `Not verified`나 challenger를 견딘 논증으로 남긴다. n8n `Prepare review step` 지시와 bridge의 review 지시가 같은 문구를 쓴다. krema#101 리뷰가 docker 이미지·배포판 패키지 build를 약 18분 돌리는 동안 runner 컨테이너가 5Gi 한도에서 두 번 OOMKilled돼 함께 돌던 리뷰 턴까지 잃었다.
- P2 blocking: PR이 들인 P2 정확성·보안 결함은 재현이나 정확한 코드 경로 논증이 있으면 blocking(REQUEST_CHANGES)이다. P3는 non-blocking이다.
- 미확인 의심(A4''): 확인도 반박도 안 된 P0–P2 의심은 file:line, 메커니즘, 구체적 trigger(입력·interleaving·상태)를 적을 수 있을 때만 후보가 되고, 가능성이 아니라 최악의 결과로 등급을 매긴다. 반박은 실행한 probe이거나, 해당 near-miss·경계를 다루는 줄을 인용하고 반례를 만들라는 독립 challenger 하위 에이전트를 견딘 코드 경로 논증이다. bulgasaribot이 연 PR에서 남은 의심은 REQUEST_CHANGES("prove or fix")로 repair 루프에 들어가고, 그 밖의 PR에서는 COMMENT다. followup의 "prove"는 의심이 사실이면 실패할 테스트나 probe를 commit하는 것이다(새 head → 새 리뷰).
- 결정 사항(A9'): 보안 정책 우회(SELinux·AppArmor·sandbox·권한, 정상 경로가 거부될 때 다른 경로로 닿는 fallback 포함)와 제품 결정은 항상 COMMENT와 decision brief다. maintainer(write 이상)의 보류(dismiss되지 않은 CHANGES_REQUESTED, 보류 요청 댓글)는 그 maintainer가 풀 때까지 APPROVE를 막고 push로 풀리지 않는다.
- lens(A6''·A16'): diff를 보고 하위 리뷰어 lens를 고른다. trigger에 걸린 lens는 생략할 수 없고 본문에 trigger와 함께 적는다. lock·thread·async·signal·subprocess·cleanup → concurrency/lifecycle, 새·바뀐 parameter·flag·schema·config key → input, 다른 언어·형식에 끼워 넣는 문자열 → injection, 좌표·크기·단위·시간 산술 → math, 바뀐 테스트 → test audit, 항상 → correctness와 docs/convention이다. 걸린 lens의 checklist가 같은 턴에서 한 번 다시 돌린 뒤에도 덮이지 않으면 COMMENT다. tooling 실패가 있어도 논증으로 checklist를 덮었으면 실패가 아니다.
- `open_items`: 에이전트 자신의 COMMENT가 결정 사항, 미확인 P0–P2 의심, 덮이지 않은 lens 때문이면 ReviewResult `open_items`에 이유를 하나씩 적는다(`### 모드와 결과 계약`의 ReviewResult와 decision 댓글).
- 취약점(U4): PR이 새로 들인 취약점(기본 브랜치와 최신 release tag·release branch에 없음)은 리뷰에 위치·메커니즘·수정안을 적고 REQUEST_CHANGES로 낸다. 이미 있던 취약점은 기존처럼 비공개 advisory 경로(PRR-19)로 보낸다. blocking 지적은 언제나 위치·메커니즘·수정안을 담는다.
- 그 밖의 스킬 규칙: 모든 head를 merge-base 대비 전체 리뷰하고 수정 commit은 hazard(잠금 안의 blocking I/O와 timeout, 기록과 실행 순서, 취소·signal 창, cleanup)를 따로 본다. 새 입력의 모든 진입 경로에 적대적 값과 주입을 probe하고, 새 type 오류 억제를 지적하며, 테스트가 주장한 동작을 실제로 검사하는지와 PR 본문의 동작 주장을 확인한다. 중단된 턴을 이어받으면 head와 환경을 다시 확인하고 증거를 다시 모은다.
- 프로젝트별 규칙: 한 저장소에만 해당하는 규칙은 `profile/skills/isac-pr-review/references/projects/<owner>__<repo>.md`에 둔다(예: `isac322__kwin-mcp.md`). 공통 스킬에는 저장소 전용 규칙을 넣지 않는다.
- 운영 감시: 배포 뒤 7일 동안 저장소별로 non-draft head 중 COMMENT로 끝난 비율을 본다. 30%를 넘으면 미확인 의심·lens 완결 규칙을 다시 검토한다.

### 자동 머지와 실행 격리의 한계

워크플로는 PR 생성·갱신과 리뷰 제출까지 수행하고 **merge는 사람이 한다**. bridge는 GitHub가 현재 head를 merge-ready로 판정할 때만 설정된 project owner를 assign하고 멘션한다. 에이전트는 읽기 전용 GitHub 토큰으로 작업하며, bridge가 결과를 받아 GitHub 쓰기를 수행한다. push는 publisher가 checkout의 `hapi-issue-[0-9]+` branch를 자기 private bare mirror로 가져온 뒤 그 mirror에서 non-force 방식으로 실행한다. 에이전트 checkout을 git의 cwd나 git dir로 쓰지 않는다. push 토큰은 publisher 사이드카에만 마운트한다.

다만 publisher와 에이전트는 Runner home PVC를 공유하므로 에이전트는 push될 커밋 내용을 정한다. push 대상은 턴이 끝난 뒤의 worktree branch head다. 에이전트가 worktree의 유일한 writer이므로 결과에 SHA를 따로 받지 않는다(flareway#138에서 손으로 옮긴 SHA가 실제 head와 앞 7자만 맞아 push가 `sha_mismatch`로 멈췄다). 공유 Runner는 악성 코드에 대한 주제별 보안 샌드박스가 아니다.

Runner Pod의 `dockerd`는 privileged 컨테이너다. daemon에는 Secret과 home root를 마운트하지 않고 socket도 UID 1000 그룹으로 제한한다. 2026-10-11 전에는 socket으로 privileged 컨테이너나 host 마운트를 요청할 수 있어 runner 프로세스가 사실상 node root였다. 이제 dockerd의 authorization plugin이 그런 요청을 거절하지만(`## Runner Docker와 DRM 장치`의 Docker 권한 정책) dockerd 자체는 여전히 privileged이고 plugin은 정책 계층이지 커널 경계가 아니다. 에이전트 컨테이너에 쓰기 토큰을 마운트하지 않는 분리는 정상 동작의 경계이며 Secret 격리를 보장하지 않는다. privileged 예외는 `issue-agent-runner` namespace에만 두고, hub·n8n·bridge가 있는 `issue-agent`는 `restricted`를 유지한다.

신뢰하지 않는 코드의 실행 경계(2026-10-11):

- 컨테이너 안에서만 PR 코드 실행(E1'): review 모드에서 PR이 제어하는 코드(추출한 함수, PR 모듈을 import하는 harness, PR의 script·test suite·build 도구)는 Runner 셸에서 실행하지 않고 에이전트가 구성한 컨테이너 안에서만 돌린다. 공식 base image 위의 가벼운 scratch Dockerfile(예: 최소 지원 Python 3.12 확인)만 `docker build`하고(`--allow` entitlement 없음, network는 build 때만), worktree 복사본이나 head의 `git archive`를 context로 쓴다. PR Dockerfile은 로컬 실행 범위(PRR-57)의 컨테이너 이미지 build라서 빌드하지 않는다. 실행은 항상 `docker run --rm --network none`이며 `--privileged`·`--cap-add`·socket·home mount를 쓰지 않고 `-e`는 literal 상수만 쓴다. 장치는 필요할 때 DRI node만 넘긴다. PR 자신의 docker wrapper script는 실행하지 않는다. 그렇게 probe할 수 없으면 challenger를 견딘 논증으로 대신한다. 이 규칙은 공통 지침·스킬의 문구이고, 강제는 아래 Docker 정책이 일부 맡는다.
- 모델 키 proxy(E2): Runner Pod에 Caddy native sidecar `model-proxy`(uid 65532, `127.0.0.1:8317`, loopback 전용)를 둔다. sidecar에만 마운트한 파일에서 provider 키를 읽어 Authorization header를 붙이고 허용한 path만 upstream으로 넘긴다. Codex provider `base_url`은 `http://127.0.0.1:8317/v1`이고 `env_key`가 없으며, runner 컨테이너에서는 `OPENAI_API_KEY` env와 키 파일을 뺐다. sidecar는 startup probe(proxy 준비 뒤 runner 시작)와 liveness probe를 가지며, `reverse_proxy`는 `flush_interval -1`이고 Codex stream idle timeout보다 짧은 read/header timeout을 두지 않는다. 남는 위험: Pod 안의 로컬 프로세스는 proxy로 모델 API를 호출할 수 있지만 키 자체는 읽을 수 없다. Docker 컨테이너와 다른 Pod는 loopback proxy에 닿지 않는다.
- Docker 권한 정책(E3): `## Runner Docker와 DRM 장치`의 Docker 권한 정책.
- 셸 환경 제외(E4): Codex `shell_environment_policy`의 `include_only`가 에이전트 셸 환경에서 비밀을 뺀다. 보조 장치다.
- 남은 경계와 다음 단계: HAPI runner는 hub 제어 토큰 `CLI_API_TOKEN`(모든 세션 읽기·조작, terminal 열기)을 에이전트와 같은 컨테이너·같은 uid로 가지므로, Runner 셸에서 도는 프로세스는 `/proc/<pid>/environ`으로 이 토큰을 읽을 수 있다. HAPI와 에이전트를 별도 컨테이너로 나누는 hub 토큰 분리가 다음 단계다. GitHub 읽기 토큰의 `repositories` 범위 축소는 선택 사항으로 남는다.

### PR 자동 수정과 merge-ready 알림

- 같은 저장소의 `hapi-issue-<n>` head를 가진 PR은 원본 이슈에 연결한다. SQLite `prs`에 head, dirty/revision, repair delivery lease, 마지막 시도 fingerprint, 수동 요청, 알림 head를 보관한다. fork의 같은 이름 branch는 관리 대상으로 삼지 않는다.
- `pull_request` 상태 변경, `pull_request_review`, `pull_request_review_comment`, `check_run`, `check_suite`, `status`, 기본 branch `push`는 최신 상태 재조회를 예약한다. GitHub App webhook에 해당 이벤트를 구독해야 한다. 누락된 webhook과 재시작은 60초 주기의 reconciliation으로 보완한다.
- 첫 actionable blocker에서 원본 `issue-<n>` worktree로 `pr_repair` followup을 보낸다. freshly fetched 기본 branch를 먼저 merge하고, 현재 head의 CI 실패와 리뷰 finding을 한 턴에서 검증·수정한다. rebase·reset·force-push와 자동 PR merge는 하지 않는다.
- repair 중 새 이벤트는 두 번째 writer를 시작하지 않고 dirty/revision만 갱신한다. 끝난 턴은 push 이후 GitHub 상태를 다시 조회한다. 이전 head의 change request는 새 head의 repair 근거로 재사용하지 않고 재리뷰를 기다린다.
- 시작 시 일시적인 GitHub 조회 실패는 같은 delivery를 backoff 후 재시도한다. 성공한 push·PR 갱신 뒤 상태 조회만 실패하면 성공 결과를 유지하고 reconciliation을 예약한다. 해결 불가능한 repair는 `needs_attention`으로 보류하며 새 repair writer를 막지만, 별도 worktree의 리뷰는 진행할 수 있다.
- readiness는 일치하는 GraphQL/REST head·base에서 open, non-Draft, `MERGEABLE`, `CLEAN` 또는 `UNSTABLE`일 때만 인정한다. `UNSTABLE`은 비필수 check 실패를 포함할 수 있다. `UNKNOWN`이나 API 간 불일치는 기다리며, assign 전과 멘션 직전에 다시 확인한다.
- 알림은 `(repo, PR, head)`별 SQLite acknowledgement와 `pr-ready:<PR>:<head>` comment marker로 중복을 방지한다. 같은 수동 repair 댓글의 재전송도 comment ID로 중복 처리한다. 현재 owner 설정은 `isac322/cc-lb`와 `isac322/pillar-csi`에만 있다.

### 리뷰·repair 반복 상한

krema#63에서 리뷰 ↔ repair 조정이 약 12시간 동안 반복돼 토큰 약 1.21억 개를 썼다. 시작점은 `finish`였다. 리뷰가 이미 `APPROVED`로 게시된 뒤 `finish`가 `agent:needs-attention` 라벨 DELETE에서 HTTP 401을 받아 실패했고, n8n `Finished?`가 `fail`로 넘어가 attention 댓글이 `@haechibot review` 재요청을 안내했다. 재요청도 같은 실패로 끝났다. 아래 규칙으로 이 반복이 유한하게 끝난다.

- 리뷰 요청 합치기와 취소: 아래 "리뷰 요청 합치기와 취소" 절의 규칙으로 PR마다 대기 리뷰는 최대 하나이고, 새 head가 오면 이전 head의 실행 중 리뷰는 끝까지 돌지 않는다.
- `finish` 순서와 라벨 제거: `finish`는 이벤트를 먼저 `completed`로 기록하고 세션 정리를 마친 뒤 라벨을 다룬다. bridge가 attention 알림에서 라벨 추가에 성공하면 `issues.attention_label`을 1로 두고, `finish`는 이 값이 1일 때만 라벨을 DELETE한다. 200·404면 0으로 내린다. 그 밖의 GitHub 오류는 경고 로그만 남기고 값을 유지해 다음 `finish`가 다시 시도한다. 라벨 제거 실패가 끝난 실행을 실패로 바꾸지 않으며, bridge가 붙이지 않은 라벨에는 DELETE를 보내지 않는다. 마이그레이션은 `needs_attention` 이벤트가 있는 대상의 값을 1로 채운다.
- 자동 repair 상한: reconciliation은 `_pr_findings`를 원인별로 나눈다. `base`는 behind 또는 conflict, `checks`는 실패한 check, `review`는 변경 요청 리뷰다. 리뷰어가 남기는 commit status(`issue-agent/review`, 설정 `review_status_context`)는 판정을 그대로 옮긴 것이므로 `checks`에서 빼고 `review`로만 센다. flareway#138에서는 이 status가 실패 check로 한 번 더 세어졌다. 리뷰 App 자신의 리뷰는 GitHub `commit_id`가 아니라 marker SHA가 현재 head일 때만 현재 head의 리뷰로 센다. 사람의 리뷰는 지금처럼 `commit_id`가 현재 head인지로 본다.
- 실행 중인 check 대기: 현재 head에 끝나지 않은 check(CheckRun `status`가 `COMPLETED`가 아니거나 StatusContext `state`가 `PENDING`·`EXPECTED`, 리뷰어 status 포함)가 하나라도 있으면 자동·수동 repair 모두 넣지 않고 `checks_pending`을 반환한다. 수동 요청(`latest_signal`)은 남겨 두고 fingerprint도 기록하지 않으며, 60초 주기 reconciliation이 다시 확인한다. flareway#138에서는 envtest가 도는 중에 repair가 push해 그 실행을 취소했고, 진짜 envtest 실패는 끝내 repair되지 않았다.
- 연속 횟수와 backoff: 자동 `pr_repair`를 넣을 때마다 `prs.repair_streaks`(JSON)에서 지금 있는 원인의 연속 횟수는 1 늘리고 없는 원인은 0으로 되돌린다. 지금 있는 원인이 연속 `MAX_PR_REPAIR_STREAK`(3)회에 도달하면 멈추지 않고 `PR_REPAIR_BACKOFF_SECONDS`(1시간, 4시간, 16시간) 단계로 기다린다. 기다리는 동안은 댓글 없이 `cooling`을 반환하고 fingerprint도 쓰지 않는다. 대기가 끝나면 근거 fingerprint가 직전 시도와 같아도 repair를 정확히 한 번 넣고(`no_change`로 끝나도 다음 단계로 간다), 그 원인이 남아 있으면 다음 단계를 시작한다. 세 단계를 다 쓰고도 원인이 남으면 원인과 backoff 소진을 적은 `pr-repair-limit:<PR>:<last_manual_id>` marker 댓글을 한 번 남기고 `repair_limit`으로 멈춘다. 상한에 닿은 원인이 사라지면 대기·단계 상태를 지운다.
- 진전 시 초기화: 마지막 repair 때 실패한 check 이름 집합(CheckRun `name`, StatusContext `context`)을 `check_names`로 기억한다. `checks`가 원인인데 실패 집합이 기억한 비어 있지 않은 집합과 다르면 repair가 진전을 낸 것으로 보고 `checks` 연속 횟수와 그 backoff 단계를 0부터 다시 센다.
- 시간 창 상한: 자동 repair 시작 시각을 `attempts`에 남기고 `PR_REPAIR_WINDOW_SECONDS`(24시간)보다 오래된 것은 버린다. 창 안에 `MAX_PR_REPAIRS_PER_WINDOW`(10)회가 차면 원인이 번갈아 나타나는 경우의 backstop으로 같은 marker 댓글을 남기고 `repair_limit`으로 멈춘다. 멈춘 상태(`stopped`)는 아래 초기화 전까지 유지된다.
- 초기화: 사람의 `@bulgasaribot` repair 요청은 상한과 무관하게 허용되며 연속 횟수, backoff, 시간 창, 멈춤 상태를 모두 지운다(`repair_streaks = '{}'`). PR이 merge-ready가 되어도 같다. 예전 행의 `total` 값은 읽어도 쓰지 않고 다음 기록 때 사라진다. 기존 DB에 남은 `prs.repair_count` 열은 쓰지 않는다.
- 로컬 CI 게이트: implement·followup 결과에는 `local_checks`(최대 30개, `{"command": "<=500자", "exit_code": int}`)가 반드시 있다. `ready`이면 비어 있지 않고 모든 `exit_code`가 0이어야 하며, 아니면 결과 검증이 실패해 교정 경로로 에이전트에게 돌려보내므로 n8n이 push하지 않는다. 에이전트는 `ready` 전에 저장소의 빠른 게이트(format·lint, build·compile, unit test, 바뀐 범위에 맞춘 빠른 test. `.github/workflows/*` job과 그 job이 부르는 Makefile/justfile 타깃에서 찾는다)를 worktree에서 돌리고, 빠른 게이트가 실패한 코드는 push하지 않는다. 빌드 산출물은 `/tmp`에 두지 않는다. 오래 걸리는 suite(e2e, GUI·Appium, multi-distro·multi-version·multi-node matrix, 컨테이너·VM integration, soak, 몇 분 넘게 걸리는 envtest류)는 CI가 돌린다. 기본으로 로컬에서 돌리지 않고 PR 본문과 `summary`에 "left to CI"로 적는다. CI가 그 suite에서 보고한 실패를 재현·수정할 때(PR repair·followup)나 바꾼 것이 그 suite의 harness 자체여서 달리 검증할 수 없을 때만 영향받는 leg·test를 로컬에서 돌리고, matrix를 직렬로 이어 돌리지 않는다(2026-10-13 사용자 결정. krema#99 implement 턴이 직렬 distro E2E를 로컬에서 6시간 넘게 돌리다 턴 예산에 걸렸다). 시크릿·외부 서비스·특수 하드웨어가 필요해 로컬에서 돌릴 수 없는 게이트는 `summary`와 PR 본문에 미실행으로 적고 `local_checks`에는 넣지 않는다. 같은 기준이 implement·followup·PR repair 지시문과 `isac-issue-to-pr`(I2P-46)에 있다.
- 변경 없는 repair 뒤 재리뷰: 리뷰가 부른 repair가 `no_change`로 끝나면(근거를 들어 지적을 반박한 경우 등) bridge는 같은 head의 리뷰를 한 번 큐에 넣는다. head당 한 번이다.

### 리뷰 요청 합치기와 취소

pillar-csi#155에서 PR 열기 → 31초 뒤 force-push → 3초 뒤 `@haechibot review` 댓글이 리뷰 세 번을, 이후 push → 12초 뒤 댓글이 리뷰 두 번을 실행했다. 2026-10-01 기준 리뷰 94회 중 16회가 직전 요청 2분 안의 중복이었다. 요청 하나가 리뷰 실행 하나가 되는 구조였고, push가 이미 리뷰를 시작하는데 footer는 push 뒤 댓글을 달라고 안내해 push마다 요청이 둘 생겼다. 이제 리뷰 요청은 PR별 대기 리뷰 하나에 모이는 수요로 다룬다.

- 대기 리뷰 하나: 새 `pr_review`(PR 열기·재개·Ready, push, `@haechibot review` 댓글, 열린 PR 리뷰 스윕)는 같은 PR의 대기(`accepted`) 리뷰를 `coalesced`로 끝내고 그 자리를 잇는다. 살아남은 행은 가장 최근 댓글 요청(본문은 프롬프트의 `COMMENT_BY_<actor>`)과 가장 최근 head를 이어받는다.
- 정착 시간: 대기 리뷰는 마지막 요청 `REVIEW_SETTLE_SECONDS`(90초) 뒤에 시작하되, 가장 오래된 대기 요청으로부터 `REVIEW_MAX_DELAY_SECONDS`(300초)를 넘기지 않는다. push와 그 뒤 댓글, PR 열기 직후 force-push는 리뷰 하나가 된다.
- 충족 기준: 요청은 그 뒤에 시작한 리뷰가 있어야 충족된다. 이미 시작한 리뷰는 그 뒤에 단 답글을 보지 못하므로, 실행 중에 온 댓글 요청은 한 번 더 리뷰한다. GitHub 리뷰 제출 시각으로 건너뛰는 규칙은 없다.
- 이전 head 취소: `begin`은 리뷰가 체크아웃할 현재 PR head를 이벤트에 기록한다. head를 가진 새 요청(push 등)이 오면 다른 head를 리뷰 중인(`dispatching`/`dispatched`) 이벤트를 `cancelled`로 끝낸다. 취소된 실행의 다음 op는 `event_terminal`이라 아무것도 게시하지 않고, `fail`은 `already`로 조용히 끝난다. 다음 dispatcher tick이 그 세션을 archive해 에이전트를 멈춘다. 같은 PR의 다른 이벤트가 이미 dispatch 슬롯을 잡았으면 공유 세션이므로 archive하지 않는다. head가 없는 댓글 요청은 취소하지 않는다. 취소된 리뷰는 그 head를 리뷰한 적이 없으므로(아래 head별 자동 리뷰 1회) branch가 그 head로 돌아오면 다시 요청된다. 자동 요청은 시작 시점에도 자기 head에 묶여 있다. 다른 요청이 이미 그 head의 리뷰를 게시했으면 `already_reviewed`로 끝난다. 시작 전에 PR head가 바뀌었으면 새 head가 요청된 적 없는 한 그 head로 옮겨 붙고(`head_sha`와 semantic key를 다시 쓴다), 이미 요청된 head면 `head_moved`로 끝난다. 댓글을 가진 요청(자기 댓글이든 합쳐져 이어받은 댓글이든)은 시작 시점의 현재 head를 리뷰하고, head 모양 semantic key를 가졌으면 그 key도 새 head로 옮긴다(새 key를 다른 행이 쥐고 있으면 풀어 둔다).
- footer: 리뷰 App이 있으면 push는 자동 리뷰되므로 footer는 push 없이(답글 뒤) 다시 받고 싶을 때나 오류로 멈춘 리뷰를 재시작할 때만 댓글을 쓰라고 안내한다. 리뷰 중 push로 생긴 stale 리뷰도 새 head는 push가 이미 리뷰를 예약했다고 쓴다.
- head별 자동 리뷰 1회: 자동 요청(`pull_request` opened/reopened/ready_for_review/synchronize, 열린 PR 리뷰 스윕)은 같은 저장소·PR·head의 `pr_review` 요청이 대기·실행 중이거나 리뷰를 만들었거나(완료) parked(`needs_attention`) 또는 다른 요청에 밀려 끝난(`superseded`) 행이 있으면 큐에 넣지 않고 `duplicate`로 답한다. 같은 delivery id의 재전송 webhook은 어떤 부수 효과 없이 먼저 `duplicate`로 답한다. 합쳐진(`coalesced`)·취소된(`cancelled`)·시작 전에 끝난(`head_moved`, `already_reviewed`) 요청은 그 head를 리뷰한 적이 없으므로 세지 않고, 그 행의 head semantic key(`#pr:<n>:review:<head>` 모양; `#comment:<id>` 키는 유지)도 풀려 같은 head의 요청이 다시 들어올 수 있다. 다만 리뷰 게시(`github.review` op)의 기록(`stages.review_published`)은 행의 상태나 `head_sha`와 관계없이 그 head를 요청한 것으로 친다. 게시 뒤 push가 이벤트를 취소했거나, head 조회가 실패해 `head_sha`가 비어 있는 댓글 리뷰여도 리뷰는 이미 GitHub에 있다. `duplicate`로 답하기 전에도 다른 head를 리뷰 중인 이벤트는 `cancelled`로 끝내므로, 이전에 리뷰된 head로 돌아온 push 뒤에도 오래된 head의 리뷰가 계속 돌지 않는다. 확인과 삽입은 `Store.enqueue_in`의 한 SQLite 쓰기 트랜잭션이다. krema#76에서 Draft일 때 댓글로 받은 리뷰가 끝난 뒤 `ready_for_review` webhook이 같은 head를 다시 리뷰했는데, 댓글 리뷰도 시작할 때 head를 기록하므로 이제 이 webhook은 `duplicate`다. `@haechibot review` 댓글은 명시적 재요청이라 항상 큐에 들어간다.
- 시작 시 게시 기록 우선: 자동 요청의 `begin`은 PR head를 조회하기 전에 다른 행의 `stages.review_published`가 자기 head인지 먼저 본다. 맞으면 `already_reviewed`로 끝내므로, GitHub가 head 조회에 실패해도 같은 head를 다시 리뷰하지 않는다.
- 시작 시 열린 PR 확인: 자동 요청의 `begin`은 head를 읽을 때 받은 PR이 닫혔거나 Draft면 `pr_not_open`으로 끝낸다(리뷰·status·차단 없음). 스윕은 PR을 쓰기 트랜잭션 밖에서 읽고, PR을 닫거나 Draft로 바꾸는 webhook은 이벤트를 넣지 않으므로 그 사이에 큐에 들어간 요청이 남을 수 있기 때문이다. `pr_not_open`은 그 head를 리뷰한 적이 없으므로 세지 않고 head key도 풀어, PR이 다시 열리면 webhook이나 스윕이 그 head를 다시 요청한다. 댓글 요청은 지금처럼 현재 head를 리뷰한다.
- head별 게시 1회: `github.review`는 `("github-review", delivery)` keyed lock 안에서 리뷰 목록 조회 → marker 확인 → 리뷰 제출 → `review_published` 기록 → status를 처리하므로, n8n이 같은 op를 동시에 재시도해도 리뷰가 둘 생기지 않는다. 자동 요청(댓글 없음)은 리뷰를 만들기 전에 같은 목록에서 리뷰 App이 이 head를 리뷰한 가장 최근 리뷰를 찾는다. 리뷰한 head는 본문 첫 줄 marker(`<!-- issue-agent:<delivery>:review:<sha> -->`)의 SHA, marker에 SHA가 없으면 같은 delivery의 로컬 `review_published.sha`로 정하며 GitHub `commit_id`는 쓰지 않는다. GitHub는 이전 head의 리뷰 `commit_id`를 새 commit으로 바꿔 달 수 있다. kwin-mcp#94에서는 이 때문에 새 head의 리뷰가 버려지고 이전 승인이 새 head의 status로 옮겨졌다. 어느 쪽으로도 정할 수 없는 예전 리뷰는 맞지 않는 것으로 친다(상태 유실이나 rebase 뒤 최대 한 번 재리뷰를 받아들인다). 찾으면 게시하지 않고 그 리뷰를 이 이벤트의 `review_published`로 기록한 뒤 marker가 이미 있을 때와 같은 응답(`created: false`)을 돌려준다. 다른 실행의 리뷰를 이어받은 것이므로 스레드 답글과 resolve도 하지 않는다(그 실행이 이미 했다). 그래서 제출은 GitHub에 반영됐는데 응답만 잃은 리뷰가 push로 취소되고 같은 head가 다시 요청돼도 두 번 게시하지 않는다. 같은 delivery의 재시도(자기 marker)와 댓글 요청은 지금처럼 동작한다.
- 버려지는 자동 요청은 댓글 리뷰를 취소하지 않는다: `duplicate`로 답하는 자동 요청이 다른 head의 실행 중 리뷰를 취소하는 것은 댓글 없는 자동 리뷰에만 해당한다. 합쳐져 `@haechibot review` 댓글을 이어받은 실행 중 리뷰는 계속 돌아 현재 head를 리뷰한다. 아무것도 넣지 않는 요청이 사람의 재요청을 지우면 안 되기 때문이다(fuzz로 찾은 순서: 리뷰된 A → 댓글 → push B가 댓글을 합쳐 시작 → A로 되돌린 push가 그 리뷰를 취소).

### 열린 PR 리뷰 스윕

2026-10-02 06:18 bridge 재시작 동안 온 webhook은 다시 오지 않았고, 관리 PR이 아닌 cc-lb#902·#892의 head는 끝내 리뷰되지 않았다. 전에는 60초 reconciliation이 `prs`에 있는 관리 PR의 head만 리뷰 요청했다. 이제 그 경로는 없애고, dispatcher 스레드의 주기 작업(`reconcile_due_prs`)이 bridge 시작 직후와 이후 `REVIEW_SWEEP_SECONDS`(600초)마다 관리 여부와 관계없이 모든 열린 PR을 훑는다.

- 범위: 리뷰 App(`haechibot`)이 설정되어 있을 때만 돈다(없으면 push도 리뷰를 요청하지 않는다). 리뷰 App 설치 저장소(`GET /installation/repositories`) 중 registry가 받는 저장소의 열린 PR(`state=open`)을 100개씩, 최대 `REVIEW_SWEEP_MAX_PAGES`(10) 페이지 읽는다. 한도에 닿으면 경고를 남긴다.
- 후보: Draft가 아니고 head commit(committer date)이 `REVIEW_SWEEP_MAX_AGE_SECONDS`(14일) 안인 PR. PR `updated_at`이 14일보다 오래되면 head commit도 오래되었으므로 commit을 읽지 않고 건너뛴다.
- 진행 중이거나 멈춰 있으면 건드리지 않는다: PR에 비종결(`accepted`/`dispatching`/`dispatched`) 이벤트가 있으면(head가 아직 기록되지 않은 댓글 리뷰, repair 포함) 건너뛰고, 관리 PR은 연결된 이슈의 비종결 이벤트도 본다(연결 이슈는 `prs` 행 또는, 아직 추적되지 않은 PR이면 `hapi-issue-<n>` branch 이름으로 찾는다). `needs_attention`으로 멈춘 리뷰가 있는 PR, 주체가 막힌(`issues.blocked`) PR, 연결 이슈가 막힌 PR도 건너뛴다. 멈춘 구현·repair 세션은 아직 살아 있을 수 있다. `prs.active_delivery`는 repair가 `needs_attention`으로 멈춘 뒤에도 남으므로 보지 않는다.
- 원격 기록: 로컬 행이 없어도 PR 리뷰 목록에 리뷰 App이 남긴, 본문의 bridge 숨은 marker SHA가 그 head인 리뷰가 있으면 건너뛴다. GitHub `commit_id`는 보지 않는다. pillar-csi#162에서 dependabot rebase가 haechibot의 APPROVED 리뷰를 status 없이 새 head로 옮겼는데, 옮겨진 리뷰는 새 head를 리뷰한 것이 아니므로 이제 새 head를 다시 리뷰한다. commit status(`review_status_context`)는 보지 않는다. status는 commit 단위라서 head가 같은 다른 PR(base가 다른 backport 등)의 리뷰가 이 PR의 빠진 리뷰를 가린다. 예전 bridge가 스레드 답글을 따로 달 때 GitHub가 남긴 빈 `COMMENTED` 리뷰는 marker가 없어 리뷰로 치지 않는다(지금은 답글도 판정 리뷰 안에 함께 제출된다). `github.review`의 head별 게시 1회도 같은 기준을 쓴다.
- live head: 큐에 넣기 직전에 PR을 다시 읽어 닫혔거나 Draft가 되었거나 head가 바뀌었으면 넣지 않는다. 새 head는 그 webhook이나 다음 스윕이 처리한다. 이 GET은 쓰기 트랜잭션 밖에서 한다. GitHub HTTP timeout(30초)이 SQLite busy timeout과 같아서, 트랜잭션 안에서 읽으면 동시에 온 webhook·op가 `database is locked`(503)로 실패할 수 있다. 읽은 뒤 push가 끼어들어도, 진행 중인 리뷰는 위 확인으로 이미 없고 시작 시점 검사(`head_moved`)가 오래된 요청을 끝낸다. 오래된 요청이 해를 끼칠 수 있는 곳은 멈춘 리뷰를 `superseded`로 끝내는 경우뿐이고, 멈춘 리뷰나 막힌 주체가 있는 PR은 스윕하지 않는다. 로컬 확인과 삽입은 한 쓰기 트랜잭션이어서 동시에 온 webhook과 섞이지 않고, 이벤트는 webhook과 같은 모양이다(delivery id만 매번 새 `pr-review-sweep-<uuid>`: 리뷰되지 않은 head의 재요청이 이전 행의 delivery id와 충돌하지 않도록).
- 한도: 스윕 한 번에 모든 저장소를 통틀어 `REVIEW_SWEEP_MAX_ENQUEUES`(10)개까지 넣는다. 한 저장소나 PR의 GitHub 오류는 경고만 남기고 다음으로 넘어가며, 스윕 오류는 dispatcher로 올라가지 않는다.
- 멈춘 리뷰의 재시도: `needs_attention`으로 멈춘 리뷰도 그 head를 요청한 것으로 치고 스윕은 다시 넣지 않는다. 일시적 원인(`park_class`)으로 멈춘 리뷰만 같은 이벤트를 bounded 자동 재시도한다(`### 오류 알림`). 그 밖의 원인은 같은 실패를 반복하지 않도록 자동으로 다시 돌리지 않는다. 사람이 `@haechibot review`로 재요청하면 멈춘 리뷰를 `superseded`로 끝내고 다시 리뷰한다.
- 남은 경계: 오래된 head의 webhook이 늦게(재전송 등) 도착하면 그 요청이 더 새 head의 대기 리뷰를 합친 뒤 살아남을 수 있다. 살아남은 요청은 시작할 때 현재 head가 요청된 적 없으면 그 head로 옮겨 붙어 리뷰하므로 리뷰가 빠지지는 않는다. 현재 head가 이미 요청된 head면 `head_moved`로 끝나고, 이미 요청된 적 있는 head의 늦은 webhook 자체는 head별 자동 리뷰 1회로 버려진다.

### 알려진 제한

- GitHub App은 PR reviewer로 요청할 수 없다. REST API로 `ironeater[bot]`(당시 이름, 현 `bulgasaribot[bot]`)을 reviewer로 요청하면 오류 없이 무시되는 것을 확인했다. 그래서 재리뷰 요청은 본문 어디든 `@haechibot` 멘션이 있는 PR 댓글(대소문자 무시)로 받되, PR 작성자 또는 저장소 collaborator·owner가 `User` sender로 남긴 댓글만 받는다.
- GitHub는 PR 작성자의 APPROVE/REQUEST_CHANGES를 금지한다. 그래서 리뷰는 작성용 `bulgasaribot`과 다른 App `haechibot`으로 제출하며, bulgasaribot이 연 PR에도 실제 승인·변경 요청이 달린다. 리뷰 App 자신이 연 PR만 `COMMENT`와 `**Verdict: <event>**` 접두로 downgrade한다(현재 그런 PR은 없다).
- 필수 승인 수에 GitHub App 승인이 포함되는지는 문서에 없어서, merge 강제는 특정 App이 남긴 상태만 인정하는 required status check(`issue-agent/review`, integration `5118831`)로 한다. 새 commit은 상태가 없으므로 재리뷰 전까지 merge되지 않는다.
- `isac322/cc-lb`는 GitHub Free의 private 저장소라 branch protection과 ruleset API가 403을 반환한다. 이 저장소는 bot 승인을 merge 조건으로 강제하지 않는다.

## 이벤트와 세션 계약

- 키는 저장소 식별자와 이슈/PR 번호의 조합이다. 서로 다른 저장소의 동일 번호를 충돌시키지 않는다.
- GitHub delivery 중복과 의미적으로 중복된 이슈를 구분한다. 전자는 영속 키로 처리하고 후자는 에이전트가 triage에서 읽기 전용 토큰으로 직접 검색·판단한다(`verdict: DUPLICATE`, `duplicate_of`).
- 이벤트는 수신 확인 전에 영속화한다. 허용하지 않은 사용자·이벤트는 모델에 전달하지 않는다. 저장소는 App 서명이 설치를 증명하므로 따로 거르지 않는다.
- 수신 경로: GitHub → `issue-agent-webhook.bhyoo.com/webhooks/github`(Cloudflare tunnel) → n8n `IssueAgentIntake01`(Raw Body Webhook → `Verify Webhook Signature`, provider `github`) → bridge 내부 `POST /webhooks/github`(`Authorization: Bearer <bridge-ops-token>`, `/ops`와 같은 토큰). 서명이 틀리거나 없으면 n8n이 401 `{"status":"bad_signature"}`로 답하고 bridge에는 전달하지 않는다. 검증된 원본 바이트와 `X-GitHub-Event`·`X-GitHub-Delivery`만 bridge로 넘기고, bridge의 상태 코드와 JSON 본문을 그대로 GitHub에 돌려준다(bridge 연결 실패는 503 `bridge_unavailable`). bridge는 HMAC을 검증하지 않고 webhook secret도 마운트하지 않으며, bearer가 틀리거나 없으면 401 `unauthorized`로 답한다.
- 서명 검증 노드는 커뮤니티 패키지 `n8n-nodes-webhook-signature@0.1.2`를 npm integrity checksum으로 고정해 `N8N_COMMUNITY_PACKAGES`로 설치한다(`N8N_UNVERIFIED_PACKAGES_ENABLED=false`). 버전을 올릴 때는 새 버전의 `dist.integrity`와 노드·자격증명 계약 변경을 확인하고 `version`과 `checksum`을 함께 바꾼다.
- 에이전트가 작성한 댓글이 재실행 루프를 만들지 않게 한다.
- 세션 생성과 메시지 전송은 결과가 불확실할 때 무조건 재전송하지 않는다. HAPI의 `localId`, queued-state와 세션 메타데이터를 사용해 확인 가능한 것만 복구한다.
- HAPI spawn 응답은 HTTP 200만으로 성공이라고 보지 않는다. `{type:'success', sessionId}`를 확인한다.
- resume/reopen 결과의 세션 ID는 기존과 다를 수 있다. 반환 ID와 superseded 매핑을 반영하여 같은 논리 이슈 대화를 유지한다.
- 운영 자동화는 일반 메시지를 queue로 전달한다. 사용자의 명시적 Steer·중단·승인은 UI를 통해 구분한다. Codex와 Claude의 중간 개입 기능이 같다고 가정하지 않는다.
- 결과는 제출 메시지의 `localId`와 `invokedAt`, 그 메시지 이후의 agent 결과에 포함된 작업별 nonce·결과 스키마를 함께 확인한다. 다른 UI 메시지가 중간에 실행되었거나 결과의 소속이 불확실하면 자동으로 다음 단계로 넘어가지 않는다. 이 경우 사람의 개입 기록은 보존하고 운영자 확인 상태로 전환한다. `/clear`를 기존 이슈의 자동 세션 이전으로 해석하지 않는다.
- 상태가 불확실하거나 권한·provider 오류가 나면 성공으로 처리하지 않는다. 운영자에게 근거를 남기고 중복 실행을 차단한다.

### 이벤트 분류(bridge `classify_event`)

- 신뢰 사용자는 저장소 collaborator·owner다. bridge가 이슈 App 토큰으로 `GET /repos/{repo}/collaborators/{login}/permission`을 호출해 `permission`이 `admin` 또는 `write`면 신뢰한다(`maintain`은 `write`, `triage`는 `read`로 매핑된다). 404는 비신뢰다. 결과는 신뢰·비신뢰 모두 SQLite `collaborators` 테이블에 600초 캐시한다. 조회는 규칙이 신뢰 여부를 필요로 할 때만 한다. 네트워크 오류·토큰 없음·그 외 HTTP 상태면 캐시하지 않고 HTTP 503 `permission_unavailable`로 응답하며 이벤트를 저장하지 않는다. GitHub가 재전달한다. 예외로 `agent:open-discussion` 이슈의 댓글은 신뢰 여부가 처리 여부를 정하지 않으므로, 조회가 실패해도 경고 로그만 남기고 비신뢰로 기록한다.
- `issues.opened`: 누구나(sender가 bot이 아닌 `User`이고 이슈 작성자와 같을 때) → `issue_opened`. 신뢰 사용자의 이슈는 항상 받는다. 비신뢰 사용자의 이슈는 전체 저장소 합산 최근 3600초(rolling) 안에 받은 비신뢰 `issue_opened`가 10개 미만일 때만 받고, 넘으면 `rate_limited`(202, 저장 안 함)다. 신뢰 사용자의 이슈는 한도에 세지 않는다.
- 예외: 저장소 owner(저장소 이름의 `<owner>`와 같은 login, 예: `isac322/*`의 `isac322`)가 연 이슈는 자동 처리하지 않는다(`owner_issue_ignored`, 저장 안 함). owner는 자기 에이전트 작업용 메모로 이슈를 여는 경우가 많기 때문이다. 이런 이슈도 신뢰 사용자가 `@bulgasaribot` 멘션 댓글을 달면 그 댓글이 `issue_comment`로 들어와 triage부터 시작한다. 조직 저장소는 login이 조직 이름과 같을 수 없으므로 해당이 없다.
- `issue_comment.created`(닫힌 이슈): bot_sender·에이전트 marker 검사 다음, 아래 `agent:open-discussion`·멘션 규칙보다 먼저 본다. 이슈 `state`가 `closed`이고 작성자가 저장소 owner(`project_owner`, 없으면 저장소 이름의 `<owner>`, 대소문자 무시)면 기존 규칙을 그대로 따른다(owner의 일반 댓글은 계속 `issue_comment_ignored`). 그 외에는 신뢰 여부를 조회하며, 조회가 실패하면(`TrustUnavailable`) 기존처럼 HTTP 503 `permission_unavailable`로 응답하고 저장하지 않는다. 신뢰 사용자(`admin`/`write` collaborator)의 댓글도 기존 규칙(멘션이면 `issue_comment`, 아니면 `issue_comment_ignored`)을 따르고 재개 이벤트를 만들지 않는다. 비신뢰 사용자의 댓글은 멘션·라벨과 무관하게 `closed_issue_comment`(`repo#comment:<comment_id>`, `trusted: false`)로 분류해 `reopen_check` 모드로 처리한다. 비신뢰 `closed_issue_comment`는 `issue_opened`와 별도로 세는 같은 한도(전체 저장소 합산 최근 3600초에 10개)를 넘으면 `rate_limited`(202, 저장 안 함)다. 열린 이슈와 PR 댓글은 바뀌지 않는다. `issues.reopened`는 계속 `action_ignored`라 재개가 이벤트를 다시 만들지 않으며, bot이 남긴 재개 안내 댓글도 `bot_sender`로 버려져 루프가 없다. GitHub는 닫힌 이슈의 댓글도 `issue_comment.created`로 보내므로 webhook 구독은 바꾸지 않았다. 계기는 2026-10-12 isac322/krema#90 댓글 6128696806이다. 구현되어 닫힌 이슈에 작성자가 "조정 범위가 부족하고 taskbar가 아니라 화면 가장자리 기준"이라고 남겼지만 `issue_comment_ignored`로 버려졌다.
- `issue_comment.created`(이슈): 이슈에 `agent:open-discussion` 라벨이 있으면 누구의 댓글이든 멘션 없이 `issue_comment`다(rate limit 없음). 누구나 의견과 자료를 보태 에이전트가 이슈를 더 잘 이해하게 하는 용도다. 이 경로도 캐시된 권한 조회로 작성자의 신뢰 여부를 계산해 기록하지만 처리 여부에는 쓰지 않으며, 조회가 실패하면(`TrustUnavailable`) 경고 로그를 남기고 비신뢰로 둔다. 비신뢰 댓글은 에이전트에게 정보일 뿐 승인·지시가 아니다. 라벨이 없으면 본문에 이슈 bot 멘션(`@bulgasaribot`, 대소문자 무시, `github_bot_login`에서 `[bot]` 제외)이 있어야 한다. 멘션이 없으면 `issue_comment_ignored`, 신뢰 사용자의 멘션은 `issue_comment`, 비신뢰 사용자의 멘션은 `actor_not_allowed`다. 에이전트가 처음 보는 이슈의 댓글도 같은 규칙으로 처리한다.
- `issue_comment.created` (PR): PR 작성자 또는 신뢰 사용자의 `@haechibot` 멘션은 재리뷰를 큐에 넣는다. 별도 리뷰 App이 있을 때 `@bulgasaribot` 멘션은 관리 PR의 원본 이슈 worktree에 수동 repair 요청을 기록한다. 그 외 댓글은 무시하며, 두 번째 App이 없으면 이슈 App 멘션으로 리뷰한다.
- `issues.edited`: `changes`에 `body`나 `title`이 있을 때만 본다(그 외 `edit_ignored`). sender는 bot이 아닌 `User`여야 하고, 이슈에 `agent:open-discussion` 라벨이 있거나 sender가 신뢰 사용자여야 한다(아니면 `actor_not_allowed`). 종류는 `issue_edited`, semantic key는 `repo#issue:<n>:edited:<delivery>`이며 새 제목·본문을 넘긴다. 이슈가 `phase: implementing`(PR을 만드는 중이거나 이미 있음)일 때만 큐에 넣고 그 외는 `edit_ignored`다.
- `pull_request.opened`/`reopened`/`ready_for_review`: Draft가 아닌 PR은 `pr_review`로 분류한다(`repo#pr:<n>:review:<head_sha>`). 리뷰 App이 설정된 non-Draft PR의 `synchronize`도 같은 head별 key로 리뷰하고, 관리 PR의 상태 재조회도 예약한다. 모든 리뷰 요청은 "리뷰 요청 합치기와 취소"의 대기 리뷰 하나로 합쳐진다. dependabot·자기 App의 PR도 리뷰할 수 있다.
- bot·자기 댓글과 에이전트 marker가 있는 댓글은 `bot_sender`로 무시한다.
- 이벤트 행에는 신뢰 여부(`trusted`)를 함께 기록한다. `begin` 응답의 `event.trusted`로 n8n에 넘기면 n8n은 triage·followup 지시문과 `context.actor_trusted`에 actor의 신뢰 여부와 신뢰 규칙(신뢰 사용자의 요청만 직접 지시·승인이며 다른 사람은 권한 API로 확인)을 넣는다. `issues.opened`의 actor는 작성자다.

`agent:open-discussion` 라벨은 bridge `LABEL_CATALOG`에 없다. 공개 토론을 허용할 저장소마다 maintainer가 직접 만들고 이슈에 붙인다.

### 모드와 결과 계약

세션은 주제마다 하나이고 HAPI branch는 `hapi-<worktree>`다. 턴은 `(delivery_id, mode)`로 식별하며 HAPI 메시지 `localId`는 `issue-agent-<delivery_id>-<mode>`다. 한 delivery에서 triage 뒤 implement를 이어 실행할 수 있다. 메시지에는 대상 이슈·PR 번호와 트리거 정보만 싣는다. 이슈·댓글·PR·리뷰·스레드 같은 GitHub 내용은 에이전트가 읽기 전용 토큰으로 `gh`(REST·`gh api graphql`)를 직접 실행해 읽는다.

동시 실행: bridge dispatcher는 저장소와 무관하게 전체에서 최대 `MAX_ACTIVE_EVENTS`(5)개 이벤트에 슬롯(`dispatching`/`dispatched`)을 주고 n8n에 넘긴다. 그중 `pr_review`는 dispatcher 후보 조회의 `MAX_ACTIVE_REVIEWS`(2)로 최대 두 개만 동시에 돌고, 상한에 걸린 리뷰는 다른 이벤트의 dispatch를 막지 않는다. 리뷰는 lens별 하위 에이전트를 띄우며, 한 세션이 동시에 여는 하위 에이전트 thread는 Codex `[agents] max_threads = 2`로 제한한다(CodeGraph 1.6.2에서 하위 에이전트마다 뜨는 MCP 서버가 runner 5Gi 제한을 넘겨 2026-10-13에 3에서 낮췄다). 같은 주제(이슈·PR 번호)의 이벤트는 세션·worktree를 공유하므로 앞선 이벤트가 끝날 때까지 기다린다. 응답이 불확실한 n8n POST는 그 이벤트의 슬롯만 유지한 채 같은 이벤트로만 재시도하고, 다른 주제는 막지 않는다. `begin`은 슬롯을 가진 이벤트만 시작시킨다. 세션 생성·재개는 bridge의 `session_lock`으로, 같은 저장소 checkout clone과 push는 publisher의 저장소별 잠금으로 직렬화된다. 모든 세션은 Runner Pod 하나의 메모리 한도를 함께 쓴다.

이벤트가 `finish`로 끝나면 bridge가 그 주제의 HAPI 세션을 `archive`해 Codex 프로세스와 MCP 서버를 멈춘다. 같은 주제의 다음 이벤트는 `ensure_session`의 resume 경로로 같은 세션 ID·같은 Codex 대화를 다시 띄운다(운영 HAPI 0.30.7에서 archive → resume이 1.2초에 같은 ID로 돌아오는 것을 확인). archive 실패는 이벤트 완료를 막지 않고 로그만 남긴다. 멈추지 않으면 끝난 세션이 Runner 재시작 전까지 세션마다 수백 MB를 계속 차지한다. 주제의 세션이 바뀌면(`_follow` 체인이나 같은 주제의 새 세션) bridge는 세션 ID를 기록할 때(`_record_session`) 바뀌기 전 세션을 archive한다. 예전에는 대체된 세션이 아무도 보지 않는 채 Runner에서 계속 돌았다. `needs_attention`으로 멈춘 이벤트의 세션은 운영자 확인을 위해 archive하지 않는다. 예외는 시간 예산 park가 마감과 유예 시간을 모두 넘긴 경우(`time_budget_expired`)와 운영자가 `dismiss_event`로 이벤트를 닫은 경우다(아래 `### 오류 알림`).

Runner 컨테이너는 시작할 때 `runner-bootstrap`이 `$HAPI_HOME/runner.state.json`과 `runner.state.json.lock`을 지운 뒤 HAPI를 띄운다. HAPI는 두 파일에 적힌 PID가 살아 있는 hapi runner면 이미 실행 중이라 보고 exit 0으로 끝나는데, 컨테이너 안의 runner는 매번 같은 PID(7)를 받는다. OOM 등으로 강제 종료된 컨테이너가 남긴 두 파일 때문에 새 컨테이너가 자기 자신을 기존 runner로 착각해 CrashLoopBackOff에 빠진 적이 있다(2026-10-01). replica 1·`Recreate`이고 모든 HAPI 프로세스가 이 컨테이너 안에 있으므로 시작 시점의 두 파일은 항상 이전 컨테이너의 것이다. 세션 복구 상태인 `runner.state.json.resume-processes.json`과 `runner.state.json.verified-exits.json`은 지우지 않는다.

같은 이유로 `runner-bootstrap`은 `$CODEX_HOME/hapi-runtime-owners/`의 `*.json`(과 중단된 쓰기의 `*.json.*.tmp`)도 지운다. HAPI shared Codex 세션은 thread 소유권을 이 파일에 `{pid, ps -o lstart= marker}`로 기록하고, 다른 runtime이 같은 thread를 resume하려 하면 기록된 owner가 살아 있을 수 있는 한 "Thread belongs to another Codex runtime"으로 거부한다(`withThreadOwnership`). 이 liveness 판정은 marker 조회가 실패하면 살아 있다고 보는 fail-closed라서, 이전 컨테이너 세대의 기록이 새 컨테이너에서 재사용된 PID와 겹치면 그 thread의 resume이 계속 500 `resume_failed`로 끝났다(2026-10-13). 컨테이너 시작 시점에는 이 세대의 runtime이 하나도 없으므로 남아 있는 기록은 모두 죽은 프로세스의 것이다. thread와 HAPI 세션의 연결(cold resume에 쓰임)을 담은 `$HAPI_HOME/codex-runtimes/*.json`과 `ownership` lock 파일은 지우지 않는다. 같은 날 부하 중 새 Codex spawn이 HAPI의 기본 session webhook 제한(15초)을 넘겨 kill된 일도 있어, runner 컨테이너는 `HAPI_RUNNER_WEBHOOK_TIMEOUT_MS=60000`으로 띄운다.

`runner-bootstrap`은 시작할 때 기존 기본 클론(`/home/agent/checkouts/<owner>/<repo>`)을 fetch하고 기본 브랜치로 fast-forward한다. 기본 브랜치가 아니거나 로컬 변경이 있으면 시작하지 않는다. fast-forward가 실패했을 때 로컬 HEAD가 `origin/<default>`의 조상이 아니면(upstream force-push로 이력이 바뀐 경우) 경고를 남기고 `reset --hard origin/<default>`로 맞춘다. 에이전트는 기본 브랜치에 커밋하지 않으므로 버려지는 작업이 없고, 에이전트 브랜치·워크트리와 그 커밋은 기본 클론의 refs에 그대로 남는다. 조상인데도 fast-forward가 실패하면 원인이 다른 것이므로 시작하지 않는다. 기본 클론을 지우고 다시 받지 않는 이유는 `hapi-issue-<n>` 브랜치와 HAPI 워크트리 메타데이터가 그 클론 안에 있기 때문이다(2026-10-02 cc-lb force-push로 runner가 CrashLoopBackOff에 빠짐).

닫힌 주제의 상태는 닫힌 뒤 다음 정리 실행에서 지운다(끝난 작업의 worktree는 남기지 않는다). n8n `IssueAgentMain01`의 `Hourly cleanup`(매시 정각)이 bridge `cleanup_closed` op(`older_than_days` 기본 0 = 닫히기만 하면 대상, `dry_run` 지원)를 부른다. bridge는 세션이나 worktree가 남은 `issues` 행마다 `accepted`/`dispatching`/`dispatched` 이벤트가 있으면 건너뛰고, 이슈 App 토큰으로 `GET /repos/{repo}/issues/{n}`을 읽어 `state == "closed"`이고 `closed_at`이 기준보다 오래된 주제만 정리한다(PR도 같은 API이며 merge도 closed다). 정리는 `session_lock`을 잡고 진행 중 이벤트를 다시 확인한 뒤 ① 현재·superseded HAPI 세션마다 `codexSessionId`를 모으고 archive → `DELETE /api/sessions/{id}`(운영 HAPI 0.30.7에서 이후 GET이 404임을 확인), ② publisher `POST /cleanup`으로 worktree·admin 디렉터리·`hapi-*` branch ref(loose와 `packed-refs`)·Codex rollout 파일 삭제, ③ `issues` 행을 세션·단계가 없는 상태로 되돌리는 순서다. branch ref까지 지우는 이유는 HAPI가 branch가 남은 이름을 피해 `issue-<n>-<4hex>` 같은 새 worktree 이름을 고르기 때문이다. publisher는 에이전트가 hook·config를 심을 수 있는 checkout에서 git을 실행하지 않는다는 원칙대로 git 없이 파일 연산만 쓰고, symlink이거나 checkout·`.git/worktrees`·`CODEX_HOME` 밖으로 풀리는 경로는 거부한다. worktree 삭제(`remove_worktree`)의 세부 규칙은 다음과 같다.

- confined worktree 경로 안의 `.git`이 파일이 아니라 디렉터리이면 git worktree가 아니라 에이전트가 만든 standalone clone이므로 디렉터리째 지운다. 경로 confinement와 symlink·escape 거부는 그대로다.
- `EACCES`로 지우지 못한 항목이 에이전트 UID(1000) 소유이면 `chmod u+rwx` 뒤 다시 지운다(쓰기 권한을 뺀 디렉터리).
- 다른 UID 소유 항목(컨테이너 안에서 root 등으로 만든 파일)이 있으면 `foreign_owner` 오류(재시도 가능, HTTP 409)로 끝낸다. dockerd janitor가 소유권을 1000으로 고치면 다음 정리 실행에서 지워진다(`## Runner Docker와 DRM 장치`).

한 주제의 실패는 다른 주제의 정리를 막지 않는다. 예전에는 한 주제의 오류가 매시 정리 실행을 실패로 끝내 error workflow 알림이 매시간 반복됐다. bridge는 주제마다 연속 실패 횟수를 `issues.cleanup_failures`에 두고 성공하면 0으로 되돌린다. 응답은 `{"cleaned": [...], "errors": [...], "persistent_errors": [...]}`이고, `persistent_errors`는 연속 `CLEANUP_PERSISTENT_FAILURES`(3)회 이상 실패한 주제(`{repo, issue_number, error, failures}`)다. janitor가 소유권을 고치는 동안의 일시적 오류는 `errors`에만 남고, n8n의 cleanup 분기는 op 자체가 실패했거나 `persistent_errors`가 비어 있지 않을 때만 `Cleanup failed`로 가서 그 내용을 error workflow에 보인다. GitHub 내용과 `events` 기록은 지우지 않으며, 정리된 주제의 다음 이벤트는 `session_state = none`에서 새 세션을 spawn한다.

Docker maintenance lease: `dry_run`이 아닌 정리가 끝날 때마다 bridge는 publisher `GET /janitor/status`(다른 publisher endpoint와 같은 인증)로 janitor 상태를 읽는다. 상태의 `checked_at`이 900초 안이고 `docker_used_pct`가 70을 넘으며 idle일 때만 maintenance를 요청한다. idle은 `dispatching`/`dispatched` 이벤트가 없고, `park_class = "time_budget"`인 `needs_attention` 이벤트가 없으며(그 턴은 아직 돌 수 있다), HAPI Hub 세션 목록에 thinking 중이거나 `agentState` 요청이 남은 세션이 없다는 뜻이다. 조건이 맞으면 bridge는 `maintenance_until = now + 1200`을 bridge DB `bridge_state`에 기록하고(재시작해도 남는다) `POST /janitor/prune-request`에 `{"lease_until": maintenance_until}`를 보낸다. 응답의 `prune_requested`와 `maintenance_until`이 결과를 알린다. `maintenance_until` 전까지 dispatcher tick은 새 이벤트를 dispatch하지 않고 `maintenance` 상태를 돌려준다. stale dispatch 감지와 늦은 결과 수거는 그대로 돈다. 따라서 dispatch hold는 Docker 사용률이 70%를 넘고 idle일 때만 생기며 최대 20분이다. dispatcher tick이나 정리 sweep에서 status의 `last_prune_lease`가 `maintenance_until`과 같으면(이 lease의 prune이 끝남) bridge가 `maintenance_until`을 지워 hold를 일찍 푼다. publisher는 `lease_until`이 없는 요청을 거부하고, `{"requested_at": <epoch>, "lease_until": <epoch>}`를 dockerd가 보는 `/home/agent/checkouts/.issue-agent-janitor/prune-request`에 원자적으로, symlink를 따라가지 않고 쓴다. `GET /janitor/status`는 같은 디렉터리의 `status`를 돌려주며, 파일이 없거나 해석할 수 없거나 symlink이면 `no_status` 오류를 낸다.

| mode | 시작 조건 | worktree | 스킬 | 결과 |
|---|---|---|---|---|
| `triage` | `issue_opened`, 또는 구현 단계가 아닌 이슈의 `issue_comment` | `issue-<n>` | `isac-issue-triage` | TriageResult |
| `implement` | TriageResult `next_action: implement`(같은 n8n 실행·같은 세션) | `issue-<n>` | `isac-issue-to-pr` | ImplementResult |
| `followup` | 구현 단계(`phase: implementing`) 이슈의 `issue_comment` 또는 `issue_edited` | `issue-<n>` | `isac-issue-to-pr` + `receiving-code-review` | ImplementResult |
| followup (PR repair) | 현재 head의 CI·리뷰·base blocker 또는 명시적 repair 댓글 | `issue-<n>` | 원본 이슈 범위, `receiving-code-review` | ImplementResult |
| `reopen_check` | 비신뢰 사용자의 닫힌 이슈 댓글 `closed_issue_comment`(단계와 무관) | `issue-<n>` | 없음(지시문의 재개 기준) | ReopenResult |
| `review` | `pr_review` | `review-pr-<n>` | `isac-pr-review` | ReviewResult |

에이전트는 턴 끝에 `ISSUE_AGENT_RESULT <nonce> {json}` 한 줄을 낸다. `session_send`가 메시지에 nonce와 해당 모드의 정확한 스키마를 넣고, `context`(트리거 정보나 triage 결과 같은 작은 보조 데이터, 200KB 이하)는 신뢰하지 않는 데이터로 fence한다. `session_turn`이 턴 모드의 스키마로 결과를 검증한다(모든 필드 필수, 알 수 없는 키 거절).

턴 시간 예산은 bridge가 정한다. `session_send`가 단계를 보낼 때 `turns.deadline_at`을 지금 + 모드별 예산(`TURN_BUDGET_SECONDS`: triage·reopen_check 1시간, review 2시간, implement·followup 6시간)으로 기록한다. 같은 턴을 다시 보내 `already`가 돌아올 때는 마감을 다시 정하지 않는다. 단계 메시지에는 절대 UTC 마감 시각과 함께, 커밋하고 결과 줄을 낼 시간을 15분 이상 남기고 끝낼 수 없으면 마감 전에 `blocked`나 부분 결과를 보고하라는 지시가 들어간다. `session_turn`은 결과가 없고 에이전트가 아직 일하는 중인데 마감이 지났으면 `{"state": "expired", "session_id", "detail": "agent turn still running at the bridge deadline <iso>"}`를 돌려준다. 그 밖의 상태는 그대로다. n8n은 턴마다 120초 간격으로 확인하고, `Within time budget?`은 상태가 `expired`가 아니고 `$runIndex < 720`(약 24시간, 마감 판단이 아닌 안전 상한)인 동안만 반복한다. 벗어나면 기존 `Return failure`로 `Within time budget? (<lane>)` 노드 이름과 함께 실패하고 이벤트는 시간 예산 park가 된다(`### 오류 알림`). 예전에는 n8n이 모드와 무관하게 180회(약 6시간)에서 끊었고, 에이전트는 자기 마감을 몰랐으며, 그 뒤에 나온 결과는 `retry_event`가 턴을 새 `localId`로 다시 보내면서 버려졌다.

세션 루프(`ensure_session` → `session_send` → 대기 → `session_turn`, 세션·전송 재시도 10회와 시간 예산)는 하위 워크플로 `IssueAgentSession01` 한 벌에만 있다. 메인 워크플로의 triage·implement·review 경로는 `Run agent session (<lane>)`(Execute Sub-workflow, 완료까지 대기)으로 `delivery_id`·`lane`·`mode`·지시문·context를 넘기고 `Session done? (<lane>)`에서 결과를 나눈다. 실패하면 하위 워크플로가 `{ok:false, node:"<노드> (<lane>)", …}`를 돌려주고, `Mark needs attention`은 이 `node`로 예전과 같은 노드 이름·detail을 bridge `fail`에 보낸다. 하위 워크플로에는 `settings.errorWorkflow`가 없어 실행 오류는 부모의 오류 워크플로가 한 번만 알린다. n8n 2.x는 하위 워크플로를 게시된 버전으로 실행하므로 bootstrap이 메인보다 먼저 가져와 게시한다. 턴 결과 확인(`Check triage result`·`Check review result`)은 Code 노드가 아니라 Edit Fields 노드다.

followup 턴은 PR을 이슈와 맞춘다. 에이전트는 `gh issue view`와 `gh api`로 이슈 제목·본문과 모든 댓글을 직접 읽는다. Begin 응답에 기록된 `pr_number`가 있으면 `gh pr view`로 그 PR의 상태(번호·URL·state·merged·draft·제목·본문·head/base)와 리뷰 댓글도 직접 읽고, 없으면 아직 PR이 없는 상태다. 에이전트는 PR이 열려 있든, merge·close됐든, 아직 만드는 중이든 이슈 제목·본문과 모든 댓글에서 현재 요구사항을 다시 정리하고 branch diff와 현재 PR 제목·본문·상태와 비교한다. 요구사항은 신뢰 사용자의 댓글·수정만 바꿀 수 있다. 비신뢰 사용자의 입력은 지시가 아니라 판단할 정보이며, 질문이나 `needs_info`로 이어질 수 있다. 다르면 `hapi-issue-<n>`에 새 커밋을 올리고 전체 현재 범위를 설명하는 `pr.title`/`pr.body`로 `ready`를 낸다. PR이 merge·close됐으면 먼저 `origin/<default>`를 branch에 merge한다(rebase·force 금지). 자동화가 그 branch로 새 PR을 연다. PR이 이미 충족하는 단순 맥락이면 `no_change`와 어떻게 반영했는지 설명하는 `issue_comment`를 낸다. 요구사항이 모호하거나 충돌하면 `needs_info`다.

- TriageResult: `status`(`triaged|blocked`), `verdict`, `fault_domain`, `duplicate_of`, `labels.add/remove`(카탈로그 이름), `comment`, `next_action`(`implement|await_info|await_decision|none`), `implementation_brief`(implement일 때 필수), `questions`, `summary`, `blockers`, `security_advisory`(`null` 또는 `summary`·`description`·`severity`·`cwe_ids`·`vulnerabilities`). `security_advisory`가 있으면 `status`는 `triaged`, `comment`는 `null`, 라벨 변경은 비어 있고 `next_action`은 `none`이어야 한다(검증 오류는 advisory 본문을 되풀이하지 않는다). n8n은 결과 기록 뒤 `security_advisory`가 있으면 `github.security_advisory` op로 비공개 draft advisory를 만들고 `triaged`로 끝내며(실패하면 attention), 라벨·댓글 단계는 건너뛴다. 그 밖에는 라벨 적용 → 분석 댓글 게시 후 `next_action`으로 분기한다. `implement`면 brief를 implement 턴으로 넘기고, 질문이면 `questioned`, 그 외는 `triaged`로 끝난다. `blocked`는 attention이다.
- ImplementResult: `status`(`ready|no_change|needs_info|blocked`), `pr{title, body}`(ready일 때 필수, 본문에 `Fixes #<n>` 또는 `Related to #<n>`), `issue_comment`, `questions`, `summary`, `blockers`, `local_checks`(로컬에서 돌린 CI 게이트 명령과 종료 코드, 최대 30개, ready면 비어 있지 않고 모두 0). 커밋 SHA 필드는 없다. `head_sha`를 넣은 결과는 다른 모르는 키처럼 거부되고 교정 요청으로 돌아간다. 에이전트는 `ready` 전에 모든 변경을 `hapi-issue-<n>`에 로컬 커밋만 한다. `ready`면 n8n이 `git.push` → `github.pr_upsert`(`git.push`가 돌려준 `sha`를 head로 쓴다. 열린 PR이 없으면 기본 브랜치 대상 일반 PR 생성, 있으면 제목·본문 PATCH) → 이슈에 PR 링크 댓글 → `implemented`. `git.push`는 publisher `POST /resolve {repo, branch}`로 branch head를 읽고, `pr_repair`면 그 head로 superseded 검사(원격 head가 이벤트 head나 읽은 head가 아니거나 PR이 닫혔으면 push하지 않음)를 한 뒤, `POST /push {repo, branch, expected_sha=읽은 head}`(non-force)를 부른다. `/push`는 branch를 다시 읽어 `expected_sha`와 다르면(조회와 push 사이에 branch가 움직이면) `sha_mismatch`로 거부한다. 요청에 남은 `head_sha`(배포 전 기록된 실행의 재시도)는 무시한다. 이미 push된 head의 재시도는 같은 커밋을 다시 push하므로 멱등이다. `no_change`는 이슈 댓글, `needs_info`는 질문 댓글과 `triage:needs-info` 라벨, `blocked`는 attention이다. implement/followup 전송 시 이슈 phase는 `implementing`이 된다.
- ReviewResult: `status`(`reviewed|blocked`), `head_sha`, `event`(`APPROVE|REQUEST_CHANGES|COMMENT`), `body`, `comments`(새 inline 지적, 최대 50), `thread_replies`(기존 스레드 comment ID에 대한 답글과 `resolve`, 최대 100. 새 head에서 finding 상태가 바뀐 미해결 스레드와 봇의 마지막 댓글 뒤에 사람이 댓글을 단 스레드에만 낸다), `summary`, `blockers`. n8n은 context로 PR 번호와 이벤트 head(`head_sha`, 없으면 에이전트가 `gh`로 현재 head를 읽는다)만 넘긴다. 에이전트는 `gh`와 `gh api graphql`로 PR 제목·본문·파일·리뷰·댓글, 리뷰 스레드(스레드 `isResolved`와 댓글 `databaseId`·`author{login}`·`createdAt` 포함, `thread_replies`의 대상 선택과 comment ID에 필요)와 연결 이슈·그 댓글을 직접 읽는다. Begin 응답의 `reviewer_login`이 남긴 이전 리뷰가 있으면 재리뷰다. `github.review`는 리뷰 App(`haechibot[bot]`) 토큰으로 동작하며, 라운드마다 GitHub 리뷰 하나만 게시한다: 이전 실행이 남긴 리뷰 App의 pending 리뷰가 있으면 먼저 지우고, GraphQL pending 리뷰 하나에 새 inline 지적(새 스레드)과 스레드 답글을 담아 `commit_id=head_sha`로 판정 이벤트·본문과 함께 제출한 뒤, `resolve`로 표시된 스레드를 resolve하고 `issue-agent/review` 상태(APPROVE → success, 그 외 failure)를 남긴다. 이미 resolve됐고 스레드 안 봇(리뷰 App·이슈 App 봇 계정)의 마지막 댓글 뒤에 사람 댓글이 없는 스레드에 대한 답글은 WARNING 로그를 남기고 버리며, 리뷰는 실패시키지 않는다. 예전처럼 답글마다 REST replies API를 부르면 GitHub가 답글마다 빈 `COMMENTED` 리뷰를 만든다(cc-lb#936: 답글 하나짜리 리뷰 184개, 그중 139개가 resolve된 스레드에 반복한 "Closed at …"). PR head가 `head_sha`와 다르면(취소 전에 제출된 리뷰 중 push) 리뷰는 그대로 `head_sha`에 제출하되 본문 첫머리에 stale 안내(리뷰 App이 있으면 push가 새 head 리뷰를 예약했다는 문장, 없으면 재리뷰 명령)를 넣고 상태는 남기지 않는다. force-push로 `head_sha`가 PR에서 빠져 422가 나면 판정·지적을 marker 댓글로 남긴다. 둘 다 성공으로 끝나며 attention을 만들지 않는다. 모두 숨은 marker 또는 기존 상태 비교로 멱등이다. inline 지적이 422로 거절되면 본문의 "Findings outside the diff" 절로 옮겨 다시 제출한다. 재리뷰 본문의 첫 절은 이전 지적의 Closed/Open 상태이고, 라운드별 상태 기록은 이 절이 맡는다. bridge가 제출하는 리뷰 본문과 `pr_review` 이벤트의 attention 댓글 끝에는 항상 같은 footer 블록이 붙고 에이전트는 body에 footer를 쓰지 않는다:
- ReopenResult: `status`(`reopen|keep_closed|blocked`), `reason`(비어 있지 않은 영어 내부 근거, 최대 1000자), `comment`(`reopen`일 때만 1-4000자 영어 markdown, 그 외 `null`), `summary`(최대 2000자), `blockers`(최대 10개·각 500자, `blocked`일 때만 비어 있지 않음). `reopen`은 댓글이 닫힌 이슈 자신의 요청이 아직 충족되지 않았음을 보일 때만이다(수정이 들어간 버전에서도 재현, 전달된 변경이 이슈 요청과 다르거나 불완전, 같은 문제의 회귀, 닫은 이유였던 빠진 사실의 제공). 감사·확인, 질문, 수정 릴리스보다 오래된 버전의 보고(krema#90 댓글 6114744450, 0.11.0), 설정·오용, 다른 요청, 새 사실 없는 not-planned·duplicate 반박은 `keep_closed`다. `session_turn`은 이 모드에서 이슈 단계를 바꾸지 않는다.

  ```
  ---
  <sub>Every push to this pull request is reviewed automatically. To request another review without pushing, after replying to the findings, comment `@haechibot review`. The same comment restarts a review that stopped with an error. The pull request author or a maintainer can request it.</sub>
  ```

  리뷰 App이 없으면 push가 리뷰를 시작하지 않으므로 footer는 push나 답글 뒤 `@<app> review` 댓글을 달라고 안내한다.

  footer의 bot login은 설정값(`GITHUB_REVIEW_BOT_LOGIN`의 `[bot]` 제외)이며 코드에 하드코딩하지 않는다.

  리뷰 본문 첫 줄에는 bridge가 marker `<!-- issue-agent:<delivery>:review:<sha> -->`를 붙인다(`<sha>`는 리뷰한 head). `issue-agent/review` 상태는 게시된 리뷰의 SHA가 현재 head와 같을 때만 남긴다.

  ReviewResult에는 `open_items`(문자열 배열, 최대 20개·각 200자)도 있다. event가 COMMENT나 REQUEST_CHANGES일 때만 허용되며 비어 있어도 된다(대체된 조언 같은 정보성 COMMENT). 에이전트 자신의 COMMENT가 결정 사항, 미확인 P0–P2 의심, 덮이지 않은 lens 때문이면 이유마다 한 항목을 적는다(`### 리뷰 판정 정책`). bridge가 `_review()`에서 검증한다.

  decision 댓글: 에이전트 자신의 event가 COMMENT이고(stale 안내나 자기 PR downgrade로 바뀐 COMMENT는 제외) `head_sha`가 live head이며 `open_items`가 비어 있지 않으면, bridge는 리뷰 App으로 project owner(없으면 저장소 owner)를 멘션해 maintainer가 답하고 `@haechibot review`를 달 때까지 merge가 막혀 있다고 알리는 댓글을 남긴다. marker `review-decision:<n>:<정규화·정렬한 open_items의 hash>`와 기존 `_comment` marker lock으로 같은 PR의 같은 항목 집합에는 head가 바뀌어도 한 번만 남긴다. 게시 실패는 재시도할 수 있다. COMMENT로 끝난 리뷰가 아무 안내 없이 merge를 막는 막다른 상태를 없애기 위해서다.

라벨은 bridge `LABEL_CATALOG`의 이름만 허용한다(목록은 README `#### 라벨`). 저장소에 없으면 카탈로그 설명·색으로 만들고, 같은 그룹(`repro:*`, direction, kind) 라벨을 추가하면 나머지를 같은 op에서 제거한다. `agent:needs-attention`은 bridge만 다룬다.

`github.security_advisory` op는 요청에 `delivery_id`만 받고 advisory 내용은 그 이벤트의 기록된 `triage_result` 단계에서 읽는다(기록에 advisory가 없으면 재시도하지 않는 오류). issue App 토큰으로 `POST /repos/{repo}/security-advisories`에 draft를 만들고, 설명 끝에 출처 이슈·delivery를 적은 marker 줄을 붙인다. 이벤트에 `advisory` 단계가 이미 있거나 draft·triage 상태 advisory 목록에서 같은 marker를 찾으면 새로 만들지 않고 그것을 돌려준다(`already: true`). 결과 `{ghsa_id, html_url}`은 `advisory` 단계에 기록한다. 오류 메시지는 HTTP 상태와 GitHub `message`만 담아 공개 attention 댓글에 advisory 내용이 새지 않게 한다(5xx·429는 재시도 가능).

`reopen_check` 흐름: n8n `Route by mode`의 `reopen_check` 출력은 먼저 `Reopen guard`(bridge `github.issue_reopen` `apply: false`)를 부르고, 대상이 아니면 `no_change`로 finish한다. 대상이면 triage와 같은 방식으로 읽기 전용 토큰·GitHub 쓰기 금지·비신뢰 댓글 fence를 담은 지시문으로 `reopen_check` 턴을 실행하고 결과를 `reopen_result` 단계에 기록한다(이미 기록돼 있으면 재시도에서 턴을 건너뛴다). `reopen`이면 `github.issue_reopen` `apply: true`를 부르고, `changed`면 `github.comment`(purpose `reopen`, 본문은 `comment`)를 남긴 뒤 `reopened`, 바뀌지 않았으면 `no_change`로 finish한다. `keep_closed`는 GitHub에 아무것도 쓰지 않고 `kept_closed`로 finish하며, `blocked`는 기존 needs-attention 경로로 간다.

`github.issue_reopen` op는 `delivery_id`·`apply`만 받고 `closed_issue_comment` 이벤트에만 쓴다(그 외 오류). 이벤트에 `issue_reopened` 단계가 이미 있으면 GitHub 호출 없이 `{eligible: true, changed: true, reason: "reopened_by_event"}`를 돌려준다(재시도 멱등). 아니면 이슈 App 토큰으로 이슈와 댓글을 읽는다. 이슈가 열려 있고 `issue_reopen_intent` 단계는 있는데 `issue_reopened` 단계가 없으면(PATCH는 적용됐지만 응답을 잃은 재시도) 이슈 이벤트를 읽어, `closed`·`reopened` 이벤트 중 가장 최근 전환(`created_at`이 같으면 목록 순서상 뒤)이 이슈 App의 `reopened`이고 intent 시각(GitHub·bridge 시계 차이 `REOPEN_CLOCK_SKEW_SECONDS` 허용) 이후일 때만 성공으로 마무리한다. `issue_reopened` 단계 기록과 `phase` `none` 전환을 한 트랜잭션으로 하고 `{eligible: true, changed: true, reason: "reopened_by_event"}`를 돌려주며, `apply: false`에서도 같다. 이 복구는 아래 비대상 이유보다 먼저 판단한다. 그 뒤 대상이 아니면 `comment_deleted`(댓글 404), `already_open`(이미 열림. bot의 이전 재개 뒤 maintainer가 닫았다가 다시 연 경우도 여기에 든다), `closed_after_comment`(댓글 뒤 maintainer가 다시 닫음, `closed_at` > 댓글 `created_at`) 순서로 첫 이유를 `eligible: false`로 돌려준다. maintainer의 재종료는 덮어쓰지 않는다. `apply: false`면 `reason: "eligible"`만 돌려준다. `apply: true`면 판정을 요청이 아니라 기록된 `reopen_result` 단계에서 읽어 `status`가 `reopen`일 때만(아니면 `no reopen verdict` 오류) `issue_reopen_intent` 단계(시각)를 먼저 기록하고 `PATCH /repos/{repo}/issues/{n}` `{"state": "open"}`을 보낸 뒤, `issue_reopened` 단계 기록과 bridge `issues` 행의 `phase`를 `none`으로 되돌리는 일을 한 트랜잭션으로 한다. 다음 댓글은 처음 보는 열린 이슈처럼 triage부터 시작한다.

### 오류 알림

에이전트를 실행하는 모든 경로는 GitHub에 보이는 상태로 끝난다. 실패는 bridge `mark_attention`으로 모인다. 입구는 워크플로의 `Mark needs attention`(`fail`), n8n 오류 워크플로 `IssueAgentError01`(Error Trigger → `fail_execution`, 메인 워크플로 `settings.errorWorkflow`), bridge 자체 포기(dispatch 8회 실패, stale dispatch, n8n 응답 없음)다. `mark_attention`은 이벤트를 `needs_attention`으로 두고 해당 이슈/PR을 block한 뒤, 멈춘 노드·단계, 이벤트 종류, delivery ID, n8n 실행 링크, HAPI 세션 링크, `retry_event` 방법을 담은 댓글과 `agent:needs-attention` 라벨을 붙인다. attention 댓글·라벨은 이벤트가 `pr_review`면 리뷰 App(`haechibot[bot]`)으로 게시하고 위의 재리뷰 footer도 붙이며, 그 외 이벤트는 작성 App(`bulgasaribot[bot]`)으로 게시한다. 둘 다 적용될 때까지 backoff 후 재시도한다. 자동 재실행은 아래 일시적 `pr_review` park, 모든 이벤트의 `provider_error` park, 시간 예산 park의 늦은 결과 수거에만 한다. 운영자는 `retry_event`(기록된 단계부터 재개), `unblock_issue`(이후 이벤트만 진행), `dismiss_event`(더 처리하지 않을 이벤트를 닫음)로 푼다. 성공한 `finish`와 `dismiss_event`는 `agent:needs-attention`을 제거한다.

- 오류 응답과 `park_class`: bridge ops 오류 응답은 `{"ok":false,"error","retryable","needs_operator","park_class"}`다. `park_class`는 `bridge_unreachable`, `hub_5xx`(dispatch와 `_resume` 실패 포함), `hub_unreachable`, `stale_dispatch`(세션 프로세스가 사라짐, Runner·hub·n8n·bridge 재시작 포함), `provider_error`(아래 모델 provider 오류), `time_budget`·`time_budget_expired`(아래 시간 예산 park) 중 하나이며 bridge나 n8n만 정하고 에이전트 출력에서 오지 않는다. `fail`은 `park_class`를 받아 `mark_attention`에 기록하고 모르는 값은 무시한다. `time_budget`은 n8n이 보내지 않고 bridge가 정한다: `fail`의 노드 이름이 `Within time budget?`으로 시작하거나 `session_turn`이 `expired`를 돌려준 턴이면 이 class로 park한다. n8n은 bridge 호출 노드의 HTTP 오류 출력을 Code 노드(`Normalize … error`)로 `{ok:false, retryable, park_class, error}`로 정규화한다. bridge에 닿지 못한 transport 오류는 `retryable`과 `bridge_unreachable`이고, 그 밖의 HTTP 오류는 영구 오류(`retryable: false`, 빈 `park_class`)다. bridge가 돌려준 오류 응답의 `park_class`는 그대로 전달한다. 세션 하위 워크플로의 정규화 결과는 기존 Session status·Send status·Turn state 분기로 들어간다.
- 일시적 park의 자동 재시도: `pr_review` 이벤트가 위 class로 멈추면 `auto_retries`·`auto_retry_at`을 기록하고 10·30·90분 뒤 최대 3회(`stale_dispatch`는 1회) 같은 이벤트를 다시 진행한다. 조건은 PR이 열려 있고 Draft가 아니며 head가 그대로이고 그 PR에 다른 진행 중·멈춘 이벤트가 없는 것이다. 이미 답한 턴은 결과를 다시 읽어(같은 `localId`) 검증을 통과하고 `head_sha`가 live head일 때만 게시한다. 답하지 않은 턴은 아직 thinking이 아니면 `lost`로 표시해 같은 세션에 다시 보내며, 세션의 machine을 hub가 모르면 기존 `ensure_session`의 orphan 경로가 새 `localId`로 다시 보낸다. 새 이벤트를 만들지 않고 같은 parked 이벤트를 다시 진행하며, 이 이벤트가 주체의 유일한 blocker일 때만 `issues.blocked`를 푼다. 스키마 검증에 실패한 결과는 자동 재시도하지 않고, 리뷰가 아닌 이벤트는 아래 `provider_error`만 자동 재시도한다.
- 모델 provider 오류(`provider_error`): upstream이 429·5xx를 돌려주면 Codex가 자체 재시도 뒤 턴을 끝내고(`task_failed`), HAPI는 이를 `Codex error: …` 에이전트 메시지(`localId`가 `:task_failed`로 끝남)로 남긴 채 idle이 된다. `session_turn`은 결과 줄 없이 idle인 턴의 마지막 에이전트 텍스트가 이런 메시지이고 문구가 일시적 오류(`exceeded retry limit, last status: 429|5xx`, `unexpected status 429|5xx`, `stream disconnected before completion`(content_filter 제외), `rate limit exceeded`, `Selected model is at capacity`, `experiencing high demand`, `Codex thread entered systemError`, `Connection failed`, `Error while reading the server response`, `request timed out`, `Flex capacity unavailable`)이면 `IDLE_WITHOUT_RESULT_LIMIT`를 기다리지 않고 턴을 새 `localId`의 `lost`로 바꾸고 `park_class: provider_error`인 `attention`을 돌려준다. n8n이 이 class를 `fail`에 넘기면 이벤트 종류와 관계없이 10·30·60·120분 뒤 최대 4회 같은 이벤트를 다시 진행해 `LOST_TURN_NOTICE`와 함께 다시 보내고, 그 뒤에는 운영자 몫이다. 리뷰가 아닌 이벤트는 같은 주체에 실행 중(`dispatching`·`dispatched`)인 다른 이벤트가 없을 때만 다시 진행한다. sub-agent의 실패(`agent-run-trace`)와 사용량·quota·context window·정책·4xx 오류는 예전처럼 idle 경로로 운영자에게 간다.
- 시간 예산 park와 늦은 결과 수거: dispatcher tick은 `park_class`가 `time_budget`인 `needs_attention` 이벤트 가운데 턴이 `sent` 상태인 것을 본다. 에이전트가 마감 뒤에라도 답했으면(`_answered_result`가 `answered`) `retry_event`와 같은 방식으로 이벤트를 다시 진행하되 턴은 `sent`와 같은 `localId`로 둔다. 그러면 n8n의 `session_send`는 `already`를, `session_turn`은 그 결과를 돌려주고, 워크플로가 push·PR·마무리를 하며 `finish`가 attention 라벨을 지운다. 답이 없는 채 마감 + `TURN_GRACE_SECONDS`(1시간)가 지나면 HAPI 세션을 archive하고 `park_class`를 `time_budget_expired`로 바꾼다. 이벤트는 운영자를 위해 `needs_attention`으로 남는다. 유예 시간의 기준은 늘 `turns.deadline_at`이다. 이전 스키마에서 남아 `deadline_at`이 NULL인 턴은 이 검사가 처음 볼 때 그 시각(park 시각)을 `deadline_at`에 기록해 기준을 고정한다. `ev.updated_at`은 다른 갱신마다 바뀌어 유예가 끝없이 밀릴 수 있으므로 쓰지 않는다.
- `retry_event`의 턴 처리: 답했지만 결과가 소비되지 않은 턴(그 모드의 결과 단계가 `stages`에 없음)은 `sent`와 같은 `localId`를 유지해 결과를 수거한다. 결과가 이미 소비된 답한 턴과, 더는 결과를 낼 수 없는 미응답 턴(정말 idle이어서 idle 규칙으로 park된 턴, provider 오류로 끝난 턴, 세션·프로세스가 죽은 턴)은 새 `localId`와 `lost`로 다시 보낸다. 예전에는 미응답 턴도 `localId`를 유지해 다시 진행한 `session_turn`이 같은 idle 턴을 읽고 곧바로 다시 park했다. 반대로 도구 호출 사이 순간 `thinking`이 꺼진 것처럼 보여 `unanswered`로 읽힌 살아 있는 턴은 `localId`를 유지해 두 번 보내지 않는다. 턴 조회가 일시적으로 실패하면 `retry_event`는 `retryable` 오류로 끝나고 이벤트는 park 상태로 남는다. 소비되지 않은 `sent` 턴이 있으면 `begin`의 `mode_hint`는 그 턴의 모드여서, 다시 진행한 implement가 followup으로 바뀌지 않는다.
- stale dispatch: `dispatched` 이벤트의 `heartbeat_at`이 `STALE_SECONDS`(30분) 넘게 갱신되지 않으면 dispatcher가 `stale_dispatch`로 park한다. heartbeat는 `begin`과 그 `delivery_id`를 가진 모든 live op(`ensure_session`, `session_send`, 120초마다 오는 `session_turn`, 단계 기록, `github.*`, `git.push` 등)가 갱신한다. op 사이 가장 긴 간격은 checkout(600초)과 spawn을 합친 약 15분이라 건강한 긴 턴은 park되지 않는다. 예전 기준 6시간은 n8n 재시작으로 잃은 실행을 6시간 뒤에야 알렸다.
- lost turn 안내: 잃어버린 턴을 다시 보낼 때 bridge는 메시지에 `LOST_TURN_NOTICE`를 붙인다. 에이전트는 head SHA와 도구 환경을 다시 확인하고, 끊긴 실행의 결론·관찰·명령 결과를 재사용하지 않고 증거를 다시 모은다.
- 리뷰 status: 멈추거나 포기한 리뷰는 `issue-agent/review`를 `pending`이 아니라 `error`("review did not complete; will retry" 또는 "needs operator")로 남긴다. 이미 게시된 판정은 덮지 않는다.
- n8n 재시도: Ensure session·Send step은 엔진 재시도(5회×5초) 뒤 오류 출력으로 기존 재시도 loop에 들어간다. Check turn은 엔진 재시도 없이 transport 오류를 기존 120초 대기 loop로 보낸다. Submit review·Finish reviewed는 엔진 재시도 뒤 응답이 없거나 `retryable`이면 60초 기다려 최대 10회 다시 부르고, 아니면 `Mark needs attention`으로 간다. Begin은 재시도하지 않는다. 오류 워크플로의 `Fail execution`은 `maxTries` 5다.
- bridge probe: `deployment-bridge.yaml`의 readiness·liveness probe는 `timeoutSeconds: 5`다. 기본 1초 timeout이 bridge 재시작을 일으켰다.
- `dismiss_event`: 더 처리할 필요가 없는 멈춘 이벤트(주제가 이미 닫히거나 머지됨, 같은 일을 다른 이벤트가 끝냄 등)를 닫는다. 요청은 `{"op":"dismiss_event","delivery_id":"<delivery-id>","reason":"<1~2000자>"}`이고 `needs_attention` 이벤트에만 쓴다(그 외 상태는 `not_needs_attention`, 재시도 불가). 이벤트를 `completed`·outcome `dismissed`·detail = `reason`으로 두고, 다른 멈춘 이벤트가 없으면 주제의 block을 풀고, attention을 게시한 App으로 `agent:needs-attention` 라벨을 지우고(`pr_review`는 리뷰 App), 턴의 HAPI 세션이 있으면 archive한다. 이벤트가 `prs.active_delivery`(PR repair lease)를 쥐고 있으면 정상 종료와 같이 lease를 풀고 PR을 dirty로 표시한다. 시도한 key 기록은 그대로 두므로 같은 시도를 되풀이하지 않고, 다음 reconcile이 새 lease를 잡을 수 있다. 종료 전환과 라벨 제거는 attention notifier와 같은 `("attention", delivery_id)` lock 안에서 하고, 라벨을 붙일 예정인 notifier 상태도 그 안에서 지우므로 dismiss 뒤에 라벨이 다시 붙지 않는다. 이미 dismiss된 이벤트에는 `{"ok":true,"already":true}`, 처음 닫으면 `{"ok":true,"already":false}`를 돌려준다. 호출은 다른 운영자 op와 같이 bridge Pod 안에서 ops 토큰으로 `/ops`에 POST한다.

```bash
kubectl --context homelab-backbone -n issue-agent exec deploy/issue-agent-bridge -c bridge -- python -B -c '
import json, sys, urllib.request
token = open("/run/issue-agent/ops/bridge-ops-token").read().strip()
req = urllib.request.Request("http://127.0.0.1:8080/ops", sys.argv[1].encode(),
                             {"Content-Type": "application/json", "Authorization": "Bearer " + token})
print(urllib.request.urlopen(req).read().decode())
' '{"op":"dismiss_event","delivery_id":"<delivery-id>","reason":"subject closed; nothing left to do"}'
```

## Runner Docker와 DRM 장치

Runner Pod는 저장소 테스트가 Docker 이미지를 build하고 컨테이너를 실행할 수 있도록 Pod 전용 Docker daemon을 둔다. daemon에 privileged 컨테이너가 필요하므로 runner·publisher·dockerd는 `issue-agent-runner` namespace에서 실행한다. 이 namespace만 Pod Security `privileged`를 enforce하고 audit·warn은 `restricted`로 두어, dockerd 외의 위반도 audit 기록과 경고로 남긴다. hub·n8n·bridge는 `restricted`를 enforce하는 `issue-agent`에 남는다.

- Pod 구성: runner, publisher, native sidecar `dockerd`와 `model-proxy`(Caddy, `### 자동 머지와 실행 격리의 한계`의 E2)가 한 Pod에 있다. Deployment는 replica 1과 `Recreate`를 유지하며 replica를 늘리지 않는다. publisher Service는 `issue-agent-publisher.issue-agent-runner`이고, runner는 `issue-agent`의 Hub에 접속한다.
- 권한: `dockerd`만 root·privileged(seccomp `Unconfined`)로 실행한다. runner와 publisher는 UID 1000이며 모든 capability를 제거하고 권한 상승을 막는다. daemon은 TCP listener 없이 Unix socket만 열고, socket은 root:1000 0660이다.
- 마운트: daemon은 home PVC의 `checkouts` subPath(`/home/agent/checkouts`), runner와 공유하는 `/tmp` emptyDir, socket 디렉터리, Docker 데이터 PVC(`/var/lib/docker`), native DRM 장치 두 개만 마운트한다. home root(`CODEX_HOME`, `HAPI_HOME`)와 Secret은 마운트하지 않는다. checkout과 `/tmp`는 runner와 daemon에서 경로가 같으므로, 이 두 경로 아래 파일만 bind mount와 build context로 쓸 수 있다.
- cgroup: `dockerd-start`는 컨테이너 cgroup을 경계로 둔다. `/proc/self/cgroup`이 `0::/`인 private cgroup namespace면 바로 쓰고, host cgroup namespace를 공유해 scope가 node 경로(`/kubepods…/cri-containerd-…scope`)로 보이면 그 scope의 유한한 `memory.max`를 먼저 확인한 뒤 `unshare --cgroup --mount --propagation private`로 재실행하고 `/sys/fs/cgroup`에 cgroup2를 remount한다. 그래도 격리된 보기를 만들 수 없으면 daemon을 띄우지 않는다. 컨테이너는 cgroupfs driver와 `--cgroup-parent=/issue-agent-docker`로 자기 scope 아래에 생기므로 Pod 메모리 제한을 넘지 못한다. `unshare`는 BusyBox에 없어 이미지에 `util-linux-misc`를 넣는다. dockerd는 `/usr/local/bin/dind docker-init` 경유로 띄워 DinD의 mount 준비와 PID 1 zombie 수거를 쓰고, legacy iptables로 바꿀 수 있는 stock `dockerd-entrypoint`는 거치지 않는다.
- DRM 장치: Pod는 host의 `/dev/dri/card0`·`/dev/dri/renderD128`만 `CharDevice` hostPath 두 개로 받는다(`macmini`는 `asahi`, `rock5bp`는 `rockchip-drm`). `rock5bp`의 RKNPU `card1`·`renderD129` 같은 다른 DRM node는 Pod에 넣지 않는다. runner는 두 장치를 `/dev/dri` 아래에 read-only로 마운트한다. privileged 컨테이너의 runtime은 volume mount 뒤에 host device 전체로 `/dev`를 채우므로 `/dev/dri`를 직접 가리면 다시 채워진다. 그래서 dockerd는 raw emptyDir `/run/issue-agent-dri`(`/dev` 밖)에 두 장치를 submount로 받고, `dockerd-start`가 cgroup 절차 뒤 `native-dri-prepare`를 실행한다. 이 helper는 raw 디렉터리에 `card0`·`renderD128` character device만 있는지 확인하고, `/dev` propagation을 private으로 바꾼 뒤 자기 mount namespace의 `/dev/dri`에 `--rbind`로 투영한다. host 경로와 device node는 만들거나 지우거나 바꾸지 않으며, 예상과 다른 상태면 daemon을 띄우지 않는다. 렌더링은 지금처럼 Mesa CPU rasterizer(llvmpipe)가 맡으므로 host 커널 module, 배포판 패키지, Nix 변경이 필요 없다.
- 시작 순서: `dockerd-start`는 home의 `checkouts/.issue-agent-home-ready`가 없으면 바로 종료한다. startup probe는 `docker info` 응답과, `/dev/dri/card0`·`/dev/dri/renderD128`이 kernel의 같은 이름 node와 device 번호가 일치하고 `asahi` 또는 `rockchip-drm` driver인 한 DRM 장치에 속하는지를 모두 요구한다. 하나라도 빠지면 runner와 publisher는 시작하지 않고 Hub에 등록하지도 않는다. runner bootstrap도 `docker info`가 실패하면 종료한다. Runner는 이 장치가 있는 `macmini`·`rock5bp`에만 스케줄된다.
- 방화벽: dockerd는 `--firewall-backend=iptables`와 `--ip6tables=false`로 실행한다. `dockerd-start`는 daemon을 띄우기 전에 `iptables`·`ip6tables`가 iptables-nft(`nf_tables`)인지 확인하고, legacy면 시작하지 않는다. default bridge와 NAT는 켜 둔 채 Docker가 filter·NAT 규칙과 IPv4 forwarding을 직접 관리한다. 그래서 `--iptables=false`나 `--network=host`를 쓰지 않고, nft CLI나 forwarding sysctl 설정도 따로 두지 않는다. 이 규칙과 forwarding은 Pod network namespace 안에만 생기며 host 방화벽은 건드리지 않는다. 이전에는 nftables backend를 썼는데, Docker 29.4의 이 backend는 kernel FIB expression을 쓴다. `rock5bp`의 vendor 커널 `6.1.84-999-rk2410`은 `# CONFIG_NFT_FIB_IPV4 is not set`이라 `nft_fib_ipv4`·`nft_fib_inet` module이 없고, 이 backend로는 dockerd가 시작에 실패했다. iptables backend는 이 expression을 쓰지 않으므로 커널을 바꾸지 않고 이 실패를 피한다.
- 이미지: dockerd 이미지(`Dockerfile.dockerd`)는 digest로 고정한 `docker:29.9.0-dind` 위에 `util-linux-misc=2.42.3-r1`만 빌드 때 설치하고, 실행 중에는 패키지를 설치하지 않는다. Alpine 3.24 base의 `iptables`·`ip6tables`가 iptables-nft(`nf_tables`) backend인지는 빌드 때 확인하고 `dockerd-start`가 실행 때 다시 확인한다. `unshare --cgroup` guard와 native DRM 장치 guard를 유지한다. Runner 이미지의 Docker CLI·buildx·compose는 digest로 고정한 `docker:29.9.0-cli`에서 복사한다. Krema처럼 KWin·CMake가 필요한 저장소는 harness가 자기 컨테이너 안에서 이를 쓰므로 Runner 이미지에는 넣지 않는다.
- Docker 권한 정책(E3, 2026-10-11): `dockerd-start`가 이미지에 든 자체 Go legacy authorization plugin(`runner/authz/`)을 먼저 띄우고 socket을 기다린 뒤 `--authorization-plugin`으로 dockerd를 시작한다(fail-closed). plugin이 거절하는 요청은 `Privileged`, `CapAdd`, host pid·ipc·uts·userns·network mode, 허용 목록 밖 장치(`PathOnHost`는 `/dev/dri`, `/dev/dri/card0`, `/dev/dri/renderD128`만 허용), `/home/agent/checkouts`와 `/tmp/issue-agent` 밖 bind·mount, docker socket mount, unconfined security opt, host 경로를 bind하는 volume DriverOpts(local driver `o=bind`·`device=`), mount의 `VolumeOptions.DriverConfig`, `VolumesFrom`, container update, plugin pull·install·enable·disable·set, privileged exec, JSON body 없는 create·exec, 모르는 mutating endpoint다. `daemon.json`은 BuildKit `network-host`·`device` entitlement를 끄고, `Dockerfile.dockerd` 빌드가 고정한 dind 이미지의 `dockerd --validate --config-file`로 검증한다. `dockerd-start`는 `native-dri-prepare` 뒤 dockerd 컨테이너의 `/dev`에서 host block device를 지운다(privileged 컨테이너 자신의 `/dev` tmpfs만 바뀐다). `/opt/issue-agent/bin/docker-smoke --policy`는 `--privileged` 거절, `/` bind 거절, `docker build --allow network.host` 거절, `--device /dev/dri` 허용을 확인한다.
- 저장소 영향: pillar-csi의 privileged Kind E2E(`test/docker-e2e/run.sh`의 `--privileged`)는 이제 Runner에서 돌 수 없다. 에이전트는 "로컬에서 실행할 수 없음, CI가 확인"으로 보고하고 CI가 이를 맡는다. krema `tests/appium/run-e2e.sh`의 `--device /dev/dri`는 허용 목록에 있어 그대로 돈다. cc-lb·flareway·kwin-mcp의 e2e script는 정책이 거절하는 flag를 쓰지 않는다.
- 저장소와 자원: Docker 데이터 PVC는 50Gi, Runner home PVC는 기존과 같은 20Gi다. dockerd 자원은 아래 `승인된 초기 자원 예외`에 있다.
- Docker janitor: `dockerd-start`가 `dockerd-janitor`(`runner/dockerd-janitor.sh`, 이미지의 `/opt/issue-agent/bin/dockerd-janitor`)를 daemon과 같은 mount namespace에서 background로 띄우고, 죽으면 60초 뒤 다시 띄운다. janitor는 dockerd에 signal을 보내지 않는다. root로 300초마다 네 가지를 한다. 에이전트가 쓸 수 있는 경로는 root가 shell pathname으로 다루지 않고, 모두 Go helper `issue-agent-chown-sweep`(`runner/chown-sweep/`, 이미지의 `/opt/issue-agent/bin/issue-agent-chown-sweep`)의 fd 기반 subcommand로 다룬다.
  - ① 소유권: worktree를 bind mount한 컨테이너가 root로 쓴 항목은 publisher(UID 1000)가 지우지 못해 `cleanup_closed`가 `foreign_owner`로 실패한다. helper는 `/home/agent/checkouts`를 `O_DIRECTORY|O_NOFOLLOW`로 연 fd에서 출발해 `<owner-dir>/<repo>-worktrees/<name>` 단계로만 내려가고, 그 아래는 재귀로 돈다. 모든 open은 `openat(parentfd, name, O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC)`, stat은 `fstatat(parentfd, name, AT_SYMLINK_NOFOLLOW)`이고, uid나 gid가 1000이 아닌 항목만 `fchownat(parentfd, name, 1000, 1000, AT_SYMLINK_NOFOLLOW)`로 바꾼다. 루트와 `st_dev`가 다른 항목은 건너뛰고(xdev), symlink는 따라가지 않는다(link 자체만 NOFOLLOW로 lchown될 수 있다). worktree가 아닌 최상위 디렉터리는 건드리지 않는다. 항목 하나의 오류는 log에 남기고 건너뛰며, 끝에 바꾼 개수를 출력한다. 예전 `find … -exec chown -h`는 pathname을 다시 해석하므로, 검사와 chown 사이에 에이전트가 경로 중간 디렉터리를 symlink로 바꾸면 root의 chown이 worktree 밖으로 갈 수 있었다. fd 기반 walk는 이미 연 부모 fd에 상대 이름만 쓰므로 그 경쟁이 없다.
  - ② prune: `.issue-agent-janitor/prune-request`를 helper `read-request`로 읽는다. 유효한 lease(`lease_until - now`가 600~3600초)가 없으면 prune하지 않는다. lease가 600초 아래로 남았거나, `lease_until`이 마지막 `last_prune_lease`와 같으면 요청을 기록 없이 버린다. 사용률이 70% 이하이면 prune하지 않고 요청을 버리되 `last_prune_lease`를 그 lease로(`last_prune_result` `ok`) 기록해 bridge가 hold를 일찍 풀게 한다. 실행 중인 컨테이너가 있으면 lease가 600초 아래가 될 때까지 요청을 남겨 둔다. 조건이 모두 맞으면 `docker container prune -f`, `docker image prune -af --filter until=24h`, `docker builder prune -af --filter until=24h`를 돌리고, 그래도 85%를 넘으면 `docker image prune -af`와 `docker builder prune -af`까지 돌린다. Docker 호출 timeout은 `ps` 30초, container prune 60초, image·builder prune 각 110초로 합이 600초보다 작아 lease 안에 끝난다. 전후 사용률을 log에 남기고, `last_prune_lease`와 결과(`ok`/`error`)를 기록한 뒤 helper `drop-request`로 요청을 지운다. 이 API 호출은 일반 client처럼 authz plugin을 지나며 정책이 허용한다. 예전에는 Docker 데이터를 지우는 경로가 없어 PVC가 계속 찼다.
  - ③ pressure prune: bridge의 lease는 시스템 전체가 idle일 때만 나오므로, 작업이 끊이지 않으면 lease prune이 오지 않아 PVC가 99%까지 찼다. 그래서 ② 뒤에 사용률이 `ISSUE_AGENT_JANITOR_PRESSURE_PCT`(기본 85%)를 넘으면 lease 없이 `docker image prune -af --filter until=12h`와 `docker builder prune -af --filter until=12h`를 각 110초 timeout으로 돌린다. image prune은 어떤 컨테이너도 참조하지 않고 12시간 전에 만들어진 이미지만 지운다. 턴에서 로컬로 빌드한 이미지는 그보다 새롭고, 오래된 pull 이미지는 다시 받을 수 있다. builder prune은 BuildKit이 사용 중인 record를 건너뛴다. 볼륨·컨테이너는 지우지 않고, `last_prune_*`와 lease 기록도 바꾸지 않는다(bridge가 lease를 일찍 푸는 데 쓰므로). 전후 사용률은 log에만 남는다.
  - ④ status: 매 loop 끝에 helper `status`가 `/home/agent/checkouts/.issue-agent-janitor/status`에 `{"checked_at", "docker_used_pct", "last_prune_at", "last_prune_lease", "last_prune_result"}`를 원자적으로(`O_EXCL|O_NOFOLLOW` 임시 파일 + `renameat`) 쓴다. `last_prune_*`는 lease prune만 나타낸다. publisher `GET /janitor/status`가 이 파일을 bridge에 돌려준다. 사용률을 읽지 못한 loop는 log만 남기고 status를 쓰지 않으므로 bridge는 900초 뒤 그 status를 낡은 것으로 보고 요청하지 않는다. 마지막 prune 상태는 janitor 컨테이너의 `/run/issue-agent-janitor`에 있어 컨테이너가 재시작되면 사라진다. 그때 진행 중인 lease는 일찍 풀리지 않고 20분 뒤 끝난다.

## 데이터 보존

| 데이터 | 보존 방식 |
|---|---|
| n8n 워크플로·실행 기록·credential 암호화 키 | 지원되는 영속 DB/볼륨과 독립 Secret, 보존 정책을 명시 |
| 이벤트·이슈 매핑·전송 상태 | 영속 저장소, 재시작 후 이어짐 |
| HAPI 세션·메시지 | Hub SQLite와 WAL을 고려한 일관된 백업 |
| Codex 네이티브 기록·설정 | 영속 `CODEX_HOME` |
| Claude 네이티브 기록·설정 | 영속 하네스 사용자 디렉터리 |
| 소스·worktree·작업 산출물 | Runner 영속 볼륨 `issue-agent-runner/issue-agent-runner-home`. 전환 전 claim `issue-agent/issue-agent-runner-home`은 PV `Retain`으로 남긴다 |
| Runner Docker 이미지·build cache | `issue-agent-runner-docker` PVC. 버릴 수 있는 캐시이며 보존 annotation과 백업이 없다. 사용률이 70%를 넘으면 bridge가 idle일 때 maintenance lease를 잡고 dockerd janitor가 그 lease 안에서 prune한다 |

HAPI `v0.30.7`은 agent 메시지 내부의 65,536자 초과 문자열을 저장 전에 축약한다. Hub DB만으로 네이티브 기록 보존을 대체하지 않는다. UI 삭제·워크플로 정리·Pod 재생성 때문에 하네스 기록이 함께 삭제되지 않도록 수명주기를 분리한다. 백업에 포함된 자격증명은 일반 조회 경로로 노출하지 않는다.

## 배포·전환 제약

- 이미지는 검증한 버전과 digest로 고정한다. Hub·Runner·CLI의 프로토콜 호환성을 확인한다.
- 사설 UI는 기존 내부 HTTPS Gateway 패턴을 재사용한다. 공개 webhook 경로(`/webhooks/github`, n8n 수신 워크플로로 연결)만 분리한다. HAPI/n8n 인증을 생략하는 fallback을 만들지 않는다.
- 기존 전용 GitHub App의 설치 범위를 임의로 확장하지 않는다. 추가 운영 레포는 사용자 지정과 설치 권한 확인 후 연결한다.
- 새 컨테이너별 tier와 자원 수치를 명시하고 14일 CPU/working-set 기록 및 클러스터 메모리 요청 비율을 확인한다. 이력이 없는 신규 서비스는 수치를 추측하지 않고 초기 측정·배포 기준을 사용자와 확정한다.
- 전환 전 미처리 작업을 확인하고, 단일 GitHub App webhook을 새 endpoint와 secret으로 변경한 뒤 실제 전달을 검증한다. 과거 Archon 대화의 HAPI 이전이나 legacy 댓글 전달 기능은 구현하지 않는다.
- 전환 검증 후 Archon 전용 리소스와 PVC 데이터를 삭제한다. 삭제 뒤 과거 Archon 세션을 재개할 수 없다는 결과를 사용자에게 고지했다. GitHub App과 SSM 인증 원본은 새 시스템의 공유 의존성이므로 유지하며, 삭제 전 새 namespace에서 독립적인 토큰 발급을 확인한다.
- 최소 운영 주의사항: 이번 n8n 업그레이드는 5개 forward migration(261→266)을 실행했으므로 downgrade 전 검증된 pre-upgrade SQLite backup restore가 선행돼야 한다.
- Runner 도구 기준 버전은 Docker 29.9.0, Codex 0.162.1, Node 26.11.1, Go 1.27.2, GitHub CLI 2.102.0이며 HAPI 0.30.7은 유지한다. Codex는 managed config(`runner/codex/managed_config.toml`)의 `service_tier = "fast"`로 모든 세션·sub-agent에서 Fast mode(`priority` tier)를 쓴다. HAPI는 resume 시 hub에 저장된 tier를 `--service-tier`로 넘겨 이 설정을 덮으므로, bridge는 Codex 세션 spawn 시 `serviceTier: "fast"`를 보내고 `ensure_session`이 돌려주는 active 세션의 저장 tier가 `fast`가 아니면 `POST /api/sessions/:id/service-tier`로 `fast`를 지정한다. n8n은 2.42.7이고 워크플로 노드는 이 버전의 최신 typeVersion을 쓴다. bridge·publisher는 GitHub REST API `2026-03-10`을 쓴다.

### Runner namespace 전환

기존 `issue-agent/issue-agent-runner-home`은 다른 namespace로 옮길 수 없으므로 새 `issue-agent-runner/issue-agent-runner-home`에 복사한다. 이 전환은 무중단이 아니다.

1. 운영자가 전환을 승인한 뒤 `issue-agent` Argo CD application sync가 기존 runner Deployment를 prune하고, `issue-agent-runner` application sync가 빈 home claim과 Runner Pod를 만든다. ready marker가 없으므로 dockerd가 종료하고 runner·publisher는 시작하지 않는다.
2. 그때부터 marker를 쓸 때까지 Runner 세션이 없고 bridge는 publisher에 닿지 못한다. 이 창 동안 intake를 멈추거나, 끝난 뒤 멈춘 이벤트를 `retry_event`로 수동 재시도한다.
3. runner가 Hub에 등록하고 bridge가 publisher를 호출하려면 `issue-agent-runner`의 ESO mirror(`issue-agent-hapi-auth`, `issue-agent-publisher`)가 Ready여야 한다.
4. 운영자가 `operations/issue-agent-runner-home-migrate migrate`를 실행한다. 기존 runner Deployment가 없거나 0 replica이고 기존 claim을 쓰는 Pod가 없을 때만 진행한다. 기존 PV를 `Retain`으로 바꾸고, 커밋하지 않은 worktree와 native 자격증명을 포함한 home 전체를 출력 없이 복사한다. 두 트리의 정렬한 SHA-256 manifest가 같을 때만 marker를 쓰고 대기 중인 Runner Pod를 다시 만든다. 새로 설치하는 환경도 비어 있는 기존 claim을 같은 방식으로 migrate한다.
5. 두 home claim은 `Prune=false,Delete=false`로 남으며 자동으로 지우지 않는다. 기존 claim은 새 Runner를 검증한 뒤 운영자가 직접 지운다. rollback하려면 새 Runner를 멈추고 새 home을 기존 claim에 다시 복사한 뒤에 기존 runner를 띄운다. 이 back-copy는 도구가 없으며 별도 승인이 필요한 수동 작업이다.

명령별 부작용과 안전 경계는 `apps/objects/issue-agent/operations/README.md`에 있다.

### Runner·dockerd 이미지 빌드

이미지는 로컬 OrbStack builder로 arm64만 빌드해 GHCR에 push한다(Runner node는 arm64이고 binfmt는 쓰지 않는다). build context는 `apps/objects/issue-agent`다.

```sh
docker buildx build --builder orbstack --platform linux/arm64 \
  -f apps/objects/issue-agent/Dockerfile.dockerd \
  -t ghcr.io/isac322/issue-agent-dockerd:<Docker 버전>-<date>-<purpose> --push apps/objects/issue-agent
docker buildx build --builder orbstack --platform linux/arm64 \
  -f apps/objects/issue-agent/Dockerfile.runner \
  -t ghcr.io/isac322/issue-agent-runner:<HAPI>-codex<v>-<date>-<purpose> --push apps/objects/issue-agent
```

- tag: Runner는 `<HAPI 버전>-codex<Codex 버전>-<YYYYMMDD>-<목적>`(예: `0.30.7-codex0.160.0-20261003-resolved-head`), dockerd는 `<Docker 버전>-<YYYYMMDD>-<목적>`(예: `29.8.2-20261002-native-drm-iptables-nft`)이다.
- push 뒤 받은 digest를 `apps/objects/issue-agent-runner/deployment-runner.yaml`에 `<tag>@sha256:<digest>`로 고정한다. runner와 publisher는 같은 Runner 이미지를 쓰므로 두 곳을 함께 바꾼다. tag만으로 배포하지 않는다.
- `Dockerfile.dockerd`는 authz plugin과 `runner/chown-sweep/`의 `issue-agent-chown-sweep`을 digest로 고정한 Go builder stage에서 `go test` 뒤 정적 빌드하고 `daemon.json`을 검증한다. `runner/dockerd-janitor.sh`를 `/opt/issue-agent/bin/dockerd-janitor`로 복사하고 빌드 때 `sh -n`으로 확인하므로 janitor나 helper를 바꾸면 dockerd 이미지를 다시 빌드한다. Docker smoke script와 publisher는 Runner 이미지에 들어 있으므로 smoke나 `publisher.py`를 바꾸면 Runner 이미지도 다시 빌드한다.
- 2026-10-11 변경의 rollout 순서: bridge(dispatch 중인 이벤트가 없을 때) → n8n(재시작 뒤 bootstrap log 확인) → dockerd 이미지 → Runner 이미지(스킬·지침, Codex 설정, `codex-untrust`, smoke) → Runner manifest(digest, 모델 키 proxy, 메모리)를 dispatch 중인 이벤트가 없을 때 Argo sync 한 번. 실제로는 Docker 정책·모델 키 proxy·메모리를 먼저(#423), 나머지를 다음에(#425) 배포했다. proxy 확인 뒤 기존 `issue-agent-provider` ExternalSecret은 지웠다.
- 2026-10-13 변경(턴 마감·늦은 결과 수거·정리·janitor·`dismiss_event`)의 rollout 순서: bridge(`turns.deadline_at`·`issues.cleanup_failures`·`bridge_state` 스키마 이전 포함, dispatch 중인 이벤트가 없을 때) → n8n(`Within time budget?`, cleanup 분기, 지시문) → dockerd 이미지(janitor, `issue-agent-chown-sweep`) → Runner 이미지(publisher `remove_worktree`·`GET /janitor/status`·`/janitor/prune-request`, `isac-issue-to-pr` 스킬) → Runner manifest digest를 dispatch 중인 이벤트가 없을 때 Argo sync. dockerd와 Runner digest는 같은 sync로 바꾼다. 새 janitor는 `lease_until` 없는 요청으로 prune하지 않고, 새 publisher는 그런 요청을 거부한다. 배포 뒤 한 번, 주제가 이미 닫히거나 머지된 `needs_attention` 이벤트를 `dismiss_event`로 닫고 주인 없는 HAPI 세션을 archive한다.

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
| dockerd(Runner Pod sidecar) | 4 | 1 | 2Gi | 8Gi |

모든 CPU 제한은 생략한다. 자동 구현은 한 번에 한 건 실행하며 여러 독립 세션의 관찰은 허용한다. 측정 시 클러스터 allocatable 메모리 70,011,109,376 bytes 대비 요청 합계 45,570,306,048 bytes(65.09%)였다. 위 요청 1,856Mi 추가 시 약 67.9%다. 배포 직전에 실제 스케줄링 예산을 재계산한다. 추가 컨테이너·DB가 필요하면 이 예산에 숨겨 넣지 않고 별도로 검토한다.

배포 직전 재계산에서는 다른 workload가 증가하여 nonterminal Pod의 일반·init·restartable sidecar 및 overhead를 반영한 메모리 요청이 51.189GiB / 65.200GiB = 78.51%였다. 새 구성 포함 예상치는 81.29%다. 사용자는 이 수치를 안내받고 **이번 병행 배포에 한시적인 75% 상한 초과 예외**를 명시적으로 승인했다. 기존 CI나 서비스를 임의로 축소하지 않는다. 평상시 자원 정책이 변경된 것은 아니다.

v2는 Runner Pod에 publisher 사이드카를 추가했다. manifest의 값은 CPU 요청 10m, 메모리 요청 64Mi, 메모리 제한 256Mi이며 CPU 제한은 없다. 위 표의 승인 수치에는 포함되지 않은 추가분이다.

위 표의 Codex Runner·dockerd 행은 초기 예외 값이다. 14일 측정(Runner 메모리 p50 515Mi·최대 3.4Gi, CPU p95 0.04코어·최대 3.05코어; dockerd 메모리 p50 61Mi·최대 168Mi, CPU 약 0) 뒤 Tier 3으로 재산정해 manifest의 Runner는 CPU 요청 100m, 메모리 요청 640Mi, native sidecar `dockerd`는 CPU 요청 10m, 메모리 요청 80Mi다. CPU 요청은 진행 보장용 하한, 메모리 요청은 p50의 약 1.25배이며 메모리 제한(4Gi·8Gi)은 그대로 두고 CPU 제한은 없다. home 복사에 쓰는 임시 scratch Pod 두 개는 각각 Tier 4, CPU 요청 1, 메모리 요청 2Gi, 메모리 제한 8Gi이며 CPU 제한이 없고, `migrate` 실행 중에만 존재한다. 사용자는 scratch Pod 값을 14일 측정 없이 초기 예외로 승인했다. 이 요청을 포함한 클러스터 메모리 요청 비율은 배포 직전에 다시 계산한다.

2026-10-11 재산정(U3): 14일 Runner 메모리는 P50 2.08 GiB, P99 3.59 GiB였고, 최대값은 제한 4Gi에 닿아 잘린 값(censored, ≥3.996 GiB)이라 실제 peak는 더 높을 수 있다. 그래서 manifest의 runner를 메모리 요청 2560Mi·제한 5Gi로, native sidecar `dockerd`를 메모리 요청 160Mi로 올린다(CPU 값과 dockerd 메모리 제한은 그대로). 산정 시 `macmini` node의 메모리 요청 비율은 0.46에서 0.59로, 클러스터 비율은 0.505가 된다. 같은 변경에서 리뷰 동시 실행을 `MAX_ACTIVE_REVIEWS`(2)와 Codex `max_threads`(3, 2026-10-13부터 2)로 제한한다. `model-proxy` sidecar 요청을 포함해 배포 직전에 비율을 다시 계산한다.

2026-10-13 재산정: 업그레이드 뒤 Codex thread마다 뜨는 MCP 서버가 커졌다(로컬 A/B에서 CodeGraph 1.6.2 idle 서버 252→373MiB, Node 26의 context-mode 60→78MiB). `max_threads`를 2로 줄이고 제한을 6Gi로 올린 뒤에도 runner가 10:10Z에 OOMKilled(working set 5.95GiB, 제한에서 잘린 값)됐으므로 제한을 1.25 × 6Gi = 7.5Gi(7680Mi)로 올린다. 14일 P50은 0.74GiB, P99는 3.37GiB이고 요청 2560Mi는 그대로라 node·클러스터 메모리 요청 비율은 바뀌지 않는다.

2026-10-13 재측정: 7.5Gi도 동시성 상한을 덮지 못한다. 10:10Z 값은 제한에서 잘린 값이라 프로세스별로 다시 쟀다. Codex 세션 하나(MCP 서버 포함)가 RSS ~751MiB, `max_threads=2` 하위 에이전트가 각자 MCP 서버를 띄워 하나당 ~275MiB를 더하고, working set은 RSS의 ~1.15배다. `MAX_ACTIVE_EVENTS=5`이면 5 × 1.27GiB RSS로 working set ~7.4GiB라 7.5Gi에는 여유가 ~1%뿐이다. 빌드는 dockerd cgroup에서 돈다. 제한을 1.2 × 7.4GiB → 9Gi로 올린다. 요청 2560Mi는 그대로다.

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
- [ ] 닫힌 이슈에 비신뢰 사용자가 이슈 요청이 아직 충족되지 않았다는 댓글(krema#90 댓글 6128696806 같은 경우)을 달면 `closed_issue_comment` → `reopen_check`가 실행되어 이슈가 다시 열리고, 재개 이유와 근거를 담은 댓글이 남는다.
- [ ] 닫힌 이슈의 비신뢰 댓글이 감사·질문·수정 전 버전의 보고·새 주제면 `kept_closed`로 끝나고 GitHub에 아무것도 쓰지 않는다(이슈·라벨·댓글 변화 없음).
- [ ] 댓글 뒤 maintainer가 이슈를 다시 닫았거나(`closed_after_comment`) 이미 열렸으면(`already_open`) 재개하지 않는다. 같은 delivery 재시도는 `issue_reopened` 단계로 멱등하다.
- [ ] 닫힌 이슈에 owner·신뢰 collaborator가 단 댓글은 이전과 같다(멘션이면 `issue_comment`, 아니면 `issue_comment_ignored`). `issues.reopened`는 `action_ignored`라 루프가 없다.

### GitHub 읽기 에이전트 이관 수용 기준

- [ ] 에이전트가 읽기 전용 설치 토큰으로 `gh`(REST·`gh api graphql`)를 직접 실행해 이슈·댓글·PR·리뷰·스레드·연결 이슈를 읽는다. 세션 메시지에는 대상 번호와 트리거·결과 맥락만 들어가고 GitHub 본문은 들어가지 않는다.
- [ ] bridge의 `github.issue`·`github.pr_context` op와 그 전용 헬퍼가 제거됐고, `op_begin` 응답이 `bot_login`·`reviewer_login`을 반환한다.
- [ ] n8n `IssueAgentMain01`에서 `Load issue`·`Issue loaded?`·`Load PR context`·`PR context loaded?` 노드가 제거됐고, `Route by mode`의 triage·followup 출력은 `Issue step`으로, review 출력은 `Prepare review step`으로 직접 연결된다. Prepare 노드는 제거된 노드를 참조하지 않는다.
- [ ] GitHub 쓰기 경로(bridge `github.comment`·`github.labels`·`github.review`·`git.push`·`github.pr_upsert`와 attention 알림)는 바뀌지 않았다.

### Docker 배포 전 수용 기준

로컬 환경과 일회용 VM에서 확인한 항목이다. production node와 클러스터에는 아무것도 설치하거나 배포하지 않았다. vgem module 기반의 이전 검증은 native DRM 전환으로 현재 근거에서 뺐다.

- [x] 로컬 ARM64 Docker에서 Runner 이미지와 dockerd 이미지 빌드가 성공했다.
- [x] 빌드한 non-root Runner 이미지가 Unix socket DinD로 실제 이미지를 build했고, 입력 bind mount와 artifact의 SHA-256 왕복이 일치했다.
- [x] 기존 `rock5bp` DRM 장치 위에서 vgem 없이 Krema commit `52f2d41a38d880b584b7e5bf7dd79adb81a29a56`의 standalone harness를 실행해 `test_smoke.py`·`test_03_preview.py` 17개가 68.268초에 모두 통과했다. 렌더링은 CPU llvmpipe다.
- [x] native DRM 전환 전 QA K3s `v1.36.4+k3s1` / containerd 2.3.4(`SystemdCgroup=true`) Pod에서 당시 dockerd sidecar의 cgroup 경계를 검증했다. privileged Pod는 host cgroup namespace를 공유하므로 `dockerd-start`가 자기 scope의 유한한 `memory.max`를 확인한 뒤 `unshare`/`cgroup2` remount로 private namespace에 재진입했다. Docker 자식은 자기 scope 아래 `/issue-agent-docker`에 있고 root ancestor에 8Gi 제한(`memory.max` 8589934592)이 있다. `-m 64m` 컨테이너에서 200MB를 할당한 process는 OOM(exit 137)이 됐고, `-m 100m` 컨테이너의 leaf `memory.max`가 104857600인 것은 따로 확인했다. cgroup 코드는 이번 DRM 전환에서 바꾸지 않았으며, 이 결과는 새 DRM 이미지의 K3s rollout 증거가 아니다.
- [x] native DRM 전환 전 dockerd 이미지(`ghcr.io/isac322/issue-agent-dockerd@sha256:6b8013967fca…`)에서 marker가 없는 home은 startup gate가 막고, marker가 있는 home은 native sidecar가 재시작 0회로 60초 이상 Ready를 유지했다. QA fixture는 Docker 데이터에 emptyDir을 쓰고 HAPI·publisher를 실제 인증 대상 없는 클라이언트로 대체했다. production HAPI 등록, ESO mirror, Longhorn-backed PVC의 rollout은 이 증거에 포함하지 않는다.
- [x] 실제 `issue-agent-runner-home-migrate`로 QA K3s의 실제 PVC 두 개(`local-path`; Longhorn은 미검증)에서 namespace 이전을 검증했다. sha `075b4f3`에서 805,334,520 bytes, 116 entries(57 files)를 복사하고 양쪽 manifest sha가 `d13e6481d5d8cbe181a5ed0906d0ffb4348b0e4529b8e21f86b3013e7e2bca60`로 일치했다. 심볼릭 링크 5개(깨진 것 포함), fifo, hardlink, 유니코드·개행 이름, dirty worktree가 유지됐고 source의 ctime은 read-only 파일까지 변하지 않았다. archive는 `.`을 생략해 PVC root 소유권을 건드리지 않는다.
- [x] 최종 도구(sha256 `6f8fc9ea50d1937b3eea98bc688f038aebe6c1d996b6c56814fd15ad1e08c455`)로 새 fixture에서 같은 경로를 다시 검증했다. 6개 사전 조건 검사가 동작했고, 중단한 copy는 rc 130으로 끝나 scratch Pod 0개, marker 없음 상태를 남겼다. 부분 복사는 wipe 없이 거절됐고 `--wipe-incomplete-destination` 후 116 entries가 동일하게 복사됐으며, source ctime은 변하지 않았고 ready claim은 거절됐다. `cleanup`은 label과 이름이 모두 맞는 도구의 slot 두 개만 지웠다. label 없는 foreign Pod 4개, 다른 slot 이름을 가진 Pod, 다른 label의 Pod는 남았고, 지울 것이 없을 때는 rc 0으로 끝났다.
- [x] production `issue-agent/issue-agent-runner-home`의 read-only 소유권 검사는 260,493개 파일이 모두 1000:1000이고 오류가 없었다.
- [x] 이번 검증에서 만든 일회용 VM, 그 안의 K3s·Docker·PVC 데이터, 생성한 SSH 키를 정리했다. 기존 VM과 운영 cluster는 건드리지 않았고 로그만 저장소 밖에 보존했다.

- [x] 첫 native DRM daemon·Runner 이미지를 실제 ARM64 node의 격리된 Docker QA에서 실행했다. `native-dri-prepare`와 exec probe가 통과했고, daemon·UID 1000 Runner·중첩 Krema 컨테이너에는 `card0`·`renderD128`만 보였다. Runner의 DRM 디렉터리는 쓰기 불가였고, `card1`·`renderD129`는 가려졌다. 장치 누락·잘못된 device number에 probe가 실패하고, raw 장치 누락·추가 항목에 projection helper가 실패하는 음성 대조군도 통과했다.
- [x] 같은 QA에서 Docker `29.4.0` 이미지 build와 non-root artifact SHA-256 왕복이 성공했다. 변경 없는 Krema `52f2d41a38d880b584b7e5bf7dd79adb81a29a56`의 smoke·preview 17개가 87.149초에 모두 통과했고 errors·failures·skips는 0이었다. KWin `6.7.5`는 OpenGL/llvmpipe로 렌더링했고 실제 `/dev/dri/renderD128` FD를 열었다. vgem은 로드되지 않았다. 중첩 테스트의 제한은 CPU 2·메모리 4Gi·swap 0이었다.
- [x] 당시 두 이미지를 GHCR에 게시한 뒤 인증 없는 요청으로 index digest와 linux/arm64 manifest를 확인했다. 이후 dockerd 이미지만 아래 iptables backend 이미지로 교체했고 Runner 이미지는 그대로다.

위 첫 native DRM QA는 그래픽 경로만 본 검증이다. 당시 설정된 nftables entrypoint의 IPv4 FIB 실패와 그래픽 경로를 분리하려고, 임시 daemon의 bridge·firewall을 끄고 테스트 자식을 그 daemon 컨테이너의 network namespace에서 실행했다. 운영 node의 host network는 쓰지 않았다. 실제 entrypoint를 대체했으므로 이 QA만으로는 설정된 daemon의 시작을 보여 주지 못했고, 이 부분은 아래 iptables backend 검증에서 따로 확인했다.

이 QA의 컨테이너, 원격 checkout·Docker 데이터·artifact 복사본, 새로 전송한 native DRM 이미지와 SDK 복사본은 정리했다. 실행 로그·JUnit·renderer 근거는 저장소 밖에 보존했다. 운영 Runner는 원래 Pod UID·node·image·container 시작 시각·Ready 상태가 그대로였고 재시작 횟수도 0이었다.

iptables backend로 바꾼 dockerd 이미지 `ghcr.io/isac322/issue-agent-dockerd:29.4.0-20261001-native-drm-iptables-nft`(`sha256:331f0a70085fa8f20a11463235ac6cbaa9863ffd1d4fbb895fa127068da6ab79`)는 같은 방식의 격리된 Docker QA에서 이미지 ENTRYPOINT `dockerd-start`를 그대로 실행해 검증했다. `--iptables=false`나 `--network=host`는 쓰지 않았다.

- [x] daemon은 Docker `29.4.0`, `FirewallBackend.Driver=iptables`, cgroupfs driver, cgroup v2로 시작했고 daemon 메모리 제한은 유한했다. 이미지의 `iptables`·`ip6tables`는 v1.8.11 `(nf_tables)`, `util-linux`는 2.41.6이며 nft CLI는 없다.
- [x] default bridge 컨테이너에서 외부 HTTPS와 DNS가 동작했고, localhost published port와 user-defined bridge의 service 이름 DNS도 동작했다.
- [x] UID 1000 Runner에서 Docker 이미지 build와 artifact bind mount 왕복이 성공했다.
- [x] 변경 없는 Krema `52f2d41a38d880b584b7e5bf7dd79adb81a29a56`의 smoke·preview 17개가 83.697초에 모두 통과했고 errors·failures·skips는 0이었다. 중첩 테스트는 `/dev/dri/card0`·`/dev/dri/renderD128`만 받았고 vgem은 없었다. `LIBGL_ALWAYS_SOFTWARE=1`에서 KWin `6.7.5`는 OpenGL/llvmpipe로 렌더링했고 `renderD128` FD를 열었다. 중첩 테스트의 제한은 CPU 2·메모리 4Gi·swap 0이었다.
- [x] daemon 시작부터 종료까지 host의 방화벽 policy·rule·순서가 그대로였다. 비교에서 시각 주석과 traffic counter는 제외했다.

최신 master 병합 뒤 Runner 이미지를 `ghcr.io/isac322/issue-agent-runner:0.30.7-codex0.159.2-20261002-docker-native-drm@sha256:317dec5af4e942ba924198108f83b110de23d781b6e4e351229271c02a6eb913`로 다시 빌드·게시했다. master의 `r4` 이미지에는 Docker CLI가 없어 그대로 사용하지 않는다. 최종 이미지에서 Docker `29.4.0`, Buildx `0.33.0`, Compose `5.1.1`, Go `1.27.1`과 Runner bootstrap·리뷰 스킬 접근을 확인했다. 익명 registry 요청도 동일한 index digest와 linux/arm64 manifest를 반환했다.

Codex는 명령을 로그인 셸(`bash -lc`)로 실행하는데, Debian `/etc/profile`이 PATH를 `/usr/local/bin:/usr/bin:/bin:...`으로 덮어써 Go·Cargo·sccache 래퍼가 에이전트 명령에서 사라졌다(flareway#135가 `go: command not found`로 막힘). Runner 이미지가 `/etc/profile.d/00-issue-agent-path.sh`로 이미지 PATH를 복원하도록 고쳐 `ghcr.io/isac322/issue-agent-runner:0.30.7-codex0.159.2-20261002-login-path@sha256:3c0190450b30800f6c179a20a1e6c99073ba1a20fcf437936c8736b0005dfe9a`로 게시했다. 이 이미지의 `bash -lc`에서 `go`·`cargo`·sccache `cc`가 잡히는 것을 확인했다.

Runner 이미지를 `ghcr.io/isac322/issue-agent-runner:0.30.7-codex0.159.2-20261002-base-reset@sha256:67599799561ac79d641fffa906712fb81e24c18cc5b094a28512100550f1bfcd`로 다시 빌드·게시했다. force-push된 기본 클론을 reset하는 bootstrap과, `local_checks`를 요구하는 `isac-issue-to-pr` 스킬이 들어 있다.

Runner와 publisher 컨테이너를 같은 이미지 `ghcr.io/isac322/issue-agent-runner:0.30.7-codex0.159.2-20261003-resolved-head@sha256:1d7972b77a033e2454ca04c76696ec4e8379e06c331c398c6a555c06b0e2ee34`로 맞췄다. publisher `/resolve`와, 결과에 `head_sha`를 쓰지 않는 스킬·지시문이 들어 있다. bridge의 `git.push`가 `/resolve`를 부르므로 bridge와 이 publisher는 함께 배포한다.

Runner namespace의 읽기 토큰에는 기존 `contents`·`issues`·`pull_requests`와 함께 `checks`·`statuses`·`actions`의 `read` 권한을 유지한다. PR 리뷰의 CI 상태 조회와 repair의 Actions 로그 조회에 필요한 권한이며 쓰기 권한은 추가하지 않는다. 최종 Runner manifest의 Kustomize 렌더·Kubernetes client-side dry-run에서 이미지 pin과 여섯 읽기 권한을 확인했다. 운영 ESO reconciliation과 실제 installation token의 대상 저장소 접근은 배포 후 확인 게이트다.

최종 Runner 이미지와 iptables-nft daemon을 함께 실행한 격리 QA에서도 UID 1000의 Docker build·artifact 왕복, default bridge의 DNS·외부 HTTPS, localhost published port와 service-name DNS가 통과했다. 변경 없는 Krema `52f2d41a38d880b584b7e5bf7dd79adb81a29a56`의 smoke·preview 17개가 JUnit 기준 100.110초에 모두 통과했고 errors·failures·skips는 0이었다. KWin은 OpenGL/llvmpipe로 렌더링하고 `renderD128` FD를 열었다. host의 IPv4·IPv6 방화벽은 시각 주석·traffic counter를 제외하면 동일했고 DRM 장치 metadata도 동일했다. QA container·원격 scratch·반입 이미지와 임시 실행 스크립트를 정리하고 로그·JUnit·renderer·이미지 identity 근거만 보존했다. 운영 Runner를 재시작하거나 운영 배포·home migration·이벤트 retry를 실행하지 않았다.

`macmini`의 native DRM graphics 실행과 새 이미지의 운영 K3s rollout은 아직 검증하지 않았다.

### Docker 배포 후 확인 게이트

배포 뒤에만 확인할 수 있으며 아직 검증하지 않았다.

- [ ] 운영 node의 새 Runner Pod에서 dockerd가 `--firewall-backend=iptables`(iptables-nft)로 시작하고, 중첩 컨테이너가 default bridge로 외부와 통신한다. 실제 entrypoint는 격리된 Docker QA에서만 확인했다.
- [ ] 운영 node의 새 Runner Pod에서 `native-dri-prepare`와 dockerd startup probe가 통과하고, dockerd와 runner의 `/dev/dri`에 `card0`·`renderD128`만 있다.
- [ ] production node의 privileged dockerd가 `dockerd-start`의 cgroup 절차(자기 scope `memory.max` 확인, private cgroup namespace 재진입, writable cgroup)를 통과하고 중첩 컨테이너가 Pod 메모리 제한 안에 있다. QA K3s 검증과 다른 점(실제 노드 cgroup 배치)만 확인 대상이다.
- [ ] `issue-agent-runner`의 `SecretStore` `issue-agent`와 두 mirror ExternalSecret이 Ready다.
- [ ] 승인된 전환 창에서 `issue-agent-runner-home-migrate migrate`가 manifest 일치와 marker 기록으로 끝나고, 기존 PV가 `Retain`이며 두 home claim이 남아 있다. QA는 `local-path` PVC로 확인했으므로 production의 Longhorn-backed PVC에서의 실행이 확인 대상이다.
- [ ] 새 Runner Pod의 dockerd startup probe, runner healthcheck, Hub 등록, publisher `/healthz`, bridge의 `issue-agent-publisher.issue-agent-runner` 호출이 성공한다.
- [ ] live Runner에서 `issue-agent-docker-smoke`가 Krema worktree를 포함해 통과한다.
- [ ] `issue-agent-records`와 `issue-agent-backup create`·`verify`가 새 namespace 기본값으로 Runner 기록을 읽는다.
- [ ] dockerd 요청을 포함한 클러스터 메모리 요청 비율을 배포 직전에 다시 계산한다.
- [ ] 전환 창 동안 멈춘 이벤트를 확인하고 필요한 것은 `retry_event`로 다시 넣는다.
### 기능 요청 제안 트랙·비공개 advisory 수용 기준

- [ ] 신뢰 사용자가 연 명확한 기능·문서 요청은 `enhancement`/`documentation` 라벨과 `next_action: implement` + `implementation_brief`로 끝나고 같은 실행에서 구현으로 넘어간다. 구조 변경이 필요하면 `triage:needs-structural-change`와 `await_decision`으로 멈춘다.
- [ ] 비신뢰 사용자의 기능 요청은 구현되지 않는다. 계약 확인·실현 가능성·방향과 기각한 대안을 담은 제안 평가 댓글, `enhancement` 라벨(구조 변경이면 ⑤ 추가), `await_decision`과 결정 질문으로 `questioned`가 된다. 계약이 이미 약속한 동작이 깨진 경우는 결함 트랙으로 간다.
- [ ] 제안 이슈에 신뢰 사용자가 방향을 승인하는 댓글을 달면 다시 triage되어 `triage:fix-direction-decided`가 붙고(`triage:needs-structural-change`는 제거), `## Direction` 댓글이 게시되며 implement로 넘어간다.
- [ ] 비신뢰 사용자의 승인 댓글은 멘션 경로에서는 `actor_not_allowed`, `agent:open-discussion` 경로에서는 정보로만 쓰여 승인 전이가 일어나지 않는다. open-discussion 댓글의 신뢰 여부가 이벤트 행과 `begin` 응답의 `event.trusted`에 기록되고, 권한 조회 실패 시 경고 로그 후 비신뢰로 처리되며 delivery는 거절되지 않는다.
- [ ] 버그와 기능 요청이 섞인 이슈는 주장별로 판정되고, 버그만 고친 PR 본문은 `Fixes` 대신 `Related to #<n>`을 쓴다.
- [ ] followup에서 비신뢰 사용자의 댓글·수정은 진행 중인 PR의 요구사항을 바꾸지 않는다(`no_change` 답변, 질문 또는 `needs_info`). 신뢰 사용자의 요구 변경은 반영된다.
- [ ] 취약점이 확인되거나 의심되는 이슈는 라벨·이슈 댓글이 없고, 재현 페이로드가 이슈·`summary`·attention 댓글 등 공개 위치에 나오지 않는다. TriageResult `security_advisory`로 비공개 draft repository security advisory가 하나 만들어지고(설명 끝에 출처 marker), 이벤트는 `triaged`로 끝난다. 재시도해도 advisory가 중복 생성되지 않는다.
- [ ] `security_advisory`가 있는데 `comment`·라벨 변경·`next_action`이 규칙과 다르면 bridge가 거절하고, 오류 메시지에 advisory 본문이 들어가지 않는다.
- [ ] `issue-agent-github-token` 생성기와 issue App(`bulgasaribot`) 등록에 `repository_advisories: write`가 있고, 갱신된 토큰으로 advisory 생성이 성공한다.

### 리뷰 게이트·실행 경계 수용 기준(2026-10-11)

배포 전후에 아래 절차를 실행하고, 결과를 확인한 항목만 체크한다.

- [x] `test_bridge.py`, authz plugin `go test`, 두 app의 Kustomize dry-run, n8n JSON 파싱, shell script `bash -n`이 통과한다.
- [x] 배포 전 offline 확인: 현재 Runner 이미지에 새 `/etc/codex/` 파일을 얹고, MCP 서버 `evil`과 `developer_instructions`를 넣은 `.codex/config.toml`이 있는 scratch 저장소를 untrusted로 등록하면 `codex mcp list --json`에 context-mode·codegraph만 있고 `evil`이 없다. git worktree 경로에서도 Codex가 그 project root를 untrusted로 본다.
- [x] 비밀 `/proc` 검사: Runner 컨테이너의 모든 프로세스 `/proc/<pid>/environ`에서 `OPENAI_API_KEY`가 0건이고, 에이전트 셸 환경에 `CLI_API_TOKEN`·`HAPI_*`·`OPENAI_API_KEY`가 없다.
- [x] Runner에서 `codex mcp list`가 context-mode·codegraph를 보이고, 실제 세션의 `ctx_execute`로 `docker version`과 `gh api` 대상 읽기가 성공한다(`env_vars`).
- [ ] `/opt/issue-agent/bin/docker-smoke --policy`가 `--privileged` 거절, `/` bind 거절, `docker build --allow network.host` 거절, `--device /dev/dri` 허용을 보이고, `--krema-worktree` smoke도 통과한다. dockerd 컨테이너 `/dev`에 host block device가 없다. (`--policy`와 block device 0건은 확인했고 `--krema-worktree` smoke는 아직 돌리지 않았다.)
- [x] 모델 키 proxy: 운영 Runner의 Codex 턴(자가 점검 `codex exec` 2회, krema#95 리뷰 1회)이 proxy로 끝까지 실행됐고, 그 뒤 기존 provider ExternalSecret을 지웠다.
- [ ] triage 턴 하나와 review 턴 하나가 effort `high`(HAPI `state_5.threads`의 세션 metadata)로 돌고, 리뷰의 하위 에이전트도 `high`이며, `change_title`(hapi MCP)이 동작한다. (review 본 스레드와 하위 에이전트의 `high`는 확인했고 triage 턴과 `change_title`은 아직 확인하지 않았다.)
- [x] chaos test: krema#95 리뷰 실행 중 bridge Pod를 55초 간격으로 세 번 지워(약 3분) 재시작시켜도 리뷰가 정확히 하나 게시되고 이벤트는 park 없이 `completed`로 끝났다. n8n bootstrap log에 `CONFLICT`가 없다.
- [x] 리뷰 본문 첫 줄 marker에 리뷰한 SHA가 있고(`…:review:bf0db2d2…`), 그 head의 `issue-agent/review` status가 새 판정(failure)으로 바뀌었다. marker SHA가 현재 head가 아닌 리뷰로 success가 남지 않는 경우는 `test_bridge.py`로 확인했다.
- [ ] 일시적 `park_class`로 멈춘 리뷰가 10·30·90분 backoff로 최대 3회(`stale_dispatch`는 1회) 자동 재시도되고, 멈춘 동안 status는 `error`다.
- [ ] 에이전트 자신의 COMMENT에 `open_items`가 있으면 decision 댓글이 한 번만 남고, 같은 항목 집합의 새 head에서는 다시 남지 않는다.
- [x] Runner가 메모리 요청 2560Mi·제한 5Gi, dockerd 요청 160Mi로 Ready이고, 배포 직전 node·클러스터 메모리 요청 비율을 다시 계산했다.
- [ ] 배포 뒤 7일 동안 저장소별 non-draft head의 COMMENT 비율을 집계한다. 30%를 넘으면 미확인 의심(A4'')·lens 완결(A16') 규칙을 다시 검토한다.

검증 기록(2026-10-12):

- 1단계(#423) 배포 뒤 운영 Runner에서 확인: 모든 프로세스 environ에 `OPENAI_API_KEY` 0건, 키 파일은 runner 컨테이너에 없음, proxy 경유 `/v1/models` 200·허용 목록 밖 path 403. Docker 정책은 `--privileged`·`/` bind·`--cap-add`·`build --allow network.host`를 거절하고 `--network none` 실행·`--device /dev/dri`·일반 build를 허용했다. `trusted`로 표시한 scratch 저장소의 `.codex/config.toml` MCP 서버도 requirements 허용 목록 때문에 `disabled_reason: requirements`로 꺼진다.
- 과거 head 재현 리뷰(로컬, GitHub 쓰기 없음, 리뷰 시점 이후 데이터를 숨긴 gh shim, 새 Runner 이미지·authz dind·model proxy): kwin-mcp #90·#92·#93·#95·#97 head(0848f633·db6fb8a3·6cae93c4·70803378·f1fd4ef4) 각 3회에서 결함 있는 head를 APPROVE한 실행은 0회였다(같은 head에서 이전 봇의 판정은 5개 모두 GREEN). 사람이 찾은 P1·P2 13개 중 13개를 과반 실행에서 찾았고(cycle 1 9/13 → cycle 2 11/13 → cycle 3 12/13 → cycle 4 13/13), 규칙 도출에 쓰지 않은 #94·#96·#98(7f72f219)에서도 f17·f22·f27(P1)을 찾았다. 사람이 승인한 head(#98 fdcbe63c, #93 bea98be3)는 오탐 0건이고, 지적은 소스로 확인한 실제·개연 결함이었다. 남은 변동: f01(락 해제 틈의 reap)은 lifecycle lens를 모듈별로 나눈 실행에서만 잡혀 2/3, #92 f08은 4회 중 3회다.
- 2단계(#425) 배포 뒤 운영 Runner에서 확인: `/etc/codex/managed_config.toml` 적용, 모든 checkout이 untrusted, `codex mcp list`는 context-mode·codegraph만 켜짐, `docker-smoke --policy` 통과, dockerd `/dev`의 block device 0건, 자가 점검 `codex exec` 턴의 셸에서 `CLI_API_TOKEN`·`HAPI_*`·`OPENAI_API_KEY` 0건이고 키 파일 없음, `ctx_execute`로 `docker version`(29.8.2)과 `gh api` 성공, 스레드 effort `high`. krema#95를 `@haechibot review`로 다시 리뷰하게 한 실제 실행은 이전 봇이 APPROVE한 같은 head에서, changed file 목록을 줄 단위로 넘기고 `strip()`하는 detector 때문에 끝 공백이나 개행이 든 파일 이름이 suite를 건너뛰게 만드는 P2를 컨테이너 probe로 재현해 REQUEST_CHANGES를 냈다.

### 턴 마감·정체 복구·정리 수용 기준(2026-10-13)

krema#99 implement 턴이 직렬 distro E2E를 로컬에서 6시간 넘게 돌리다 턴 예산에 걸린 사고와, 늦은 결과 유실·매시 정리 실패·Docker 데이터 증가·대체된 세션 잔류·닫을 수 없는 멈춘 이벤트를 고친다. 배포 전후에 아래 절차를 실행하고, 결과를 확인한 항목만 체크한다.

- [ ] `test_bridge.py`, `runner/test_publisher.py`, `runner/chown-sweep`의 `go test`, n8n JSON 파싱, `dockerd-janitor.sh`·`dockerd-start.sh`의 `sh -n`, 두 app의 Kustomize dry-run이 통과한다.
- [ ] 로컬 게이트: implement·followup·PR repair 지시문과 `isac-issue-to-pr` I2P-46이 빠른 게이트만 `ready` 전 조건으로 요구한다. 배포 뒤 첫 implement 턴의 `local_checks`에 e2e·matrix 실행이 없고, PR 본문과 `summary`에 CI에 맡긴 suite가 "left to CI"로 적혀 있다.
- [ ] 턴 마감: `session_send`가 `turns.deadline_at`을 모드별 예산으로 기록하고 `already` 재전송에서는 바꾸지 않으며, 단계 메시지에 절대 UTC 마감 시각이 있다. 마감이 지났는데 에이전트가 아직 일하는 턴의 `session_turn`은 `expired`이고, n8n은 그 응답에서 `Within time budget? (<lane>)`로 실패해 이벤트가 `park_class = "time_budget"`으로 멈춘다. `$runIndex` 720 상한은 마감 판단에 쓰이지 않는다.
- [ ] 늦은 결과 수거: `time_budget`으로 멈춘 이벤트의 에이전트가 마감 뒤에 답하면 다음 dispatcher tick이 같은 `localId`로 이벤트를 다시 진행하고, 워크플로가 그 결과로 push·PR·마무리를 해 `agent:needs-attention`이 지워진다. 답 없이 마감 + 1시간이 지나면 세션이 archive되고 `park_class`가 `time_budget_expired`가 된다. `deadline_at`이 NULL인 이전 턴은 처음 본 park 시각이 기준으로 고정되어, 2시간 동안 24번 검사해도 1시간 유예 뒤 정확히 한 번 archive된다.
- [ ] `retry_event`: 결과가 소비되지 않은 답한 턴은 `sent`와 같은 `localId`로 수거되고, 소비된 턴만 새 `localId`와 `lost`가 된다. 다시 진행한 implement 이벤트의 `begin` `mode_hint`가 `implement`로 남는다.
- [ ] 정리: 한 주제의 실패가 같은 sweep의 다른 주제 정리를 막지 않고, 일시적 실패는 `errors`에만 남아 `Cleanup failed`가 돌지 않는다. 연속 3회 실패한 주제만 `persistent_errors`로 error workflow에 보인다. standalone clone worktree와 쓰기 권한을 뺀 디렉터리가 지워지고, 다른 UID 소유 항목은 `foreign_owner`(409)로 끝난다.
- [ ] dockerd janitor 소유권: worktree 아래 root 소유 항목이 5분 안에 1000:1000이 되고 다음 정리 실행에서 지워진다. 에이전트가 worktree에 심은 symlink는 따라가지 않아 worktree 밖 대상의 소유자가 바뀌지 않고, 다른 파일시스템과 worktree가 아닌 최상위 디렉터리는 건드리지 않는다.
- [ ] maintenance lease: Docker 사용률이 70% 이하이거나 status가 900초보다 오래됐거나 idle이 아니면(`dispatching`/`dispatched`, `time_budget` park, thinking 중이거나 `agentState` 요청이 남은 HAPI 세션) bridge가 lease를 요청하지 않는다. 요청하면 `maintenance_until`이 bridge 재시작 뒤에도 남고, 그동안 dispatcher tick은 `maintenance`를 돌려주며 새 이벤트를 dispatch하지 않되 stale dispatch 감지와 늦은 결과 수거는 돈다. janitor는 유효한 lease가 있고 실행 중인 컨테이너가 없으며 70%를 넘을 때만 24시간 넘은 이미지·build cache를 지우고 전후 사용률을 log에 남긴다. `last_prune_lease`가 `maintenance_until`과 같아지면 hold가 20분이 되기 전에 풀린다. lease 없는 prune 요청은 publisher가 거부하고 janitor도 prune하지 않는다.
- [ ] 대체된 세션: 같은 주제의 세션이 바뀌면 이전 세션이 archive되어 Runner에 대체된 세션 프로세스가 남지 않는다.
- [ ] `dismiss_event`: `needs_attention` 이벤트를 `completed`·`dismissed`로 닫고, 다른 멈춘 이벤트가 없으면 block을 풀고, 게시한 App으로 attention 라벨을 지우고, 세션을 archive한다. PR repair lease를 쥔 이벤트면 dismiss 뒤 `reconcile_pr`이 `active`가 아니고 새 lease를 잡을 수 있다. attention notifier와 겹쳐도 라벨이 남지 않는다. 다른 상태의 이벤트에는 `not_needs_attention`을 돌려주고, 두 번째 호출은 `already: true`다.
- [ ] stale dispatch: n8n 실행이 사라진 `dispatched` 이벤트가 heartbeat 30분 뒤 다음 dispatcher tick에서 `stale_dispatch`로 park되고, 6시간 가까이 도는 정상 implement 턴은 park되지 않는다.
- [ ] 배포 뒤 한 번: 주제가 닫히거나 머지된 `needs_attention` 이벤트를 `dismiss_event`로 닫고 주인 없는 HAPI 세션을 archive했다. 그 뒤 `Hourly cleanup`이 연속 24시간 `Cleanup failed` 없이 돈다.

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
