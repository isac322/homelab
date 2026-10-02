---
name: isac-github-publishing
description: Use in the issue-agent automation whenever you draft GitHub-facing text (analysis comments, issue notes, PR titles/bodies, review bodies, inline review comments, thread replies) or choose catalog labels for the ISSUE_AGENT_RESULT fields that n8n publishes.
---

## Automation adaptation

이 사본은 issue-agent 자동화(n8n + bridge + HAPI + Codex)용으로 기계적으로만 바꿨다. 에이전트는 읽기 전용 GitHub 토큰만 가지며 GitHub에 어떤 쓰기도 하지 않는다. 모든 게시는 턴 끝의 `ISSUE_AGENT_RESULT <nonce> {json}` 한 줄에 담긴 결과를 n8n이 bridge `/ops`로 적용한다.

바꾼 것:

- 게시 모드/초안 모드 구분 → 항상 초안 모드다. 에이전트는 초안을 결과 필드에 넣고, 자동화가 게시한다(GHP-01, GHP-15).
- 댓글 게시·본문 수정·이슈 생성·종결·라벨 생성·교체·PR 생성·리뷰 제출·스레드 답글·push → 해당 결과 필드에 내용과 의도를 넣는다. 에이전트는 그 쓰기를 시도하지 않는다(GHP-09~GHP-15, `references/labels-mechanics.md`).
- 사용자에게 한국어로 하는 최종 보고 → 결과의 `summary`(짧은 영어). 실질 내용은 다른 결과 필드가 담는다(순서, GHP-02).
- 게시 후 다시 읽어 대조하는 단계 → n8n/bridge가 게시 결과(URL, idempotent marker)를 기록한다. 에이전트는 결과에 넣기 전 대조만 한다(GHP-15).
- 제자리 수정(본문·기존 댓글 편집)은 결과 필드가 없으므로 권고로 표현한다: 새 댓글 필드에 정정·보강 내용을 넣고, 제자리 수정이 낫다는 판단은 `summary`에 권고로 적는다(GHP-11, GHP-13).
- `isac-skill-correction` 관련 문장은 삭제했다(설치되지 않음). `humanizer` 스킬도 이 러너에 설치돼 있지 않다: 설치된 `writing-clearly-and-concisely`와 `comment-writer`를 적용하고, 이 스킬과 `references/style.md`에 적힌 humanizer 규칙(em dash·en dash 금지)은 그대로 지킨다.

단계 → 결과 필드:

| 산출물 | triage (TriageResult) | implement / followup (ImplementResult) | review (ReviewResult) |
|---|---|---|---|
| 분석·상태 댓글 | `comment` | `issue_comment` | — |
| 질문 | `questions` + `comment` 본문 | `questions` (+ `issue_comment`) | — |
| 라벨 | `labels.add` / `labels.remove` (카탈로그 이름만) | — | — |
| 중복 | `verdict: DUPLICATE` + `duplicate_of` | — | — |
| PR 제목·본문 | — | `pr.title` / `pr.body` | — |
| 코드 보강 | — | 워크트리 브랜치 로컬 커밋 (`ready` 전에 모두 커밋, 브랜치 head push는 자동화) | — |
| 리뷰 본문·판정 | — | — | `body` / `event` / `head_sha` |
| 인라인 리뷰 댓글 | — | — | `comments[]` |
| 기존 스레드 답글·resolve | — | — | `thread_replies[]` |
| 최종 보고 | `summary` | `summary` | `summary` |
| 막힘(도구·인프라·자격증명) | `status: blocked` + `blockers` | `status: blocked` + `blockers` | `status: blocked` + `blockers` |

새 이슈 생성, 이슈·PR 종결, 재오픈, 기존 본문·댓글 편집, 라벨 카탈로그 밖 라벨에는 결과 필드가 없다. 필요하면 현재 모드의 댓글 필드(리뷰면 `body`)에 초안을 넣고 `summary`에 권고로 적는다. 사람이 판단해 적용한다.

# GitHub Publishing

