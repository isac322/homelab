# 이슈 라벨 의미와 기준

`isac-issue-triage`가 라벨의 **의미와 부착 기준**을 소유한다. 조회·생성·교체 적용은 n8n bridge(`github.labels`, 카탈로그 이름만)가 하며, 에이전트는 TriageResult `labels.add`/`labels.remove`에 이름만 넣는다. 이름과 GitHub description은 영어로 둔다. `agent:needs-attention`은 bridge 전용이라 넣지도 빼지도 않는다.

## 라벨 표

| 축 | 이름 | GitHub description (영어) | 색(생성 시 기본값) | 배타성 |
|---|---|---|---|---|
| ① 재현 | `repro:reproduced` | Reported defect reproduced locally; see the comment for affected and fixed versions. | `0e8a16` | ①의 셋 중 하나 |
| ① 재현 | `repro:not-reproduced` | Exercised locally without observing the defect; see the comment for limitations. | `fbca04` | |
| ① 재현 | `repro:blocked` | Reproduction inconclusive because required conditions remain unavailable. | `d4c5f9` | |
| ② 원인 | `triage:root-cause-identified` | Root cause established with evidence; see the analysis comment. | `1d76db` | 가산 |
| ③ 정보 | `triage:needs-info` | Waiting on the reporter for information listed in the latest comment. | `e99695` | 가산, 답을 받으면 제거 |
| ④ 방향 | `triage:fix-direction-decided` | Fix direction is agreed and ready to implement. | `5319e7` | ④ ⟂ ⑤ |
| ⑤ 구조 | `triage:needs-structural-change` | Proper fix needs a structural change; direction requires a maintainer decision. | `b60205` | |
| 분류 | `bug` | (저장소 기존 라벨 재사용) | - | `bug` ⟂ `enhancement` |
| 분류 | `enhancement` | (저장소 기존 라벨 재사용) | - | |
| 분류 | `documentation` | (저장소 기존 라벨 재사용) | - | AD-01 문서 요청, 문서 결함(TRI-51)에만 |
| 관계 | `duplicate` | (저장소 기존 라벨 재사용) | - | 가산 |

## 판정 → 라벨 · 댓글 · 다음 단계

판정 어휘는 `issue-validation`의 verdict 하나만 쓴다. 담당자 반환의 `needs_approval`은 구조 변경 게이트(TRI-25) 여부다. "라벨" 열은 `labels.add`(교체 시 `labels.remove`), "댓글" 열은 `comment`, "다음 단계" 열은 `next_action`(괄호 안)이다. 닫기 제안·제외 사유는 `summary`(필요하면 `comment`)에 적고 에이전트는 닫지 않는다. 취약점(TRI-53)이면 verdict와 상관없이 이 표의 라벨·댓글을 쓰지 않는다: 라벨 없음, `comment: null`, `next_action: none`, 내용은 `security_advisory`(AD-04).

