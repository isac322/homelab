#!/usr/bin/env python3
"""Issue Agent publisher sidecar.

The only component that pushes to GitHub. It runs next to the runner (same
pod, separate container), holds the contents:write installation token, and is
called only by the bridge (bearer token the agent container cannot read).

  GET  /healthz
  POST /checkout {repo}                        -> {path, created, default_branch}
  POST /resolve  {repo, branch}                -> {sha}
  POST /push     {repo, branch, expected_sha}  -> {sha}
  POST /cleanup  {repo, worktree, branch, codex_session_ids} -> {removed}
  POST /janitor/prune-request {lease_until}   -> {requested_at, lease_until}
  GET  /janitor/status                        -> the janitor's status JSON

/resolve reports the commit the checkout's branch points at; /push pushes that
branch only while it still points at expected_sha.

Git never runs with an agent-controlled checkout as its working directory or
git dir: commits are fetched *from* the checkout by path into a private bare
mirror, and pushed from that mirror. The GitHub token is passed only through
`git -c http.extraHeader=...` on the command line; it is never written to any
config file and never logged. /cleanup runs no git at all: it removes a
worktree, its branch ref and Codex rollouts with plain file operations. Entries
a Docker container left owned by another uid fail it with ``foreign_owner``
(409, retryable): the dockerd sidecar's janitor (dockerd-janitor) chowns them
back to the agent uid. /janitor/prune-request asks that janitor to prune
unused Docker data within the bridge's maintenance lease (no dispatch until
lease_until); /janitor/status returns the janitor's last report (Docker usage,
last prune and the lease it served). Every route but /healthz needs the token.

/checkout also marks the checkout and its worktrees untrusted for Codex
(codex-untrust) on every call, so a session never loads the repository's own
.codex/ layer.
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
import time
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
UNTRUST = "/opt/issue-agent/bin/codex-untrust"
UNTRUST_TIMEOUT = 60

REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
BRANCH_RE = re.compile(r"^hapi-issue-[0-9]+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
WORKTREE_RE = re.compile(r"^(issue|review-pr)-[0-9]+(-[0-9a-f]{4})?$")
CLEANUP_BRANCH_RE = re.compile(r"^hapi-(issue|review-pr)-[0-9]+(-[0-9a-f]{4})?$")
CODEX_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
MAX_CODEX_IDS = 50
PACKED_REF_RE = re.compile(r"^[0-9a-f]{40,64} (refs/\S+)$")
# Shared with the dockerd sidecar, which mounts the same checkouts directory at
# the same path (runner/dockerd-janitor.sh reads the request and writes the
# status there, through runner/chown-sweep).
JANITOR_DIR = ".issue-agent-janitor"
PRUNE_REQUEST = "prune-request"
JANITOR_STATUS = "status"
MAX_JANITOR_STATUS_BYTES = 4096
JANITOR_RESULTS = ("ok", "error")
# Each pass of rmtree_agent unblocks at least one directory; the pre-pass in
# restore_dir_modes normally leaves nothing for later passes.
MAX_RMTREE_PASSES = 100

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
            "X-GitHub-Api-Version": "2026-03-10",
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


def untrust_checkout(path: str) -> None:
    """Mark the checkout and its HAPI worktrees untrusted in CODEX_HOME before any session starts there.

    Codex auto-trusts an unlisted repository root at thread start and then
    loads the repository's own .codex/ layer; an explicit untrusted entry
    prevents both. Fails the request rather than spawn into a trusted root.
    """
    try:
        result = subprocess.run(
            [UNTRUST, path],
            env={"PATH": git_env()["PATH"], "CODEX_HOME": CODEX_HOME, "LANG": "C.UTF-8"},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=UNTRUST_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise PublisherError(HTTPStatus.GATEWAY_TIMEOUT, "untrust_timeout", f"codex-untrust exceeded {UNTRUST_TIMEOUT}s") from None
    if result.returncode != 0:
        raise PublisherError(HTTPStatus.INTERNAL_SERVER_ERROR, "untrust_failed", (result.stderr or "").strip()[-2000:])


def do_checkout(repo: str) -> dict:
    token = read_secret(PUSH_TOKEN_FILE, "push token")
    info = github_repo(repo, token)
    default_branch = info.get("default_branch")
    if not isinstance(default_branch, str) or not default_branch:
        raise PublisherError(HTTPStatus.BAD_GATEWAY, "github_error", "repository has no default_branch")
    path = checkout_path(repo)
    created = clone_checkout(repo, path, token)
    # Every call, not only the first clone: the bridge checks out before each
    # spawn, and the bootstrap's reinstalled config dropped earlier entries.
    untrust_checkout(path)
    return {"path": path, "created": created, "default_branch": default_branch}


def clone_checkout(repo: str, path: str, token: str) -> bool:
    """Clone ``repo`` into ``path`` unless it exists; True when this call cloned it."""
    if os.path.lexists(path):
        return False

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
            return False
        os.rename(target, path)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    log.info("cloned %s into %s", repo, path)
    return True


def fetch_branch(repo: str, branch: str) -> str:
    """Commit ``branch`` points at in the checkout, fetched into the private mirror (no token needed)."""
    path = checkout_path(repo)
    if not os.path.isdir(os.path.join(path, ".git")):
        raise PublisherError(HTTPStatus.NOT_FOUND, "checkout_missing", f"no checkout for {repo}")
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
    return sha


def do_resolve(repo: str, branch: str) -> dict:
    return {"sha": fetch_branch(repo, branch)}


def do_push(repo: str, branch: str, expected_sha: str) -> dict:
    token = read_secret(PUSH_TOKEN_FILE, "push token")
    sha = fetch_branch(repo, branch)
    # The caller resolved the branch first; refuse if it moved since.
    if sha != expected_sha:
        raise PublisherError(HTTPStatus.CONFLICT, "sha_mismatch", f"{branch} is at {sha}, expected {expected_sha}")

    result = run_git(
        [
            "--git-dir", mirror_path(repo),
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
    """Admin dir named by the worktree's ``.git`` file (``gitdir: <path>``).

    None when ``.git`` is gone, or is a real directory: the worktree is then a
    standalone clone whose repository is removed together with it. Any other
    failure to inspect ``.git`` (EACCES on the worktree root) raises: treating
    it as absent would leave the admin dir behind.
    """
    dot_git = os.path.join(worktree, ".git")
    try:
        st = os.lstat(dot_git)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(st.st_mode):
        raise PublisherError(HTTPStatus.CONFLICT, "unsafe_path", f"{dot_git} is a symlink")
    if stat.S_ISDIR(st.st_mode):
        return None
    if not stat.S_ISREG(st.st_mode):
        raise PublisherError(HTTPStatus.CONFLICT, "unsafe_path", f"{dot_git} is not a regular file")
    with open(dot_git, encoding="utf-8", errors="replace") as handle:
        text = handle.read(4096).strip()
    if not text.startswith("gitdir:"):
        raise PublisherError(HTTPStatus.CONFLICT, "unsafe_path", f"{dot_git} has no gitdir line")
    return os.path.join(worktree, text.removeprefix("gitdir:").strip())


def foreign_owner(path: str, uid: int) -> PublisherError:
    return PublisherError(HTTPStatus.CONFLICT, "foreign_owner",
                          f"{path} is owned by uid {uid}; the dockerd janitor chowns it back")


def unblock_dir(path: str) -> bool:
    """Give an agent-owned directory u+rwx; True when its mode changed.

    A directory owned by another uid (a Docker container wrote it as root)
    raises ``foreign_owner``: only the dockerd janitor can chown it back.
    """
    st = os.lstat(path)
    if not stat.S_ISDIR(st.st_mode):
        return False
    if st.st_uid != os.getuid():
        raise foreign_owner(path, st.st_uid)
    if st.st_mode & stat.S_IRWXU == stat.S_IRWXU:
        return False
    os.chmod(path, stat.S_IMODE(st.st_mode) | stat.S_IRWXU)
    return True


def restore_dir_modes(root: str) -> None:
    """Top-down u+rwx on agent-owned directories (Go module caches, read-only test fixtures) before removal."""
    uid = os.getuid()

    def fix(path: str) -> None:
        st = os.lstat(path)
        if stat.S_ISDIR(st.st_mode) and st.st_uid == uid and st.st_mode & stat.S_IRWXU != stat.S_IRWXU:
            os.chmod(path, stat.S_IMODE(st.st_mode) | stat.S_IRWXU)

    fix(root)
    # Unreadable or foreign directories are skipped here; rmtree_agent reports them.
    for dirpath, dirnames, _ in os.walk(root, onerror=lambda _exc: None):
        for name in dirnames:
            try:
                fix(os.path.join(dirpath, name))
            except OSError:
                pass


class _Unblocked(Exception):
    """A directory blocking rmtree got u+rwx; run the removal again."""


def rmtree_agent(root: str) -> None:
    """``shutil.rmtree`` of an already confined ``root`` that also removes agent-owned read-only trees.

    On EACCES/EPERM the blocking directory (the one rmtree could not list, or
    the parent of the entry it could not unlink) gets u+rwx when the agent uid
    owns it and the removal is retried; entries owned by another uid raise
    ``foreign_owner``. Symlinks are never followed (rmtree's own guarantee).
    """
    restore_dir_modes(root)

    def onexc(func, failed: str, exc: BaseException) -> None:
        if not isinstance(exc, PermissionError):
            raise exc
        blocker = failed if func in (os.open, os.scandir) else os.path.dirname(failed)
        if (blocker == root or inside(blocker, root)) and unblock_dir(blocker):
            raise _Unblocked
        try:
            owner = os.lstat(failed).st_uid
        except OSError:
            raise exc from None
        if owner != os.getuid():
            raise foreign_owner(failed, owner)
        raise exc

    for _ in range(MAX_RMTREE_PASSES):
        try:
            shutil.rmtree(root, onexc=onexc)
            return
        except _Unblocked:
            continue
    raise PublisherError(HTTPStatus.INTERNAL_SERVER_ERROR, "cleanup_failed",
                         f"{root}: still blocked after {MAX_RMTREE_PASSES} permission fixes")


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
    # The worktree root may be agent-chmodded (e.g. 000): give it u+rwx (or
    # raise foreign_owner) before reading its .git file.
    unblock_dir(path)
    admin = worktree_admin_dir(path)
    if admin is not None and os.path.lexists(admin):
        admin_root = confined_root(os.path.join(base, ".git", "worktrees"))
        real_admin = os.path.realpath(admin)
        if os.path.islink(admin) or not os.path.isdir(real_admin) or not inside(real_admin, admin_root):
            raise PublisherError(HTTPStatus.CONFLICT, "unsafe_path", f"{admin} is not a worktree admin directory")
        # Admin dir first: a worktree left without it is still found and removed on retry.
        rmtree_agent(real_admin)
        removed.append(real_admin)
    real_path = os.path.realpath(path)
    rmtree_agent(real_path)
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


def open_janitor_dir(*, create: bool) -> int:
    """O_NOFOLLOW fd of <checkouts>/.issue-agent-janitor (agent-writable, so never a pathname)."""
    nofollow_dir = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    checkouts_fd = os.open(CHECKOUTS, nofollow_dir)
    try:
        if create:
            try:
                os.mkdir(JANITOR_DIR, 0o700, dir_fd=checkouts_fd)
            except FileExistsError:
                pass
        return os.open(JANITOR_DIR, nofollow_dir, dir_fd=checkouts_fd)
    finally:
        os.close(checkouts_fd)


def do_prune_request(lease_until: int) -> dict:
    """Atomically (re)write the janitor's prune request: ``{"requested_at", "lease_until"}``.

    The janitor prunes only while enough of the lease is left. The checkouts
    directory is agent-writable, so every step goes through O_NOFOLLOW
    directory fds: a planted symlink cannot redirect the write.
    """
    requested_at = int(time.time())
    request = {"requested_at": requested_at, "lease_until": lease_until}
    payload = json.dumps(request).encode()
    try:
        dir_fd = open_janitor_dir(create=True)
    except OSError as exc:
        raise PublisherError(HTTPStatus.CONFLICT, "unsafe_path",
                             f"{os.path.join(CHECKOUTS, JANITOR_DIR)}: {exc.strerror or exc}") from None
    tmp = f".{PRUNE_REQUEST}.{os.getpid()}.{threading.get_ident()}"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dir_fd)
        try:
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, PRUNE_REQUEST, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    except OSError as exc:
        try:
            os.unlink(tmp, dir_fd=dir_fd)
        except OSError:
            pass
        raise PublisherError(HTTPStatus.INTERNAL_SERVER_ERROR, "prune_request_failed",
                             f"{exc.filename or PRUNE_REQUEST}: {exc.strerror or exc}") from None
    finally:
        os.close(dir_fd)
    log.info("janitor prune requested at %d, lease until %d", requested_at, lease_until)
    return request


def _is_int(value, *, nullable: bool = False, low: int = 1, high: int | None = None) -> bool:
    if value is None:
        return nullable
    return (isinstance(value, int) and not isinstance(value, bool) and value >= low
            and (high is None or value <= high))


def read_janitor_status() -> dict:
    """The janitor's status file, validated; ``no_status`` (404) if missing, linked or malformed."""
    def no_status(detail: str) -> PublisherError:
        return PublisherError(HTTPStatus.NOT_FOUND, "no_status", detail)

    try:
        dir_fd = open_janitor_dir(create=False)
    except OSError as exc:
        raise no_status(f"{JANITOR_DIR}: {exc.strerror or exc}") from None
    try:
        fd = os.open(JANITOR_STATUS, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    except OSError as exc:
        raise no_status(f"{JANITOR_STATUS}: {exc.strerror or exc}") from None
    finally:
        os.close(dir_fd)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise no_status(f"{JANITOR_STATUS} is not a regular file")
        raw = os.read(fd, MAX_JANITOR_STATUS_BYTES + 1)
    except OSError as exc:
        raise no_status(f"{JANITOR_STATUS}: {exc.strerror or exc}") from None
    finally:
        os.close(fd)
    if len(raw) > MAX_JANITOR_STATUS_BYTES:
        raise no_status(f"{JANITOR_STATUS} is too large")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise no_status(f"{JANITOR_STATUS} is not valid JSON") from None
    if not (isinstance(data, dict)
            and _is_int(data.get("checked_at"))
            and _is_int(data.get("docker_used_pct"), low=0, high=100)
            and _is_int(data.get("last_prune_at"), nullable=True)
            and _is_int(data.get("last_prune_lease"), nullable=True)
            and (data.get("last_prune_result") is None or data.get("last_prune_result") in JANITOR_RESULTS)):
        raise no_status(f"{JANITOR_STATUS} has an unexpected shape")
    return {key: data.get(key) for key in
            ("checked_at", "docker_used_pct", "last_prune_at", "last_prune_lease", "last_prune_result")}


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
        try:
            if self.path == "/healthz":
                self.reply(HTTPStatus.OK, {"ok": True})
                return
            self.authorize()
            if self.path == "/janitor/status":
                self.reply(HTTPStatus.OK, read_janitor_status())
            else:
                raise PublisherError(HTTPStatus.NOT_FOUND, "not_found", self.path)
        except PublisherError as exc:
            log.warning("%s failed: %s %s", self.path, exc.error, exc.detail)
            self.error(exc)
        except Exception as exc:  # pragma: no cover - last-resort JSON error
            log.exception("%s crashed", self.path)
            self.error(PublisherError(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", type(exc).__name__))

    def authorize(self) -> None:
        expected = read_secret(AUTH_TOKEN_FILE, "publisher token")
        header = self.headers.get("Authorization", "")
        scheme, _, supplied = header.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(supplied.strip().encode(), expected.encode()):
            raise PublisherError(HTTPStatus.UNAUTHORIZED, "unauthorized", "missing or invalid bearer token")

    def body(self, fields: dict[str, re.Pattern], *, nullable: tuple[str, ...] = (),
             lists: dict[str, re.Pattern] | None = None, ints: tuple[str, ...] = ()) -> dict:
        """Validated JSON body: ``fields`` are strings (None allowed for ``nullable``), ``lists`` string
        arrays, ``ints`` required positive integers."""
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
        unknown = sorted(set(data) - set(fields) - set(lists) - set(ints))
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
        for name in ints:
            if not _is_int(data.get(name)):
                raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", f"invalid {name}")
            values[name] = data[name]
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
            elif self.path == "/resolve":
                args = self.body({"repo": REPO_RE, "branch": BRANCH_RE})
                with repo_lock(args["repo"]):
                    self.reply(HTTPStatus.OK, do_resolve(args["repo"], args["branch"]))
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
            elif self.path == "/janitor/prune-request":
                args = self.body({}, ints=("lease_until",))
                self.reply(HTTPStatus.OK, do_prune_request(args["lease_until"]))
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