GitHub에 쓰는 모든 행위의 공통 절차. 각 호출 스킬(`isac-issue-triage`, `isac-issue-to-pr`, `isac-pr-review`, `isac-live-qa`)은 내용·판정·템플릿·라벨 의미를 소유하고, 이 스킬은 초안 작성과 결과 필드 기록 절차만 소유한다. 실제 게시는 n8n이 한다. PR 생성·머지·리뷰 대응의 승인과 필수 메타데이터는 전역 pull-request 가드가 소유한다.

## 순서

1. 모드 확정(GHP-01) → 2. 게시 주체 확인(GHP-15) → 3. 초안 작성(GHP-02~07, `references/style.md`) → 4. 결과에 넣기 직전 상태 재확인·중복 확인·sanitize 체크리스트(GHP-08~10) → 5. 초안과 라벨 요청을 결과 필드에 기록(GHP-11, GHP-14; 게시는 n8n) → 6. 결과 필드를 승인된 초안과 대조한 뒤 `summary`에 요청한 라벨, 라벨 매핑, 권고(제자리 수정·종결 등)를 짧게 적는다(GHP-12, GHP-15).

## 모드

- **GHP-01** 전역 `task-intent-boundary`가 우선한다. 이 자동화에서는 항상 초안 모드다: 에이전트는 어떤 GitHub 쓰기(댓글, 라벨 생성·교체, 이슈 생성·수정·종결, PR 생성, 리뷰 제출, push)도 하지 않고, 게시할 내용을 결과 필드에 넣는다. n8n이 결과를 적용한다. 이 모드는 PR 생성·머지 승인을 대신하지 않는다.

## 언어와 문체

- **GHP-02** [U] GitHub 대화 산출물(이슈, 댓글, 리뷰 댓글, PR 제목·본문, 라벨 이름·description, 릴리스 노트)은 **영어**로 쓴다. 사용자에게 하는 최종 보고는 결과의 `summary`에 짧은 영어로 쓴다. 이슈·댓글·리뷰 댓글·라벨 description은 핵심만 담아 아주 간결하게 쓰고, PR 본문은 길어도 된다.
- **GHP-03** [U] 공개 텍스트 작성에는 `writing-clearly-and-concisely`와 `humanizer` 스킬을 반드시 적용한다. 문체 세부는 그 스킬들이 소유하며 여기서는 호출만 한다.
- **GHP-04** 공개 댓글에는 `comment-writer` 스킬도 적용한다.
- **GHP-05** 판정·결론을 글 맨 앞에 두고, 이어서 근거(무엇을 어느 버전·환경에서 실행했고 무엇이 관찰됐는지)를 적는다. 세부 구조·템플릿·길이 예산은 각 호출 스킬이 소유한다(기본값은 `references/style.md`). 큰 구조 변경 PR이면 본문에 전반 구조·방향·설계를 적는다(사족 없이). 커밋되는 코드·문서는 저장소의 기존 언어 규약을 따르고, 규약이 없으면 영어로 쓴다. 제품·리소스 식별자는 영어 원문을 유지한다.
- **GHP-06** 실행하지 않은 검증·재현은 실행한 것처럼 쓰지 않는다. 아직 실행 전인 것은 “pending”으로 표시하고 공개하지 않으며, 추론·측정하지 않은 주장은 `[INFERENCE]` 등으로 표시한다. 지어낸 사실·존재하지 않는 근거·과장 표현을 쓰지 않는다(정직 근거는 전역 `verification` 가드 소유).
- **GHP-07** 호출 스킬이 판정한 분류(결함 vs 개선 요청)를 제목·본문·라벨에 그대로 반영하고, 잠재적 문제를 입증된 장애로 부풀리지 않는다.

## 위생 (sanitize)

- **GHP-08** 공개 본문에 비공개 정보를 넣지 않는다. 대상 저장소의 공개 여부와 무관하게 모든 GitHub 텍스트에 적용한다. 실환경 값은 `example.com`, `<zone-id>` 같은 합성 값으로 바꾸고, 버전·고정 SHA·pinned 링크를 명시한다. 금지 항목과 결과에 넣기 전 체크리스트는 `references/sanitize.md`를 따른다. `summary`와 `blockers`도 GitHub에 게시될 수 있으므로 같은 위생을 적용한다.

## 중복·수정·추적

