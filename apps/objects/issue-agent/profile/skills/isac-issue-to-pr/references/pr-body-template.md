# PR 본문과 종료 댓글 템플릿

I2P-41, I2P-42, I2P-57의 기본 템플릿이다. 이 자동화에서 PR 본문은 결과 `pr.body`(제목은 `pr.title`)에 쓰고 n8n이 PR을 열거나 갱신한다. 에이전트는 `gh pr create/edit`나 댓글을 쓰지 않는다. 문체, 공개 위생(로컬 경로·run ID·실 식별자·내부 에이전트 이름 금지, synthetic 픽스처 값), 게시 전 중복 확인은 `isac-github-publishing`이 소유한다. 섹션 구성은 바꿀 수 있는 기본값이지만 `Fixes #N`, QA 매핑, 실행한 검증, NOT run / NOT changed는 빼지 않는다.

## PR 본문

```markdown
Fixes #<N>

## Summary
<One paragraph: what was broken for users and what this PR changes.>

## Root cause
<Two or three sentences. Link the root-cause comment on the issue.>

## Design
<Overall structure and direction. Alternatives considered and why this one. Upgrade path from the last release.>

## Changes
- <component>: <behavior change>
- Docs / CHANGELOG: <sections touched>

## QA checklist
| ID | Behavior | Test | Tier |
|---|---|---|---|
| QA-01 | <expected behavior> | `<test name>` | unit / integration / e2e |

## Verification
Commands run:
- `<command>`: <result>

Old vs new (same test code):
| QA ID | `<default branch>` (`<sha>`) | this branch (`<sha>`) | Environment |
|---|---|---|---|
| QA-01 | fails: <observed> | passes | <OS / versions / install path> |
| control | passes | passes | <same> |

- [ ] Reporter-equivalent environment check (required before merge): <planned environment>

## Risks and upgrade impact
- <known risk, migration step, one-time behavior>

## Not run / not changed / not added
- Not run: <test or environment>. Reason: <reason>
- Not changed: <pre-existing or upstream defect>. Evidence: <evidence, tracking issue>
- Not added: <deferred item>. Tracked in: <sibling PR or issue>

## Non-gating CI legs
- <job>: `continue-on-error` because <reason>; failing tests: <names>. (Omit if none.)
```

- 부분 해결이거나 이슈를 일부러 열어 둘 때는 `Fixes` 대신 `Related to #<N>`을 쓰고, 이유를 본문과 `summary`에 적는다(I2P-42).
- 동등 환경 검증은 머지 전 단계(흐름 13)라 `ready`를 반환할 때 턴 안에서 못 했으면 체크리스트 항목으로만 둔다. 결과가 나오면 다음 followup 턴에서 `pr.body`를 갱신해 반환한다.
- 사용자가 공개 문구를 지정했으면 그대로 쓴다(I2P-43).
- 재작업 PR이면 `## Defect attribution`을 더해 결함마다 main / previous PR head / this branch 중 어디서 왔는지 적는다.

## 머지 후 이슈 종료 댓글

이 자동화에서는 머지 후 단계가 범위 밖이라 에이전트가 이 댓글을 쓰지 않는다. 참고용으로 남긴다.

```markdown
Fixed in #<PR> (merged to `<default branch>` at `<sha>`).

- Release: <included in vX.Y.Z | not in a published release yet; use `<install-from-source command>` until the next release>
- Verified: <regression tests and environment actually used>
- Limits: <reporter environment differences or anything not verified>

If this still happens for you on <version>, please reply with your version and environment.
```

- 부분 해결이면 "Fixed" 대신 `Partially fixed`로 시작하고 남은 증상을 적는다. 이슈를 닫지 않는다(I2P-58).
- 수정이 릴리스에 없으면 Release 줄에 그 사실을 쓰고 사용자에게도 릴리스 필요를 알린다(I2P-60).

## 머지 전 범위 고지 (사용자에게, 한국어)

머지 승인이나 머지 알림에 붙이는 한 줄 형식이다(I2P-56). 이 자동화에서는 에이전트가 머지하지 않으므로 같은 정보를 `summary`에 영어로 담는다.

```
범위: <테스트 전용 | 제품 런타임 변경> · 건드리지 않은 것: <컴포넌트> · 검증: <old/new, 동등 환경, CI>
```
