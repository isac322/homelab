#!/usr/bin/env python3
"""Issue Agent publisher sidecar.

The only component that pushes to GitHub. It runs next to the runner (same
pod, separate container), holds the contents:write installation token, and is
called only by the bridge (bearer token the agent container cannot read).

  GET  /healthz
  POST /checkout {repo}                        -> {path, created, default_branch}
  POST /push     {repo, branch, expected_sha}  -> {sha}
  POST /cleanup  {repo, worktree, branch, codex_session_ids} -> {removed}

Git never runs with an agent-controlled checkout as its working directory or
git dir: commits are fetched *from* the checkout by path into a private bare
mirror, and pushed from that mirror. The GitHub token is passed only through
`git -c http.extraHeader=...` on the command line; it is never written to any
config file and never logged. /cleanup runs no git at all: it removes a
worktree, its branch ref and Codex rollouts with plain file operations.
"""

from __future__ import annotations

import base64
import glob
import hmac
import json
import logging
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PUBLISHER_PORT", "8090"))
AUTH_TOKEN_FILE = os.environ.get("PUBLISHER_TOKEN_FILE", "/run/issue-agent/publisher/token")
PUSH_TOKEN_FILE = os.environ.get("GITHUB_PUSH_TOKEN_FILE", "/run/issue-agent/push/token")
CHECKOUTS = os.environ.get("ISSUE_AGENT_CHECKOUTS", "/home/agent/checkouts")
CODEX_HOME = os.environ.get("CODEX_HOME", "/home/agent/.codex")
STATE_DIR = os.environ.get("PUBLISHER_STATE_DIR", "/var/lib/issue-agent-publisher")
GITHUB_API = "https://api.github.com"
MAX_BODY = 16 * 1024
CLONE_TIMEOUT = 1800
GIT_TIMEOUT = 600

REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
BRANCH_RE = re.compile(r"^hapi-issue-[0-9]+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
WORKTREE_RE = re.compile(r"^(issue|review-pr)-[0-9]+(-[0-9a-f]{4})?$")
CLEANUP_BRANCH_RE = re.compile(r"^hapi-(issue|review-pr)-[0-9]+(-[0-9a-f]{4})?$")
CODEX_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
MAX_CODEX_IDS = 50
PACKED_REF_RE = re.compile(r"^[0-9a-f]{40,64} (refs/\S+)$")

log = logging.getLogger("publisher")

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


class PublisherError(Exception):
    def __init__(self, status: HTTPStatus, error: str, detail: str = ""):
        super().__init__(error)
        self.status = status
        self.error = error
        self.detail = detail


def repo_lock(repo: str) -> threading.Lock:
    key = repo.lower()
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def read_secret(path: str, what: str) -> str:
    try:
        with open(path, encoding="utf-8") as handle:
            value = handle.read().strip()
    except OSError as exc:
        raise PublisherError(HTTPStatus.SERVICE_UNAVAILABLE, "credential_unavailable", f"{what}: {exc.strerror}") from None
    if not value:
        raise PublisherError(HTTPStatus.SERVICE_UNAVAILABLE, "credential_unavailable", f"{what} is empty")
    return value


def git_env() -> dict[str, str]:
    # Built from scratch: nothing from the image environment (GIT_CONFIG_SYSTEM,
    # GH_CONFIG_DIR, credential helpers) may influence publisher git runs.
    return {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": STATE_DIR,
        "LANG": "C",
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "false",
        "SSH_ASKPASS": "false",
    }


def auth_header_args(token: str) -> list[str]:
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return ["-c", f"http.extraHeader=Authorization: Basic {basic}"]


def scrub(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
            text = text.replace(base64.b64encode(f"x-access-token:{secret}".encode()).decode(), "***")
    return text.strip()[-2000:]


def run_git(args: list[str], *, token: str | None = None, timeout: int = GIT_TIMEOUT) -> subprocess.CompletedProcess:
    cmd = ["git", "-c", "core.hooksPath=/dev/null", "-c", "credential.helper="]
    if token is not None:
        cmd += auth_header_args(token)
    cmd += args
    try:
        result = subprocess.run(
            cmd,
            cwd=STATE_DIR,
            env=git_env(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise PublisherError(HTTPStatus.GATEWAY_TIMEOUT, "git_timeout", f"git {args[0]} exceeded {timeout}s") from None
    result.stderr = scrub(result.stderr or "", [token or ""])
    result.stdout = scrub(result.stdout or "", [token or ""])
    return result


def github_repo(repo: str, token: str) -> dict:
    request = urllib.request.Request(
        f"{GITHUB_API}/repos/{repo}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "issue-agent-publisher",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 404):
            raise PublisherError(HTTPStatus.NOT_FOUND, "repo_not_found", f"GitHub returned {exc.code} for {repo}") from None
        raise PublisherError(HTTPStatus.BAD_GATEWAY, "github_error", f"GitHub returned {exc.code} for {repo}") from None
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise PublisherError(HTTPStatus.BAD_GATEWAY, "github_unreachable", str(getattr(exc, "reason", exc))) from None


def checkout_path(repo: str) -> str:
    return os.path.join(CHECKOUTS, repo)


def mirror_path(repo: str) -> str:
    return os.path.join(STATE_DIR, "mirrors", repo + ".git")


def ensure_mirror(repo: str) -> str:
    mirror = mirror_path(repo)
    if not os.path.isfile(os.path.join(mirror, "HEAD")):
        os.makedirs(os.path.dirname(mirror), mode=0o700, exist_ok=True)
        shutil.rmtree(mirror, ignore_errors=True)
        result = run_git(["init", "--quiet", "--bare", mirror])
        if result.returncode != 0:
            raise PublisherError(HTTPStatus.INTERNAL_SERVER_ERROR, "mirror_init_failed", result.stderr)
    return mirror


def do_checkout(repo: str) -> dict:
    token = read_secret(PUSH_TOKEN_FILE, "push token")
    info = github_repo(repo, token)
    default_branch = info.get("default_branch")
    if not isinstance(default_branch, str) or not default_branch:
        raise PublisherError(HTTPStatus.BAD_GATEWAY, "github_error", "repository has no default_branch")
    path = checkout_path(repo)
    if os.path.lexists(path):
        return {"path": path, "created": False, "default_branch": default_branch}

    owner_dir = os.path.dirname(path)
    os.makedirs(owner_dir, mode=0o700, exist_ok=True)
    # Dot-prefixed so neither the runner bootstrap nor HAPI treats a partial
    # clone as a repository; the rename publishes it atomically.
    staging = tempfile.mkdtemp(prefix=f".publisher-clone-{os.path.basename(path)}-", dir=owner_dir)
    target = os.path.join(staging, "repo")
    try:
        result = run_git(
            ["clone", "--quiet", "--", f"https://github.com/{repo}.git", target],
            token=token,
            timeout=CLONE_TIMEOUT,
        )
        if result.returncode != 0:
            raise PublisherError(HTTPStatus.BAD_GATEWAY, "clone_failed", result.stderr)
        if os.path.lexists(path):
            return {"path": path, "created": False, "default_branch": default_branch}
        os.rename(target, path)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    log.info("cloned %s into %s", repo, path)
    return {"path": path, "created": True, "default_branch": default_branch}


def do_push(repo: str, branch: str, expected_sha: str) -> dict:
    path = checkout_path(repo)
    if not os.path.isdir(os.path.join(path, ".git")):
        raise PublisherError(HTTPStatus.NOT_FOUND, "checkout_missing", f"no checkout for {repo}")
    token = read_secret(PUSH_TOKEN_FILE, "push token")
    mirror = ensure_mirror(repo)
    local_ref = f"refs/issue-agent/{branch}"

    # Fetch by path from the checkout (the agent's worktree branches live in
    # the base checkout's refs). No token: the local fetch needs none.
    result = run_git(
        [
            "--git-dir", mirror,
            "-c", "protocol.file.allow=always",
            "fetch", "--quiet", "--no-tags", "--no-write-fetch-head", "--", path,
            f"+refs/heads/{branch}:{local_ref}",
            "+refs/remotes/origin/*:refs/remotes/origin/*",
        ]
    )
    if result.returncode != 0:
        if "couldn't find remote ref" in result.stderr:
            raise PublisherError(HTTPStatus.NOT_FOUND, "branch_missing", f"{branch} does not exist in the checkout")
        raise PublisherError(HTTPStatus.INTERNAL_SERVER_ERROR, "local_fetch_failed", result.stderr)

    result = run_git(["--git-dir", mirror, "rev-parse", "--verify", "--quiet", f"{local_ref}^{{commit}}"])
    sha = result.stdout.strip()
    if result.returncode != 0 or not SHA_RE.match(sha):
        raise PublisherError(HTTPStatus.INTERNAL_SERVER_ERROR, "local_fetch_failed", f"cannot resolve {branch}")
    if sha != expected_sha:
        raise PublisherError(HTTPStatus.CONFLICT, "sha_mismatch", f"{branch} is at {sha}, expected {expected_sha}")

    result = run_git(
        [
            "--git-dir", mirror,
            "push", "--quiet", "--porcelain", "--no-verify", "--",
            f"https://github.com/{repo}.git",
            f"{sha}:refs/heads/{branch}",
        ],
        token=token,
    )
    if result.returncode != 0:
        output = f"{result.stdout}\n{result.stderr}"
        if any(marker in output for marker in ("non-fast-forward", "fetch first", "[rejected]", "stale info")):
            raise PublisherError(HTTPStatus.CONFLICT, "non_fast_forward", result.stderr or result.stdout)
        raise PublisherError(HTTPStatus.BAD_GATEWAY, "push_failed", result.stderr or result.stdout)
    log.info("pushed %s %s -> %s", repo, branch, sha)
    return {"sha": sha}


def inside(path: str, root: str) -> bool:
    """``path`` is strictly below ``root`` (both already resolved)."""
    return path != root and os.path.commonpath([path, root]) == root


def confined_root(path: str) -> str:
    """Resolved ``path``, refused unless it stays inside the checkouts root (a planted symlink cannot redirect it)."""
    root = os.path.realpath(path)
    if not inside(root, os.path.realpath(CHECKOUTS)):
        raise PublisherError(HTTPStatus.CONFLICT, "unsafe_path", f"{path} resolves outside the checkouts root")
    return root


def worktree_admin_dir(worktree: str) -> str | None:
    """Admin dir named by the worktree's ``.git`` file (``gitdir: <path>``), None when the file is gone."""
    dot_git = os.path.join(worktree, ".git")
    if not os.path.lexists(dot_git):
        return None
    if os.path.islink(dot_git) or not os.path.isfile(dot_git):
        raise PublisherError(HTTPStatus.CONFLICT, "unsafe_path", f"{dot_git} is not a regular file")
    with open(dot_git, encoding="utf-8", errors="replace") as handle:
        text = handle.read(4096).strip()
    if not text.startswith("gitdir:"):
        raise PublisherError(HTTPStatus.CONFLICT, "unsafe_path", f"{dot_git} has no gitdir line")
    return os.path.join(worktree, text.removeprefix("gitdir:").strip())


def remove_worktree(repo: str, name: str) -> list[str]:
    base = checkout_path(repo)
    worktrees_dir = base + "-worktrees"
    path = os.path.join(worktrees_dir, name)
    if not os.path.lexists(path):
        return []
    worktrees_root = confined_root(worktrees_dir)
    if os.path.islink(path) or not os.path.isdir(path) or not inside(os.path.realpath(path), worktrees_root):
        raise PublisherError(HTTPStatus.CONFLICT, "unsafe_path", f"{path} is not a worktree directory")
    removed = []
    admin = worktree_admin_dir(path)
    if admin is not None and os.path.lexists(admin):
        admin_root = confined_root(os.path.join(base, ".git", "worktrees"))
        real_admin = os.path.realpath(admin)
        if os.path.islink(admin) or not os.path.isdir(real_admin) or not inside(real_admin, admin_root):
            raise PublisherError(HTTPStatus.CONFLICT, "unsafe_path", f"{admin} is not a worktree admin directory")
        # Admin dir first: a worktree left without it is still found and removed on retry.
        shutil.rmtree(real_admin)
        removed.append(real_admin)
    real_path = os.path.realpath(path)
    shutil.rmtree(real_path)
    removed.append(real_path)
    return removed


def remove_branch(repo: str, branch: str) -> list[str]:
    """Drop ``refs/heads/<branch>`` (loose and packed) so HAPI can reuse the unsuffixed worktree name."""
    git_dir = os.path.join(checkout_path(repo), ".git")
    if not os.path.lexists(git_dir):
        return []
    git_root = confined_root(git_dir)
    removed = []
    loose = os.path.join(git_root, "refs", "heads", branch)
    if os.path.lexists(loose):
        if os.path.islink(loose) or not os.path.isfile(loose) or not inside(os.path.realpath(loose), git_root):
            raise PublisherError(HTTPStatus.CONFLICT, "unsafe_path", f"{loose} is not a regular file")
        os.remove(loose)
        removed.append(loose)
    packed = os.path.join(git_root, "packed-refs")
    if not os.path.lexists(packed):
        return removed
    if os.path.islink(packed) or not os.path.isfile(packed):
        raise PublisherError(HTTPStatus.CONFLICT, "unsafe_path", f"{packed} is not a regular file")
    with open(packed, encoding="utf-8", newline="") as handle:
        lines = handle.readlines()
    kept, dropped, peel = [], False, False
    for line in lines:
        if peel and line.startswith("^"):
            continue  # peeled target of the dropped (annotated) ref
        match = PACKED_REF_RE.match(line.rstrip("\r\n"))
        peel = bool(match) and match.group(1) == f"refs/heads/{branch}"
        if peel:
            dropped = True
        else:
            kept.append(line)
    if dropped:
        mode = stat.S_IMODE(os.stat(packed).st_mode)
        fd, tmp = tempfile.mkstemp(prefix=".packed-refs-", dir=git_root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.writelines(kept)
            os.chmod(tmp, mode)
            os.replace(tmp, packed)
        except BaseException:
            if os.path.lexists(tmp):
                os.remove(tmp)
            raise
        removed.append(f"{packed}:refs/heads/{branch}")
    return removed


def remove_codex_records(codex_ids: list[str]) -> list[str]:
    """Rollout files (live and archived) of the given Codex sessions, only as regular files under CODEX_HOME."""
    if not codex_ids or not os.path.isdir(CODEX_HOME):
        return []
    root = os.path.realpath(CODEX_HOME)
    removed = []
    for codex_id in codex_ids:
        patterns = (
            os.path.join(CODEX_HOME, "sessions", "*", "*", "*", f"rollout-*-{codex_id}.jsonl"),
            os.path.join(CODEX_HOME, "archived_sessions", f"rollout-*-{codex_id}.jsonl"),
        )
        for pattern in patterns:
            for path in sorted(glob.glob(pattern)):
                real = os.path.realpath(path)
                if os.path.islink(path) or not os.path.isfile(real) or not inside(real, root):
                    log.warning("cleanup skipped %s: not a regular file under %s", path, CODEX_HOME)
                    continue
                os.remove(real)
                removed.append(real)
    return removed


def do_cleanup(repo: str, worktree: str | None, branch: str | None, codex_ids: list[str]) -> dict:
    removed = []
    try:
        if worktree is not None:
            removed += remove_worktree(repo, worktree)
        if branch is not None:
            removed += remove_branch(repo, branch)
        removed += remove_codex_records(codex_ids)
    except OSError as exc:
        raise PublisherError(HTTPStatus.INTERNAL_SERVER_ERROR, "cleanup_failed",
                             f"{exc.filename or ''}: {exc.strerror or exc}") from None
    log.info("cleaned %s worktree=%s branch=%s codex=%d: removed %d",
             repo, worktree, branch, len(codex_ids), len(removed))
    return {"removed": removed}


class Handler(BaseHTTPRequestHandler):
    server_version = "issue-agent-publisher"
    sys_version = ""

    def log_message(self, fmt: str, *args) -> None:  # noqa: D401 - http.server hook
        log.info("%s %s", self.address_string(), fmt % args)

    def reply(self, status: HTTPStatus, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def error(self, exc: PublisherError) -> None:
        self.reply(exc.status, {"error": exc.error, "detail": exc.detail})

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            self.reply(HTTPStatus.OK, {"ok": True})
        else:
            self.error(PublisherError(HTTPStatus.NOT_FOUND, "not_found", self.path))

    def authorize(self) -> None:
        expected = read_secret(AUTH_TOKEN_FILE, "publisher token")
        header = self.headers.get("Authorization", "")
        scheme, _, supplied = header.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(supplied.strip().encode(), expected.encode()):
            raise PublisherError(HTTPStatus.UNAUTHORIZED, "unauthorized", "missing or invalid bearer token")

    def body(self, fields: dict[str, re.Pattern], *, nullable: tuple[str, ...] = (),
             lists: dict[str, re.Pattern] | None = None) -> dict:
        """Validated JSON body: ``fields`` are strings (None allowed for ``nullable``), ``lists`` string arrays."""
        lists = lists or {}
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            raise PublisherError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "invalid_request", "Content-Type must be application/json")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            raise PublisherError(HTTPStatus.LENGTH_REQUIRED, "invalid_request", "Content-Length required") from None
        if length < 0 or length > MAX_BODY:
            raise PublisherError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "invalid_request", "body too large")
        try:
            data = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError):
            raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "body is not valid JSON") from None
        if not isinstance(data, dict):
            raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "body must be a JSON object")
        unknown = sorted(set(data) - set(fields) - set(lists))
        if unknown:
            raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", f"unknown fields: {', '.join(unknown)}")
        values = {}
        for name, pattern in fields.items():
            value = data.get(name)
            if value is None and name in nullable:
                values[name] = None
                continue
            if not isinstance(value, str) or not pattern.fullmatch(value):
                raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", f"invalid {name}")
            values[name] = value
        for name, pattern in lists.items():
            value = data.get(name, [])
            if (not isinstance(value, list) or len(value) > MAX_CODEX_IDS
                    or not all(isinstance(item, str) and pattern.fullmatch(item) for item in value)):
                raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", f"invalid {name}")
            values[name] = list(dict.fromkeys(value))
        repo = values.get("repo")
        if repo is not None and any(part in (".", "..") or part.endswith(".git") for part in repo.split("/")):
            raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "invalid repo")
        return values

    def do_POST(self) -> None:  # noqa: N802
        try:
            self.authorize()
            if self.path == "/checkout":
                args = self.body({"repo": REPO_RE})
                with repo_lock(args["repo"]):
                    self.reply(HTTPStatus.OK, do_checkout(args["repo"]))
            elif self.path == "/push":
                args = self.body({"repo": REPO_RE, "branch": BRANCH_RE, "expected_sha": SHA_RE})
                with repo_lock(args["repo"]):
                    self.reply(HTTPStatus.OK, do_push(args["repo"], args["branch"], args["expected_sha"]))
            elif self.path == "/cleanup":
                args = self.body({"repo": REPO_RE, "worktree": WORKTREE_RE, "branch": CLEANUP_BRANCH_RE},
                                 nullable=("worktree", "branch"), lists={"codex_session_ids": CODEX_ID_RE})
                with repo_lock(args["repo"]):
                    self.reply(HTTPStatus.OK, do_cleanup(args["repo"], args["worktree"], args["branch"],
                                                         args["codex_session_ids"]))
            else:
                raise PublisherError(HTTPStatus.NOT_FOUND, "not_found", self.path)
        except PublisherError as exc:
            log.warning("%s failed: %s %s", self.path, exc.error, exc.detail)
            self.error(exc)
        except Exception as exc:  # pragma: no cover - last-resort JSON error
            log.exception("%s crashed", self.path)
            self.error(PublisherError(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", type(exc).__name__))


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(message)s")
    os.umask(0o077)
    os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.daemon_threads = True

    def stop(_signum, _frame):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    log.info("listening on :%d", PORT)
    server.serve_forever()


if __name__ == "__main__":
    main()
