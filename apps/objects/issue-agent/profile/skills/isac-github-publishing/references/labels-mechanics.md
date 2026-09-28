# 라벨 메커닉

`isac-github-publishing`의 GHP-14 세부 절차. **메커닉만** 소유한다.

- 이슈 라벨의 이름·description·색·배타성·부착 기준, 붙이지 않는 기본 라벨, 라벨과 코멘트의 정합: `isac-issue-triage` 스킬 소유.
- PR 리뷰 판정은 라벨이 아니라 리뷰 이벤트로 남긴다: `isac-pr-review` 스킬 소유(`ReviewResult.event`).

자동화 적응: 에이전트는 라벨을 만들거나 붙이거나 떼지 않는다. 어떤 카탈로그 라벨을 원하는지 `TriageResult.labels.add`/`labels.remove`에 이름으로 요청하면, bridge가 없는 카탈로그 라벨을 카탈로그 description·색으로 만들고, 기존 저장소 라벨은 그대로 재사용하며, 상호배타 그룹을 강제한다. 요청할 수 있는 이름은 자동화 라벨 카탈로그뿐이다: `repro:reproduced`, `repro:not-reproduced`, `repro:blocked`, `triage:root-cause-identified`, `triage:needs-info`, `triage:fix-direction-decided`, `triage:needs-structural-change`, `bug`, `enhancement`, `documentation`, `duplicate`. `agent:needs-attention`은 bridge 전용이라 요청하지 않는다.

## 절차

0. **권한** — 라벨 쓰기 권한은 에이전트에게 없고 필요하지도 않다. 적용은 bridge가 한다. bridge가 라벨을 적용하지 못하면 자동화가 그 실패를 GitHub에 보고한다.
1. **조회** — 라벨을 고르기 전에 저장소 라벨을 확인한다. 읽기 전용이므로 읽기 토큰으로 할 수 있다:
   `gh label list -R <owner>/<repo> --limit 200 --json name,description,color`
2. **의미 매핑** — 붙이려는 의미와 같은 기존 라벨이 있어도 요청은 카탈로그 이름으로만 한다. 저장소 고유 라벨(예: 저장소 고유의 needs-info 계열 라벨)이 같은 의미를 이미 커버하면 그 매핑과, 카탈로그 라벨 대신 그 라벨을 쓰자는 권고를 `summary`에 적는다. 카탈로그 밖 라벨은 요청하지 않는다.
3. **생성** — 에이전트는 라벨을 만들지 않는다. 필요한 카탈로그 라벨을 `labels.add`에 넣으면, 저장소에 없을 때 bridge가 카탈로그의 영어 description·색으로 만든다.
4. **교체** — 상호배타 그룹(소유 스킬이 정의; 카탈로그 그룹 `repro`, `direction`, `kind`)은 하나를 `labels.add`에 넣으면 bridge가 같은 그룹의 다른 라벨을 같은 op에서 제거한다. 그룹 밖 전이(예: 정보가 도착해 `triage:needs-info`를 떼는 경우)는 `labels.remove`에 명시한다.

## 금지

- 기존 라벨의 rename·recolor·delete·description 변경 요청(저장소 변경이며 타인의 결정).
- 카탈로그 밖 라벨 요청. GitHub 기본 라벨(`bug`, `enhancement`, `duplicate` 등)은 카탈로그에 있는 것만 요청하고, 저장소에 이미 있으면 bridge가 재사용한다.
- 호출 스킬이 정의한 전이·상호배타 교체 대상이 아닌 라벨의 `labels.remove` 요청. 그 밖의 라벨은 누가 붙였든 제거를 요청하지 않고, 필요하면 `summary`에서 제안한다.
