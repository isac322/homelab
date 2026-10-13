# isac-pr-review 케이스

실행 중에는 읽지 않는다.

## 케이스

### CASE-20260918-is-it-really-fixed
- 상태: applied
- 출처: omp session 01a0ae59 msg 70385fee
- 상황: 이슈가 해결됐는지, 아니면 열려 있던 PR까지 머지해야 해결되는지 사용자가 물었다.
- 대상: 이슈 해결 여부 확인과 관련 열린 PR 필요성 판정 / 사용자 소유 공개 저장소(flareway) / 이슈, 에이전트가 만든 열린 PR / 중간(잘못 답하면 불필요한 머지나 잘못된 종결)
- 적용 조건: 열린 PR이 main에 이미 들어간 수정과 겹칠 수 있을 때, 그 PR이 여전히 필요한지 판정하는 모든 PR 리뷰·감사. 저장소 소유권과 PR 작성자와 무관하다.
- 사용자 기대: main 기준으로 문제가 해결됐는지와 열린 PR이 아직 필요한지를 구분한 답.
- 실제 행동: 첫 보고에서 열린 PR의 커밋이 다른 PR을 통해 이미 main에 간접 머지된 것을 놓쳤고, 질문을 받은 뒤 다시 추적해 정정했다.
- 원인 분류: missing / 규칙: PRR-17
- 변경: 신규 규칙으로 시드("여전히 필요한가" 판정에 간접 머지 추적 포함)
- 일반화: global
- 재발 확인 기준: PR 리뷰 판정에 "현재 main에서 이 PR이 여전히 필요한가"가 있고, 커밋 단위로 다른 PR을 통한 간접 머지 여부를 확인한 근거가 붙는다.

### CASE-20260926-reverify-before-close
- 상태: applied
- 출처: omp session 01a0d288 msg 59de466d
- 상황: PR 감사 보고가 여러 PR을 "이미 main에 반영, 닫기 권장"으로 분류하자, 사용자는 그것이 확실한지 되묻고 한 번 더 검수한 뒤 확실하면 관련 정보와 사용할 버전을 댓글로 알리고 닫으라고 했다.
- 대상: 열린 PR 일괄 감사 후 닫기 / 사용자 소유 공개 저장소(kwin-mcp), 외부 기여자 PR 포함 / PR 코멘트와 close / 높음(되돌리기 어려운 공개 종결, 기여자 대상)
- 적용 조건: 외부 기여자 PR을 superseded로 판정해 닫거나 닫기를 권고할 때. 판정이 이전 패스에서 나왔으면 닫기 직전에 현재 main 기준으로 재검증한다. 사용자의 닫기 지시가 있어야 실제로 닫는다(PRR-02). 판정만 하고 닫지 않는 리뷰, 에이전트나 사용자 자신의 PR을 일회성으로 정리하는 경우(예: 01a0b303 9d9980a8에서 재검증 없이 바로 닫으라고 한 사례)는 제외한다.
- 사용자 기대: 닫기 전 확실성을 다시 확인하고, 고친 위치와 사용할 버전이 담긴 코멘트와 함께 닫는다.
- 실제 행동: 첫 보고의 superseded 판정만으로는 확실성이 부족했다. 이후 릴리스 아티팩트에서 판별 재현을 다시 돌려 확인하고 닫기 코멘트와 함께 닫았다.
- 원인 분류: loose / 규칙: PRR-33, PRR-34 (PRR-35는 태그 없는 기본값)
- 변경: 신규 규칙으로 시드
- 일반화: global
- 재발 확인 기준: superseded 판정마다 수정 커밋, 첫 릴리스, 판별 재현 근거가 있고, 닫기 직전 재검증 패스가 따로 기록된다.