| verdict | 라벨 | 댓글(`comment-template.md`) | 다음 단계 |
|---|---|---|---|
| CONFIRMED_CURRENT | `repro:reproduced`, `bug`, 증거에 따라 ②, ④ 또는 ⑤ | 분석 댓글 | 원인 확정 + ④ + 우리 코드 + 열린 PR 없음 → `isac-issue-to-pr`(`implement` + `implementation_brief`). ⑤면 TRI-25(`await_decision`). 그 밖은 `none` |
| PARTIALLY_FIXED | `repro:reproduced`, `bug`, 남은 주장 기준으로 ②④⑤ | 분석 댓글(주장별 판정) | 남은 부분만 위와 같이 |
| CONFIRMED_HISTORICAL_FIXED | `repro:reproduced`, `bug` | 분석 댓글 + Version status(TRI-32) | `summary`에 닫기 제안, main에만 있으면 "릴리스 필요"(`none`) |
| DUPLICATE | `duplicate` (+ 정본과 같은 `repro:*`), `duplicate_of` | 중복 판정 댓글 | `summary`에 닫기 제안(`none`) |
| ENVIRONMENTAL | `repro:reproduced` 또는 `repro:not-reproduced` | 분석 댓글(원인이 환경임, 우리 쪽 대응) | 업스트림·환경 기록(TRI-22, `none`). 우리 쪽 대응이 있으면 그 범위만 인계(`implement`) |
| NOT_A_BUG | `repro:*` 결과대로, `bug` 붙이지 않음 | 계약 설명 댓글 | 비례성 판단(TRI-13): 개선 후보면 `enhancement`, 아니면 `summary`에 닫기 제안(`none`) |
| FEATURE_REQUEST (신뢰된 작성자의 명확한 범위 안 요청, AD-01) | `enhancement`/`documentation`, 구조 변경이면 ⑤ | 없음(`null`). ⑤면 분석 댓글의 구조 변경 절 | `implement` + `implementation_brief`. ⑤면 TRI-25(`await_decision`) |
| FEATURE_REQUEST (그 밖의 요청, 제안 트랙 TRI-54) | `enhancement`, 구조 변경이면 ⑤, 승인 후 ④ | 제안 평가 댓글 | `await_decision`. 신뢰된 사용자가 승인하면(AD-02) `implement` + `implementation_brief` |
| FEATURE_REQUEST (제외, TRI-03) | 없음 | 없음(`null`) | `summary` "제외(사유)"(`none`) |
| NOT_REPRODUCED | `repro:not-reproduced`, `triage:needs-info` | 재현 안 됨 댓글 | 중단(TRI-09, `await_info`) |
| INCONCLUSIVE (조건 부족) | `repro:blocked`, 필요하면 `triage:needs-info` | 재현 안 됨 댓글(blocked 변형) | 중단, 필요한 조건을 `questions`에 보고(`await_info`) |
| INCONCLUSIVE (재현됨, 원인 미확정) | `repro:reproduced`, ② 없음 | 분석 댓글(사실/가설/판별 증거, TRI-21) | 판별 실험 후 재판정(재판정된 행의 다음 단계) |

결함 영역(TRI-51)은 verdict와 별개 필드(`fault_domain`)다. 영역이 테스트·오라클 결함이면 verdict 행의 `repro:*`·②·④는 그대로 붙이되 `bug`는 붙이지 않고(제품은 계약대로 동작), 수정 대상은 오라클·하니스로 적는다(TRI-14). 우리 저장소의 테스트·하니스면 `isac-issue-to-pr` 인계 대상이다(`implement`). 문서 결함이면 `bug`를 붙이지 않고 `documentation`(bridge 카탈로그에 있다)을 붙이며, 수정 대상은 문서다.

## 부착 기준

