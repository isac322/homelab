# n8n + HAPI Issue Agent 구현·운영 설계

## 상태와 변경 경계

이 문서는 구현 체크리스트이자 수용 기준이다. 체크되지 않은 항목은 완료·검증되지 않았다. 설계 작성만으로 배포나 검증이 완료되었다고 보고하지 않는다.

사용자가 선택한 구성은 n8n + HAPI다. 기존 Archon은 새 구성의 검증과 안전한 전환 전까지만 유지한다. 사용자의 후속 명시 지시로 **전환 후 Archon 전용 배포·도메인·ArgoCD 등록·코드·대화/worktree/상태 DB PVC와 데이터를 모두 삭제**한다. 앞선 Archon 기록 보존 결정은 폐기되었다. 실제 GitHub 이슈·PR과 새 시스템이 재사용하는 GitHub App·인증 원본은 삭제 대상이 아니다. 이 작업은 임의의 Git 커밋·푸시·PR 머지를 승인하지 않는다. 사용자는 `apps/objects/issue-agent/bridge.py`, `test_bridge.py`의 이벤트 검증·영속 상태·세션 연결·복구·결과 보고와 n8n 워크플로 구현을 명시적으로 승인했다. HAPI·n8n upstream 및 대상 레포 제품 코드의 임의 변경은 승인 범위에 포함하지 않는다.

## 확정된 요구사항

- 공통 Issue Agent를 여러 GitHub 저장소에서 사용할 수 있게 구현한다. 이번 운영 연결은 사용자 선택에 따라 `isac322/cc-lb`만 한다. 복수 레포 분리는 임시 로컬 테스트 저장소로 검증하며 다른 GitHub 저장소의 App 설치를 확장하지 않는다.
- GitHub 이슈마다 독립 세션과 해당 저장소의 worktree를 만든다. 동일 이슈 후속 댓글은 같은 논리 세션으로 전달한다. 이슈별 Pod도 허용하지만 최소 조건은 세션·worktree 분리다.
- 웹에서 모든 이슈 세션을 찾고 실행 중 관찰·메시지 전달·중단·승인을 처리한다. UI 접속 때문에 자동화 구독이나 실행을 종료하지 않는다.
- Codex·Claude Code면 충분하다. 자동 학습 기능은 범위에서 제외한다.
- 하네스가 기록하는 대화·도구 호출·실행 기록을 영속 보존하고 외부 에이전트가 조회할 수 있게 한다. 저장소가 여러 곳이어도 된다. 하네스가 생략한 원시 stdout/stderr의 별도 무손실 수집은 요구하지 않는다.
- 지침·스킬은 외부에서 갱신할 수 있으며 새 세션·재시작·재빌드로 반영해도 된다.
- 커스텀 provider와 모델 설정을 독립적으로 관리한다. 자체 ARM64 이미지 빌드는 허용된다.
- 선호가 불명확한 경우 추측하지 않고 질문한다.
- 허용 사용자의 명확한 요청은 중복·정보 부족 검사를 거친 뒤 자동으로 수정·검증·PR 생성까지 수행한다. 불명확한 요청은 질문하며 자동 머지는 하지 않는다.

## 책임 분리

| 구성 요소 | 책임 |
|---|---|
| n8n | GitHub 이벤트 처리 흐름, 분류 결과에 따른 분기, 질문·승인·구현 단계, 실행 상태 표시 |
| 연결 계층 | webhook 검증, 저장소·사용자 허용 목록, 이벤트 영속화·중복 방지, 이슈/세션 매핑, HAPI API 인증·상태 확인, GitHub 결과 보고 |
| HAPI Hub | 세션 목록·메시지·승인 API, 웹 UI, 다중 구독, Hub 데이터 저장 |
| HAPI Runner | 실제 Codex/Claude 실행, 저장소별 worktree, 하네스 설정·기록 보존 |
| 공통 에이전트 프로필 | 역할·성향·분류/중복 검사/구현/PR 전달 지침과 스킬 |
| 저장소 등록부 | 저장소 식별자, 기본 브랜치, 기존 라벨 매핑, 허용 사용자, 실행 프로필과 운영 정책 |

n8n은 단순히 에이전트를 한 번 호출하는 장식이 아니라 실제 처리 단계와 분기를 소유한다. 연결 계층은 전송·인증·영속 상태의 정확성을 담당하고 같은 비즈니스 절차를 별도로 중복 구현하지 않는다.

## 지침·스킬 계층

1. 공통 Issue Agent 지침: 구현 전 기존 이슈·PR 검색, 증거 기반 중복 판단, 불충분한 정보 질문, 요청 범위 준수, 검증과 결과 보고.
2. 공통 스킬: `issue-triage`, `duplicate-check`, `issue-implementation`, `pr-delivery`에 해당하는 절차. 저장 위치·패키징은 선택한 하네스의 실제 검색 규칙을 확인한 뒤 확정한다.
3. 저장소 지침: 각 저장소의 `AGENTS.md` 또는 `CLAUDE.md`, 테스트 명령과 기여 규칙을 worktree에서 읽는다. 두 하네스가 같은 파일을 자동으로 읽는다고 가정하지 않는다.
4. 접근 제한: 연결 API는 저장소·사용자·작업을 검사하고, GitHub App 설치 토큰은 등록된 저장소로 제한한다. 지침 문구를 강제적인 보안 격리로 설명하지 않는다.

