# 댓글 구조와 길이 예산

이 파일은 댓글(TriageResult `comment`)의 **구조와 길이**를 정한다. 영어 문체, 위생 처리, 실행 확인과 추론의 구분은 `isac-github-publishing` 스킬을 따른다. 게시, 제자리 수정과 새 댓글 선택, 게시 전 중복 확인은 n8n이 하며 에이전트는 `comment`에 본문만 담는다. 필수 요소(현상, 근본 원인, 근본 해결, 복사해 실행 가능한 재현)는 SKILL.md의 `[U]` 규칙이다. 절 이름과 길이는 바꿀 수 있는 기본값이다.

## 길이 예산(기본값)

| 댓글 | 예산 |
|---|---|
| 분석 댓글 | 150-250단어. 구조 변경이 걸린 RCA만 넘길 수 있고, 그때도 Root cause 1-3문장, Why chain 5단계 이내 한 줄씩 |
| 재현 안 됨 댓글 | 100-200단어 |
| 상태 갱신·종결 댓글 | 40-80단어. 앞선 상세 근거는 반복하지 않고 링크한다 |

## 분석 댓글(재현됨)

````markdown
<Verdict in one sentence: what is wrong, which versions are affected.> Reproduced on <version/commit> in <environment>: <what ran> produced <observed>, while <healthy control> produced <expected>. <If mock: "Mock reproduction against <spec/doc + version>; live provider not observed.">

## Reproduction
```sh
<minimal commands / config / code that reproduce the defect when pasted>
```
Expected: <contract>. Actual: <observation>.

## Root cause
<1-3 sentences. Name the broken invariant, not the symptom site.>

## Why chain
1. <why> (`path/file.ext:line`)
2. <why> (`path/file.ext:line`)
3. …

## Fix direction
- <smallest safe systemic change that restores the invariant>
- Regression test: <observable behavior the missing test must assert>
- Considered and rejected: <alternative>, because <one-line reason>

## Scope
<affected paths/siblings, API or schema change (or "none"), upgrade impact.>
````

선택 절(필요할 때만): `## Version status`(fixed-in-PR / merged / released / deployed 중 해당 상태, 수정 PR·커밋, 첫 릴리스 또는 "unreleased", 사용할 버전), `## Limits`(검증하지 않은 환경), 반증된 가설, 원인과 증폭 요인(amplifier)의 구분.

재현 테스트가 "PASS"로 끝나는 형태라면 그것이 "버그 상태를 재현함"을 뜻한다고 첫 단락에 적는다.

## 재현 안 됨 댓글

````markdown
Not reproduced yet. Tried <versions> on <environment/mode> with <steps>; observed <result>. This does not rule out the report: <what differs from the reporter's setup>.

Could you run the following and share the output? It only reads state.
```sh
<read-only diagnostic commands that do not change what the reporter observes>
```
````

`repro:blocked`이면 첫 문장을 "Reproduction is blocked: <missing condition>."으로 바꾸고 필요한 조건을 적는다.

## 구조 변경이 필요한 경우

분석 댓글의 `## Fix direction`을 다음으로 바꾼다. 선택지 비교는 `design-research.md`의 결과에서 가져온다.

````markdown
## Fix direction (needs a maintainer decision)
The proper fix changes <public API / schema / persisted state / security invariant / architecture boundary>.
- Option A: <change>: <effect>; trade-off: <trade-off>
- Option B: <change>: <effect>; trade-off: <trade-off>
- Recommended: <option> because <reason>.
Regression risk: <current vs proposed for each affected case; remaining gap and mitigation>.
````

승인 후(⑤ → ④, 재트리아지) 같은 절을 다음으로 바꾼 댓글을 `comment`에 담는다.

````markdown
## Fix direction
The maintainers chose <option>: <change that restores the invariant>.
- Regression test: <observable behavior the missing test must assert>
- Considered and rejected: <other options>, because <one-line reason>
````

## 일부 주장만 확인된 경우

주장마다 한 줄로 판정을 적고 해결되지 않은 증상을 명시한다.

```markdown
- Claim 1 (<summary>): reproduced, root cause below.
- Claim 2 (<summary>): not reproduced on <env>; left open.
```

## 상태 갱신 댓글

```markdown
<#PR> merged to <branch> at <sha>. It is not in a published release yet (<channel>). Verified: <scope>. Not verified: <reporter's exact environment>.
```

## 중복 판정 댓글

```markdown
Same mechanism as #<canonical>: <one-line mechanism>, confirmed by running this issue's own path (<command/version>). Tracking there.
```
