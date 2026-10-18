# 리뷰 코멘트 템플릿

GitHub에 올리는 본문은 영어다. 문체, 길이, 공개 위생은 `isac-github-publishing`을 따른다. 아래는 PR 리뷰가 담아야 할 요소와 순서다. 해당 없는 섹션은 지운다. 에이전트는 게시하지 않는다. 본문은 `ReviewResult.body`, 이벤트는 `ReviewResult.event`, APPROVE를 막는 열린 항목은 `ReviewResult.open_items`에 담고, n8n이 bridge `github.review`로 게시한다. 본문 첫 줄의 숨은 리뷰 마커와 재리뷰 footer는 bridge가 붙이므로 쓰지 않는다.

공개 텍스트(body, comments, thread_replies, open_items, summary)에는 리뷰어 스킬 이름, 규칙 ID(PRR-*, KM-*, MAC-*, I2P-* 등), 자동화·runner 내부 경로(`/etc/codex`, `/tmp/issue-agent`, `CODEX_HOME` 등)를 쓰지 않는다. 판단 이유는 프로젝트 쪽 사실로 쓴다(예: "this bypasses the distribution's SELinux policy, which is a maintainer decision"). 저장소의 `file:line` 참조는 지금처럼 필수다. `Lenses`와 `Considered`의 렌즈 이름은 예외다. 아래 템플릿 설명의 규칙 ID는 리뷰어용이고 게시 텍스트에 옮기지 않는다.

## Visual evidence

For GUI, KWin, or web user-visible changes, inspect the visual-evidence links in the PR body. Images open in GitHub; videos open from the evidence link. Treat the repository evidence ref as the visual evidence; do not run capture commands or create replacement media. If required media is missing or does not establish the claimed change, record that in `Not verified` and apply the appropriate review decision; do not attempt capture yourself.

## 리뷰 (`ReviewResult.event` + `ReviewResult.body`)

이벤트는 판정으로 정한다(PRR-25, PRR-56): `GREEN` → `APPROVE`, `BLOCKING` → `REQUEST_CHANGES`, `OPEN` → `COMMENT`, 판정이 아닌 안내 → `COMMENT`. 리뷰 계정이 PR 작성자면 GitHub가 approve·request-changes를 거부하므로 bridge가 같은 본문을 `COMMENT`로 게시한다. 에이전트는 판정대로 event를 적는다.

판정 줄에는 CI·required check 상태나 `PR-ready`를 쓰지 않는다. CI 결과는 근거로도 인용하지 않는다(PRR-38). `Verified`에는 리뷰어가 직접 실행하거나 읽어 확인한 것만 적는다.

```markdown
**Verdict: BLOCKING** reviewed at <head-sha>

<One or two sentences: does this PR fix the claimed problem at its root cause, and what must change before merge. Mention a merge conflict with <base> here if there is one.>

## Blocking
- **P1** `path/to/file.go:123`: <mechanism: what breaks, for whom, under which input>. Fix: <smallest change; hazards of the fix itself, e.g. the lock it adds covers <I/O> with timeout <t>>. Evidence: <command run in <container/image> or line reference>.

## Open items
- <one line per decision, unrefuted P0–P2 concern, or uncovered lens; same text as `open_items`>

## Non-blocking
- **P3** `path/to/file_test.go:45`: <issue>. Suggestion: <change>.

## Verified
- Reproduced <symptom> on merge-base <sha> with `<command>` in `<image>` (`docker run --rm --network none`): fails.
- Same reproducer on this head rebased onto main <sha>: passes. Healthy control: passes.
- Repository instructions applied (base <sha>): `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, <...>.

## Not verified
- <area or environment not exercised, and why; probes that could not run in an isolated container, or long-running suites left to CI (PRR-57), and the argument used instead>.

## Lenses
- correctness — always — covered: claim "<claim>" by `src/x.py:40-60` + probe `<command>`.
- docs/convention — always — covered: sync triggers `CLAUDE.md:12` (test list) checked against `CONTRIBUTING.md:30`.
- concurrency/lifecycle — `src/x.py:40` adds a lock around a D-Bus call — covered: lock-held I/O and setup timeouts `src/x.py:41-48` (probe `<command>`); signal window `src/x.py:52` (argument+challenger(<agent name>)); cleanup `src/x.py:70-80` (probe `<command>`).
- input — `src/cli.py:12` new `--max-edge` flag — covered: MCP schema, CLI argv, CLI JSON (bypasses schema), repeated flag — each with probe `<command>`.

<details><summary>Considered</summary>