Codex의 공통 지침은 전용 `CODEX_HOME/AGENTS.md`에서 읽고 프로젝트 지침과 결합할 수 있다. 전용 프로필은 개인 설정과 분리한다. 레포 안의 지침이 공통 지침을 덮어쓸 수 있으므로 비밀 보호나 접근 제어의 유일한 장치로 사용하지 않는다.

공통 지침·스킬은 버전 관리한다. 이슈 worktree에서의 수정은 다른 worktree에 자동 전파되지 않는다. 공통 반영은 기준 브랜치나 공통 이미지·설정 배포를 통해 수행한다.

### 자동 머지와 실행 격리의 한계

워크플로는 PR 생성에서 종료하고 merge 단계를 제공하지 않는다. 공통 에이전트 지침도 merge를 금지한다. 다만 Git push에 필요한 GitHub App의 `contents:write` 권한은 기술적으로 merge API 호출도 허용한다. 따라서 자동 머지 금지는 워크플로·에이전트 동작 정책이지, 임의 코드를 실행하는 Runner에 대한 권한 차원의 차단은 아니다. 공유 Runner 역시 악성 코드에 대한 이슈별 보안 샌드박스로 보장하지 않는다. 이번 범위에서 저장소 branch protection을 변경하거나 별도 자격증명 프록시를 추가하지 않는다.

## 이벤트와 세션 계약

- 키는 저장소 식별자와 이슈 번호의 조합이다. 서로 다른 저장소의 동일 이슈 번호를 충돌시키지 않는다.
- GitHub delivery 중복과 의미적으로 중복된 이슈를 구분한다. 전자는 영속 키로 처리하고 후자는 에이전트가 검색·판단한다.
- 이벤트는 수신 확인 전에 영속화한다. 허용하지 않은 저장소·사용자·이벤트는 모델에 전달하지 않는다.
- 에이전트가 작성한 댓글이 재실행 루프를 만들지 않게 한다.
- 세션 생성과 메시지 전송은 결과가 불확실할 때 무조건 재전송하지 않는다. HAPI의 `localId`, queued-state와 세션 메타데이터를 사용해 확인 가능한 것만 복구한다.
- HAPI spawn 응답은 HTTP 200만으로 성공이라고 보지 않는다. `{type:'success', sessionId}`를 확인한다.
- resume/reopen 결과의 세션 ID는 기존과 다를 수 있다. 반환 ID와 superseded 매핑을 반영하여 같은 논리 이슈 대화를 유지한다.
- 운영 자동화는 일반 메시지를 queue로 전달한다. 사용자의 명시적 Steer·중단·승인은 UI를 통해 구분한다. Codex와 Claude의 중간 개입 기능이 같다고 가정하지 않는다.
- 결과는 제출 메시지의 `localId`와 `invokedAt`, 그 메시지 이후의 agent 결과에 포함된 작업별 nonce·결과 스키마를 함께 확인한다. 다른 UI 메시지가 중간에 실행되었거나 결과의 소속이 불확실하면 자동으로 다음 단계로 넘어가지 않는다. 이 경우 사람의 개입 기록은 보존하고 운영자 확인 상태로 전환한다. `/clear`를 기존 이슈의 자동 세션 이전으로 해석하지 않는다.
- 상태가 불확실하거나 권한·provider 오류가 나면 성공으로 처리하지 않는다. 운영자에게 근거를 남기고 중복 실행을 차단한다.

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

### 현재 실행 증거