### CASE-20260926-explain-merge-verdicts
- 상태: applied
- 출처: omp session 01a0d288 msg 59de466d
- 상황: PR 판정을 "머지 가능 / 수정 후 머지 / 이미 반영·닫기 권장 / 일부만 유효" 표로 보고했고, 사용자는 이 묶음을 받아들이면서 "머지 가능"과 "수정 후 머지"가 각각 무슨 내용인지 설명하라고 했다.
- 대상: 여러 PR 감사 결과의 사용자 보고 / 사용자 소유 공개 저장소(kwin-mcp) / 한국어 사용자 보고(GitHub 게시물 아님) / 낮음
- 적용 조건: 여러 PR의 판정을 한 번에 사용자에게 보고할 때. 단일 PR 리뷰 보고에는 결정 단위 묶음 대신 그 PR의 판정 의미 설명만 적용한다.
- 사용자 기대: 결정 단위 묶음과 함께 각 판정이 구체적으로 뜻하는 바(바뀐 것, 이유, 남은 것).
- 실제 행동: 표에 핵심 근거 한 줄만 있었고 판정별 의미 설명이 없었다.
- 원인 분류: missing / 규칙: PRR-31
- 변경: 신규 규칙으로 시드
- 일반화: global
- 재발 확인 기준: 사용자 보고의 판정 그룹마다 무엇이 바뀌었고 왜 그 판정이며 무엇이 남았는지가 적혀 있다.

### CASE-20260927-verdict-as-review-event
- 상태: applied
- 출처: omp session 01a0dda6 msg 84a012fa
- 상황: 스킬 패밀리 초안이 PR 리뷰를 COMMENT로만 남기고 판정은 `review:*` 라벨로 붙이게 했다. 사용자 근거가 없는 에이전트 기본값이었고, 사용자는 라벨 대신 GitHub 리뷰 유형(APPROVE / REQUEST_CHANGES / COMMENT)을 쓰라고 교정했다.
- 대상: PR 리뷰 게시 방식 / 모든 저장소 / GitHub PR 리뷰 이벤트와 라벨 / 중간(APPROVE는 required review 충족에 쓰인다)
- 적용 조건: 이 스킬로 PR 리뷰를 게시하는 모든 경우. 리뷰 계정이 PR 작성자라 GitHub가 이벤트를 거부할 때만 COMMENT로 대체한다.
- 사용자 기대: 판정을 리뷰 이벤트로 표현하고, 판정 라벨을 붙이지 않는다.
- 실제 행동: 초안 PRR-25가 APPROVE·REQUEST_CHANGES를 금지했고, PRR-27이 판정 라벨을 붙이게 했다.
- 원인 분류: wrong / 규칙: PRR-25, PRR-27
- 변경: PRR-25를 판정별 이벤트 매핑 [U]로 바꾸고, PRR-27을 폐기하고, 재리뷰 이벤트 갱신을 PRR-37로 추가
- 일반화: global
- 재발 확인 기준: 게시된 리뷰의 이벤트가 판정과 맞고(GREEN=APPROVE, BLOCKING=REQUEST_CHANGES), `review:*` 라벨이 붙지 않는다.