- [concurrency] `src/x.py:52` signal between spawn and registry insert leaks the child — dismissed: probe `<command>` sent SIGTERM in the window; child reaped.
- [math] `src/geom.py:88` off-by-one at the right edge — dismissed: argument+challenger(<spawn-tool agent name/id>) `src/geom.py:80-90` clamps to `w-1`; the challenger's answer cites `src/geom.py:88` and found no counterexample.

</details>
```

`GREEN`일 때 첫 줄:

```markdown
**Verdict: GREEN** reviewed at <head-sha>. No blocking findings.
```

`OPEN`일 때 첫 줄. `OPEN`은 메인테이너의 결정이나 증거 없이는 승인할 수 없는 상태다(PRR-47, PRR-49, PRR-53). 결정 항목·hold가 남으면 다른 blocking finding이나 prove-or-fix 우려가 있어도 `OPEN`이다. 예외는 PRR-48 [U]의 확인된 PR 도입 취약점뿐이다(PRR-56). 그때 blocking finding은 `## Blocking`에 그대로 적는다. 이유마다 `## Open items`에 한 줄, `open_items`에 한 항목을 적는다:

```markdown
**Verdict: OPEN** reviewed at <head-sha>. <n> open items need a maintainer decision or evidence before approval.
```

구현 봇(`bulgasaribot[bot]`) PR의 미반박 P0–P2 우려는 남은 결정 항목·hold가 없을 때 `BLOCKING`으로 내고 finding을 이렇게 적는다(PRR-49, PRR-56):

```markdown
- **P1 (unrefuted)** `path/to/file.py:77`: <mechanism> when <concrete trigger>. Prove or fix: commit a test or probe that would fail if this were real, or change the code to <fix>.
```

