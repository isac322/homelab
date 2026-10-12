# isac322/kwin-mcp 감사 맥락

저장소에 접근하는 모든 역할이 kwin-mcp PR을 다룰 때 먼저 읽는다(SKILL "파일" 표, agent-prompts COMMON). 공개 저장소의 런타임, probe 방법, 저장소 규칙만 적는다. 지난 결함이나 감사 결과는 적지 않는다. 경로와 줄 번호는 2026-10 초 head 기준이며, 판정할 때는 그 head에서 다시 확인한다(policy: pilot-kwin-20261012 T3).

## 대상 플랫폼

- KDE Plasma 6 Wayland용 MCP 서버다. 런타임은 Linux 전용이다: KWin(`kwin_wayland --virtual`, KWin scripting, ScreenShot2 D-Bus), AT-SPI2(`accessibility.py`), D-Bus(`dbus-python`, `dbus-run-session`), libei/EIS 입력(`input.py`), `/proc`, POSIX signal과 tty.
- 모듈: `src/kwin_mcp/core.py`(AutomationEngine), `server.py`(MCP tool 등록), `cli.py`(`kwin-mcp-cli` REPL·pipe 모드), `session.py`, `screenshot.py`, `accessibility.py`, `input.py`. CLI는 출하된 보조 진입점이다(rubric §2 절차 2).
- 의존성은 `pyproject.toml`의 범위(예: `mcp>=2.2.0,<3`)와 `uv.lock`의 잠긴 버전으로 정해진다. Python 3.12 이상이다.

## 오프라인 probe: e2e Docker 이미지

- 저장소의 `docker/e2e.Dockerfile`(Debian trixie snapshot)이 KWin, AT-SPI2, D-Bus, Xvfb와 설치된 `kwin-mcp`(`/opt/kwin-mcp-venv`)를 담은 이미지를 만든다. Fedora, openSUSE, Arch 변형(`docker/e2e-*.Dockerfile`)도 있다. 설명과 테스트 파일 목록은 `docker/README.md`, CI는 `.github/workflows/e2e.yml`이다.
- 이미지 빌드는 네트워크가 필요하므로 probe가 아니라 라운드 준비다. 오케스트레이터가 라운드 전에 `docker build --file docker/e2e.Dockerfile --tag kwin-mcp-e2e:<tag> .`로 만들고 tag와 출처 커밋을 `versions.json`의 notes에 적는다.
- head의 코드를 그 이미지에서 네트워크 없이 돌린다. scratch checkout을 읽기 전용으로 붙이고 `src`를 설치본보다 앞에 둔다:

  ```bash
  docker run --rm --network none \
    --volume "<scratch>/repo:/workspace:ro" --workdir /workspace \
    --env PYTHONPATH=/workspace/src \
    kwin-mcp-e2e:<tag> \
    /opt/kwin-mcp-venv/bin/python -m pytest -p no:cacheprovider tests/e2e/<file>.py -v
  ```

  entrypoint(`/app/docker/e2e-entrypoint.sh`)는 그대로 둔다. 테스트 대신 작은 스크립트를 돌려도 된다. 다른 head의 테스트를 쓸 때는(예: 수정 head의 회귀 테스트를 reviewed head의 `src`에) 어느 head의 `src`와 `tests`를 썼는지 근거에 적는다.
- 이미지는 `uv.lock`을 쓰지 않고 Python 의존성을 빌드 시점에 `pyproject.toml`의 범위 안에서 새로 고른다(예: `mcp`는 `>=2.2.0,<3`에서 고르고, 2026-10 초 head의 `uv.lock`은 2.2.0을 고정한다). 결함이 의존성 버전에 걸리면 이미지의 버전(`/artifacts/environment.json` 또는 `pip list`)을 head의 `uv.lock`과 비교한다. 다르면 잠긴 버전을 로컬 uv 캐시에서 scratch venv로 오프라인 설치해 돌리거나, 그 probe를 `code_path_only`로 적는다(rubric §1 probe 충실도).
- 컨테이너는 `/dev/dri` 없이 llvmpipe로 돌며, KWin virtual backend는 ScreenShot2 캡처를 돌려주지 않는다(`docker/README.md`). 스크린샷 성공 경로는 nested KWin/Xvfb fixture로만 확인된다.

## stub으로 보일 수 없는 것

macOS에서 돌린 probe, 또는 `gi`·`dbus`를 stub한 Linux probe는 `code_path_only`다. stub은 실제 시스템 서비스의 동작과 timing(D-Bus, AT-SPI, KWin, libei/EIS), `/proc`의 내용, signal·tty·pipe 동작, 기본 실행 환경을 보일 수 없다. 이런 것에 기대는 항목은 위 이미지에서 확인하기 전에는 `invalid`로 만들지 않는다.

## 문서 규칙 (`repo_rule`)

- `CLAUDE.md`의 docs-seo auto-trigger 표(2026-10 초 head에서 60–66줄)가 문서 동기화 규칙이다. `src/kwin_mcp/server.py`를 바꾸면 tool 수, README tool 표, CONTRIBUTING 구조, `integrations/*/skills/*/SKILL.md`의 tool 목록을 확인해야 하고, `src/kwin_mcp/*.py`를 바꾸면 구체적 숫자, CONTRIBUTING 파일 목록, SKILL.md의 capability 수를 확인해야 한다. `session.py`·`core.py`는 README 구조 설명, `pyproject.toml`·`CHANGELOG.md`·`README.md`는 positioning 동기화를 요구한다.
- tool 수와 테스트 목록이 여러 문서에 있다: `README.md`(tool 표와 아키텍처 다이어그램), `CONTRIBUTING.md`(구조와 테스트 목록), `docker/README.md`(테스트 파일 목록), `docs/ai-agent-integration.md`, `integrations/*/skills/*/SKILL.md`. tool이나 테스트 파일을 더하고 이 중 하나를 빠뜨리면 `repo_rule` 결함이다. 빠진 것 하나로 여러 문서가 낡았으면 결함 하나다(rubric §6 딸린 hunk).
- `CHANGELOG.md`는 Keep a Changelog 형식과 `[Unreleased]` 절을 요구한다. 모든 문서와 주석은 영어다.
