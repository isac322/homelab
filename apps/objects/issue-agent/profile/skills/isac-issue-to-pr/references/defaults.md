# 바꿀 수 있는 기본값

에이전트 관례에서 온 기본값이다. 사용자 의무가 아니며, 프로젝트 reference나 사용자 지시가 좁히거나 바꿀 수 있다. `[U]` 규칙과 전역 가드는 여기서 완화하지 않는다.

## 수정 설계

- 유효한 수정이 여럿이면 실행한 증거로 고르고 근거를 적는다. 가능하면 저장소 밖 scratch 프로토타입으로 before/after 시나리오 매트릭스를 먼저 만들어 acceptance 기준선으로 삼는다.
- 안전한 코드 수정이 없다는 증거가 나오면 `comment_only`(한계 문서화)도 정당한 결론이다.
- 반복된 수정 패턴(원격 자원을 관리하는 제품의 예):
  - applied status는 단조적이고 진실해야 한다. 실패 시 desired를 applied로 게시하지 않고, 일시적 관측으로 확인된 원격 ID를 지우지 않는다.
  - create/adopt 직후 원격 identity를 checkpoint해 중복 생성을 막는다.
  - cache에 기반한 일회성 원격 작업 직전에는 live로 재조회한다.
- 라이브 e2e로 드러난 외부 시스템의 공식 한계(길이 제한, 비용 제한, pagination, wire precision)는 공식 문서에서 가져오고, 임의 tolerance로 실제 결함을 가리지 않는다(I2P-20 보조).
- 긴 작업에서 목표를 몰래 좁히지 않고 blocker는 일찍 알린다(I2P-06 보조).
- 업그레이드 경로는 필수 변경 차원이다. 직전 릴리스가 남긴 상태를 소유권이나 무관한 모드를 깨지 않고 이전하거나 제거한다.

## 오케스트레이션

하네스의 위임 계약(Task 형식, 서브에이전트 검증 금지 등)은 여기서 다시 쓰지 않는다. 이 스킬에 특화된 기본값만 둔다.

- 슬라이스마다 파일 소유권이 겹치지 않는다. 범위 밖 파일은 부모에게 먼저 확장을 요청한다. 공유 계약(helper 프로토콜 등)은 코드를 쓰기 전에 피어 메시지로 협상한다. 공유 파일(Makefile, 의존성 manifest, CI, suite 등록)은 통합 owner 한 명이 맡는다.
- 게이트 분담: owner는 old/new QA와 자기 파일의 focused test만 돌리고(I2P-12), 프로젝트 전역 게이트는 통합 후 main이 한 번 돌린다(I2P-13). 실수로 전역 게이트를 돌렸다면 숨기지 않고 보고한다.
- 통합은 별도의 마지막 슬라이스다. 최신 main에 올리고 충돌은 양쪽 기능을 온전히 보존하며 푼다(한 줄씩 섞지 않는다). 이동한 코드는 전후 diff로 의도치 않은 변경이 없음을 보인다. 합집합 때문에 생긴 중복(관찰자, 픽스처, alias, shim)은 제거한다. 호환 불가능한 의도 사이에서는 임의로 고르지 않고 보고한다. 같은 파일을 건드리는 두 수정은 한 integrator가 순서대로 올리고, 통합본에 별도 QA와 리뷰를 한다. 형제 worktree에서 복사한 파일은 최종 커밋 전에 동일성을 다시 확인한다.
- 실패하거나 중단된 서브에이전트의 부분 편집은 되돌리지 않는다. 전용 repair 태스크가 부분 편집을 모두 점검해 망가진 구문과 로직을 고치고, 계약을 완성하고, 버려진 조각을 지운 뒤 전체 diff를 검토한다.
- 기존 저장소 컨벤션과 helper를 재사용한다. 저장소에 없는 공통 추상화, 호환 alias, shim을 새로 만들지 않는다. lint·스타일 정리는 동작 변경 없는 별도 sweep으로 분리한다.

