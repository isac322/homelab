# 리뷰 코멘트 템플릿

GitHub에 올리는 본문은 영어다. 문체, 길이, 공개 위생은 `isac-github-publishing`을 따른다. 아래는 PR 리뷰가 담아야 할 요소와 순서다. 해당 없는 섹션은 지운다. 에이전트는 게시하지 않는다. 본문은 `ReviewResult.body`, 이벤트는 `ReviewResult.event`에 담고, n8n이 bridge `github.review`로 게시한다.

## 리뷰 (`ReviewResult.event` + `ReviewResult.body`)

이벤트는 판정으로 정한다(PRR-25): `GREEN` → `APPROVE`, `BLOCKING` → `REQUEST_CHANGES`, 판정이 아닌 안내 → `COMMENT`. 리뷰 계정이 PR 작성자면 GitHub가 approve·request-changes를 거부하므로 bridge가 같은 본문을 `COMMENT`로 게시한다. 에이전트는 판정대로 event를 적는다.

```markdown
**Verdict: BLOCKING** (PR-ready: false) reviewed at <head-sha>

<One or two sentences: does this PR fix the claimed problem at its root cause, and what must change before merge.>

## Blocking
- **P1** `path/to/file.go:123`: <mechanism: what breaks, for whom, under which input>. Fix: <smallest change>. Evidence: <command or line reference>.

## Non-blocking
- **P2** `path/to/file_test.go:45`: <issue>. Suggestion: <change>.

## Verified
- Reproduced <symptom> on merge-base <sha> with `<command>` (<version, environment>): fails.
- Same reproducer on this head rebased onto main <sha>: passes. Healthy control: passes.
- CI: <passing | failing: job name, deterministic or transient>.

## Not verified
- <area or environment not exercised, and why>.
```

`GREEN`일 때 첫 줄. `PR-ready`는 required check 통과와 충돌 없음까지 확인된 경우에만 `true`다(PRR-24):

```markdown
**Verdict: GREEN** (PR-ready: true) reviewed at <head-sha>. No blocking findings.
```

```markdown
**Verdict: GREEN** (PR-ready: false: <required check failing | merge conflict with main>) reviewed at <head-sha>. No blocking findings in the diff.
```

공개 저장소의 보안 finding은 세부 없이 적고, 비공개 보고 경로를 메인테이너가 정해 달라고 요청한다. 세부는 결과의 어떤 필드에도 넣지 않는다(`references/review-dimensions.md` §5):

```markdown
## Blocking
- **P0** A security concern affects this change. Details will be shared with the maintainers privately.
```

일부만 main에 반영된 PR(`partially superseded`)은 `BLOCKING` 리뷰(`REQUEST_CHANGES`)로 낸다. 요약 문단에 반영된 부분(main 커밋)과 main에 아직 없는 부분을 나눠 적고, 남은 부분만 남기도록 PR을 좁히는 방법을 blocking finding의 수정안으로 적는다.

- 첫 줄에 판정, PR-ready, 리뷰한 head SHA를 둔다.
- 요약 문단에 넣을 것: 무엇을 어떤 버전·환경에서 실행했는지, 재현 결과, 근본 원인(모르면 unknown이라고), PR이 그 원인을 고치는지, main이 무엇으로 이 PR을 대체했는지(해당 시), 머지하려면 무엇을 바꿔야 하는지.
- 추론이면 "by source reading, not run"처럼 표시한다.

## 재리뷰 본문

```markdown
**Verdict: GREEN** (PR-ready: true) re-reviewed at <new-head-sha> (previous: <old-head-sha>)

## Previous findings
- Closed: P1 `file.go:123` <short title>. Fixed at `file.go:130`; regression test `TestX` fails without the fix.
- Open: P2 `file_test.go:45` <short title>. Unchanged.

## New findings
- None.
```

## 인라인 finding과 스레드 답글

- 새 finding 중 PR diff 안의 줄에 고정할 수 있는 것은 `ReviewResult.comments[]`에 `path`, `line`, `side`(추가·문맥 줄은 `RIGHT`), 여러 줄이면 `start_line`, `body`로 담는다. 본문의 `## Blocking`/`## Non-blocking` 목록에도 같은 finding을 남긴다. diff 밖이면 본문에만 둔다.
- 재리뷰에서 이 봇이 열었거나 봇에게 물은 기존 스레드마다 `ReviewResult.thread_replies[]`에 `comment_id`와 현재 상태를 담는다. 예: `Fixed at <new-head-sha>: <file:line evidence>.` / `Still open at <new-head-sha>: <why>.` 수정이 새 head에서 확인된 것만 `resolve: true`다.

## 닫기 권고 (외부·오래된 PR)

작성자가 저장소 소유자일 수 있으니 비례적인 어조를 유지한다. 에이전트는 PR을 닫지 않는다. 닫기 권고를 `ReviewResult.body`(`COMMENT` 이벤트)에 담고, 닫기는 메인테이너가 정한다.

```markdown
Thanks for this PR. The problem it targets is already fixed on main by <commit-sha> (<#PR>), first released in <tag>.

Verification: <discriminating reproducer> fails on <old version> and passes on <released version> (<environment>).

Please use <version> or later. I recommend closing this PR. If you still see the problem on <version>, please reopen with the traceback and your environment.
```

main에는 있지만 릴리스되지 않았으면 버전 문장을 "The fix is merged but not yet in a published release."로 바꾼다(PRR-35).

## 판정별 리뷰 이벤트

| 판정 | 이벤트 | 비고 |
|---|---|---|
| `GREEN` | `APPROVE` | `PR-ready: false`여도 diff에 blocking finding이 없으면 APPROVE, 이유는 첫 줄 |
| `BLOCKING` (`partially superseded`, `close-without-merge` 포함) | `REQUEST_CHANGES` | |
| superseded 닫기 권고, 판정 없는 정보 | `COMMENT` | |
| 리뷰 계정 = PR 작성자 | `COMMENT` | bridge가 대체하고 본문 앞에 `**Verdict: <event>**`를 붙인다. 에이전트는 판정 이벤트를 그대로 적는다 |

- 판정을 라벨로 만들지 않는다. P0–P3도 라벨로 만들지 않고 본문에만 적는다.
- 재리뷰는 새 판정의 이벤트로 새 ReviewResult를 낸다. 같은 리뷰어의 최신 리뷰가 이전 상태를 대체한다(PRR-37).