### CASE-20261011-kwin-mcp-review-gate
- 상태: applied
- 출처: omp session 01a11ff7 (kwin-mcp #90, #92–#98 수정 세션과 haechibot 리뷰 대조)
- 상황: 사용자 세션이 kwin-mcp PR #90, #92–#98을 고치면서 찾은 결함을 haechibot 리뷰와 대조했다. 리뷰는 #92, #93, #94, #95, #97을 `GREEN`(APPROVE)으로 냈고 판정 줄에 `PR-ready: false: CI still pending` 같은 CI 상태를 붙였다. 놓친 것: #90 시그널 핸들러 예외가 AnyIO TaskGroup 안에서 종료를 막음(P1), 종료 중 registry 락 해제로 SIGKILL escalation이 건너뛰어짐(P1), 등록과 정리 사이 창의 자식 프로세스 누수, 새 `ty: ignore`; #92 축소 이미지 좌표가 픽셀 중심이 아니라 모서리로 매핑, 부분 캡처에서 무효 영역으로 필터가 번짐, `--screenshot-max-edge` 반복 플래그, Python 3.12/3.13 CLI annotation 파싱; #93 registry 락 아래 D-Bus 연결·introspection의 25초 기본 타임아웃(P1), 복원 상태를 기록하기 전에 설정을 바꿈; #94 같은 크기 형제 창이 fail-closed 매칭을 깸, 테스트의 `type: ignore`; #95 SELinux가 거부한 경로를 우회하는 fallback과 `Exec=` 파싱 차이(승인됨); #96 순차 placeholder 치환으로 KWin JS 인젝션(P1, 세션 수정 전 리뷰 없음); #97 `10**400`이 Infinity가 되는 숫자 검증 누락과 CLI JSON의 스키마 우회, 관찰하지 않은 "Geometry set" 응답; #97·#98이 같은 도구 수를 따로 올림; CONTRIBUTING·README 테스트 목록 동기화 누락. 우리가 제안한 수정(락을 복원 끝까지 유지)이 새 블로킹 I/O hazard를 들여온 경우도 있었다. kwin-mcp 리뷰 실행 24회 중 17회가 PR 코드를 runner 호스트 셸에서 돌렸다.
- 대상: PR 리뷰 판정 게이트 / 사용자 소유 공개 저장소(kwin-mcp), 일반화는 모든 저장소 / GitHub PR 리뷰 이벤트와 본문, `issue-agent/review` 상태 / 높음(APPROVE가 required review를 채우고, 놓친 P1이 머지될 수 있다. 호스트 실행은 자격 증명 노출 위험)
- 적용 조건: 이 스킬로 PR을 리뷰하는 모든 경우. kwin-mcp 고유 규칙(문서 동기화 트리거, 억제 0 정책, live desktop 안전, `_render_script` 단일 인코딩 등)은 `references/projects/isac322__kwin-mcp.md`에만 두고 여기서 일반화하지 않는다.
- 사용자 기대: 리뷰 판정이 CI와 무관하고 lint·type·test 결과를 보고하지 않는다 [U]; PR이 들여온 취약점은 위치·메커니즘·수정안과 함께 리뷰에 적는다 [U]; PR 코드는 격리된 컨테이너에서만 실행한다 [U]; "결함 없음"과 APPROVE에는 반박 근거가 있고, 반박하지 못한 P0–P2 의심이나 메인테이너 결정이 남으면 APPROVE하지 않는다.
- 실제 행동: 판정 줄이 CI·`PR-ready`를 근거처럼 썼고, 동시성·시그널·수치·입력 경로를 렌즈로 나누지 않아 결함 부류 전체를 놓쳤다. "알려진 입력이 없다", "probe가 도구 문제로 실패했다"는 이유로 후보를 버렸다. 저장소 CLAUDE.md의 동기화 트리거를 적용하지 않았고, 수정 커밋의 hazard를 다시 보지 않았다. 보안 정책 우회를 결정 요청 없이 승인했다.
- 원인 분류: wrong(CI를 판정 근거로 씀, PR-ready), missing(렌즈, 반박 규칙, 입력 경로, hazard 패스, 저장소 관례, 실행 채널) / 규칙: PRR-19, PRR-24, PRR-25, PRR-28, PRR-29, PRR-30, PRR-38–PRR-56
- 변경: PRR-38 [U], PRR-48 [U], PRR-55 [U] 신규; PRR-39–PRR-47, PRR-49–PRR-54, PRR-56 신규; PRR-24·PRR-25에서 `PR-ready` 제거와 `OPEN` 판정 추가; PRR-29를 head마다 전체 리뷰로 확장; PRR-30을 문구 전용 fix-round로 좁힘; PRR-19를 기존 취약점으로 좁힘; PRR-28 폐기; `open_items` 결과 필드 추가; review-dimensions §8 blocking 기준(PR이 들여온 근거 있는 P2)과 §10–§14 추가
- 일반화: global
- 재발 확인 기준: 게시된 리뷰의 판정 줄과 근거에 CI·`PR-ready`가 없다. 트리거된 렌즈마다 트리거와 커버리지가 적혀 있고, 버린 후보가 `Considered` 고정 형식으로 남는다. 결정 항목·hold가 남으면 이벤트가 COMMENT(확인된 PR 도입 취약점만 예외)이고, 그 밖의 미반박 P0–P2 의심은 COMMENT(구현 봇 PR은 "prove or fix" REQUEST_CHANGES)이며, 어느 쪽이든 `open_items`가 그 이유를 담고 본문에 @멘션이 없다. 메인테이너 답은 write 이상 권한이 확인될 때만 항목을 해소한다. PR 코드 실행 기록이 모두 `docker run --rm --network none` 컨테이너 안이다. 롤아웃 후 7일 동안 저장소별 non-draft head 중 COMMENT로 끝난 비율이 30%를 넘으면 PRR-49·PRR-53을 다시 본다.

### CASE-20261013-review-suites-to-ci
- 상태: applied
- 출처: omp session 01a1333f (2026-10-13 사용자 결정; isac-issue-to-pr CASE-20261013-long-suites-to-ci와 같은 결정)
- 상황: homelab #435가 로컬 게이트 분담(빠른 게이트는 로컬, 오래 걸리는 suite는 CI)을 implement·followup·PR repair에만 넣고 review 모드에는 넣지 않았다. krema#101(Ubuntu 26.10 패키징을 distro matrix에 추가하는 PR) 리뷰가 패키징 claim을 확인하려고 runner에서 docker 이미지·패키지 build를 네 번 돌렸다(native-install build 581초, ubuntu-26.10 deb build 216초, ubuntu-26.04 deb build 207초, cross-install build 53초, 합계 약 18분). 함께 돌던 cc-lb#936 리뷰와 겹쳐 runner 컨테이너가 5Gi 한도에서 2026-10-13 06:22Z·06:29Z 두 번 OOMKilled됐고, 두 리뷰 턴이 모두 사라져 `-r2`까지 다시 보내졌다.
- 대상: PR 리뷰 로컬 실행 범위 / 모든 저장소 / 리뷰어의 테스트·빌드·probe 실행 / 높음(runner OOM이 같은 Pod의 모든 진행 중 턴을 잃게 한다)
- 적용 조건: 이 스킬로 PR을 리뷰하는 모든 경우. 리뷰어는 오래 걸리는 suite를 필요할 때도 로컬에서 돌리지 않는다(구현 쪽의 CI 실패 재현 예외는 리뷰에 없다)
- 사용자 기대: 모든 프로젝트에서 e2e 같은 오래 걸리는 테스트는 로컬에서 기본으로 돌리지 않는다. CI가 돌리고, 로컬에서는 필요할 때만 돌린다 [U]. 리뷰어는 오래 걸리는 suite의 CI 결과를 읽고, 특정 claim 확인에 필요한 빠른 targeted check만 로컬에서 돌린다.
- 실제 행동: PRR-38·PRR-55가 "PRR-55 채널에서 무엇이든 직접 돌릴 수 있다", "PR의 Dockerfile을 빌드해도 된다"고 해 리뷰어가 distro 패키지 matrix와 컨테이너 이미지 build를 로컬에서 돌렸다. n8n `Prepare review step` 지시도 "you may run anything yourself"였다.
- 원인 분류: missing(리뷰 모드의 로컬 실행 범위) / 규칙: PRR-11, PRR-38, PRR-43, PRR-44, PRR-46, PRR-55
- 변경: PRR-57 [U] 신규(오래 걸리는 suite — e2e, GUI·Appium, multi-distro·패키지 matrix, 컨테이너 이미지 build, envtest, integration·soak — 는 CI 몫이고 리뷰어는 로컬에서 돌리지 않으며 CI 결과는 입력으로만 읽는다; 로컬은 특정 claim 확인용 빠른 targeted check만). PRR-11, PRR-38, PRR-43, PRR-44, PRR-46, PRR-55(PR Dockerfile build 허용 삭제), 완료 조건, review-dimensions §1·§7·§9·§10·§12·§14, comment-template `Not verified`, stale-pr-audit 재현 단계, `references/projects/isac322__kwin-mcp.md` §2(E2E 이미지는 CI 몫, lint와 probe는 scratch 이미지), n8n `Prepare review step` 지시를 같은 범위로 고침
- 일반화: global
- 재발 확인 기준: 리뷰 턴의 실행 기록에 e2e·matrix 실행, PR Dockerfile이나 배포판 패키지 build가 없고, 리뷰 턴 하나의 단일 명령이 몇 분을 넘지 않는다. 오래 걸리는 suite로만 확인할 수 있는 claim은 `Not verified`나 argument+challenger로 남는다. 롤아웃 뒤 runner 컨테이너 OOMKilled 재시작이 리뷰 실행과 겹쳐 생기지 않는다.

### CASE-20261013-redundant-thread-replies
- 상태: applied
- 출처: 2026-10-13 사용자 결정 (cc-lb#936 haechibot 리뷰 기록 감사)
- 상황: cc-lb#936에서 haechibot이 재리뷰마다 이전 봇 스레드 전부에 답글을 다시 달았다. 답글 184개 중 139개가 이미 resolve된 스레드에 반복한 "Closed at …"였고, 새 사람 댓글이 없는 스레드였다. bridge는 답글마다 REST `POST /repos/{repo}/pulls/{n}/comments/{root}/replies`를 불렀고 GitHub가 그 답글을 각각 빈 `COMMENTED` 리뷰로 감싸, PR 하나에 답글 하나짜리 리뷰 184개와 판정 리뷰 13개가 쌓였다.
- 대상: 재리뷰 스레드 답글 / 모든 저장소 / `ReviewResult.thread_replies`와 bridge `github.review` 게시 / 중간(리뷰 타임라인이 소음으로 덮여 사람이 판정과 새 finding을 찾지 못한다)
- 적용 조건: 이 스킬로 이전 봇 리뷰가 있는 PR을 재리뷰하는 모든 경우
- 사용자 기대: 스레드 답글은 (1) 새 head에서 finding 상태가 바뀐 미해결 스레드, (2) 해결 여부와 무관하게 봇의 마지막 댓글 뒤에 사람이 댓글을 단 스레드에만 단다 [U]. 해결된 스레드는 다시 확인하지 않고, 상태가 그대로인 열린 스레드에도 답하지 않는다. 라운드별 상태는 본문 Closed/Open 절이 기록한다. 해결된 스레드의 finding이 회귀하면 새 인라인 finding으로 낸다. 한 라운드는 GitHub 리뷰 하나로 게시한다.
- 실제 행동: SKILL.md 재요청 문단, `thread_replies` 표 줄, PRR-29, 완료 조건("재리뷰면 이전 봇 스레드마다 `thread_replies`가 있다"), `comment-template.md`, `defaults.md`, n8n `Prepare review step`("answer existing threads with `thread_replies`")이 모두 이전 봇 스레드마다 답글을 요구했다. `reviewThreads` 지시는 `isResolved`와 댓글 작성자를 읽게 하지 않았다.
- 원인 분류: wrong(모든 스레드에 답글 요구) / 규칙: PRR-29, 완료 조건
- 변경: PRR-29 [U](답글 조건 두 가지, 해결된 스레드 재확인 금지, 상태 그대로인 열린 스레드 답글 금지, 해결된 스레드의 회귀는 새 인라인 finding), 입력 문단(`reviewThreads`에서 `isResolved`, 댓글 `author{login}`·`createdAt` 선택), 재요청 문단, `thread_replies` 표 줄, 완료 조건(조건에 맞는 스레드에만 정확히 하나씩), `comment-template.md` 인라인 finding과 스레드 답글 절, `defaults.md` 게시, n8n `Prepare review step` 지시. bridge는 해결됐고 봇의 마지막 댓글 뒤에 사람 댓글이 없는 스레드에 대한 답글을 경고 로그와 함께 버리고(리뷰는 실패시키지 않는다), 남은 pending 리뷰를 먼저 지운 뒤 GraphQL pending 리뷰 하나에 새 인라인 스레드·스레드 답글·판정 본문을 담아 함께 제출하고 그다음 resolve한다.
- 일반화: global
- 재발 확인 기준: 롤아웃 뒤 재리뷰 라운드마다 봇 리뷰가 하나만 생기고 답글 하나짜리 빈 `COMMENTED` 리뷰가 없다. 해결된 스레드에 새 사람 댓글 없이 봇 답글이 달리지 않고, 상태가 그대로인 열린 스레드에 "Still open" 답글이 없다. bridge 로그의 답글 버림 경고가 드물다(에이전트가 규칙을 따른다).

## 출처 색인

`패밀리 설계 요청` = 이 스킬 패밀리 증류를 요청한 사용자 메시지의 PR 리뷰 프레이밍(PR 이해, blast radius, 프로젝트 영향 심각도, 실제 해결 여부, 보안, 성능, 구조, 리뷰 코멘트를 달아야 하고 라벨도 추가하면 좋다). 판정을 라벨 대신 리뷰 이벤트로 표현하라는 이후 교정(CASE-20260927-verdict-as-review-event)이 라벨 부분을 대체한다.

| 규칙 ID | 근거 |
|---|---|
| PRR-01 | omp 01a0d288 a1dd383e; 패밀리 설계 요청 |
| PRR-02 | omp 01a0d288 a1dd383e, 59de466d |
| PRR-03 | omp 01a0d288 59de466d |
| PRR-05 | omp 01a0dbf0 8809e0ec |
| PRR-08 | omp 01a0d288 a1dd383e; omp 01a0dbf0 8809e0ec; 패밀리 설계 요청 |
| PRR-09 | omp 01a0d288 a1dd383e, 59de466d |
| PRR-10 | omp 01a0d288 59de466d |
| PRR-12 | omp 01a0dbf0 8809e0ec |
| PRR-13 | omp 01a0dbf0 8809e0ec; 패밀리 설계 요청 |
| PRR-14 | 패밀리 설계 요청 |
| PRR-15 | 패밀리 설계 요청 |
| PRR-16 | 패밀리 설계 요청 |
| PRR-17 | omp 01a0d288 59de466d; omp 01a0ae59 70385fee (CASE-20260918-is-it-really-fixed) |
| PRR-22 | 패밀리 설계 요청 |
| PRR-19 | omp 01a11ff7 (CASE-20261011-kwin-mcp-review-gate): PR이 들여온 취약점은 PRR-48로 분리 |
| PRR-25 | omp 01a0dda6 84a012fa (CASE-20260927-verdict-as-review-event); omp 01a11ff7 (CASE-20261011-kwin-mcp-review-gate) |
| PRR-31 | omp 01a0d288 59de466d (CASE-20260926-explain-merge-verdicts) |
| PRR-32 | omp 01a0d288 59de466d |
| PRR-33 | omp 01a0d288 59de466d (CASE-20260926-reverify-before-close) |
| PRR-34 | omp 01a0d288 59de466d (CASE-20260926-reverify-before-close) |
| PRR-24, PRR-29, PRR-30 | omp 01a11ff7 (CASE-20261011-kwin-mcp-review-gate) |
| PRR-29 [U] (스레드 답글 조건) | 2026-10-13 사용자 결정 (CASE-20261013-redundant-thread-replies) |
| PRR-38–PRR-56 | omp 01a11ff7 (CASE-20261011-kwin-mcp-review-gate); PRR-38, PRR-48, PRR-55는 그 세션의 사용자 결정 [U] |
| PRR-57 | omp 01a1333f (CASE-20261013-review-suites-to-ci); 2026-10-13 사용자 결정 [U] |

## 규칙 이력

| 날짜 | 규칙 | 변경 | 케이스 |
|---|---|---|---|
| 2026-09-27 | PRR-36 | 폐기: 에이전트가 만든 PR 하나를 닫으라는 일회성 지시였고, 내용은 PRR-17·PRR-33·PRR-02가 다룬다 | — |
| 2026-09-27 | PRR-25 | "COMMENT만" 기본값을 판정별 리뷰 이벤트 매핑 [U]로 교체 | CASE-20260927-verdict-as-review-event |
| 2026-09-27 | PRR-27 | 폐기: 판정 라벨을 리뷰 이벤트로 대체 | CASE-20260927-verdict-as-review-event |
| 2026-09-27 | PRR-37 | 신규: 재리뷰 시 새 판정 이벤트로 다시 남김 | CASE-20260927-verdict-as-review-event |
| 2026-10-11 | PRR-28 | 폐기: fork PR의 CI 실패 해석은 CI를 판정 근거로 쓰지 않는 PRR-38 [U]로 대체 | CASE-20261011-kwin-mcp-review-gate |
| 2026-10-11 | PRR-24, PRR-25 | `PR-ready`와 CI 상태 제거, `OPEN` 판정(`COMMENT`)과 `open_items` 추가 | CASE-20261011-kwin-mcp-review-gate |
| 2026-10-11 | PRR-19 | 범위를 PR이 들여오지 않은 기존 취약점으로 좁힘(PR이 들여온 것은 PRR-48) | CASE-20261011-kwin-mcp-review-gate |
| 2026-10-11 | PRR-29, PRR-30 | PRR-29: head마다 merge-base 기준 전체 리뷰. PRR-30: 문구 전용 fix-round로 좁힘 | CASE-20261011-kwin-mcp-review-gate |
| 2026-10-11 | PRR-38–PRR-56 | 신규: CI 무관 판정, 원문 읽기, 저장소 관례, 재개 턴, 최소 런타임, 렌즈, 입력·인젝션, 억제, 테스트 감사, 보안 정책 우회·메인테이너 hold, PR이 들여온 취약점, 미반박 의심, 반박 규칙, 런타임 claim, 내용 없는 blocking 금지, 렌즈 완결성, hazard 패스, 격리 실행 채널, 이벤트 결정 순서 | CASE-20261011-kwin-mcp-review-gate |
| 2026-10-12 | review-dimensions §10 (R1) | cycle 2, replay 유래: 시그널·취소 창을 예외가 나타날 수 있는 모든 프레임(루프 대기, 태스크 그룹 안 실행, 워커, `finally`)과 프레임워크 래핑(ExceptionGroup, 취소 변환, goroutine·task panic)으로 확장. 시그널 probe는 격리 채널로만(kwin-mcp #90 f00) | CASE-20261011-kwin-mcp-review-gate |
| 2026-10-12 | PRR-43, PRR-53, review-dimensions §10 (R2) | cycle 2, replay 유래: 렌즈 항목마다 `file:line`+probe/논증 근거. 일괄 "source inspection" 주장은 아무것도 덮지 않는다. 관찰한 이상 동작은 finding·Considered로. 근거 없는 렌즈 답은 한 번 재실행, 그래도 없으면 덮이지 않음 → COMMENT + open_items(#90 f00, #92 f11) | CASE-20261011-kwin-mcp-review-gate |
| 2026-10-12 | PRR-50, review-dimensions §12 (R3) | cycle 2, replay 유래: 논증은 같은 인터리빙을 다룬다(임계 구역 사이 틈의 다른 행위자). challenger 독립성(논증 작성자 아님, 같은 후보, 답이 후보 `file:line` 인용), `argument+challenger(<agent name>)` 형식. 반박 아님 (e) 문서화된 한계는 claim, (f) 받아들인 값을 조용히 무시·대체(기본 P3, 출력이 거짓이면 P2)(#90 f01, #92 f10·f11) | CASE-20261011-kwin-mcp-review-gate |
| 2026-10-12 | review-dimensions §10 (R4) | cycle 2, replay 유래: 이름 예약은 배타적 생성이나 증명된 전용 namespace만 안전. 프로세스 안 직렬화는 반박이 아니다. 실패 정리는 배타적으로 만든 것만 지운다(#92 f10) | CASE-20261011-kwin-mcp-review-gate |
| 2026-10-12 | PRR-54, comment-template Fix hazards (R5) | cycle 2, replay 유래: 이전 제안을 따른 수정이라는 출처(커밋 메시지·스레드 답글·일치하는 diff)가 보일 때만 "This head applies the fix suggested in <link>"와 hazard 귀속(#93) | CASE-20261011-kwin-mcp-review-gate |
| 2026-10-12 | comment-template 머리말 (R6) | cycle 2, replay 유래: 공개 텍스트에 스킬 이름·규칙 ID·자동화 경로 금지, 판단 이유는 프로젝트 사실로. 렌즈 이름은 예외(#95 공개 본문의 PRR-47 인용) | CASE-20261011-kwin-mcp-review-gate |
| 2026-10-12 | PRR-39 (R7) | cycle 2, replay 유래: 변경 파일 목록·diff는 새로 fetch한 base의 merge-base에 대한 shell `git diff --name-only <merge-base>...HEAD`. `ctx_*` 색인 메타데이터로 읽을 파일을 정하지 않는다(#93) | CASE-20261011-kwin-mcp-review-gate |
| 2026-10-12 | review-dimensions §8 (R8) | cycle 2, replay 유래: 확인된 결함의 심각도 하한. P0/P1은 현실적 트리거 필요, stub 전용 재현은 실제 프레임워크 probe 시도 후에만 최대 P2(실제 API가 낼 수 있는 실패 주입은 예외), 원자적 API 없는 본질적 경합은 최대 P2·계약 밖이면 P3. 미반박 의심 등급은 낮추지 않는다(#98 noise) | CASE-20261011-kwin-mcp-review-gate |
| 2026-10-12 | PRR-40, review-dimensions §13 (R9 generic) | cycle 2, replay 유래: 저장소 merge 설정에서 기본 브랜치 커밋이 되는 텍스트(squash 제목 출처)를 배우고 그 관례를 확인한다. kwin-mcp 고유 부분은 프로젝트 파일 KM-C1(#97 f29) | CASE-20261011-kwin-mcp-review-gate |
| 2026-10-12 | review-dimensions §10 (C3-1) | cycle 3, replay 유래: lifecycle에 필수 항목 둘 추가 — 락을 놓고 다시 잡는 틈(sleep·wait·grace·여러 단계 escalation)마다 다른 행위자의 할 수 있는 일, close/shutdown 후 등록·변경(스냅샷은 뒤의 등록을 덮지 못함)(#90 f01·f02) | CASE-20261011-kwin-mcp-review-gate |
| 2026-10-12 | review-dimensions §8 (C3-2) | cycle 3, replay 유래: stub 전용 재현 상한 제거. fault injection(실제 API가 낼 수 있는 실패 재현)은 현실적 트리거, 외부 API로 현실적으로 닿으면 등급 유지, "실제 입력을 아직 못 찾음"은 낮추는 이유 아님(#98 f27이 P2로 잘못 깎임) | CASE-20261011-kwin-mcp-review-gate |
| 2026-10-12 | PRR-50, review-dimensions §12, comment-template (C3-3) | cycle 3, replay 유래: `argument+challenger(<name>)`의 이름은 spawn 도구가 돌려준 서브 에이전트 id. 일반 이름이면 반박이 아니고 항목은 덮이지 않은 것 | CASE-20261011-kwin-mcp-review-gate |
| 2026-10-12 | PRR-43 (C3-4) | cycle 3, replay 유래: 한 렌즈의 체크리스트 항목이 ~5개를 넘으면 모듈별 서브 에이전트로 나눈다(동시 최대 2개, 나머지 순차). 나눠도 항목별 근거가 없으면 덮이지 않은 것 | CASE-20261011-kwin-mcp-review-gate |
| 2026-10-12 | PRR-43, review-dimensions §10 | cycle 3 sign-off 후속: 락·프로세스/스레드·시그널·close/shutdown 상태를 가진 변경 모듈이 둘 이상이면 concurrency/lifecycle 렌즈를 모듈별 서브 에이전트로 나누는 것을 필수로 함(락 틈·close 후 사용 항목별 `file:line` 근거). 다른 렌즈는 ~5개 초과 규칙 유지. f01은 lifecycle 렌즈를 나눴을 때만 찾았다(#90) | CASE-20261011-kwin-mcp-review-gate |
| 2026-10-13 | PRR-57 신규 [U]; PRR-11, PRR-38, PRR-43, PRR-44, PRR-46, PRR-55, 완료 조건, review-dimensions §1·§7·§9·§10·§12·§14, comment-template, stale-pr-audit, projects/isac322__kwin-mcp §2 | 리뷰어 로컬 실행 범위: 오래 걸리는 suite(e2e, GUI·Appium, multi-distro·패키지 matrix, 컨테이너 이미지 build, envtest, integration·soak)는 CI 몫으로 로컬에서 돌리지 않고 CI 결과는 입력으로만 읽음; 로컬은 특정 claim 확인용 빠른 targeted check만. PRR-55의 "PR의 Dockerfile을 빌드해도 된다" 삭제, "무엇이든" 실행 허용을 PRR-57 범위로 좁힘(krema#101 리뷰의 약 18분 docker 패키지 build와 runner OOM 2회) | CASE-20261013-review-suites-to-ci |
| 2026-10-13 | PRR-29 [U], 완료 조건, comment-template 인라인 finding과 스레드 답글, defaults 게시 | 스레드 답글은 상태가 바뀐 미해결 스레드와 봇의 마지막 댓글 뒤 사람 댓글이 있는 스레드에만. 해결된 스레드 재확인·상태 그대로인 열린 스레드 답글 금지, 해결된 스레드의 회귀는 새 인라인 finding. bridge는 조건 밖 답글을 버리고 라운드당 리뷰 하나로 게시 | CASE-20261013-redundant-thread-replies |
