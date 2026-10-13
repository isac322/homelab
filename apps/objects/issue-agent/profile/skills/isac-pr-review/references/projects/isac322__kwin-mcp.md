# isac322/kwin-mcp

공개 저장소 isac322/kwin-mcp의 PR 리뷰에만 적용한다. 이 문서는 SKILL.md와 `references/defaults.md`의 기본값을 이 저장소에 맞게 좁히거나 구체화할 뿐, `[U]` 규칙(PRR-38, PRR-48, PRR-55, PRR-57 등)과 전역 가드를 완화하지 못한다. 일반 규칙(최소 런타임·requested vs observed PRR-42, 진입 경로별 적대적 입력 PRR-44, 억제 PRR-45, 보안 정책 우회 PRR-47, 재리뷰 hazard pass PRR-54)은 SKILL.md가 소유하고, 여기에는 이 저장소의 구체 사실과 확인 방법만 적는다. 규칙마다 무엇을 하는지, 왜(한 줄), 어떻게 확인하는지를 적는다. scratch 파일과 산출물은 `/tmp/issue-agent/<worktree-name>/`에 둔다. 경로는 저장소 루트 기준이다.

## 0. 직접 읽을 저장소 지침

PRR-40에 따라 아래 지침을 base 브랜치에서 직접 읽는다. 이 저장소에는 AGENTS.md와 `.agents/skills`가 없고, 지침은 아래에 있다. 적용한 파일을 body에 적는다.

- `CLAUDE.md`: 툴체인, 코드 스타일, `## Pre-work Checklist`, `### docs-seo Auto-Trigger Files` 표(변경 파일마다 확인할 문서).
- `CONTRIBUTING.md`: `## Pull Request Process`(CHANGELOG/README, plugin sync), `## Project Structure`(테스트 파일 목록), 그 아래 exit path 계약 단락.
- `docker/README.md`: E2E 하네스, `## Test-file inventory` 표, 배포판·아키텍처·백엔드 한계.
- `.claude/agents/docs-seo.md`(코드 변경 종류별 문서 갱신 대상: `tool-registration`, `code-general`, `session-api` 등), `.claude/skills/check-docs-seo`, `.claude/skills/release-notes`, `.claude/positioning.yml`.
- `README.md`의 도구 표, `Every tool publishes MCP tool annotations` 단락, Known Limitations, 그리고 `docs/design/*.md`(`dbus-call-call-sites.md`, `real-session-support.md`): 사용자 계약.

## 1. 저장소 사실

- `main`은 squash merge만 쓰고 `squash_merge_commit_title=COMMIT_OR_PR_TITLE`이다. non-merge 커밋이 하나뿐인 PR은 그 커밋 subject가, 여러 개면 PR 제목이 main 커밋 제목이 된다(KM-C1).
- `pyproject.toml`: `requires-python = ">=3.12"`, classifiers 3.12–3.15. 저장소 E2E 이미지의 Python은 Debian trixie·openSUSE 3.13, Arch 3.14라서 3.12는 저장소 하네스로 실행되지 않는다(§2.2로 직접 본다).
- `scripts/check_docs_seo.py`가 보는 것은 SEO 키워드, plugin keyword, SKILL mirror, `server.py`의 `@_tool(` 개수와 `TOOL_COUNT_CANONICAL`의 일치뿐이다. 테스트 파일 목록, 문서 본문의 도구 개수, 동작 설명은 보지 않으므로 KM-D1–D3로 직접 확인한다.
- 동적 모듈(`gi.repository`, `dbus.bus`)은 `pyproject.toml` `[[tool.ty.overrides]]`에서 파일 단위로만 예외를 둔다. `src`·`tests`의 `# ty: ignore`·`# type: ignore`는 2026-10-11 main 기준 0개이고, `# noqa`는 모두 코드를 명시하며 `cast(`는 소수다.

## 2. 실행 방법 (리뷰어가 PRR-57 범위의 빠른 targeted check가 필요하다고 판단할 때만)

