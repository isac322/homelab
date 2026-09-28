# 외부·오래된 PR 감사

외부 기여 PR이나 오래 열린 PR이 아직 필요한지, 이미 main에 반영됐는지 판정한다. SKILL.md의 PRR-33–PRR-35와 권한 규칙(PRR-01–PRR-03)을 전제로 한다. 수정 출처 기록 방식(fixed-in-PR / merged / released / deployed 구분)은 `issue-validation`이 소유한다. 에이전트는 PR을 닫거나 라벨을 붙이거나 코멘트를 게시하지 않는다. 아래의 닫기·라벨·코멘트 조치는 모두 `ReviewResult.body`의 권고가 되고, 게시는 n8n이 한다.

## 판정 어휘

PR마다 하나를 고른다. PRR-24 판정 줄은 오른쪽 열처럼 함께 쓴다.

| 판정 | 뜻 | 기본 조치 | PRR-24 판정 |
|---|---|---|---|
| `needed` | 문제가 main에 남아 있고 PR 접근이 맞다 | 일반 리뷰로 진행 | 리뷰 결과대로 `GREEN` 또는 `BLOCKING` |
| `needs changes` | 문제는 실재하지만 PR을 고쳐야 한다 | blocking finding을 ReviewResult에 담는다. 리뷰어는 push하지 않는다 | `BLOCKING` |
| `partially superseded` | 일부는 main에 이미 있고 일부는 남았다 | 남은 부분과 좁히는 방법을 `BLOCKING` 리뷰(`REQUEST_CHANGES`)로 | `BLOCKING` |
| `superseded` | main이 이미 고쳤다(증명 완료) | 닫기 권고(`COMMENT` 이벤트, PRR-25) | Verdict 줄 대신 닫기 권고 템플릿 |
| `close-without-merge` | 문제가 없거나, 머지하면 해가 된다 | 근거와 함께 닫기 권고 | `BLOCKING`(머지하면 안 되는 이유가 finding) |

코드 수정 없이 코멘트만 남기는 것이 올바른 결론이면 `ReviewResult.summary`에 그렇게 적고 브랜치는 건드리지 않는다.

`ReviewResult.summary`에서는 이 판정을 SKILL.md PRR-31의 결정 단위(머지 가능 / 수정 후 머지 / 이미 main 반영·닫기 권장 / 일부만 유효)로 묶는다.

## 절차

1. **대상 목록**: 열린 PR 전체를 나열하고 연결 이슈, head SHA, 마지막 갱신, 충돌 상태, CI 상태를 기록한다. 시작과 끝에 다시 확인해 목록이 바뀌지 않았는지 본다.
2. **재현**: PR마다 주장된 문제를 merge-base와 현재 main 양쪽에서 재현한다. 연결 이슈가 없어도 같은 순서로 한다(새 이슈는 만들지 않는다, PRR-10).
3. **설계 비교**: PR의 접근을 main의 현재 설계와 비교한다. main이 다른 방식으로 고쳤으면 PR을 머지할 때 그 수정과 충돌하거나 되돌리는지 본다.
4. **superseded 증명** (PRR-33):
   1. main에서 이를 고친 정확한 커밋을 찾는다(`git log -S '<symbol>'`, `git blame`, `git log --grep`).
   2. 그 커밋을 포함하는 첫 릴리스 태그를 찾는다(`git tag --contains <sha>`, 정렬 후 첫 태그).
   3. 릴리스된 아티팩트(패키지 레지스트리의 wheel, 컨테이너 이미지 등)를 받아 판별 재현을 돌린다. 옛 버전은 실패하고 새 버전은 통과해야 한다.
   4. main에는 있지만 릴리스에는 없으면 "merged but unreleased"로 기록한다(PRR-35).
5. **재검증** (PRR-34): 외부 기여자 PR의 닫기를 권고할 때 판정이 이전 패스에서 나왔으면, 권고 직전에 현재 main 기준으로 판별 증거를 다시 돌린다. 이전 감사 결과를 재사용하지 않는다. 에이전트나 사용자 자신의 PR을 일회성으로 정리할 때는 이 단계를 건너뛸 수 있다. 확실하지 않으면 닫기를 권고하지 않고 불확실한 이유를 `ReviewResult.body`에 적는다.
6. **닫기 권고**: 권고 문구는 `references/comment-template.md`의 닫기 권고를 `ReviewResult.body`(`COMMENT` 이벤트)에 담는다. 닫기와 브랜치 삭제는 메인테이너가 정하고, 에이전트는 하지 않는다.
7. **정리**: 재검증에 쓴 컨테이너, 이미지, scratch 디렉터리를 정리하고 `ReviewResult.summary`에 정리 여부를 적는다.

## 산출물 (바꿀 수 있는 기본값)

여러 PR을 감사할 때 PR마다 `/tmp/issue-agent/<worktree-name>/` 아래 날짜별 scratch 디렉터리(커밋하지 않음)에 둔다.

- `dossier.md`: claim, 재현 명령과 출력, 기준점별 결과, 원인, 판정 근거.
- `result.json`: `{pr, certain, superseded_by, first_release, recommended_version, evidence, reasons_if_not_certain}`.
- `comment.md`: `ReviewResult.body`에 넣을 영어 본문 초안.
- `logs/`: 원본 실행 로그.

결과를 내기 전에 담당자와 다른 독립 리뷰어가 산출물을 검증한다. 모든 claim을 실행 로그와 소스에 교차 확인하고, 문구가 실제로 실행한 범위와 일치하는지 본다. 승인은 파일 단위(result.json / dossier / comment)로 한다. 문체·위생은 `isac-github-publishing`을 따르고, 게시는 n8n이 한다.

## 대량 감사

- 같은 형태의 로그나 diff가 20건 이상이면 눈으로 훑지 않는다. 파일로 저장하고 고정된 판정 루브릭으로 분류한 뒤 표시된 후보만 직접 확인한다.
- PR별 감사는 병렬로 돌린다. 리뷰어 병렬 구성과 합의 라운드는 `isac-multi-agent-consensus`를 따른다.

## 자주 놓치는 것

- fork PR의 CI 실패(권한 부족 403 등)를 PR 결함으로 판정하지 않는다(PRR-28).
- 의존성 업데이트 PR은 목표 버전에도 공개 취약점이 남아 있는지 확인한다. 남아 있으면 더 높은 버전을 요구한다.
- "다른 PR이 대체한다"는 주장은 그 PR이 머지 가능한 상태인지까지 확인한다. 충돌 중인 PR은 대체가 아니다.
- 커밋이 이미 다른 PR로 들어간 PR은 superseded다(PRR-17). 커밋 단위로 main에 있는지 확인한다(`git branch -r --contains`, `git cherry`).
