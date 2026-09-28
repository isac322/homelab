# QA list 토론 (구현 전)

I2P-22, I2P-23의 세부다. 토론 절차 자체(독립 조사 → 상호 반박 → 합의/중재, 판정 어휘, 규모 게이트)는 `isac-multi-agent-consensus`(QA 목록 판정, 표준 규모)를 따른다. 여기에는 이 스킬이 QA list에 요구하는 입력, 각도, 산출물 형식만 둔다. 이 문서의 내용은 바꿀 수 있는 기본값이다.

## 위치와 입력

- I2P-22 단계다. 코어 변경 게이트(I2P-14)를 통과한 뒤, 코드를 한 줄도 쓰기 전에 한다.
- 입력: 이슈의 근본 원인 댓글(`isac-issue-triage` 산출물), 합의된 수정 방향, 승인된 brief가 있으면 그 범위, 기존 테스트와 CI 구성.
- "X 지원" 요청이면 parity 인벤토리(`isac-issue-triage` 스킬, TRI-25 절차)를 먼저 만들고 그 항목도 QA 후보로 넣는다.

## 영향 반경 각도(체크리스트)

각 연구자는 한 각도 이상을 맡아 독립적으로 매핑한다. 해당 없는 각도는 "해당 없음 + 근거 한 줄"로 닫는다.

1. 변경 함수의 모든 caller와 lifecycle 전이
2. 같은 status·계약을 소비하는 형제 컴포넌트
3. status / conditions / 사용자에게 보이는 출력
4. 생성 산출물(렌더된 설정, 다른 컴포넌트가 읽는 출력 등)
5. cleanup과 삭제 경로(예: 컨트롤러면 finalizer)
6. 보안 불변식: 소유권 provenance, 식별자 검증 쓰기, 비밀의 status·log 비노출, fail-closed 인가 순서
7. 성능과 외부 API 호출량, 캐시 stale, 동시 실행·리더 선출
8. 직전 릴리스가 남긴 상태에서의 upgrade 경로(기존 객체, status 필드). 일회성 위험은 알려진 위험으로 upgrade 문서에 적는다
9. docs / CHANGELOG / conformance 영향
10. 탐색·state-machine 기대(미지 버그 탐색 트랙)
11. 같은 패턴의 형제 결함(I2P-03)

## 증거 규칙

- 주장은 실제 artifact와 심볼(file:line)에 근거한 반증 가능한 형태여야 한다.
- 실행하지 않았거나 지어낸 코드를 근거로 든 challenge는 기각한다.
- 통합자는 각 finding을 repo 증거로 확인하고, 가능하면 결함 메커니즘을 실증한다.

## 두 트랙

- (a) 계약 편입: 알려진 계약을 테스트 피라미드에 넣는 항목.
- (b) 탐색: 미지 버그를 찾는 항목(seed 회전, state-machine). 발견된 버그는 최소 재현으로 줄여 (a)로 승격한다(`test-codification.md`).
- 두 트랙을 한 항목에 섞지 않는다. 리뷰어는 만들지 말아야 할 과잉 설계도 적는다.

## 통합 산출물

합의 리뷰어(통합자)는 다음을 낸다.

- 모든 QA ID 보존. 합치거나 쪼갠 항목은 원래 ID를 참조한다(keep / split / move 판정).
- 누락 감사: 위 각도 중 비어 있는 것.
- 첫 구현 묶음: TDD로 먼저 실패를 볼 항목.
- 알려진 미수정 버그의 처리: 이 PR에서 고침 / 별도 이슈 / 범위 밖(I2P-05).
- 기각 항목과 근거.

## QA-ID 표

GitHub에 올리는 경우(PR 본문 등) 표는 영어로 쓴다.

| ID | Behavior (expected) | Observation that proves it | Test (name) | Tier | Exec |
|---|---|---|---|---|---|
| QA-01 | Deleting the owner removes the remote record | remote API lookup returns 404 after delete; status cleared | `TestDeleteRemovesRemote` | e2e | executable |
| QA-02 | Reconcile never writes when mode is observe-only | fake journal shows zero write calls | `TestObserveOnlyNoWrites` | integration | executable |
| QA-03 | Missing credentials fail closed | request denied; no partial state | `TestMissingSecretDenied` | e2e | permission-negative |

- Observation은 "삭제 성공" 같은 자기 보고가 아니라 효과를 증명하는 독립 관측이다.
- Exec 값: `executable` / `conditional`(조건과 함께) / `permission-negative` / `BLOCKED`(사유와 함께).
- 실환경에서 돌릴 항목에는 원격 보존 의도, 소유권 확인 방법, 의존 순서대로의 cleanup 단계를 열로 더하고 `isac-live-qa`의 안전 절차를 따른다.
- Tier 열은 `test-codification.md`의 계층 기준으로 채우고, 계층 쟁점은 같은 토론에서 합의한다(I2P-34).