판정·증거·격리 실행 규칙은 SKILL.md PRR-38, PRR-49–PRR-55를 따르고, 로컬 실행 범위는 PRR-57을 따른다. 아래는 kwin-mcp의 이미지·런타임·하네스에 관한 실행 방법이다. 리뷰어가 로컬에서 돌릴 수 있는 것은 PRR-57의 빠른 targeted check(단일 unit test, lint, 바뀐 모듈의 빠른 build)뿐이다. E2E 이미지 build·실행(§2.1, GUI·Appium·multi-distro suite)은 CI가 돌리고, 리뷰어는 그 CI 결과를 입력으로만 읽는다(PRR-38). 실행할 수 없는 것은 `Not verified`에 적고 PRR-50의 argument+challenger로 다룬다.

- PR의 `scripts/run-e2e-docker.sh`는 실행하지 않는다. 왜: docker를 부르는 PR 소유 wrapper이고, worktree를 그대로 마운트한다. 참고로 이 스크립트는 인자를 `pytest tests/e2e -v --junitxml=...` 뒤에 덧붙이므로 `-- tests/e2e/test_x.py`는 집중 실행이 되지 않고 전체 suite를 돈다. 문서나 PR이 그렇게 주장하면 claim으로 검토한다.
- 러너는 arm64이고 binfmt 에뮬레이션이 없다. Debian(`docker/e2e.Dockerfile`), Fedora(`e2e-fedora.Dockerfile`), openSUSE(`e2e-opensuse.Dockerfile`)는 native arm64로 빌드된다. Arch(`e2e-arch.Dockerfile`)는 `linux/amd64` 전용이라 여기서 돌리지 않고 "cannot run locally"로 적는다. `docker/README.md`의 에뮬레이션 전용 실패(`test_observation_tools.py::test_launch_app_rejects_a_missing_command`)는 native arm64에는 해당하지 않으므로, 여기서 실패하면 원인을 따로 본다.
- `--privileged`, `--cap-add`, GPU, `/dev/dri`는 필요 없다(이미지가 `LIBGL_ALWAYS_SOFTWARE=1`, `setcap -r /usr/bin/kwin_wayland`). 실행 중 네트워크 때문에만 실패하는 테스트는 네트워크를 열지 말고 환경 한계로 적는다.

### 2.1 Debian E2E 이미지 (CI가 돌리는 suite — 로컬 실행 금지, PRR-57)

```bash
W=/tmp/issue-agent/<worktree-name>/e2e
SHA=<head-sha>
rm -rf "$W" && mkdir -p "$W/ctx"
git -C <worktree> archive --format=tar "$SHA" | tar -x -C "$W/ctx"
# 네트워크는 build 단계에서만 쓴다(Debian snapshot, uv). --allow 엔타이틀먼트를 주지 않는다.
docker build -f "$W/ctx/docker/e2e.Dockerfile" -t "kwin-mcp-e2e:${SHA:0:12}" "$W/ctx"

# 정적 검사: CI가 이 이미지에서 src와 tests 모두 돌린다(ruff 캐시는 끈다). 리뷰어의 lint는 §2.2 scratch 이미지에서 한다.
docker run --rm --network none -v "$W/ctx:/workspace:ro" -w /workspace "kwin-mcp-e2e:${SHA:0:12}" \
  /bin/sh -c '/opt/kwin-mcp-venv/bin/ruff check --no-cache src tests &&
              /opt/kwin-mcp-venv/bin/ruff format --check --no-cache src tests &&
              /opt/kwin-mcp-venv/bin/ty check src tests'

# E2E: 이미지에 build 시점의 tests/가 들어 있다. CI가 이 suite를 돌리고, 리뷰어는 결과를 읽는다.
docker run --rm --network none "kwin-mcp-e2e:${SHA:0:12}" \
  /opt/kwin-mcp-venv/bin/python -m pytest -p no:cacheprovider -v tests/e2e/test_<area>.py
```

Fedora·openSUSE에 닿는 변경(libei, KWin, Qt, 배포판 패키지)은 `-f "$W/ctx/docker/e2e-fedora.Dockerfile"` 또는 `e2e-opensuse.Dockerfile`로 CI가 같은 방식으로 만든다. 리뷰어는 로컬에서 이 이미지를 build·실행하지 않고, harness를 검토할 때만 이 명령을 참고한다.

