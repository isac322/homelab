# 안전 경계와 격리

LQA-05~LQA-18, LQA-20~LQA-22의 세부. 태그 없는 항목은 바꿀 수 있는 기본값이다. 인터뷰에서 사용자가 정한 경계가 항상 우선한다.

## 1. 읽기 전용 기본값

- **클러스터(Kubernetes 예)**: get/describe/logs와 읽기 전용 exec(`cat` 등)만 쓴다. 기존 객체를 create/update/patch/delete/annotate/restart하지 않는다. 테넌트 권한 객체(RBAC 등)도 건드리지 않는다.
- **production·실사용 환경**: 명시가 없어도 읽기 전용이다. 워크로드 생성, 벤치마크·부하 생성, 변경성 exec를 하지 않는다.
- **진단 엔드포인트**: GET만 쓴다. 종료·drain·런타임 설정 변경·카운터 리셋 같은 변경성 admin 엔드포인트에 POST하지 않는다. 공개 hostname에 대한 평범한 HTTP GET과 port-forward는 허용된다.
- **외부 provider API**: 조회만 한다. 원격 객체는 제품이 임시 리소스를 reconcile할 때만 간접적으로 생긴다. 조회 결과는 개수·메타데이터로 보고한다.
- **네트워크 probe**: 기존 health endpoint와 DNS로 한정하고 요청량을 낮게 유지한다.
- **금지된 영향 분석**: 노드 장애처럼 live에서 일으킬 수 없는 영향은 코드 기반 반사실 추론으로 제시하고 그렇게 표시한다.
- **파괴에 가까운 probe**: 포커스·활성화 변경처럼 읽기 전용이 아닌 probe는 유일한 판별 수단이어도 부적합으로 표시한다. probe마다 능력과 허용된 변경 범위를 적어 둔다.
- **mutation 고지**: LQA-12.

## 2. 허용 범위 제안(LQA-05)

변경이 필요한 검증 전에 사용자에게 제시하는 틀이다. `isac-decision-brief` 형식 안에 넣는다.

```text
목적: <이 변경이 없으면 확인할 수 없는 것>
만드는 것: <리소스 종류, 위치(namespace·계정·zone), 이름 규칙(run prefix), 개수>
읽기만 하는 것: <기존 리소스 범위>
절대 건드리지 않는 것: <production, 기존 서비스, 공유 설정, 보존 대상>
격리 근거: <기존 서비스에 영향이 없는 이유와, 격리가 유효하지 않은 경계>
필요 권한: <자격증명별 최소 권한과 용도>
정리·복구: <teardown 순서, 비상 정리, 확인 방법>
남는 위험: <공유 계정에서 남는 위험, 실패 시 영향>
권장: <권장 범위와 이유>
```

## 3. 격리: run prefix, label, ledger

- 임시 리소스 이름에 run prefix(`<project>-qa-<runId>-*` 형태)를 붙이고, 모든 객체에 run label을 단다.
- 생성 즉시 ledger에 기록한다. 이 기록이 정리의 유일한 근거다(`cleanup-and-recovery.md`).

  ```text
  kind | namespace | name | uid | created_at | creator(agent) | remote: type/id/name | depends_on | preserve(no)
  ```

- 조사자마다 자기 격리 단위와 scratch 디렉터리를 쓴다. 다른 조사자와 orchestrator의 것은 읽기만 한다.
- 새 공개 hostname을 만들지 않고 기존 zone 아래 hostname만 쓴다. namespace·hostname 충돌을 미리 확인하고, TLS 인증서가 실제로 덮는 hostname 형태(예: 한 단계 subdomain)를 쓴다. 사용할 hostname은 모두 명시적으로 허용받는다.
- 연결 중이거나 사용 중인 원격 리소스는 목록에 따로 표시하고 건드리지 않는다.
- 실행 전에 생성·읽기·수정·삭제할 모든 객체를 필요한 토큰 권한에 매핑한다. 계정 전역 변경과 부여된 권한으로 덮이지 않는 호출을 표시한다. 계정 전역 변경은 기본 실행에서 제외하고 별도 label로 분리한다.
- 격리의 한계 고지: LQA-07.