결정 요청(보안 정책 우회, 제품 결정, PRR-47)은 본문에 `isac-decision-brief` 형식의 결정 브리프(배경, 선택지와 각 결과, 권고)를 두고, `## Open items`와 `open_items`에는 200자 이하의 짧은 항목만 둔다. 본문과 `open_items`에서 @멘션하지 않는다. project owner 멘션과 재리뷰 요청 안내는 bridge의 결정 요청 코멘트(C7')가 한 번 한다:

```markdown
## Decision needed
<Context: what the change does at `file:line` and which project policy or product choice it depends on, stated as a project fact (e.g. the distribution's SELinux policy), never as a reviewer rule.>
- A: <option> — <consequence>.
- B: <option> — <consequence>.
- C: <option> — <consequence>.
Recommendation: <option and why>.

## Open items
- Maintainer decision: <policy/product choice at file:line>. Options: <A | B | C>.
```

메인테이너 hold가 있으면 `- Maintainer hold by <login> (<link>) is still in place.`를 `Open items`에 둔다(@ 없이). 답한 사람의 write 이상 권한을 확인하지 못했으면 그 항목을 그대로 두고 `- Maintainer decision: <item>. Waiting for an answer from a user with verified write access.`처럼 적는다(PRR-47). 자기 루프 가드로 같은 head를 다시 낼 때는 요약 문단에 `No maintainer answer since <previous review link>; open items unchanged.`만 적는다.

공개 저장소에서 이 PR이 들여오지 않은 보안 finding(기존 취약점, PRR-19)은 세부 없이 적고, 비공개 보고 경로를 메인테이너가 정해 달라고 요청한다. 세부는 결과의 어떤 필드에도 넣지 않는다(`references/review-dimensions.md` §5). 이 문구는 blocking finding이 아니다:

```markdown
## Security
- A security concern that predates this change affects the code it touches. Please tell us how you would like the details shared privately.
```

PR이 들여온 취약점(기본 브랜치와 최신 릴리스에 없음, PRR-48)은 일반 blocking finding처럼 위치, 메커니즘, 수정안을 적는다. 비밀 값과 바로 쓸 수 있는 익스플로잇 입력은 인용하지 않는다.

일부만 main에 반영된 PR(`partially superseded`)은 `BLOCKING` 리뷰(`REQUEST_CHANGES`)로 낸다. 요약 문단에 반영된 부분(main 커밋)과 main에 아직 없는 부분을 나눠 적고, 남은 부분만 남기도록 PR을 좁히는 방법을 blocking finding의 수정안으로 적는다.

- 첫 줄에 판정과 리뷰한 head SHA를 둔다.
- 요약 문단에 넣을 것: 무엇을 어떤 버전·환경(컨테이너 이미지)에서 실행했는지, 재현 결과, 근본 원인(모르면 unknown이라고), PR이 그 원인을 고치는지, main이 무엇으로 이 PR을 대체했는지(해당 시), main과 충돌하는지, 머지하려면 무엇을 바꿔야 하는지.
- 추론이면 "by source reading, not run"처럼 표시한다. challenger를 통과한 논증이면 "argument checked by an independent challenger"라고 적는다.
- `Considered`는 `<details>`로 접고, 줄마다 `- [lens] <file:line> <hypothesis> — dismissed: <probe|argument+challenger(<agent name>)> <one line>` 형식을 지킨다(PRR-50). `argument+challenger`는 논증을 쓰지 않은 challenger가 그 후보를 받고 답에서 후보의 `file:line`을 인용했을 때만 쓴다. `<agent name>`은 spawn 도구가 돌려준 서브 에이전트의 이름/id다. 일반 이름이면 그 줄은 반박이 아니고 항목은 덮이지 않은 것으로 본다. 보안 후보는 PR이 들여온 것만 적는다.
- `Lenses` 줄은 항목마다 근거(`file:line`과 probe 또는 argument+challenger)를 단다. "covered by source inspection" 같은 일괄 문구는 쓰지 않는다. 관찰한 이상 동작은 finding이나 `Considered`로 옮긴다(PRR-43).
- 끝나지 않은 명령이나 probe는 어디에도 인용하지 않는다(PRR-53).

## `open_items` (`ReviewResult.open_items`)

| 상황 | event | `open_items` |
|---|---|---|
| `GREEN` | `APPROVE` | `[]` |
| `OPEN`: 결정·hold(PRR-47), 미반박 P0–P2 우려(PRR-49), 덮이지 않은 트리거 렌즈(PRR-53) | `COMMENT` | 이유마다 한 항목. 하나도 빼지 않는다 |
| `BLOCKING` (구현 봇 PR의 "prove or fix" 포함) | `REQUEST_CHANGES` | 남은 결정·hold, 미반박 P0–P2 우려, 덮이지 않은 트리거 렌즈마다 한 항목. 확인된 finding만 있으면 `[]` |
| superseded 닫기 권고, 판정 없는 정보 | `COMMENT` | `[]` |

- 필드는 항상 넣는다. 최대 20개, 항목마다 200자 이하의 영어 한 문장이다. 위치(`file:line`)와 무엇이 필요한지(결정, 증거, 렌즈 재실행)를 담는다. 이유는 남은 결정·hold, 미반박 P0–P2 우려, 덮이지 않은 트리거 렌즈 세 가지뿐이다. 확인된 blocking finding은 body/comments에 적고 그 이유만으로 `open_items`에 중복하지 않는다(PRR-56). @멘션하지 않는다.
- 공개될 수 있다. PRR-19 세부, 비밀 값, 익스플로잇 입력은 넣지 않는다.
- bridge는 event가 `COMMENT`이고, `head_sha`가 현재 head이고, `open_items`가 비어 있지 않을 때만 project owner를 멘션하는 결정 요청 코멘트를 PR에 한 번 게시한다. 같은 항목 집합에는 다시 게시하지 않으니, 상태가 그대로인 항목은 같은 문구를 유지하고 바뀐 항목만 새로 쓴다.

## 재리뷰 본문

```markdown
**Verdict: GREEN** re-reviewed at <new-head-sha> (previous: <old-head-sha>)

## Previous findings
- Closed: P1 `file.go:123` <short title>. Fixed at `file.go:130`; regression test `TestX` fails without the fix.
- Open: P2 `file_test.go:45` <short title>. Unchanged.
- Closed: open item "<text>". Maintainer <login> (verified write access) decided <decision> (<link>).

## Fix hazards
- <head가 이전 리뷰(이 봇 포함)의 제안을 따른 수정이고 그 출처가 커밋 메시지, 스레드 답글, 또는 제안과 일치하는 diff로 보이면 첫 문장에 "This head applies the fix suggested in <link>."를 쓰고, 그 수정이 들여온 hazard를 같은 단락에 적는다. 그 hazard에서 나온 finding도 같은 링크를 단다. 출처가 보이지 않으면 이 문장을 쓰지 않는다.> <for fix commits: locks across blocking I/O and their timeouts, record-vs-act order, cancellation/signal windows, cleanup — what was checked and how>.

## New findings
- None.
```

재리뷰도 merge-base 기준 전체 diff를 다시 리뷰한다(PRR-29). 기본 브랜치를 머지한 head면 들어온 변경과 PR의 상호작용을 `Verified`나 finding에 적는다(PRR-54). 이전 리뷰의 `Considered` 항목을 새 head에서 다시 보고, 여전히 버릴 수 있으면 다시 적는다.

## 인라인 finding과 스레드 답글

- 새 finding 중 PR diff 안의 줄에 고정할 수 있는 것은 `ReviewResult.comments[]`에 `path`, `line`, `side`(추가·문맥 줄은 `RIGHT`), `start_line`, `body`로 담는다. 한 줄 코멘트는 `start_line: null`이고, 여러 줄 코멘트는 `start_line`이 범위의 첫 줄이며 `line`보다 작다. 본문의 `## Blocking`/`## Non-blocking` 목록에도 같은 finding을 남긴다. diff 밖이면 본문에만 둔다.
- 재리뷰에서 `ReviewResult.thread_replies[]`는 PRR-29 조건에 맞는 스레드에만 `comment_id`와 함께 낸다. `reviewThreads`에서 스레드마다 `isResolved`와 댓글의 `author{login}`·`createdAt`을 읽고 고른다.
  - 해결되지 않은(`isResolved: false`) 봇 스레드 중 새 head에서 finding 상태가 바뀐 것. 예: `Fixed at <new-head-sha>: <file:line evidence>.`(`resolve: true`) / `Partially fixed at <new-head-sha>: <what remains>.` / `Regressed at <new-head-sha>: <why>.` 수정이 새 head에서 확인된 것만 `resolve: true`다.
  - 해결 여부와 무관하게 봇의 마지막 댓글 뒤에 사람(리뷰 App·이슈 App 봇이 아닌 계정)이 댓글을 단 스레드. 그 댓글에 답한다.
- 그 밖의 스레드에는 답글을 내지 않는다. 이미 해결된 스레드를 다시 확인하지 않고(`Closed at …` 금지), 상태가 그대로인 열린 스레드에 `Still open …`을 달지 않는다. 라운드별 상태는 본문 `## Previous findings`의 Closed/Open이 기록한다.
- 이미 해결된 스레드의 finding이 새 head에서 회귀하면 그 스레드에 답하지 않고 `ReviewResult.comments[]`에 새 인라인 finding으로 내며, 본문에 이전 finding을 언급한다(예: `Regression of the earlier finding <link>: …`).

## 닫기 권고 (외부·오래된 PR)

작성자가 저장소 소유자일 수 있으니 비례적인 어조를 유지한다. 에이전트는 PR을 닫지 않는다. 닫기 권고를 `ReviewResult.body`(`COMMENT` 이벤트, `open_items: []`)에 담고, 닫기는 메인테이너가 정한다.

```markdown
Thanks for this PR. The problem it targets is already fixed on main by <commit-sha> (<#PR>), first released in <tag>.

Verification: <discriminating reproducer> fails on <old version> and passes on <released version> (<environment>).

Please use <version> or later. I recommend closing this PR. If you still see the problem on <version>, please reopen with the traceback and your environment.
```

main에는 있지만 릴리스되지 않았으면 버전 문장을 "The fix is merged but not yet in a published release."로 바꾼다(PRR-35).

## 판정별 리뷰 이벤트

| 판정 | 이벤트 | 비고 |
|---|---|---|
| `GREEN` | `APPROVE` | CI 상태와 무관하다(PRR-38). `open_items: []` |
| `BLOCKING` (`partially superseded`, `close-without-merge`, 구현 봇 PR의 "prove or fix" 포함) | `REQUEST_CHANGES` | 결정 항목·hold가 남으면 PRR-48 [U]의 확인된 PR 도입 취약점이 있을 때만 `BLOCKING`이고, 아니면 `OPEN`이다(PRR-56) |
| `OPEN` (결정·hold, 미반박 P0–P2 우려, 덮이지 않은 트리거 렌즈) | `COMMENT` | `open_items`에 이유를 모두 적는다. 결정 항목이 원인이면 다른 blocking finding이 있어도 `OPEN`이다 |
| superseded 닫기 권고, 판정 없는 정보 | `COMMENT` | `open_items: []` |
| 리뷰 계정 = PR 작성자 | `COMMENT` | bridge가 대체하고 본문 앞에 `**Verdict: <event>**`를 붙인다. 에이전트는 판정 이벤트를 그대로 적는다 |

- 판정을 라벨로 만들지 않는다. P0–P3도 라벨로 만들지 않고 본문에만 적는다.
- 재리뷰는 새 판정의 이벤트로 새 ReviewResult를 낸다. 같은 리뷰어의 최신 리뷰가 이전 상태를 대체한다(PRR-37).