### 2.2 Python 3.12·3.13 scratch 이미지 (PRR-57의 빠른 targeted check)

다음을 건드리는 PR은 3.12와 3.13에서 직접 실행해 본다: `typing`/`inspect` introspection(`cli._parse_value`, `cli._parse_args`, `typing.get_type_hints`), engine 메서드의 새 `X | None` 파라미터, 버전마다 동작이 다른 표준 라이브러리. 아래 네 테스트 파일은 dbus와 gi를 stub으로 바꿔도 안전하게 돈다(2026-10-11 main에서 3.12·3.13 모두 60 passed). 다른 파일을 stub으로 돌린 실패는 해석하지 않는다.

lint가 필요하면 E2E 이미지를 만들지 않고, 같은 방식의 `python:3.12-slim` scratch 이미지에 `ruff`와 `ty`만 설치해 `ruff check --no-cache`, `ruff format --check --no-cache`, `ty check`를 바뀐 파일에 돌린다.

```bash
P=/tmp/issue-agent/<worktree-name>/py
rm -rf "$P" && mkdir -p "$P/src" "$P/stub/kwin_mcp-0.0.0.dist-info"
git -C <worktree> archive --format=tar <head-sha> | tar -x -C "$P/src"
printf 'Metadata-Version: 2.1\nName: kwin-mcp\nVersion: 0.0.0\n' > "$P/stub/kwin_mcp-0.0.0.dist-info/METADATA"
cat > "$P/stub/sitecustomize.py" <<'EOF'
import sys
from unittest import mock
for n in ("dbus", "dbus.bus", "dbus.service", "dbus.lowlevel", "dbus.exceptions",
          "dbus.mainloop", "dbus.mainloop.glib", "gi", "gi.repository"):
    sys.modules.setdefault(n, mock.MagicMock(name=n))
EOF
cat > "$P/Dockerfile" <<'EOF'
ARG PY
FROM python:${PY}-slim
RUN pip install --no-cache-dir 'Pillow>=10' 'mcp>=2.2,<3' pytest
COPY stub /stub
COPY src /src
WORKDIR /src
ENV PYTHONPATH=/stub:/src/src PYTHONDONTWRITEBYTECODE=1
EOF
for v in 3.12 3.13; do
  docker build --build-arg PY="$v" -t "kwin-mcp-py$v" "$P" &&
  docker run --rm --network none "kwin-mcp-py$v" python -m pytest -q -p no:cacheprovider --noconftest \
    tests/e2e/test_cli_value_parsing.py tests/e2e/test_kwin_script_render.py \
    tests/e2e/test_window_match.py tests/e2e/test_window_set_geometry_validation.py
done
```

새 CLI 파라미터는 같은 이미지에서 `python -c 'from kwin_mcp.cli import _parse_args; from kwin_mcp.core import AutomationEngine; print(repr(_parse_args(AutomationEngine().<method>, "<name>=<value>")))'`로 3.12와 3.13의 변환 타입을 본다.

## 3. 변경 유형별 규칙

### 문서 동기화 (`CLAUDE.md` docs-seo 트리거)

- **KM-D1 테스트 파일 목록은 두 곳을 함께 맞춘다.** `tests/e2e/test_*.py`를 추가·이름 변경·삭제하면 `CONTRIBUTING.md` `## Project Structure` tree와 `docker/README.md` `## Test-file inventory` 표를 모두 고쳐야 한다.
  - 왜: README는 docker/README를 "complete test-file inventory"라 부르고, `CLAUDE.md` docs-seo 표는 `src/kwin_mcp/*.py` 변경 때 "CONTRIBUTING file listing" 확인을 요구한다. #90, #92, #93, #94, #96, #98이 모두 빠뜨렸다.
  - 확인:

    ```bash
    files=$(ls tests/e2e/test_*.py | xargs -n1 basename | sort)
    comm -23 <(echo "$files") <(grep -oE 'test_[a-z0-9_]+\.py +#' CONTRIBUTING.md | grep -oE 'test_[a-z0-9_]+\.py' | sort -u)
    comm -23 <(echo "$files") <(grep -oE '^\| `test_[a-z0-9_]+\.py`' docker/README.md | grep -oE 'test_[a-z0-9_]+\.py' | sort -u)
    ```

  - 등급: PR이 새로 만든 누락만 non-blocking finding이다. main에 이미 있던 누락(2026-10-11 기준 CONTRIBUTING 6개, docker/README 5개)은 관찰 사항이다.