| 라벨 | 붙이는 조건 | 붙이지 않는 경우 |
|---|---|---|
| `repro:reproduced` | `issue-validation`의 실행 증거 게이트를 통과한 재현(계약에 충실한 mock 재현 포함, 댓글에 mock임을 명시) | 코드·로그·제보 글만 읽은 경우, 다른 이슈의 재현에 기댄 경우 |
| `repro:not-reproduced` | 실행 재현을 시도했지만 결함이 관찰되지 않음. 댓글에 시도 버전·환경·관찰을 적음. 제보자 환경의 판별 정보(버전, OS·모드, 설정)를 몰라 맞추지 못했으면 이 라벨 + `triage:needs-info`를 쓰고, 시도하지 못한 차원을 댓글에 적음 | "버그 아님"의 대체 표현으로 쓰지 않는다 |
| `repro:blocked` | 필요한 조건(하드웨어, 자격증명, 외부 서비스)이 없어 결론이 나지 않음. 무엇이 없는지 댓글에 적음 | 조건은 있는데 관찰이 안 된 경우, 제보자 환경 정보만 모르는 경우(→ not-reproduced) |
| `triage:root-cause-identified` | `repro:reproduced`가 있고, 합의된 인과 사슬의 모든 edge에 증거가 있음 | 가설이 둘 이상 남음, 원인이 제보자 설명뿐 |
| `triage:needs-info` | 재현 불가이거나, 제보자 환경의 판별 정보(버전, OS·모드, 설정)가 필요함. 필요한 정보 목록이 최신 댓글에 있음 | 요청할 정보를 댓글에 적지 않은 경우 |
| `triage:fix-direction-decided` | 수정 방향이 댓글에 있고 구조 변경 게이트 대상이 아님, 또는 구조 변경 방향을 사용자가 승인함, 또는 제안 방향을 신뢰된 사용자가 승인함(TRI-54, AD-02) | 방향이 대안 나열 수준 |
| `triage:needs-structural-change` | 근본 수정이 구조 변경(공개 API·스키마·영속 상태·보안 불변식·아키텍처 경계·사용자가 소비하는 계약)을 요구함 | 내부 구현 선택만 다른 경우 |
| `bug` | 확인된 제품 결함 | 의도된 동작, 기능 요청, 테스트·오라클 결함 |
| `enhancement` | 계약은 지켜지지만 개선 가치가 있는 의도된 동작(TRI-13), 기능 요청(AD-01: 신뢰된 작성자의 직접 지시 또는 제안 트랙 TRI-54) | 제외된 기능 요청(TRI-03: 라벨 없이 제외) |
| `duplicate` | 비정본 이슈에서 자기 경로를 실행해 정본과 같은 메커니즘을 확인함 | 제목·증상만 같음 |

전제 관계: `repro:reproduced` → ② → ④ 또는 ⑤. 주장별로 증거가 다르면 라벨은 증거가 뒷받침하는 범위만 반영하고, 나머지는 댓글에 적는다.

제안 트랙(TRI-54)은 `enhancement` → (구조 변경이면 ⑤) → 신뢰된 사용자 승인(AD-02) → ④이며 ①·②를 쓰지 않는다.

## 전이

- ⑤ → ④: 구조 변경 방향이 `isac-decision-brief` 형식의 승인으로 확정되면(재트리아지 메시지의 신뢰된 사용자 댓글, AD-02) `labels.remove`에 `triage:needs-structural-change`를, `labels.add`에 `triage:fix-direction-decided`를 넣고, 같은 결과의 `comment`에 분석 댓글의 `## Fix direction (needs a maintainer decision)` 절을 승인된 방향 변형(`comment-template.md`)으로 바꾼 내용을 담는다(적용은 n8n). 승인 댓글 작성자가 신뢰된 사용자가 아니면(`gh api repos/<owner>/<repo>/collaborators/<login>/permission --jq .permission`이 `admin`·`write`가 아니면) 전이하지 않는다(TRI-25).
- ③ 제거: 제보자가 요청한 정보를 주면 `labels.remove`에 넣고, 받은 정보로 재현을 다시 시도한다.
- ① 교체: 재시도 결과가 바뀌면 같은 그룹의 이전 값을 `labels.remove`에, 새 값을 `labels.add`에 넣는다(한 결과로).
- `bug` → `enhancement`: 판정이 의도된 동작 + 개선 후보로 바뀌면 교체한다(`labels.remove`/`labels.add`).
- 닫기·`invalid`·`wontfix`·`question`: 메인테이너 처분이므로 넣거나 실행하지 않는다. 필요하면 `summary`에서 제안만 한다.

## 라벨과 댓글 일치

- 라벨만 있고 근거 댓글이 없는 상태를 만들지 않는다.
- `repro:reproduced`이면 댓글에 영향받는 버전과 (있으면) 수정 버전을 적는다.
- `repro:reproduced`와 `triage:needs-info`가 함께 있으면 댓글에 필요한 정보가 무엇인지 적는다.
- mock 재현이면 댓글에 "mock reproduction; live provider not observed"에 해당하는 한계를 적는다.
- 라벨은 bridge 카탈로그 이름만 쓴다. 저장소의 기존 같은 이름 라벨은 bridge가 그대로 재사용한다.
