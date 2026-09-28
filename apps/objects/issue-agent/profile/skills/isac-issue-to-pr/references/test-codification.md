# QA를 테스트 코드로

I2P-25, I2P-33~40의 세부다. `[U]` 규칙은 SKILL.md에 있고, 여기 내용은 그 규칙을 수행하는 방법과 바꿀 수 있는 기본값이다.

## 계층 배치 (가장 낮은 적정 계층)

- unit: 계산, 변환, validation.
- integration(예: 로컬 API 서버, 컨트롤러면 envtest): 이벤트 처리, 상태 전이, status 기록, 정리 로직.
- e2e: 실제 외부 시스템 동작(발급 값, 전파, 권한 차이, 실제 설치 경로).
- fake가 우리 가정을 그대로 구현할 뿐이면 순환 논증이다. 그 항목은 e2e에 남긴다.
- 라이브 전용 계약을 낮은 계층에서 흉내 내지 않는다.
- 기존 커버리지와 중복되면 추가하지 않고 그 근거(기존 테스트 이름)를 보고한다.
- 내리는 조건: 낮은 계층이 같은 계약을 증명할 때만. 공유 테넌트를 파괴하거나 계정 전역에 영향을 주는 케이스는 fake/integration으로 옮기되, 순 계약 커버리지는 줄이지 않고 대체 불가능한 라이브 seam은 e2e에 남긴다. 커버리지가 부족하면 e2e를 늘린다.
- QA-ID별 배치 표: `| ID | Tier | Reason | Required assertion | Blocked handling |`.

## old 실패 / new 통과 증명

- 기준선을 고정한다: commit SHA와 기준선 산출물(wheel, 이미지 등).
- old와 new는 분리된 빌드나 이미지로 비교한다. 새 테스트 파일만 기준선 빌드에 mount하고 기준선 코드는 바꾸지 않는다.
- 회귀 테스트는 기준선에서도 돌아가야 하므로 새 내부 모듈을 import하지 않는다. literal payload와 공개 API만 쓴다.
- 테스트한 산출물의 provenance를 기록한다(설치된 파일 해시와 worktree 파일 일치).
- 결과는 A/B 표로 남긴다: `| QA ID | <default branch> (<sha>) | branch (<sha>) | Environment |`.
- healthy control: 결함 조건이 없는 정상 경로를 old와 new 양쪽에서 돌려 둘 다 통과함을 보인다. 테스트가 아무 것이나 실패시키는 게 아님을 증명한다.
- assertion에 도달하지 못한 실행(예: import 오류, NameError)은 아무것도 증명하지 않는다. 그렇게 보고하고 old/new를 다시 돌린다.

## 제보자 동등 환경

- 제보자 환경(OS, 버전, 설정, 설치 경로)을 적고, 같은 환경 또는 차이를 명시한 동등 환경에서 새 버전으로 재현이 사라짐을 확인한다.
- 사용자 설치 경로(README의 공개 설치법)로 설치한 산출물을 쓴다(I2P-28).
- 동등 환경에서만 확인했으면 "제보자 환경에서 검증"이라고 쓰지 않는다.

## oracle

- 공개 신호나 독립 관측(외부 도구 조회, 원격 API, UI 접근성 트리)을 쓴다. 제품의 자기 보고나 구현 introspection에 기대면 같은 oracle로 old와 new를 판정할 수 없다.
- healthy control도 같은 oracle로 관측 가능해야 한다.
- 확률적 재현은 증거가 아니다. 결정적 oracle(예: 프로세스를 SIGSTOP해 창을 고정, 특정 phase까지 요청을 붙잡는 watcher)을 만든다. 확률적 재현이 안 되면 그렇게 말하고 결정적 테스트로 대체하며 주장을 부풀리지 않는다.

## 금지 패턴

영구 회귀 테스트는 소비자가 관측하는 계약(status·출력, 생성된 자원의 존재와 소유권, 원격 호출 결과, 최종 상태)을 assert하고, 수정을 되돌리면 실패해야 한다. 다음은 금지다.

- source text나 메시지 wording pinning
- 부수적 호출 횟수에 결합
- 반증 불가능한 assertion, tautology, mock echo
- private-field unit test. 결함이 행동이면 행동 테스트나 E2E oracle을 쓴다
- 모든 입력을 echo하는 fake, 아무것도 assert하지 않는 scaffold spec을 커버리지로 세기
- 에러를 우회하거나 assertion을 약화해 통과시키기. 유효한 전제조건을 구성하고 의도한 상태를 기다린다
- 고정 sleep, 타이밍 휴리스틱. 관측 가능한 조건을 bounded poll로 기다린다
- 가짜 API로 만든 픽스처. 실제 코드 픽스처를 쓰고 픽스처가 참조하는 심볼이 존재하는지 확인한다

loose mock보다 stateful fake나 journaled stub을 쓰고, e2e에서 관측한 provider 차이를 fake에 반영한다.

## 장애 주입

- 보안 계약(fail-closed 등)은 실제 장애를 주입해 검증한다. 예: 비밀을 실제로 삭제해 차단을 관측하고, 복원 후 자동 복구를 관측한다.
- 주입은 실제 외부 경계에서만 한다: 실행 파일 PATH shim, 컴포지터·OS 조건, API stub의 fault rule.
- 프로젝트 비즈니스 로직을 mock이나 모듈 교체(PYTHONPATH shadow 등)로 바꾸거나 readiness 이벤트를 위조하지 않는다.

## 탐색 테스트와 seed

- 고정 seed는 실패 재현용이다. 발견이 목적이면 seed를 바꿔 새 상태 조합을 본다. 저장소 테스트 문서가 seed 운용을 다루면 이 원리를 적는다.
- 탐색에는 명시적 action과 이름 붙은 invariant, 독립 oracle(stub journal + status), sanitize된 trace를 둔다. artifact 디렉터리를 지정하지 않으면 저장소에 아무것도 쓰지 않는다.
- 실패는 고정 seed replay와 delta debugging으로 최소 재현 시퀀스까지 줄인다.
- 탐색·대형 random·e2e trace는 영구 테스트로 보존하지 않는다. 발견된 버그마다 최소 결정적 재현을 가장 낮은 유효 계층의 영구 회귀로 승격한다.
- oracle이 틀렸던 것이면 oracle을 고치고, 같은 seed·설정으로 다시 돌려 통과를 보인다. 새 seed에서 나온 새 실패는 별개 원인으로 보고한다.

## flaky와 harness 결함

- full E2E에서 나온 flaky를 "환경 문제"로 넘기지 않는다. 결정적 재현으로 product defect / test oracle defect / environment 중 하나로 분류한다. 실제 결함이면 새 이슈가 필요하다는 사실과 최소 재현을 `issue_comment`와 `summary`에 적는다(이슈 등록은 에이전트가 하지 않는다). 등록된 이슈는 이 파이프라인으로 고친다.
- harness 자체의 버그(e2e cleanup 순서 등)면 제품 테스트와 harness 테스트를 분리해 둘 다 만든다.

## 게이트 검증과 scratch

- mutation-check: 수정을 되돌리거나 의존성 상한을 빼는 등 결함을 다시 넣었을 때 바뀐 테스트나 CI가 실제로 실패하는지 보인다(I2P-39).
- 투기적 테스트와 probe 코드는 저장소 밖에 둔다(`/tmp` 계열 scratch 복사, 언어별 overlay, 기준선 이미지에 mount). 확정된 것만 저장소에 넣는다.
- failing, skipped, TODO 상태의 영구 테스트는 커밋하지 않는다.