- **KM-D2 도구 개수는 모든 숫자 참조가 같아야 한다.** `server.py`의 `@_tool(`이 늘거나 줄면 README(소개·기능 문단, 아키텍처 다이어그램, 테스트 bullet), CONTRIBUTING, `docker/README.md`(`test_mcp_protocol.py` 행), `docs/ai-agent-integration.md`, `.claude/positioning.yml`(`tool_count`, `tool_count_canonical`), `.claude/agents/docs-seo.md`, `CLAUDE.md` docs-seo 표, `integrations/claude-code/.claude-plugin/plugin.json`, `integrations/claude-code/skills/kwin-desktop-automation/SKILL.md`, `scripts/check_docs_seo.py`의 `TOOL_COUNT_CANONICAL`, `tests/e2e/test_mcp_protocol.py`의 `EXPECTED_*` 표를 모두 갱신한다. main을 병합한 head에서도 다시 센다.
  - 왜: #97과 #98은 각자 33을 34로 올렸지만 둘 다 머지되면 35가 맞다. 숫자 검사는 PR마다 따로 돌아 이런 충돌을 못 잡는다.
  - 확인: `grep -cE '^\s*@_tool\(' src/kwin_mcp/server.py`와 `git grep -nIE '\b[0-9]+ (MCP )?(tools|capabilities)\b|all [0-9]+ (registered )?tools|tool_count(_canonical)?: [0-9]+|TOOL_COUNT_CANONICAL = [0-9]+' -- ':!CHANGELOG.md'`의 숫자가 모두 같아야 한다. 도구를 추가하는 열린 형제 PR은 `gh pr list --repo isac322/kwin-mcp --state open --json number,title,files --jq '.[] | select(any(.files[]; .path=="src/kwin_mcp/server.py")) | [.number,.title] | @tsv'`로 찾고, 합산 개수가 달라지면 body에 적는다.
- **KM-D3 docs-seo 트리거 표를 체크리스트로 쓴다.** 변경 파일마다 `CLAUDE.md` `### docs-seo Auto-Trigger Files`가 지정한 문서를 확인하고 결과(갱신 필요 여부)를 `Verified`에 적는다. 동작이 바뀐 도구는 README 도구 표, Known Limitations, `integrations/claude-code/skills/kwin-desktop-automation/SKILL.md`(source of truth)까지 본다. OpenCode mirror는 직접 편집하지 않는 생성물이다. user-facing 변경에는 CHANGELOG `[Unreleased]`에 Keep a Changelog 범주(Added, Changed, Fixed 등) 항목이 있어야 한다.
  - 왜: 이 문서들의 정합성은 어떤 자동 검사도 보지 않는다.

### 억제와 Python 버전

- **KM-T1 억제는 tests까지 저장소 기준선으로 본다.** `# ty: ignore`와 `# type: ignore`는 `src`와 `tests` 모두 0개가 기준선이라 새로 생기면 하나하나 finding이다. `# noqa`는 기존 패턴(`gi.require_version` 뒤 import의 `E402`, D-Bus·cmd 메서드 이름의 `N802`/`N815`, 일부러 열어 두는 임시 파일의 `SIM115`)에 코드를 명시하고 이유가 있을 때만 허용하고, 코드 없는 `noqa`나 새 범주는 finding이다. 타입 오류를 숨기려고만 쓴 새 `cast(`도 같다. 동적 모듈 예외는 `[[tool.ty.overrides]]` 파일 단위로만 둔다. 등급과 수정안 형식(시그니처 명시, fake 객체용 `Protocol`)은 PRR-45를 따르고, 이 저장소에서는 lint 억제(`noqa`)도 PRR-45가 말하는 "프로젝트 관례가 금지한 억제"로 본다.
  - 왜: #90은 `spawn(**kwargs: object)`의 타입 손실을 억제로 덮었고, #94는 fake 객체에 억제 4개를 붙였다.
  - 확인: `git diff <merge-base>...HEAD -U0 -- src tests | grep -nE '^\+.*(#\s*(ty|type):\s*ignore|\bcast\(|#\s*noqa)'`.