## 4. 자격증명과 비밀

- 요청·전달·막힘 처리는 `isac-decision-brief`를 따른다(LQA-08). 격리 방식(전용 계정·zone vs 기존 영역 + prefix)은 `isac-decision-brief`대로 트레이드오프를 보여 주고 묻는다. 전용 계정을 쓰면 별도 쓰기 토큰을 쓴다.
- Secret data는 읽거나 출력하지 않는다. 자격증명은 위치와 이름으로만 식별한다. Secret에 대한 단언은 존재, key 이름, 개수, 길이, ownerRef로만 한다. 값이 없으면 누락된 key 이름을 보고하고 probe하지 않는다.
- 증거 파이프라인은 끝까지 secret-safe여야 한다: 자격증명 파일은 echo 없이 소비하고, token과 그 base64 형태를 sanitizer에 등록한다. argv에 토큰을 넣지 않는다. scratch는 mode 600이다. 위임된 자동화는 전용 토큰을 쓰고 계정을 바꾸지 않는다.
- 증거에서 금지하는 필드: API token, tunnel/service token, 인증 audience 값, bearer header, 쿠키.

## 5. 위험 등급과 QA 원장

실행 순서(안전한 것부터):

1. schema 검증·server-side dry-run
2. status만 읽는 확인
3. 개별 원격 리소스를 만드는 케이스
4. permission-negative(권한 없는 경로가 거부되는지)
5. conditional(선행 조건이나 승인이 필요한 케이스)
6. blocked(공유 환경 위험으로 실행하지 않음, LQA-18)

원장 열: `ID | 등급 | 실행 방법 | 의도된 결과(클러스터) | 의도된 결과(원격·데이터플레인) | 실제 관측 | 정리 결과 | 증거 경로 | triage`. 모든 행은 `PENDING`으로 시작한다. 분모는 처음에 고정하고, blocked는 별도 열로 센다. sub-variant는 부모 행 아래에서 추적하되 합계에 다시 더하지 않는다(LQA-20).

## 6. 실행 게이트(대규모·공유 계정 run, LQA-22)

- runbook, 원장, 증거 정책을 먼저 쓴다. 스크립트는 작성과 문법 검사(`bash -n` 등)까지만 하고 게이트 전에는 실행하지 않는다.
- 독립 실행 검토와 보안 검토를 `isac-multi-agent-consensus`로 돌려 둘 다 차단 발견 0이어야 실행한다. 수정하면 재검토한다.
- 보안 검토 체크리스트: 공유 계정 blast radius, 금지된 전역 쓰기, 증거의 비밀값 누출, run 생성물 소유권, orphan 정리, conditional 케이스 처리, 비상 정리 경로, fail-closed 정리, run 밖 객체 삭제 불가능성.
- 문서 사이의 대기·재시도 예산, ID, 합계, 순서가 서로 맞는지 교차 검증한다. 모든 대기는 bounded poll이며 sleep이나 "N번 돌림"을 증거로 쓰지 않는다.
- 증거 아티팩트는 출처를 확인할 수 있게 이름과 label을 붙인다(`<suite>-<head_sha>` 등). 형식은 subcase마다 bounded JSONL `{case, subcase, expected, observed, pass}`와 blocked 분류(닫힌 집합)다.

## 7. 로컬·공유 호스트 실행

- 재현은 가장 싼 환경부터 한다(일회용 컨테이너 → 필요할 때만 무거운 하네스). 기존 재현 하네스와 일회용 이미지를 재사용한다.
- 공유 호스트에서 QA 컨테이너를 돌릴 때는 자원 제한(`--cpus`, `--memory`), 고유 이름 prefix, `--rm`을 쓰고 무거운 suite는 한 번에 하나만 돌린다.
- 부하로 생긴 timeout 처리는 `problem-criteria.md` 4절.
- 명시 승인(LQA-05) 없이는 자체 빌드를 공유 live 클러스터에 배포하지 않는다. 수정 검증 배포는 기본적으로 LQA-37의 격리 환경에서 한다.
