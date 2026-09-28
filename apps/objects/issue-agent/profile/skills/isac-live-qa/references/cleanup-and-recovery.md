# 정리와 복구

LQA-16, LQA-17, LQA-38~LQA-40의 세부. 되돌릴 수 없는 삭제 전 준비는 전역 `destructive-operations`를 따른다. 태그 없는 항목은 바꿀 수 있는 기본값이다.

## 1. 실행 전 복구 준비(LQA-17)

- teardown 계획을 먼저 쓴다: 생성 역순, 의존·소유권 역순. 예(외부 서비스와 연동하는 Kubernetes 컨트롤러): 원격 앱·라우트 → 공유 정책 → 토큰 → 원격 연결 객체 → namespace → class·계정 단위 객체, 그다음 패키지 릴리스 → cluster-scoped 객체 → 자격증명. 다른 대상도 "의존하는 것 먼저, 자격증명은 마지막" 원칙으로 순서를 정한다.
- 비상 정리 경로를 둔다: 스크립트는 EXIT trap으로도 정리하고, 각 단계에 명시적 timeout을 두며, 실패하면 멈추고 nonzero로 끝난다.
- 공유·baseline fixture를 건드려야 하면 원래 값을 기록해 두고, 케이스가 끝나면 복구한다. 케이스 뒤 공유 설정이 바뀐 채 남으면 다음 케이스의 blocker다.
- suite 실행마다 run identity를 따로 기록한다.
- 정리 수단이 없는 객체(삭제 API가 없거나 권한이 없는 것)는 만들지 않는다.

## 2. ledger 기반 삭제(LQA-16)

- 삭제 대상은 ledger에 있는 객체뿐이다. 정확한 name+UID(UID precondition)로 지운다. 이름만으로 지우거나 prefix 전체를 지우는 janitor는 쓰지 않는다. run 밖 객체 삭제가 구조적으로 불가능하게 만든다.
- UID가 ledger와 다른 객체는 교체된 것이다. resolved로 보고 건드리지 않는다.
- 연결 중·정상 동작 중인 원격 리소스는 prefix가 맞아도 자동 삭제하지 않는다.
- 다음 케이스로 넘어가기 전에 paginated residue scan 결과가 0이어야 한다.

## 3. fail-closed 정리

- HTTP·전송 오류를 "없음"으로 바꾸지 않는다. 실제 404나 실제 삭제 표시만 삭제 완료로 인정한다.
- 재시도는 횟수가 정해져 있고, 정리 실패 시 nonzero로 끝난다.
- residue 탐색은 pagination을 끝까지 돌고 응답 envelope을 검증한다(`id` 대신 `uid`를 쓰는 리소스처럼 ID 필드가 비대칭인 경우 포함). 중간 실패가 뒤 리소스 유형을 조용히 건너뛰게 두지 않는다.
- kind는 discovery로 찾고 모르는 kind가 나오면 크게 실패시킨다. namespace 삭제 timeout은 삼키지 않고 드러낸다.
- 원격 삭제 호출은 정확한 endpoint와 cascade 옵션을 쓴다. 비슷한 이름의 구형 endpoint를 쓰지 않는다.
- 자격증명이 살아 있는 동안 finalizer 완료를 기다린다. 자격증명을 먼저 지우면 원격 정리가 막힌다.

## 4. IaC 관리 리소스(LQA-39)

- Terraform 등 IaC가 관리하는 리소스는 수동으로 지우지 않는다. IaC로 회수하도록 사용자에게 보고한다.
- residue 감사는 IaC 소유 영구 리소스와 임시 테스트 리소스를 구분하고, state 밖에 남았을 가능성도 보고한다.

## 5. 멈춘 삭제(LQA-06)

자기 임시 객체가 테스트 대상 버그 때문에 삭제 중 멈추면(예: finalizer):

1. read-only 원격 조회로 원격에 남은 것이 없는지 확인한다.
2. 복구 조작이 인터뷰에서 허용됐으면 자기 객체에서만 finalizer를 제거하고 namespace가 사라졌는지 확인한다. 허용되지 않았으면 상태를 보고하고 요청한다.
3. 기존 객체에는 절대 하지 않는다. 조치와 근거를 보고서에 적는다. 이 현상 자체가 finding 후보다.

## 6. 전체 정리 요청(LQA-40)

1. 테스트를 위해 배포·생성한 모든 것을 표면별로 read-only 조사한다: 원격 provider, 모든 kube context, 클라우드, GitHub(임시 브랜치·PR·workflow run·artifact·cache·environment·package·release), 로컬(Docker 컨테이너·이미지·volume, `/tmp`·scratch, 프로세스). 표면별 조사는 병렬로 한다.
2. 목록을 결과에 보고한다. 삭제는 그 뒤 별도 지시를 받아 한다. GitHub 표면(임시 브랜치·PR·workflow run 등)의 삭제는 에이전트가 하지 않고 목록과 권고만 결과에 넣는다.
3. 조사 결과와 삭제 전 redacted 백업(checksum 포함)을 `/tmp/issue-agent/<worktree-name>/`에 저장한다.
4. 사용자가 지정한 보존 예외는 지우지 않는다(예: 에이전트 세션, GitHub 임시 리소스·PR).
5. 정리 후 대상이 사라졌는지와 보존 대상이 살아 있는지를 정확한 개수로 이중 확인한다.

## 7. residue 감사 분류

감사는 아무것도 지우지 않고 모든 객체를 분류한다.

| 분류 | 의미 |
|---|---|
| existing | 우리가 만들지 않았거나 보존 대상 |
| removed | ledger에 있었고 삭제가 확인됨 |
| unverified | 조회 실패·권한 부족으로 판단 불가(없음으로 세지 않음) |
| delete-candidate | 임시성 증거가 있는 삭제 후보(증거 첨부) |
| cache | 재생성 가능한 캐시, 정리 대상과 구분 |
| intended-persistent | 의도된 영구 산출물(릴리스 등) |

live API로 확인할 수 없는 경우에는 간접 증거(controller DELETE 로그, 정리 작업 성공 횟수)로 판정하고, 그렇게 했다고 밝힌다.

## 8. scratch와 증거 보존

- 실행 로그와 관측 증거는 저장소 밖 scratch 경로에 남기고 사용자에게 위치를 알린다(공개 산출물에는 쓰지 않는다).
- worktree·scratch를 지우기 전에 clean 여부와 내용이 main에 반영됐는지 확인하고 복구 수단(브랜치 ref)을 남긴다.
- 조사 subagent는 끝날 때 정리 증명("temp resources removed: <목록>" 또는 "none created")과 scratch 파일 삭제 여부를 반환한다.

## 9. 최종 보고의 정리 절

```text
## 정리 결과
- 삭제한 임시 리소스: <namespace N개, cluster-scoped M개, 원격 K개> (ledger 기준 전부/일부)
- 잔여 확인: <표면별 residue scan 결과, 0 또는 남은 목록과 이유>
- 멈춘 객체 처리: <없음 | 객체, 조치, 근거>
- 복구한 공유 설정: <없음 | 항목>
- 보존 대상 확인: <목록, 생존 확인>
- 수동 조치 필요: <IaC 회수, 권한 부족으로 못 지운 것>
- 증거 위치: <로컬 scratch 경로>
```