- **KM-P1 CLI annotation 해석은 3.12·3.13에서 따로 본다.** engine 메서드에 새로 생긴 `X | None` 파라미터는 `cli._parse_value`를 거치는데, 3.12·3.13은 3.14와 다르게 해석한다. §2.2로 확인한다.
  - 왜: #92의 `screenshot max_edge=640`이 CLI에서 문자열로 넘어가 TypeError를 냈다. af20dd9 기준 같은 parser가 3.12·3.13에서는 `str`, 3.14에서는 `int`를 냈다.

### 입력 경로

- **KM-I1 입력 검증은 engine(`core.py` `AutomationEngine`)에 둔다.** engine 메서드에 닿는 경로는 셋이다: (1) MCP stdio — `server.py` `Annotated`로 만든 pydantic schema(`int`에 범위 없음), (2) CLI `key=value` — annotation 기반 변환, (3) CLI JSON 객체 `{...}` — `cli._parse_args`가 `json.loads` 결과를 검증 없이 넘겨 MCP schema를 우회한다. 그래서 타입(`bool`과 `int` 구분 포함), 유한성, 범위(KWin geometry는 int32) 검사는 engine에 있어야 한다. 선례는 `window_set_geometry`의 검증 블록이다.
  - 왜: #97에서 `width=10**400`이 MCP schema를 통과해 KWin JS에서 `Infinity`가 됐고, CLI JSON으로는 NaN, 소수, 문자열 좌표가 KWin에 그대로 닿았다.
  - 확인: engine 메서드에 `True`, `1.5`, `"10"`, `float("nan")`, `10**400`, 음수, 0을 직접 넘기고, `cli._parse_args(engine.<method>, '{"<name>": 1.5}')`도 본다(§2.2 scratch 컨테이너 안에서).
- **KM-I2 KWin geometry·activation 결과는 readback으로만 성공을 말한다.** KWin은 client가 configure를 ack하고 commit한 뒤에야 변경을 반영하므로, 요청 직후 값은 관측값이 아니다. readback이 다르거나 실패했는데 응답이 "set"/"done"이면 결함이다.
  - 확인: readback을 바뀌지 않은 값과 실패로 stub해 응답 문구를 본다.

### KWin 스크립트

- **KM-K1 caller 값은 `geometry._render_script`로만 KWin JavaScript에 넣는다.** 이 함수는 모든 placeholder를 한 번에 치환하고 값마다 `json.dumps`를 쓴다. caller 값을 `.replace()`로 차례차례 치환하지 않는다. `run_kwin_script`의 `{sink}`, `{path}` 치환은 내부 상수 전용이다.
  - 왜: #96(P1)에서 두 번째 `.replace`가 첫 치환 결과를 다시 처리해, `focus_window`(`_NON_DESTRUCTIVE_IDEMPOTENT`)로 임의 KWin JS를 실행하고 live 세션의 `window_close` guard를 우회해 실제 창을 닫을 수 있었다.
  - 확인: `git diff <merge-base>...HEAD -- src | grep -nE '^\+.*\.replace\(\s*"\{'`. 새 placeholder는 `tests/e2e/test_kwin_script_render.py`의 `_assert_literals`로 덮여야 하고, 조합 selector 주입 사례(`app_name='{window_id}'`, `window_id='";workspace.activeWindow.closeWindow();//'`)를 포함해야 한다.

### live 데스크톱 안전

`session_connect`와 `--default-live-session`은 사용자의 실제 데스크톱에 붙는다.