- 관리자 Secret `issue-agent/issue-agent-n8n-owner` 생성 및 ESO Ready 확인. 이메일 일치, 무작위 비밀번호 복잡도, bcrypt 해시 형식 검증. 평문 미출력. `https://n8n.bhyoo.com/rest/login`에 저장된 자격증명으로 실제 로그인하여 HTTP 200, 이메일 `bhyoo@bhyoo.com`, 역할 `global:owner`를 확인했다.
- HAPI ARM64 이미지 빌드·push 완료: `ghcr.io/isac322/issue-agent-hapi:0.30.7-20260926@sha256:936f5569c8c143fef9250785c339657e1c443f2be4aaa79771c8c7e96ab53b6e`. 컨테이너에서 `hapi --version` → `0.30.7`.
- Runner ARM64 이미지 빌드·push 완료. 초기 이미지의 비루트 지침 디렉터리 접근 오류를 수정한 현재 버전: `ghcr.io/isac322/issue-agent-runner:0.30.7-codex0.157.0-20260926-r2@sha256:359285ea165f65ff826b4f396a99237ed3baa5d63456fb806cfe3af73af4345c`. 실제 컨테이너에서 HAPI `0.30.7`, Codex `0.157.0`, gh `2.101.0`, rustup `1.29.1` 실행 및 비루트 프로필·스킬 접근 확인. Rust compiler toolchain은 아직 설치되지 않은 상태.
- 리뷰에서 발견한 불확실한 n8n 전달의 전역 동시성, HAPI invocation 순서, tool/reasoning 결과 오인 문제 수정 후 bridge 회귀 테스트 **33개 통과**. 모의 외부 서버를 사용한 테스트이며 실제 HAPI/n8n 종단 증거를 대체하지 않는다.
- 실제 파일로 Kustomize 렌더링 및 Kubernetes server-side dry-run 성공. 네 Deployment의 승인된 자원·CPU 제한 없음·이미지 digest 고정을 확인.
- `issue-agent` namespace의 네 Deployment가 Ready이며 HAPI 사설 HTTPS `/health`, 인증 교환, Runner 등록과 Codex availability를 확인했다. GitHub App webhook을 새 수신기로 전환하고 Archon 전용 코드/정의 19개, namespace, 20Gi+1Gi PVC, 두 backing zvol과 두 DNS 이름을 제거했다. Kubernetes NotFound와 rock5bp ZFS 조회, DNS 조회로 삭제 결과를 확인했다.
- n8n 실제 인증 API로 `IssueAgentMain01`의 51개 노드, `active=true`, `activeVersionId=versionId`를 확인했다. 실제 브라우저에서 Owner 계정과 Published 워크플로 캔버스도 확인했다. 여섯 QA 이벤트가 `implemented/replied/duplicate/unclear/implemented/questioned`로 완료됐다.
- HAPI 브라우저 두 탭의 동시 세션 관찰, 단일 명령 승인, pending 명령 Abort, 실행 중 Codex Steer를 실제 UI에서 확인했다. 부모 프로세스의 동시 인증 SSE 구독 두 개도 각각 HTTP 200과 `connection-changed`를 수신했다. 최초 175초 SSE 관찰에서 최종 응답을 수신하지 못했으므로 이를 최종 응답 수신 증거로 사용하지 않는다.
- GitHub QA #869는 bot 작성 실제 이슈와 서명된 synthetic webhook fixture를 사용했다. fixture의 sender/issue.user를 허용 사용자로 구성했으며 실제 GitHub delivery로 간주하지 않는다. n8n execution 1이 완료되고 실제 Draft PR #870(`master ← hapi-issue-869`)에 QA Markdown 한 파일을 생성한 뒤 브리지가 이슈에 결과를 보고했다. 동일 delivery와 동일 이벤트의 새 delivery ID 모두 중복으로 거절되고 새 실행은 생성되지 않았다.
- Hub·Runner·bridge·n8n의 동시 재시작 후 모두 rollout 성공. 새 Pod 네 개가 Running/Ready, 재시작 횟수 0, 이전 OOM 종료 없음이었다. 로컬 A/B는 명시적 resume 후 같은 native ID/JSONL에서 기존 nonce를 기억하고 후속 읽기 명령을 수행했다. 재시작 직후 idle 세션이 inactive로 보이는 것은 자동 재개가 아닌 명시적 resume 방식이다.
- `operations/issue-agent-backup create`와 `verify`를 실제 실행해 4개 component archive의 체크섬과 SQLite DB 9개의 `integrity_check`를 검증했다. 재시작이나 신규 binary 없이 온라인 snapshot을 사용한다. component 간 원자성은 보장하지 않는다. 원본 DB backup은 인증 자료가 포함될 수 있는 **비공개 운영자 자료**이며 외부 transcript export와 다르다. 파일 0600/디렉터리 0700으로 보호한다. restore 절차는 문서화했으며 빈 클러스터에 전체 복원하는 재해복구 실험은 수행하지 않았다.
- 로컬 A/B QA worktree는 export 검증 후 제거했다. Hub 메시지 23개씩과 `archived_sessions`의 원본 Codex JSONL은 보존했다. 운영 #869 worktree와 GitHub 기록은 이 정리에서 변경하지 않았다.
- GitHub App `5063990`의 webhook URL과 secret을 새 수신기로 전환했다. 실제 GitHub 재전달 ID `3844760011376959488`, GUID `97969f60-b902-11f1-8a2a-4e579a1bc4e6`이 `2026-09-25T17:04:56Z` 새 endpoint에서 HTTP 202를 받았다. bridge는 새 서명을 검증한 뒤 bot 작성 #871의 이벤트를 `bot_sender`로 제외했다. 이는 실제 전송·서명 검증 증거이며 허용 사용자의 실제 이슈 생성부터 이어진 end-to-end 실행 증거는 아니다. App identity/권한/설치 범위와 공유 SSM/TFC 인증 원본은 변경하지 않았다.
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