## 브랜치와 diff 위생 (I2P-11, I2P-45)

- 순 diff에서 stacked 내용, 흩어진 dotfile·노트, 무관한 version bump를 뺀다.
- 최신화는 `git fetch origin` 후 `git merge origin/main`으로만 한다. 이 자동화에서는 n8n push가 fast-forward만 하므로 rebase·amend·force(`--force-with-lease` 포함)를 쓰지 않는다.
- 사용자의 기존 untracked 도구 데이터는 커밋하지도 지우지도 않는다.

## CI

- 완료 보고의 "구현 완료"는 build, lint 0, unit, integration, 실제 컴포넌트 테스트, 해당하면 공식 conformance, install smoke까지 통과를 뜻한다. 병렬 fixture starvation처럼 도구가 공식 옵션(직렬 실행 등)을 제공하면 그것을 쓰고 테스트를 생략하지 않는다.
- CI 하드닝 후보: 생성 파일 parity 검사, lint/test/build, 렌더 게이트, 컨테이너 게이트, 최소 권한, pinned action, job timeout, 시크릿 없음, 외부 변경 없음. 로컬에서 같은 Make 타깃으로 재현할 수 있어야 한다. 의존성·자동화 설정 변경은 머지 전에 그 스키마와 게이트를 따로 리뷰한다.
- 대규모 완전성 작업(parity 등)은 기계 판독 가능한 ledger와 CI checker로 되돌림을 막는다.
- 비게이트 leg(`continue-on-error`)는 사용자가 원인 수정을 이미 범위 밖으로 둔 경우에만 쓴다. 실패 테스트와 사유를 `pr.body`, README, CHANGELOG에 적고, 실패가 계속 보이게 둔다. 그 외에는 묻는다(`questions`, `needs_info`).
- multi-distro 확장: distro별 digest-pinned 베이스 이미지, lint/type은 한 leg에서만, 환경 drift 기록.
- 테스트 전용 PR도 CI green 게이트에서 면제되지 않는다.
- "CI가 무엇을 검증하냐"는 질문에는 커버되는 경로와 안 되는 경로(설치 대상, 의존성 해석, 클라이언트, README 경로)의 gap 분석으로 답한다.

## 머지 해석

머지 승인, head 변경 시 재승인, admin bypass, 브랜치 삭제는 전역 pull-request-merge 가드가 소유한다. 이 자동화에서 에이전트는 머지하지 않는다(`ready` 결과로 끝난다). 다음 운영 기본값은 결과 작성에만 쓴다.

- 브랜치 보호나 저장소 설정이 머지를 막을 것으로 보이면 `summary`에 적는다.
- 충돌 해결과 최신화(`git merge origin/main`)를 모두 끝내고 그 결과까지 커밋한 뒤 `ready`를 반환한다. 자동화는 그때의 브랜치 head를 push한다.
- 사람 리뷰 대기를 권장안으로 둘지는 `isac-decision-brief` DBR-10을 따르고, 필요하면 `summary`에 적는다.

## 완료 보고 (I2P-61)

완료 보고는 결과 `summary`(짧은 영어)다. 아래 상세는 `pr.body`에 담는다.

- 표: `| Issue | Cause | Fix | PR | Status (fixed-in-PR / merged / released / deployed) |`
- 이어서 검증 결과(실행한 명령, old/new, 동등 환경), 검증하지 않은 것, 남은 한계.
- 전체 goal 점검은 내 PR 하나로 끝내지 않는다: 전체 이슈 목록, 열린 PR과 head/base SHA, 라벨과 댓글, 중복 관계, 다른 PR로 정당화된 제외 항목을 감사한다.
- `summary`에 cleanup 내역(`/tmp/issue-agent/<worktree-name>/` scratch, 컨테이너, 임시 원격 리소스)과 총 소요 시간을 넣는다. HAPI worktree는 지우지 않는다. 삭제 전 확인은 전역 destructive-operations 규칙을, 원격 리소스 정리 절차는 `isac-live-qa`를 따른다.