- **KM-L1 tool annotation은 실제 효과와 맞아야 한다.** 상수는 `server.py`의 `_READ_ONLY`, `_DESTRUCTIVE`, `_DESTRUCTIVE_IDEMPOTENT`, `_NON_DESTRUCTIVE_IDEMPOTENT`, `_SPAWN`, `_SPAWN_COMMAND`, `_DBUS_CALL`이다. 상태를 바꾸는 도구는 `_DESTRUCTIVE*`여야 하고, read-only·non-destructive 도구에는 입력 주입, 창 닫기, 임의 스크립트 실행으로 가는 경로가 없어야 한다.
  - 왜: README는 client가 이 annotation으로 사용자 확인 여부를 정한다고 명시한다.
  - 확인: 새·변경 도구의 annotation과 호출 경로를 대조한다.
- **KM-L2 데이터를 잃을 수 있는 동작은 LiveSession에서 거부한다.** 선례는 `AutomationEngine.window_close`와 README `window_close` 행("Disabled in live sessions to protect unsaved work")이다. 새 도구가 닫기·종료·폐기를 하면 같은 guard를 두거나, 두지 않는 이유를 PR이 밝혀야 한다.
  - 왜: live 세션은 저장되지 않은 사용자 작업을 가진다.
  - 확인: 새 도구를 LiveSession 경로로 따라가 guard 유무를 본다.
- **KM-L3 live 데스크톱의 전역 상태 변경은 opt-in이고, 변경 전에 복원을 기록한다.** `org.a11y.Status.IsEnabled` 같은 전역 상태는 복원 의무를 먼저 기록한 뒤 바꾸고, `session_stop`과 서버 종료 때 모두 복원한다. 응답 유실이나 그 사이 Ctrl-C에도 복원돼야 한다. 선례는 `session.py` `switch_accessibility_on`의 `_accessibility_restores.append` 후 `set_accessibility_enabled` 순서다.
  - 왜: 기록 전에 바꾸면 그 창에서 끊긴 세션이 사용자 데스크톱 설정을 영구히 바꿔 둔다.
  - 확인: 기록과 변경 사이에 응답 유실이나 신호를 주입해 본다.

### AT-SPI

- **KM-A1 "정확히 하나" 계약은 fail-closed다.** 대상은 요소의 창 매칭(정확히 하나가 아니면 `@ unavailable (reason)`, README Known Limitations)과 `invoke_ui_action`(일치 대상이 정확히 하나일 때만 실행)이다. 탐색이 불완전하면 거부해야 한다: AT-SPI 읽기 예외, 읽을 수 없는 subtree, depth 한계(`accessibility.py` `_ACTION_SEARCH_MAX_DEPTH`), 스냅샷 사이 변화가 모두 해당한다(`_IncompleteDiscoveryError`). 탐색 경로의 `except Exception: pass`나 빈 값 대체는 결함이다.
  - 왜: #98(P1)에서 두 번째 후보 읽기가 실패하자 첫 후보가 실행됐다. #94(P2)에서는 caption만 다른 같은 크기 형제 창이 다른 창의 좌표를 가져갔다.
  - 확인: `tests/e2e/test_accessibility_actions.py`·`test_window_match.py`의 fake 객체 방식으로 두 번째 후보를 읽기 실패, 같은 크기 형제, caption 불일치로 만들어 action 0회 또는 `unavailable`을 확인한다.

### D-Bus와 종료 경로

- **KM-B1 registry lock 아래의 D-Bus 왕복은 처음부터 끝까지 시간 제한이 있어야 한다.** 대상은 `session_stop`, 서버 종료, `OwnedProcessRegistry` lock을 쥔 상태에서 닿는 모든 D-Bus 왕복이고, 연결·인증·name owner 조회·introspection·호출 전부에 제한이 걸려야 한다. dbus-python의 메서드 timeout=과 introspect=False만으로는 연결·인증·name owner 조회까지 제한되지 않는다(`get_object()`는 기본으로 introspect하며 25초 기본 timeout을 쓴다). registry lock 아래에서는 `session._a11y_dbus_send`처럼 전체 subprocess를 wall-clock deadline으로 감싸거나(`dbus-send --reply-timeout`, `_A11Y_CALL_TIMEOUT_S`), 연결·인증·조회·introspection·호출 모두에 동일한 전체 deadline이 실제 적용됨을 입증한 경로만 허용한다. 개별 호출 timeout만 있는 경로(예: `core._DBUS_CALL_TIMEOUT`, `docs/design/dbus-call-call-sites.md`)는 허용 형태가 아니다.
  - 왜: #93(P1)에서 lock을 쥔 채 서버 종료가 25초 넘게 멈췄고, 그 lock 유지는 haechibot이 직전 리뷰에서 권고한 수정이었다.
  - 확인: 새 D-Bus 호출(`get_object(`, `BusConnection(`, `SessionBus(`, `dbus.Interface(` 등)의 lock 보유자와 연결부터 반환까지의 deadline을 추적한다. probe는 dbus-python과 `dbus-daemon`만 넣은 가벼운 scratch 컨테이너(PRR-57) 안의 실제 dbus-python/DBusConnection과 응답을 지연·누락하는 D-Bus 서비스로 한다. 연결·이름 조회·Introspect·메서드 호출을 각각 막아 전체 종료 제한을 확인한다. Python setter/BusConnection fake만으로 setup-timeout 후보를 반박하지 않는다. E2E 이미지가 있어야 하거나 실행할 수 없으면 PRR-50의 argument+challenger를 쓴다.