- **GHP-09** 결과에 넣기 직전에 현재 상태를 다시 확인한다(읽기 전용 토큰으로 조회). 새 이슈 초안을 만들기 전에는 open·closed 전체를 검색하고(`gh issue list -R <owner>/<repo> --state all --search "<keywords>"`), 중복이면 초안을 만들지 않고 그 URL을 결과에 적는다(triage면 `verdict: DUPLICATE` + `duplicate_of`). 댓글 초안은 대상의 기존 댓글을 확인해 같은 내용의 중복을 막는다. 관련된 닫힌 선행 작업(이전 fix PR, 설계 문서)은 복제하지 않고 참조한다.
- **GHP-10** [U] 게시하려는 내용과 관련된 기존 이슈·PR이 이미 있을 때(GHP-09로 확인): 이미 반영돼 있으면 건너뛰고, 아니면 새 이슈를 제안하지 않고 그 이슈·PR을 보강하는 내용을 결과에 넣는다(댓글 필드, 코드는 워크트리 브랜치 로컬 커밋; 브랜치 head push는 자동화가 한다). 관련 대상이 없으면 새 이슈 초안을 현재 모드의 댓글 필드에 넣고 `summary`에 권고로 적는다.
- **GHP-11** 보강은 본문·댓글 제자리 수정을 우선한다. 결과에는 제자리 편집 필드가 없으므로, 보강 내용은 새 댓글 필드에 넣고 제자리 수정이 낫다는 판단은 `summary`에 권고로 적는다. 같은 스킬의 분석 댓글은 대상당 하나를 유지하는 것을 권고하고, 판정이 바뀌는 후속 사건(수정 머지·릴리스·종결)은 짧은 새 댓글로 남긴다. 사용자가 준 문구나 승인된 초안 문구는 그대로 쓴다. 고칠 대상인 자기 산출물(댓글·이슈·PR)은 작성자(자동화의 게시 주체 `bulgasaribot[bot]`와 author 비교, 또는 PR 컨텍스트의 `from_agent`)로 식별하고, 서브에이전트 초안이나 빈 검색 결과만으로 단정하지 않는다. 게시 URL 수집과 산출물 추적은 n8n/bridge가 한다.
- **GHP-12** [U] 에이전트가 만든 이슈·PR을 사용자가 “제거”하라고 하면 삭제가 아니라 close로 처리해야 한다. 에이전트는 close하지 않고, close 권고를 `summary`(와 필요하면 댓글 필드)에 적는다.
- **GHP-13** 공개 글에서 이전에 잘못 쓴 내용은 명시적으로 정정하는 새 댓글을 결과 필드에 넣고, 본문 수정이 필요하면 `summary`에 권고로 적는다. 닫힌 이슈의 오래된 종료 주장이 새 검증으로 바뀌면 증거 댓글로 보정하되, 사용자가 직접 닫은 이슈·PR은 다시 열자고 권고하지 않는다(지시가 있을 때만). 인용 증거는 의미가 바뀌게 잘라내지 않는다.

## 라벨

- **GHP-14** 어떤 카탈로그 라벨을 요청할지 고르는 조회·의미 매핑 규칙은 이 스킬이 소유하고(`references/labels-mechanics.md`), 라벨 이름·설명·색·배타성·부착 기준은 호출 스킬이 소유한다. 라벨은 `TriageResult.labels.add`/`labels.remove`에 자동화 카탈로그 이름으로만 요청한다. 에이전트는 라벨을 만들거나 붙이거나 떼지 않는다. 없는 카탈로그 라벨은 bridge가 카탈로그 description·색으로 만들고, 기존 저장소 라벨은 그대로 재사용하며, 상호배타 그룹은 bridge가 강제한다. 기존 라벨의 rename·recolor·delete는 요청하지 않는다.

## 게시 주체

- **GHP-15** GitHub에는 지정된 게시 주체 하나만 쓴다. 이 자동화에서 게시 주체는 n8n(bridge를 통한 GitHub App)뿐이다. 메인 에이전트와 서브에이전트, 헬퍼는 모두 초안만 만들고, 메인 에이전트가 최종 초안을 결과 필드에 넣는다. 결과에 넣기 전에는 초안 작성자가 아닌 독립 검토자가 초안의 주장을 실행 결과와 대조한다(단독 작업이면 메인 에이전트가 수행). 게시 후 대조와 게시 기록은 자동화가 맡는다.
