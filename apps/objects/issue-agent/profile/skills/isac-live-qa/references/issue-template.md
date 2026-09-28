# 이슈·담당자 brief·최종 보고 틀

LQA-27, LQA-33~LQA-36, LQA-42, LQA-43의 세부. 템플릿은 바꿀 수 있는 기본값이다. GitHub에 올리는 글의 언어·문체·위생·중복 확인·기존 이슈 보강은 `isac-github-publishing` 스킬을 따른다. 이 자동화에서 이슈는 초안으로만 만들고, 초안은 현재 모드의 댓글 필드(`TriageResult.comment` 또는 `ImplementResult.issue_comment`)에 finding마다 `Proposed issue` 절로 넣는다. 에이전트는 이슈를 만들지 않는다.

## 1. finding 담당자 brief(LQA-27)

위임 브리프 형식은 하네스의 위임 계약을 따른다. live QA 담당자에게는 다음을 채운다.

- **Target**: 의심 문제 한 문장.
- **Evidence found by orchestrator**: 객체 이름, 조건, 메트릭, 설정 dump 사실, 관측 시각.
- **Investigate**: 번호 붙인 질문. 반드시 포함: 버그인가 의도인가(근거 spec), 배포 tag 기준 코드 위치, 보안·불변식 영향, 가능하면 자기 임시 namespace에서 재현.
- **Write boundary**: 인터뷰에서 확정된 경계 블록 그대로(기존 리소스 R만, 허용된 임시 리소스 범위, 저장소 무변경).
- **Content/hygiene rules**: `isac-github-publishing` 준수, 실명·식별자는 placeholder.
- **Acceptance**: 이슈 초안, 또는 중복·not-a-bug 정당화(개선 후보면 enhancement 초안). 자기 임시 리소스 제거.
- **Final report schema**: 아래 3절.

## 2. 이슈 본문(영어)

### 결함(`bug`)

```markdown
## Symptom
<What was observed, with concrete evidence and numbers. Deployed version: <tag> (<digest>).>

## Reproduction
1. <Minimal step, sanitized manifest or command>
2. <...>
Observed: <result>. Reproduced <N>/<M> times on <environment class>.

## Expected
<Intended behavior, citing the spec or documentation at a pinned version.>

## Suspected cause (hypothesis)
<Optional. Only when known without extra effort. `path/to/file.go:123` at <tag>. Mark unproven claims as hypotheses.>

## Possible fix
<Optional. Only when known without extra effort.>
```

### 개선(`enhancement`)

```markdown
## Current behavior
<What the product does now and what it costs in this deployment (counts, rates, noise).>

## Proposal
<The concrete change.>

## Effect
<What improves and by how much, if measured.>

## Current vs proposed
| Case | Current | Proposed | Gap / mitigation |
|---|---|---|---|

## Tests needed
<Tests that would prove the change and guard against regressions.>
```

- Symptom과 Reproduction은 필수다(LQA-33). 재현하지 못했으면 시도한 방법과 조건을 적고 그 사실을 첫 줄에 쓴다.
- source 링크는 버전·SHA로 고정한다.
- 권장 라벨은 `bug` 또는 `enhancement`만 초안에 적는다. `repro:*`, `triage:*`는 `isac-issue-triage`의 몫이다.
- QA에서 확인한 계약은 재현 명령과 기대값, 추천 테스트 tier(unit / envtest·통합 / proxy / e2e 중 가장 싼 것)를 적어 코드화할 수 있게 한다(LQA-36).

## 3. 담당자 최종 반환

```text
status: drafted | duplicate | not-a-bug | enhancement-proposed | inconclusive
issue_draft: <초안 본문 또는 없음>
duplicate_of: <URL 또는 없음>
verdict_basis: <issue-validation dossier 경로와 증거 등급>
corrected_claims: <orchestrator 주장 중 정정한 것>
live_mutations: <수행한 변경, 없으면 none>
cleanup: temp resources removed: <목록> | none created
scratch: <남긴 증거 위치, 삭제한 scratch 파일>
```

## 4. 최종 보고(LQA-43)

결과 `summary`에는 첫 줄 한 줄 판정만 짧은 영어로 쓰고, 아래 상세 보고는 댓글 필드에 넣는다. 아래 틀과 `cleanup-and-recovery.md` 9절 틀의 절 제목·항목은 영어로 옮겨 쓴다(공개 위생은 `isac-github-publishing`, 공개 댓글에는 영향 대상 식별자를 넣지 않는다).

```text
<One-line verdict: N problems (a defects, b enhancements), k issue drafts, temporary resources removed, no code change>

## 대상과 아티팩트
- 환경 종류, 대상 버전, digest ↔ 릴리스 일치 여부, 배포 버전과 main 차이

## 점검 범위
- 기존 리소스 read-only 점검: <항목>
- 임시 리소스 점검: <항목, QA 원장 PASS/FAIL/BLOCKED/PENDING 수(분모 고정)>

## 등록한 이슈
| # | 한 줄 증상 | 결함/개선 | 심각도 |
|---|---|---|---|

## 등록하지 않은 후보
- <후보>: <이유(중복 URL, not-a-bug 근거, 증거 부족)>

## 정리 결과
<cleanup-and-recovery.md 9절 틀>

## 수행한 live 변경
- <없음 | 변경과 이유>

## 검증 수준과 한계
- 검증됨 / 추론 / 측정하지 않음
- 커버리지 한계, "이 이슈의 검증"과 "전체 릴리스 게이트 통과"의 구분

## 소요 시간
```

## 5. 결과 페이지(LQA-42)

- 첫 화면에 남은 문제 목록과 각 문제의 한 줄 요약, 심각도, 이슈 링크를 둔다.
- 문제마다 재현 정보(환경, 횟수, 로그 위치)를 적는다.
- detached 서비스로 띄우고, 다른 기기에서 HTTP 200과 레이아웃을 확인한 뒤 주소를 보고한다.