### 보안 정책과 upstream 의미

- **KM-S1 배포판 confinement를 피하는 기본 경로는 maintainer 결정이다.** SELinux·AppArmor·sandbox가 거부한 서비스를 다른 경로로 직접 띄우는 변경(예: D-Bus activation 밖에서 `at-spi-bus-launcher` 실행)은 PRR-47에 해당한다. 명시적 opt-in(flag·env)이나 upstream 정책 수정이 아니면 APPROVE하지 않고, 결함이 아닌 결정 항목으로 `open_items`에 넣어 event `COMMENT`로 maintainer 결정을 요청한다(`isac-decision-brief` 형식).
  - 왜: #95는 maintainer가 이 이유로 머지를 보류했는데(issuecomment-6105195627), haechibot은 그보다 앞서 APPROVE를 냈다.
  - 확인: 거부·실패 시 대체 실행 경로(fallback)가 생겼는지 diff에서 찾는다.
- **KM-S2 D-Bus `Exec=` 파싱은 upstream 의미와 같아야 한다.** D-Bus `.service`나 `.desktop`의 `Exec=`를 실행하는 대체 경로는 D-Bus `_dbus_shell_parse_argv`와 같은 quoting·escape 규칙으로 인자를 나눠야 한다. bash word splitting(`$launcher &`)은 안 된다.
  - 왜: 다른 규칙으로 나누면 공백·따옴표가 든 경로에서 다른 프로그램이나 인자가 실행된다.
  - 확인: 공백이 든 quoted 경로와 `--label="two words"`가 든 `Exec=`로 probe를 돌린다(§2.2 scratch 컨테이너 안에서).

### PR 제목과 커밋 subject

- **KM-C1 main 커밋 제목이 될 텍스트는 Conventional Commits 형식이다.** 형식은 `type(scope): summary`다(예: `feat(window): add exact window geometry control (#97)`). PR 제목은 항상 본다. PR에 non-merge 커밋이 하나뿐이면 그 커밋 subject도 본다. 어느 쪽이든 어기면 고친 제목·subject를 담은 finding을 `ReviewResult.body`에 적는다. maintainer가 달리 정했다고 밝힌 경우는 예외다. 리뷰어는 PR이나 커밋을 고치지 않는다(PRR-03). 판단은 리뷰한 head 시점의 제목과 커밋 기준이다.
  - 왜: `squash_merge_commit_title=COMMIT_OR_PR_TITLE`이라 커밋이 하나인 PR은 그 subject가 main 커밋 제목이 되고, Semantic PR check도 그때는 그 단일 non-merge 커밋을 검사한다.
  - 확인: `gh pr view <N> --repo isac322/kwin-mcp --json title,headRefOid`로 제목과 head가 `ReviewResult.head_sha`와 같은지 보고, `gh api repos/isac322/kwin-mcp/pulls/<N>/commits --paginate --jq '.[] | select((.parents | length) < 2) | .commit.message | split("\n")[0]'`로 non-merge 커밋 subject를 얻는다(하나뿐일 때만 적용). 둘 다 `^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\([^)]+\))?!?: .+`와 대조한다.
