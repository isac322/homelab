#!/usr/bin/env python3
"""Issue Agent publisher sidecar.

The only component that pushes to GitHub. It runs next to the runner (same
pod, separate container), holds the contents:write installation token, and is
called only by the bridge (bearer token the agent container cannot read).

  GET  /healthz
  POST /checkout {repo}                        -> {path, created, default_branch}
  POST /resolve  {repo, branch}                -> {sha}
  POST /push     {repo, branch, expected_sha, stale_sha?} -> {sha}
  POST /cleanup  {repo, worktree, branch, codex_session_ids, hapi_session_ids?} -> {removed}
  POST /cleanup/caches {max_age_days?, dry_run?} -> {orphan_worktrees, global_caches}
  POST /worktree/restore {repo, worktree, branch} -> {restored, path, already} | {restored: false, reason}
  POST /visual-evidence {repo, worktree, pr_number, head_sha, base_sha, manifest_path, marker, body,
                         reuse_existing} -> {created, already_published, ref_url, commit_url, assets, asset_urls}
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
back to the agent uid. /worktree/restore re-creates a removed HAPI worktree on
its retained branch without running git there either: the branch is fetched
into the mirror, checked out from the mirror into a staging tree, and the
linked-worktree metadata is written as plain files, so unpushed commits are
kept and the branch never moves. /janitor/prune-request asks that janitor to prune
unused Docker data within the bridge's maintenance lease (no dispatch until
lease_until); /janitor/status returns the janitor's last report (Docker usage,
last prune and the lease it served). Every route but /healthz needs the token.

/checkout also marks the checkout and its worktrees untrusted for Codex
(codex-untrust) on every call, so a session never loads the repository's own
.codex/ layer.
"""

from __future__ import annotations

import base64
import fcntl
import glob
import hashlib
import hmac
import json
import logging
import os
import re
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PUBLISHER_PORT", "8090"))
AUTH_TOKEN_FILE = os.environ.get("PUBLISHER_TOKEN_FILE", "/run/issue-agent/publisher/token")
PUSH_TOKEN_FILE = os.environ.get("GITHUB_PUSH_TOKEN_FILE", "/run/issue-agent/push/token")
MAX_VISUAL_ARTIFACTS = 20
MAX_VISUAL_ARTIFACT_BYTES = 10 * 1024 * 1024
MAX_VISUAL_MANIFEST_BYTES = 256 * 1024
RUNNER_HOME = os.environ.get("RUNNER_HOME", "/home/agent")
CHECKOUTS = os.environ.get("ISSUE_AGENT_CHECKOUTS", "/home/agent/checkouts")
CODEX_HOME = os.environ.get("CODEX_HOME", "/home/agent/.codex")
HAPI_HOME = os.environ.get("HAPI_HOME", "/home/agent/.hapi")
RUNNER_TMP = os.environ.get("ISSUE_AGENT_RUNNER_TMP", "/tmp")
STATE_DIR = os.environ.get("PUBLISHER_STATE_DIR", "/var/lib/issue-agent-publisher")
GITHUB_API = "https://api.github.com"
MAX_BODY = 16 * 1024
CLONE_TIMEOUT = 1800
GIT_TIMEOUT = 600
PUSH_RETRY_DELAYS = (1.0, 2.0)
UNTRUST = "/opt/issue-agent/bin/codex-untrust"
UNTRUST_TIMEOUT = 60
CODEX_BIN = os.environ.get("CODEX_BIN", "codex")
CODEX_DELETE_TIMEOUT = 60
RUSTUP_BIN = os.environ.get("RUSTUP_BIN", "rustup")
NPM_BIN = os.environ.get("NPM_BIN", "npm")
GO_BIN = os.environ.get("GO_BIN", "/usr/local/go/bin/go")
HAPI_BIN = os.environ.get("HAPI_BIN", "/usr/local/bin/hapi")
CACHE_CMD_TIMEOUT = 120
DEFAULT_CACHE_MAX_AGE_DAYS = 14
HAPI_LOG_MAX_AGE_DAYS = 7
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
BRANCH_RE = re.compile(r"^hapi-issue-[0-9]+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
WORKTREE_RE = re.compile(r"^(issue|review-pr)-[0-9]+(-[0-9a-f]{4})?$")
CLEANUP_BRANCH_RE = re.compile(r"^hapi-(issue|review-pr)-[0-9]+(-[0-9a-f]{4})?$")
VISUAL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
VISUAL_MARKER_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")
VISUAL_MEDIA_TYPES = {
    "image/png", "image/jpeg", "image/gif", "image/webp",
    "video/mp4", "video/webm", "video/quicktime",
}
VISUAL_MARKER_LITERAL = "<!-- issue-agent:visual-evidence -->"
VISUAL_ARTIFACT_LINE_RE = re.compile(
    r"^Artifact: (?P<id>[A-Za-z0-9][A-Za-z0-9_.-]{0,63}) "
    r"(?P<sha256>[0-9a-f]{64}) (?P<blob>[0-9a-f]{40}) (?P<path>\S+)$"
)
VISUAL_ARTIFACT_ERROR_FIELDS = frozenset({"sha256", "bytes", "media_type", "source_sha"})
VISUAL_MANIFEST_PATH_RE = re.compile(r"^[^/\x00][^\x00]{0,1023}$")
CODEX_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
HAPI_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
MAX_CODEX_IDS = 50
PACKED_REF_RE = re.compile(r"^[0-9a-f]{40,64} (refs/\S+)$")
CONFIG_PROJECT_HEADER_RE = re.compile(r'^\s*\[\s*projects\s*\.\s*("(?:[^"\\]|\\.)*"|\'[^\']*\')\s*\]\s*(?:#.*)?$')
CONFIG_TABLE_RE = re.compile(r"^\s*\[")
ROLLOUT_FILE_RE = re.compile(r"^rollout-.*-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$")
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
    def __init__(self, status: HTTPStatus, error: str, detail: str = "",
                 artifact_error: dict[str, str | int] | None = None):
        super().__init__(error)
        self.status = status
        self.error = error
        self.detail = detail
        self.artifact_error = artifact_error


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


def run_git(args: list[str], *, token: str | None = None, timeout: int = GIT_TIMEOUT,
            extra_env: dict[str, str] | None = None, stdin_text: str | None = None) -> subprocess.CompletedProcess:
    cmd = ["git", "-c", "core.hooksPath=/dev/null", "-c", "credential.helper="]
    if token is not None:
        cmd += auth_header_args(token)
    cmd += args
    try:
        kwargs: dict[str, Any] = {
            "cwd": STATE_DIR,
            "env": git_env() | (extra_env or {}),
            "capture_output": True,
            "text": True,
            "timeout": timeout,
            "check": False,
        }
        if stdin_text is None:
            kwargs["stdin"] = subprocess.DEVNULL
        else:
            kwargs["input"] = stdin_text
        result = subprocess.run(cmd, **kwargs)
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


def do_push(repo: str, branch: str, expected_sha: str, stale_sha: str | None = None) -> dict:
    token = read_secret(PUSH_TOKEN_FILE, "push token")
    sha = fetch_branch(repo, branch)
    # The caller resolved the branch first; refuse if it moved since.
    if sha != expected_sha:
        raise PublisherError(HTTPStatus.CONFLICT, "sha_mismatch", f"{branch} is at {sha}, expected {expected_sha}")

    mirror = mirror_path(repo)

    def push(refspec: str, *, lease: str | None = None) -> None:
        push_args = [
            "--git-dir", mirror,
            "push", "--quiet", "--porcelain", "--no-verify",
        ]
        if lease is not None:
            push_args.append(f"--force-with-lease=refs/heads/{branch}:{lease}")
        push_args += [
            "--", f"https://github.com/{repo}.git",
            refspec,
        ]
        for attempt in range(len(PUSH_RETRY_DELAYS) + 1):
            result = run_git(push_args, token=token)
            output = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
            if result.returncode == 0:
                return
            if any(marker in output for marker in ("non-fast-forward", "fetch first", "[rejected]", "stale info", "cannot lock ref", "failed to update ref")):
                raise PublisherError(HTTPStatus.CONFLICT, "non_fast_forward", output or "non-fast-forward")
            if attempt < len(PUSH_RETRY_DELAYS):
                time.sleep(PUSH_RETRY_DELAYS[attempt])
                continue
            raise PublisherError(HTTPStatus.BAD_GATEWAY, "push_failed", output or "git push failed")

    if stale_sha is not None and stale_sha != expected_sha:
        result = run_git(["--git-dir", mirror, "merge-base", "--is-ancestor", stale_sha, expected_sha])
        if result.returncode != 0:
            raise PublisherError(
                HTTPStatus.CONFLICT,
                "non_fast_forward",
                f"{stale_sha} is not an ancestor of {expected_sha}",
            )
        push(f"{stale_sha}:refs/heads/{branch}", lease=expected_sha)
    push(f"{expected_sha}:refs/heads/{branch}")
    log.info("pushed %s %s -> %s", repo, branch, expected_sha)
    return {"sha": expected_sha}


def inside(path: str, root: str) -> bool:
    """``path`` is strictly below ``root`` (both already resolved)."""
    return path != root and os.path.commonpath([path, root]) == root


def confined_root(path: str) -> str:
    """Resolved ``path``, refused unless it stays inside the checkouts root (a planted symlink cannot redirect it)."""
    root = os.path.realpath(path)
    if not inside(root, os.path.realpath(CHECKOUTS)):
        raise PublisherError(HTTPStatus.CONFLICT, "unsafe_path", f"{path} resolves outside the checkouts root")
    return root
def visual_worktree_path(repo: str, name: str) -> str:
    if not WORKTREE_RE.fullmatch(name):
        raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "invalid worktree")
    root = confined_root(checkout_path(repo) + "-worktrees")
    path = os.path.realpath(os.path.join(root, name))
    if not inside(path, root) or not os.path.isdir(path):
        raise PublisherError(HTTPStatus.CONFLICT, "unsafe_path", "worktree is missing or outside checkout")
    try:
        if stat.S_ISLNK(os.lstat(os.path.join(root, name)).st_mode):
            raise PublisherError(HTTPStatus.CONFLICT, "unsafe_path", "worktree is a symlink")
    except FileNotFoundError:
        raise PublisherError(HTTPStatus.CONFLICT, "unsafe_path", "worktree is missing") from None
    return path
def visual_worktree_head(worktree: str) -> str:
    result = run_git(["-C", worktree, "rev-parse", "--verify", "HEAD"])
    head = result.stdout.strip()
    if result.returncode != 0 or not SHA_RE.fullmatch(head):
        raise PublisherError(HTTPStatus.CONFLICT, "worktree_head_unavailable", "cannot resolve worktree HEAD")
    return head



def visual_artifact_error(relpath: str, field: str, expected: Any, actual: Any) -> dict[str, str | int] | None:
    """Return only bounded machine-readable detail safe for the HTTP boundary."""
    if not isinstance(field, str) or field not in VISUAL_ARTIFACT_ERROR_FIELDS:
        return None
    if field in {"sha256", "source_sha"}:
        pattern = r"[0-9a-f]{64}" if field == "sha256" else r"[0-9a-f]{40}"
        if (not isinstance(expected, str) or not re.fullmatch(pattern, expected)
                or not isinstance(actual, str) or not re.fullmatch(pattern, actual)):
            return None
    elif field == "bytes":
        if (not isinstance(expected, int) or isinstance(expected, bool) or expected < 0
                or expected > MAX_VISUAL_ARTIFACT_BYTES
                or not isinstance(actual, int) or isinstance(actual, bool) or actual < 0
                or actual > MAX_VISUAL_ARTIFACT_BYTES):
            return None
    elif not isinstance(expected, str) or expected not in VISUAL_MEDIA_TYPES or actual != "magic":
        return None
    if (not isinstance(relpath, str) or not re.fullmatch(r"[A-Za-z0-9_. /-]{1,1024}", relpath)
            or relpath.startswith("/") or any(part in ("", ".", "..") for part in relpath.split("/"))):
        return None
    return {"relpath": relpath, "field": field, "expected": expected, "actual": actual}


def visual_artifact_mismatch(relpath: str, field: str, expected: Any, actual: Any,
                             detail: str) -> PublisherError:
    return PublisherError(HTTPStatus.BAD_REQUEST, "artifact_mismatch", detail,
                          visual_artifact_error(relpath, field, expected, actual))


def read_visual_manifest(root: str, manifest_path: str) -> list[dict[str, Any]]:
    """Read a bounded JSON list through no-follow directory FDs."""
    if (not isinstance(manifest_path, str) or not VISUAL_MANIFEST_PATH_RE.fullmatch(manifest_path)
            or "\\" in manifest_path):
        raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "invalid manifest_path")
    parts = manifest_path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "invalid manifest_path")
    flags = os.O_RDONLY | os.O_CLOEXEC
    directory_flags = flags | os.O_DIRECTORY | os.O_NOFOLLOW
    fd: int | None = None
    try:
        fd = os.open(root, directory_flags)
        for part in parts[:-1]:
            next_fd = os.open(part, directory_flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        file_fd = os.open(parts[-1], flags | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except FileNotFoundError:
        raise PublisherError(HTTPStatus.NOT_FOUND, "manifest_missing", manifest_path) from None
    except OSError:
        raise PublisherError(HTTPStatus.CONFLICT, "unsafe_path", "manifest is not a safe regular file") from None
    finally:
        if fd is not None:
            os.close(fd)
    try:
        st = os.fstat(file_fd)
        if not stat.S_ISREG(st.st_mode):
            raise PublisherError(HTTPStatus.CONFLICT, "unsafe_path", "manifest is not a regular file")
        if st.st_size > MAX_VISUAL_MANIFEST_BYTES:
            raise PublisherError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "invalid_request", "manifest is too large")
        chunks: list[bytes] = []
        size = 0
        while size <= MAX_VISUAL_MANIFEST_BYTES:
            chunk = os.read(file_fd, min(64 * 1024, MAX_VISUAL_MANIFEST_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        if size > MAX_VISUAL_MANIFEST_BYTES:
            raise PublisherError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "invalid_request", "manifest is too large")
    except OSError:
        raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "manifest cannot be read") from None
    finally:
        os.close(file_fd)
    try:
        data = json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "manifest is not valid UTF-8 JSON") from None
    if not isinstance(data, list) or not data or len(data) > MAX_VISUAL_ARTIFACTS:
        raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "manifest must be a non-empty list")
    return data


def visual_artifact_path(root: str, relpath: str) -> str:
    if not isinstance(relpath, str) or not relpath or os.path.isabs(relpath) or "\x00" in relpath:
        raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "invalid artifact relpath")
    parts = relpath.replace("\\", "/").split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "invalid artifact relpath")
    path = os.path.realpath(os.path.join(root, *parts))
    if not inside(path, root):
        raise PublisherError(HTTPStatus.CONFLICT, "unsafe_path", "artifact resolves outside worktree")
    try:
        st = os.lstat(path)
    except OSError:
        raise PublisherError(HTTPStatus.NOT_FOUND, "artifact_missing", relpath) from None
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise PublisherError(HTTPStatus.CONFLICT, "unsafe_path", "artifact is not a regular file")
    return path


def visual_magic(media_type: str, prefix: bytes) -> bool:
    if media_type == "image/png":
        return prefix.startswith(b"\x89PNG\r\n\x1a\n")
    if media_type == "image/jpeg":
        return prefix.startswith(b"\xff\xd8\xff")
    if media_type == "image/gif":
        return prefix.startswith((b"GIF87a", b"GIF89a"))
    if media_type == "image/webp":
        return len(prefix) >= 12 and prefix[:4] == b"RIFF" and prefix[8:12] == b"WEBP"
    if media_type == "video/webm":
        return prefix.startswith(b"\x1aE\xdf\xa3")
    if media_type in ("video/mp4", "video/quicktime"):
        return len(prefix) >= 12 and prefix[4:8] == b"ftyp" and (
            media_type == "video/mp4" or prefix[8:12] == b"qt  "
        )
    return False


def validate_visual_artifacts(root: str, artifacts: Any, allowed_source_shas: set[str] | None = None) -> list[tuple[dict[str, Any], str]]:
    allowed_source_shas = None if allowed_source_shas is None else set(allowed_source_shas)
    if not isinstance(artifacts, list) or not artifacts or len(artifacts) > MAX_VISUAL_ARTIFACTS:
        raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "artifacts must be a non-empty list")
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    validated: list[tuple[dict[str, Any], str]] = []
    for item in artifacts:
        if not isinstance(item, dict):
            raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "invalid visual artifact")
        expected = {"id", "role", "relpath", "sha256", "bytes", "media_type", "source_sha", "caption"}
        if set(item) != expected:
            raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "invalid visual artifact fields")
        ident = item["id"]
        role = item["role"]
        relpath = item["relpath"]
        if not isinstance(ident, str) or not VISUAL_ID_RE.fullmatch(ident) or ident in seen_ids:
            raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "invalid or repeated artifact id")
        if role not in ("before", "after", "control"):
            raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "invalid artifact role")
        if (not isinstance(item["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
                or not isinstance(item["source_sha"], str) or not SHA_RE.fullmatch(item["source_sha"])):
            raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "invalid artifact hash")
        if allowed_source_shas is not None and item["source_sha"] not in allowed_source_shas:
            expected_source = min(allowed_source_shas) if allowed_source_shas else None
            raise PublisherError(
                HTTPStatus.CONFLICT, "source_sha_mismatch", "artifact source_sha is not allowed",
                visual_artifact_error(relpath, "source_sha", expected_source, item["source_sha"]),
            )
        if (not isinstance(item["bytes"], int) or isinstance(item["bytes"], bool)
                or item["bytes"] <= 0 or item["bytes"] > MAX_VISUAL_ARTIFACT_BYTES):
            raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "invalid artifact size")
        if not isinstance(item["media_type"], str) or item["media_type"] not in VISUAL_MEDIA_TYPES:
            raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "invalid artifact media_type")
        if not isinstance(item["caption"], str) or not item["caption"].strip() or len(item["caption"]) > 500:
            raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "invalid artifact caption")
        path = visual_artifact_path(root, relpath)
        if path in seen_paths:
            raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "repeated artifact path")
        st = os.stat(path)
        if st.st_size != item["bytes"]:
            raise visual_artifact_mismatch(relpath, "bytes", item["bytes"], st.st_size,
                                           f"{relpath}: bytes")
        with open(path, "rb") as handle:
            prefix = handle.read(32)
            digest = hashlib.sha256(prefix)
            remaining = st.st_size - len(prefix)
            while remaining:
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise PublisherError(HTTPStatus.BAD_REQUEST, "artifact_mismatch", f"{relpath}: truncated")
                digest.update(chunk)
                remaining -= len(chunk)
        if not visual_magic(item["media_type"], prefix):
            raise visual_artifact_mismatch(relpath, "media_type", item["media_type"], "magic",
                                           f"{relpath}: magic/MIME")
        if digest.hexdigest() != item["sha256"]:
            raise visual_artifact_mismatch(relpath, "sha256", item["sha256"], digest.hexdigest(),
                                           f"{relpath}: sha256")
        seen_ids.add(ident)
        seen_paths.add(path)
        validated.append((item, path))
    return validated


def normalize_visual_marker(marker: str) -> str:
    if marker == VISUAL_MARKER_LITERAL:
        return "default"
    if VISUAL_MARKER_RE.fullmatch(marker):
        return marker
    raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "invalid visual marker")


def visual_evidence_ref(pr_number: int, head_sha: str) -> str:
    return f"issue-agent-visual/pr-{pr_number}-{head_sha}"


def visual_evidence_basename(relpath: str) -> str:
    basename = os.path.basename(relpath.replace("\\", "/"))
    basename = re.sub(r"[^A-Za-z0-9_.-]", "_", basename)[:160]
    return basename or "artifact"


def visual_evidence_path(pr_number: int, head_sha: str, item: dict[str, Any]) -> str:
    return (f".issue-agent/visual-evidence/pr-{pr_number}/{head_sha}/"
            f"{item['id']}-{visual_evidence_basename(item['relpath'])}")


def visual_github_url(repo: str, kind: str, value: str, path: str | None = None) -> str:
    encoded = urllib.parse.quote(value, safe="/-._~")
    if kind == "blob":
        assert path is not None
        return f"https://github.com/{repo}/blob/{encoded}/{urllib.parse.quote(path, safe='/-._~')}"
    if kind == "tree":
        return f"https://github.com/{repo}/tree/{encoded}"
    return f"https://github.com/{repo}/commit/{encoded}"


def visual_git_error(result: subprocess.CompletedProcess, operation: str, token: str | None = None) -> None:
    if result.returncode != 0:
        raise PublisherError(HTTPStatus.BAD_GATEWAY, "github_error",
                             scrub(result.stderr or "", [token or ""]) or operation)


def visual_existing_ref(repo: str, ref: str, token: str, mirror: str) -> tuple[str | None, bool]:
    """Return the remote ref commit, fetching it into the mirror when present."""
    url = f"https://github.com/{repo}.git"
    result = run_git(["ls-remote", "--", url, f"refs/heads/{ref}"], token=token)
    visual_git_error(result, "cannot inspect evidence ref", token)
    rows = [line.split() for line in result.stdout.splitlines() if line.strip()]
    if not rows:
        return None, False
    if len(rows) != 1 or len(rows[0]) != 2 or not SHA_RE.fullmatch(rows[0][0]) \
            or rows[0][1] != f"refs/heads/{ref}":
        raise PublisherError(HTTPStatus.BAD_GATEWAY, "github_error", "invalid evidence ref response")
    remote_sha = rows[0][0]
    result = run_git(["--git-dir", mirror, "fetch", "--quiet", "--no-tags", "--", url,
                      f"refs/heads/{ref}:refs/heads/{ref}"], token=token)
    visual_git_error(result, "cannot fetch evidence ref", token)
    return remote_sha, True


def visual_verify_commit(mirror: str, commit: str, head_sha: str, marker_text: str,
                         artifacts: list[tuple[dict[str, Any], str, str]], pr_number: int) -> None:
    result = run_git(["--git-dir", mirror, "rev-list", "--parents", "-n", "1", commit])
    visual_git_error(result, "cannot inspect evidence commit")
    parents = result.stdout.strip().split()
    if len(parents) != 2 or parents[1] != head_sha:
        raise PublisherError(HTTPStatus.CONFLICT, "evidence_ref_conflict", "evidence commit has unexpected lineage")
    result = run_git(["--git-dir", mirror, "show", "-s", "--format=%B", commit])
    visual_git_error(result, "cannot inspect evidence commit")
    expected_lines = {
        f"Artifact: {item['id']} {item['sha256']} {blob_sha} {visual_evidence_path(pr_number, head_sha, item)}"
        for item, _, blob_sha in artifacts
    }
    if marker_text not in result.stdout or not expected_lines <= set(result.stdout.splitlines()):
        raise PublisherError(HTTPStatus.CONFLICT, "evidence_ref_conflict", "evidence commit marker or artifacts differ")
    for item, _, blob_sha in artifacts:
        path = visual_evidence_path(pr_number, head_sha, item)
        result = run_git(["--git-dir", mirror, "ls-tree", "-r", "--full-tree", commit, "--", path])
        visual_git_error(result, "cannot inspect evidence tree")
        fields = result.stdout.strip().split()
        if len(fields) < 3 or fields[1] != "blob" or fields[2] != blob_sha:
            raise PublisherError(HTTPStatus.CONFLICT, "evidence_ref_conflict", "evidence tree differs")

def visual_verify_existing_commit(
    mirror: str,
    commit: str,
    head_sha: str,
    marker_text: str,
    requested: list[tuple[dict[str, Any], str]],
    pr_number: int,
) -> list[tuple[dict[str, Any], str, str]]:
    """Validate an existing canonical ref without comparing a re-encoded capture."""
    result = run_git(["--git-dir", mirror, "rev-list", "--parents", "-n", "1", commit])
    if result.returncode != 0:
        raise PublisherError(HTTPStatus.CONFLICT, "evidence_ref_conflict", "cannot inspect evidence lineage")
    parents = result.stdout.strip().split()
    if len(parents) != 2 or parents[1] != head_sha:
        raise PublisherError(HTTPStatus.CONFLICT, "evidence_ref_conflict", "evidence commit has unexpected lineage")

    result = run_git(["--git-dir", mirror, "show", "-s", "--format=%B", commit])
    if result.returncode != 0:
        raise PublisherError(HTTPStatus.CONFLICT, "evidence_ref_conflict", "cannot inspect evidence manifest")
    lines = result.stdout.splitlines()
    if marker_text not in lines:
        raise PublisherError(HTTPStatus.CONFLICT, "evidence_ref_conflict", "evidence commit marker differs")

    prefix = f".issue-agent/visual-evidence/pr-{pr_number}/{head_sha}/"
    canonical: list[tuple[str, str, str, str]] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for line in lines:
        match = VISUAL_ARTIFACT_LINE_RE.fullmatch(line)
        if match is None:
            continue
        ident, sha256, blob, path = match.group("id", "sha256", "blob", "path")
        if (not path.startswith(prefix) or ident in seen_ids or path in seen_paths
                or not os.path.basename(path).startswith(ident + "-")):
            raise PublisherError(HTTPStatus.CONFLICT, "evidence_ref_conflict",
                                 "evidence commit artifact manifest is invalid")
        seen_ids.add(ident)
        seen_paths.add(path)
        canonical.append((ident, sha256, blob, path))
    if not canonical:
        raise PublisherError(HTTPStatus.CONFLICT, "evidence_ref_conflict",
                             "evidence commit has no artifacts")

    requested_paths = {visual_evidence_path(pr_number, head_sha, item) for item, _ in requested}
    canonical_paths = {path for _, _, _, path in canonical}
    if requested_paths != canonical_paths:
        raise PublisherError(HTTPStatus.CONFLICT, "evidence_ref_conflict",
                             "evidence artifact identities differ")

    by_path = {path: (ident, sha256, blob) for ident, sha256, blob, path in canonical}
    indexed: list[tuple[dict[str, Any], str, str]] = []
    for item, source in requested:
        path = visual_evidence_path(pr_number, head_sha, item)
        ident, _, blob = by_path[path]
        if ident != item["id"]:
            raise PublisherError(HTTPStatus.CONFLICT, "evidence_ref_conflict",
                                 "evidence artifact identities differ")
        result = run_git(["--git-dir", mirror, "ls-tree", "-r", "--full-tree", commit, "--", path])
        if result.returncode != 0:
            raise PublisherError(HTTPStatus.CONFLICT, "evidence_ref_conflict",
                                 "cannot inspect evidence tree")
        fields = result.stdout.strip().split()
        if len(fields) < 3 or fields[1] != "blob" or fields[2] != blob:
            raise PublisherError(HTTPStatus.CONFLICT, "evidence_ref_conflict", "evidence tree differs")
        indexed.append((item, source, blob))
    return indexed




def visual_create_commit(mirror: str, head_sha: str, marker_text: str,
                         artifacts: list[tuple[dict[str, Any], str]], pr_number: int) -> tuple[str, list[tuple[dict[str, Any], str, str]]]:
    """Add only validated blobs to a tree rooted at ``head_sha`` and commit it."""
    indexed: list[tuple[dict[str, Any], str, str]] = []
    for item, source in artifacts:
        result = run_git(["--git-dir", mirror, "hash-object", "-w", "--", source])
        visual_git_error(result, "cannot store evidence blob")
        blob_sha = result.stdout.strip()
        if not SHA_RE.fullmatch(blob_sha):
            raise PublisherError(HTTPStatus.BAD_GATEWAY, "github_error", "invalid evidence blob id")
        with open(source, "rb") as handle:
            digest = hashlib.sha256()
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != item["sha256"]:
            raise PublisherError(
                HTTPStatus.CONFLICT, "artifact_mismatch", f"{item['relpath']}: changed during publish",
                visual_artifact_error(item["relpath"], "sha256", item["sha256"], digest.hexdigest()),
            )
        indexed.append((item, source, blob_sha))

    index_file = tempfile.NamedTemporaryFile(prefix=".visual-index-", dir=STATE_DIR, delete=False)
    index_file.close()
    os.unlink(index_file.name)
    env = {"GIT_INDEX_FILE": index_file.name}
    try:
        result = run_git(["--git-dir", mirror, "read-tree", head_sha], extra_env=env)
        visual_git_error(result, "cannot read evidence parent")
        for item, _, blob_sha in indexed:
            path = visual_evidence_path(pr_number, head_sha, item)
            result = run_git(["--git-dir", mirror, "update-index", "--add",
                              "--cacheinfo", f"100644,{blob_sha},{path}"], extra_env=env)
            visual_git_error(result, "cannot add evidence path")
        result = run_git(["--git-dir", mirror, "write-tree"], extra_env=env)
        visual_git_error(result, "cannot write evidence tree")
        tree = result.stdout.strip()
    finally:
        try:
            os.unlink(index_file.name)
        except FileNotFoundError:
            pass
    message_lines = ["Issue-agent visual evidence", "", marker_text, f"Head: {head_sha}"]
    for item, _, blob_sha in indexed:
        message_lines.append(f"Artifact: {item['id']} {item['sha256']} {blob_sha} "
                             f"{visual_evidence_path(pr_number, head_sha, item)}")
    result = run_git(["--git-dir", mirror, "commit-tree", tree, "-p", head_sha, "-F", "-"], extra_env={
        "GIT_AUTHOR_NAME": "issue-agent[bot]",
        "GIT_AUTHOR_EMAIL": "issue-agent[bot]@users.noreply.github.com",
        "GIT_COMMITTER_NAME": "issue-agent[bot]",
        "GIT_COMMITTER_EMAIL": "issue-agent[bot]@users.noreply.github.com",
    }, stdin_text="\n".join(message_lines) + "\n")
    visual_git_error(result, "cannot create evidence commit")
    commit = result.stdout.strip()
    if not SHA_RE.fullmatch(commit):
        raise PublisherError(HTTPStatus.BAD_GATEWAY, "github_error", "invalid evidence commit id")
    return commit, indexed


def visual_verified_ancestor_sources(mirror: str, head_sha: str, artifacts: Any,
                                      exact_sources: set[str]) -> set[str]:
    """Extend the exact source allowlist only with commits proven to be ancestors of ``head_sha``."""
    allowed = set(exact_sources)
    if not isinstance(artifacts, list):
        return allowed
    for item in artifacts:
        source = item.get("source_sha") if isinstance(item, dict) else None
        if not isinstance(source, str) or not SHA_RE.fullmatch(source) or source in allowed:
            continue
        exists = run_git(["--git-dir", mirror, "cat-file", "-e", f"{source}^{{commit}}"])
        if exists.returncode != 0:
            continue
        relation = run_git(["--git-dir", mirror, "merge-base", "--is-ancestor", source, head_sha])
        if relation.returncode == 0:
            allowed.add(source)
        elif relation.returncode != 1:
            visual_git_error(relation, "cannot verify visual source ancestry")
    return allowed


def do_visual_evidence(repo: str, worktree: str, pr_number: int, head_sha: str, marker: str,
                       body: str, manifest_path: str, *, base_sha: str | None = None,
                       reuse_existing: bool = False) -> dict[str, Any]:
    if not SHA_RE.fullmatch(head_sha) or not _is_int(pr_number):
        raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "invalid PR head")
    if base_sha is not None and (not isinstance(base_sha, str) or not SHA_RE.fullmatch(base_sha)):
        raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "invalid PR base")
    if not isinstance(reuse_existing, bool):
        raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "invalid reuse_existing")
    marker = normalize_visual_marker(marker)
    if not isinstance(body, str) or not body.strip() or len(body) > 60000:
        raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "invalid visual evidence body")
    root = visual_worktree_path(repo, worktree)
    artifacts = read_visual_manifest(root, manifest_path)
    if visual_worktree_head(root) != head_sha:
        raise PublisherError(HTTPStatus.CONFLICT, "worktree_head_mismatch", f"worktree HEAD is not {head_sha}")
    branch = f"hapi-{worktree}"
    if fetch_branch(repo, branch) != head_sha:
        raise PublisherError(HTTPStatus.CONFLICT, "worktree_head_mismatch", f"{branch} is not {head_sha}")
    mirror = ensure_mirror(repo)
    exact_sources = {head_sha}
    roles = {item.get("role") for item in artifacts
             if isinstance(item, dict) and isinstance(item.get("role"), str)}
    if {"before", "after"} <= roles and base_sha is not None:
        exact_sources.add(base_sha)
    allowed = visual_verified_ancestor_sources(mirror, head_sha, artifacts, exact_sources)
    validated = validate_visual_artifacts(root, artifacts, allowed)
    token = read_secret(PUSH_TOKEN_FILE, "push token")
    ref = visual_evidence_ref(pr_number, head_sha)
    marker_text = f"Marker: <!-- issue-agent:visual-evidence:{marker} -->"
    remote_commit, exists = visual_existing_ref(repo, ref, token, mirror)
    already_published = False
    replaced = False
    if exists:
        assert remote_commit is not None
        if reuse_existing:
            indexed = visual_verify_existing_commit(
                mirror, remote_commit, head_sha, marker_text, validated, pr_number)
            already_published = True
            commit, created = remote_commit, False
        else:
            commit, indexed = visual_create_commit(mirror, head_sha, marker_text, validated, pr_number)
            push = run_git(
                ["--git-dir", mirror, "push", "--quiet", "--porcelain", "--no-verify",
                 f"--force-with-lease=refs/heads/{ref}:{remote_commit}", "--",
                 f"https://github.com/{repo}.git", f"{commit}:refs/heads/{ref}"],
                token=token,
            )
            if push.returncode != 0:
                current_commit, current_exists = visual_existing_ref(repo, ref, token, mirror)
                if current_exists and current_commit == commit:
                    pass
                elif current_exists and current_commit != remote_commit:
                    raise PublisherError(
                        HTTPStatus.CONFLICT, "evidence_ref_conflict",
                        "evidence ref changed during replacement",
                    )
                else:
                    visual_git_error(push, "cannot replace evidence ref", token)
            result = run_git(["--git-dir", mirror, "update-ref", f"refs/heads/{ref}", commit])
            visual_git_error(result, "cannot retain evidence ref")
            created = False
            replaced = True
    else:
        commit, indexed = visual_create_commit(mirror, head_sha, marker_text, validated, pr_number)
        push = run_git(["--git-dir", mirror, "push", "--quiet", "--porcelain", "--no-verify", "--",
                        f"https://github.com/{repo}.git", f"{commit}:refs/heads/{ref}"], token=token)
        created = push.returncode == 0
        if push.returncode != 0:
            remote_commit, exists = visual_existing_ref(repo, ref, token, mirror)
            if not exists or remote_commit != commit:
                visual_git_error(push, "cannot publish evidence ref", token)
        result = run_git(["--git-dir", mirror, "update-ref", f"refs/heads/{ref}", commit])
        visual_git_error(result, "cannot retain evidence ref")
    assets = []
    for item, _, _ in indexed:
        path = visual_evidence_path(pr_number, head_sha, item)
        assets.append({
            "id": item["id"], "role": item["role"], "caption": item["caption"],
            "media_type": item["media_type"], "path": path,
            "blob_url": visual_github_url(repo, "blob", ref, path),
        })
    ref_url = visual_github_url(repo, "tree", ref)
    return {
        "created": created, "replaced": replaced, "already_published": already_published, "marker": marker, "ref": ref,
        "ref_url": ref_url, "evidence_ref_url": ref_url,
        "commit_url": visual_github_url(repo, "commit", commit),
        "evidence_commit_url": visual_github_url(repo, "commit", commit),
        "evidence_url": ref_url, "assets": assets,
        "asset_urls": [asset["blob_url"] for asset in assets],
        "body": body.strip(),
    }


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


def worktree_target_paths(repo: str, worktree: str | None) -> list[str]:
    """Lexical and canonical (realpath) spellings of ``<repo>-worktrees/<worktree>``."""
    if worktree is None:
        return []
    base = checkout_path(repo)
    worktrees_dir = base + "-worktrees"
    lexical = os.path.join(worktrees_dir, worktree)
    paths = [lexical]
    if os.path.lexists(worktrees_dir) and not os.path.islink(worktrees_dir) and os.path.isdir(worktrees_dir):
        real_dir = confined_root(worktrees_dir)
        canonical = os.path.join(real_dir, worktree)
        if canonical not in paths:
            paths.insert(0, canonical)
        target = os.path.join(worktrees_dir, worktree)
        if os.path.lexists(target) and not os.path.islink(target) and os.path.isdir(target):
            real_target = os.path.realpath(target)
            if inside(real_target, real_dir) and real_target not in paths:
                paths.insert(0, real_target)
    return paths


def _safe_sqlite_path(root_dir: str, name: str) -> str | None:
    if not os.path.isdir(root_dir) or os.path.islink(root_dir):
        return None
    root = os.path.realpath(root_dir)
    path = os.path.join(root_dir, name)
    if not os.path.lexists(path) or os.path.islink(path):
        return None
    real = os.path.realpath(path)
    if not os.path.isfile(real) or not inside(real, root):
        return None
    return real


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()
    return row is not None


def _runtime_directories() -> list[str]:
    dirs = []
    for candidate in (
        os.path.join(CODEX_HOME, "hapi-runtime-owners"),
        os.path.join(HAPI_HOME, "codex-runtimes"),
    ):
        if os.path.isdir(candidate) and not os.path.islink(candidate):
            dirs.append(os.path.realpath(candidate))
    return list(dict.fromkeys(dirs))


def discover_codex_threads(
    codex_ids: list[str],
    worktree_paths: list[str] = (),
    hapi_ids: list[str] = (),
) -> tuple[list[str], list[str]]:
    """Return ``(root_ids, all_ids)`` for the subject's Codex sessions and spawned subagents."""
    seeds: list[str] = []
    seen_seeds: set[str] = set()

    def add_seed(value: Any) -> None:
        if isinstance(value, str):
            lower = value.lower()
            if CODEX_ID_RE.fullmatch(lower) and lower not in seen_seeds:
                seen_seeds.add(lower)
                seeds.append(lower)

    for cid in codex_ids:
        add_seed(cid)

    hapi_set = {hid for hid in hapi_ids if isinstance(hid, str) and HAPI_ID_RE.fullmatch(hid)}
    if hapi_set:
        for rdir in _runtime_directories():
            for entry in sorted(os.listdir(rdir)):
                if not entry.endswith(".json"):
                    continue
                fpath = os.path.join(rdir, entry)
                if os.path.islink(fpath) or not os.path.isfile(fpath):
                    continue
                try:
                    with open(fpath, encoding="utf-8") as handle:
                        data = json.load(handle)
                except (OSError, ValueError):
                    continue
                sessions = data.get("sessions") if isinstance(data, dict) else None
                if not isinstance(sessions, dict):
                    continue
                for sid, meta in sessions.items():
                    if sid in hapi_set and isinstance(meta, dict):
                        add_seed(meta.get("threadId"))

    state_db = _safe_sqlite_path(CODEX_HOME, "state_5.sqlite")
    if state_db is None:
        return list(seeds), list(seeds)

    children_of: dict[str, list[str]] = {}
    parents_of: dict[str, set[str]] = {}
    try:
        with closing(sqlite3.connect(state_db, timeout=30.0)) as conn:
            if _table_exists(conn, "threads"):
                for wt in worktree_paths:
                    prefix = wt.rstrip("/") + "/"
                    for (tid,) in conn.execute(
                        "SELECT id FROM threads WHERE cwd = ? OR substr(cwd, 1, ?) = ? ORDER BY created_at, id",
                        (wt, len(prefix), prefix),
                    ):
                        add_seed(tid)
                for parent_id, child_id in conn.execute(
                    "SELECT attached_thread_parent_id, id FROM threads WHERE attached_thread_parent_id IS NOT NULL"
                ):
                    if isinstance(parent_id, str) and isinstance(child_id, str):
                        p, c = parent_id.lower(), child_id.lower()
                        if CODEX_ID_RE.fullmatch(p) and CODEX_ID_RE.fullmatch(c):
                            children_of.setdefault(p, []).append(c)
                            parents_of.setdefault(c, set()).add(p)
            if _table_exists(conn, "thread_spawn_edges"):
                for parent_id, child_id in conn.execute(
                    "SELECT parent_thread_id, child_thread_id FROM thread_spawn_edges"
                ):
                    if isinstance(parent_id, str) and isinstance(child_id, str):
                        p, c = parent_id.lower(), child_id.lower()
                        if CODEX_ID_RE.fullmatch(p) and CODEX_ID_RE.fullmatch(c):
                            children_of.setdefault(p, []).append(c)
                            parents_of.setdefault(c, set()).add(p)
    except sqlite3.Error as exc:
        log.warning("codex state_5.sqlite thread discovery failed: %s", exc)
        return list(seeds), list(seeds)

    all_ids: list[str] = []
    visited: set[str] = set()
    queue = list(seeds)
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        all_ids.append(current)
        for parent in sorted(parents_of.get(current, ())):
            if parent not in visited:
                queue.append(parent)
        for child in children_of.get(current, ()):
            if child not in visited:
                queue.append(child)

    all_set = set(all_ids)
    root_ids = [tid for tid in all_ids if not (parents_of.get(tid, set()) & all_set)]
    for tid in all_ids:
        if tid not in root_ids:
            root_ids.append(tid)
    return root_ids, all_ids


def run_codex_delete(thread_id: str) -> bool:
    """Invoke ``codex delete --force <thread_id>`` when the CLI and state DB exist."""
    if _safe_sqlite_path(CODEX_HOME, "state_5.sqlite") is None:
        return False
    binary = CODEX_BIN if os.path.isabs(CODEX_BIN) else shutil.which(CODEX_BIN)
    if not binary or not os.path.exists(binary):
        return False
    env = {**os.environ, "CODEX_HOME": os.path.realpath(CODEX_HOME)}
    try:
        res = subprocess.run(
            [binary, "delete", "--force", thread_id],
            env=env,
            capture_output=True,
            text=True,
            timeout=CODEX_DELETE_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("codex delete %s failed: %s", thread_id, exc)
        return False
    return res.returncode == 0


def _delete_codex_sqlite_rows(thread_ids: list[str], *, vacuum: bool = False) -> list[str]:
    """Remove any remaining SQLite records for ``thread_ids`` across CODEX_HOME databases."""
    if not thread_ids and not vacuum:
        return []
    removed: list[str] = []
    db_tables: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
        ("state_5.sqlite", (
            ("thread_spawn_edges", "parent_thread_id"),
            ("thread_spawn_edges", "child_thread_id"),
            ("thread_read_receipts", "thread_id"),
            ("thread_dynamic_tools", "thread_id"),
            ("thread_attachments", "thread_id"),
            ("guardian_review_feedback", "thread_id"),
            ("threads", "id"),
        )),
        ("thread_history_1.sqlite", (
            ("thread_items", "thread_id"),
            ("thread_turns", "thread_id"),
            ("thread_history_projection_state", "thread_id"),
            ("thread_realtime_items", "thread_id"),
        )),
        ("logs_2.sqlite", (("logs", "thread_id"),)),
        ("queue_1.sqlite", (
            ("queued_items", "thread_id"),
            ("queued_thread_revisions", "thread_id"),
        )),
        ("goals_1.sqlite", (
            ("thread_goal_continuation_deferrals", "thread_id"),
            ("thread_goals", "thread_id"),
        )),
        ("memories_1.sqlite", (("stage1_outputs", "thread_id"),)),
    )
    for db_name, specs in db_tables:
        db_path = _safe_sqlite_path(CODEX_HOME, db_name)
        if db_path is None:
            continue
        deleted = 0
        try:
            with closing(sqlite3.connect(db_path, timeout=30.0)) as conn:
                for start in range(0, len(thread_ids), 100):
                    chunk = thread_ids[start:start + 100]
                    marks = ", ".join("?" for _ in chunk)
                    with conn:
                        for table, col in specs:
                            if _table_exists(conn, table):
                                cur = conn.execute(f'DELETE FROM "{table}" WHERE "{col}" IN ({marks})', tuple(chunk))
                                if cur.rowcount and cur.rowcount > 0:
                                    deleted += cur.rowcount
                if vacuum:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    conn.execute("VACUUM")
                elif deleted > 0:
                    conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except sqlite3.Error as exc:
            log.warning("cleanup sqlite %s failed: %s", db_name, exc)
            continue
        if deleted > 0:
            removed.append(f"{db_path}:rows={deleted}")
    return removed


def remove_codex_records(
    codex_ids: list[str],
    worktree_paths: list[str] = (),
    hapi_ids: list[str] = (),
    *,
    vacuum: bool = False,
) -> list[str]:
    """Delete Codex sessions (parent + subagents, SQLite history and rollout files) under CODEX_HOME."""
    if not os.path.isdir(CODEX_HOME) or os.path.islink(CODEX_HOME):
        return []
    root_ids, all_ids = discover_codex_threads(codex_ids, list(worktree_paths), list(hapi_ids))
    if not all_ids and not vacuum:
        return []
    root = os.path.realpath(CODEX_HOME)
    removed: list[str] = []

    # 1. Native Codex CLI deletion (cascades parent -> subagents in state_5/thread_history_1 + rollout files).
    state_db = _safe_sqlite_path(CODEX_HOME, "state_5.sqlite")
    if state_db is not None and all_ids:
        for tid in root_ids:
            try:
                with closing(sqlite3.connect(state_db, timeout=30.0)) as conn:
                    exists = _table_exists(conn, "threads") and conn.execute(
                        "SELECT 1 FROM threads WHERE id = ?", (tid,)
                    ).fetchone() is not None
            except sqlite3.Error:
                exists = True
            if exists and run_codex_delete(tid):
                removed.append(f"codex:{tid}")

    # 2. Remove any rollout files still present on disk (e.g. when codex CLI is absent in tests or skipped a file).
    for codex_id in all_ids:
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

    # 3. Clean any remaining SQLite rows across all Codex DBs.
    removed += _delete_codex_sqlite_rows(all_ids, vacuum=vacuum)
    return removed



def _config_header_key(line: str) -> str | None:
    match = CONFIG_PROJECT_HEADER_RE.match(line)
    if not match:
        return None
    try:
        return tomllib.loads(f"k = {match.group(1)}")["k"]
    except tomllib.TOMLDecodeError:
        return None


def remove_codex_project_trust(worktree_paths: list[str]) -> list[str]:
    """Remove ``[projects."<worktree_path>"]`` tables from ``$CODEX_HOME/config.toml`` under ``config.toml.lock``."""
    drop = {
        p for p in worktree_paths
        if isinstance(p, str) and "-worktrees/" in p.replace("\\", "/")
    }
    if not drop or not os.path.isdir(CODEX_HOME) or os.path.islink(CODEX_HOME):
        return []
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        dir_fd = os.open(CODEX_HOME, os.O_RDONLY | os.O_DIRECTORY | nofollow | os.O_CLOEXEC)
    except OSError:
        return []
    try:
        lock_fd = os.open("config.toml.lock", os.O_RDWR | os.O_CREAT | nofollow | os.O_CLOEXEC, 0o600, dir_fd=dir_fd)
    except OSError:
        os.close(dir_fd)
        return []
    try:
        if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
            return []
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            cfg_fd = os.open("config.toml", os.O_RDONLY | os.O_NONBLOCK | nofollow | os.O_CLOEXEC, dir_fd=dir_fd)
        except FileNotFoundError:
            return []
        try:
            if not stat.S_ISREG(os.fstat(cfg_fd).st_mode):
                return []
            chunks = []
            while chunk := os.read(cfg_fd, 1 << 16):
                chunks.append(chunk)
            text = b"".join(chunks).decode("utf-8")
        finally:
            os.close(cfg_fd)
        try:
            before = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            return []
        projects = before.get("projects", {})
        if not isinstance(projects, dict):
            return []
        present = [k for k in sorted(drop) if k in projects]
        if not present:
            return []
        lines: list[str] = []
        skipping = False
        for line in text.splitlines(keepends=True):
            if CONFIG_TABLE_RE.match(line):
                skipping = _config_header_key(line) in drop
            if not skipping:
                lines.append(line)
        new_text = "".join(lines)
        try:
            after = tomllib.loads(new_text)
        except tomllib.TOMLDecodeError:
            return []
        if {k: v for k, v in after.items() if k != "projects"} != {k: v for k, v in before.items() if k != "projects"}:
            return []
        after_projects = after.get("projects", {})
        expected_projects = {k: v for k, v in projects.items() if k not in drop}
        if after_projects != expected_projects:
            return []
        tmp = f".config.toml.cleanup.{os.getpid()}.{threading.get_ident()}"
        try:
            os.unlink(tmp, dir_fd=dir_fd)
        except FileNotFoundError:
            pass
        out_fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow | os.O_CLOEXEC, 0o600, dir_fd=dir_fd)
        try:
            with os.fdopen(out_fd, "wb") as handle:
                handle.write(new_text.encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, "config.toml", src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        except BaseException:
            try:
                os.unlink(tmp, dir_fd=dir_fd)
            except FileNotFoundError:
                pass
            raise
        os.fsync(dir_fd)
        return [f"config.toml:{k}" for k in present]
    finally:
        os.close(lock_fd)
        os.close(dir_fd)


def remove_hapi_runtime_records(
    codex_ids: list[str],
    hapi_ids: list[str] = (),
    *,
    idle_sweep: bool = False,
    live_tids: set[str] | None = None,
) -> list[str]:
    """Remove HAPI queue files and dead runtime ownership files for the cleaned sessions."""
    target_tids = {cid.lower() for cid in codex_ids if CODEX_ID_RE.fullmatch(cid.lower())}
    target_sids = {sid for sid in hapi_ids if isinstance(sid, str) and HAPI_ID_RE.fullmatch(sid)}
    keep_tids = (live_tids or set()) - target_tids
    removed: list[str] = []

    for rdir in _runtime_directories():
        for entry in sorted(os.listdir(rdir)):
            if not entry.endswith(".json"):
                continue
            fpath = os.path.join(rdir, entry)
            if os.path.islink(fpath) or not os.path.isfile(fpath):
                continue
            real = os.path.realpath(fpath)
            if not inside(real, rdir):
                continue
            try:
                with open(real, encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            sessions = data.get("sessions")
            if not isinstance(sessions, dict):
                continue
            matched_sids = [
                sid for sid, meta in sessions.items()
                if sid in target_sids or (isinstance(meta, dict) and str(meta.get("threadId") or "").lower() in target_tids)
            ]
            for sid in matched_sids:
                if HAPI_ID_RE.fullmatch(sid):
                    target_sids.add(sid)
            has_live_thread = any(
                isinstance(meta, dict) and str(meta.get("threadId") or "").lower() in keep_tids
                for meta in sessions.values()
            )
            try:
                stale_record = (time.time() - os.lstat(real).st_mtime) > 6 * 3600
            except OSError:
                stale_record = False
            all_inactive = (
                all(isinstance(meta, dict) and meta.get("active") is False for meta in sessions.values())
                and not data.get("pendingCreations")
            ) or stale_record
            if all_inactive and not has_live_thread and (idle_sweep or (sessions and len(matched_sids) == len(sessions))):
                try:
                    os.remove(real)
                    removed.append(real)
                except FileNotFoundError:
                    pass
    queues_dir = os.path.join(HAPI_HOME, "codex-runtimes", "queues")
    if os.path.isdir(queues_dir) and not os.path.islink(queues_dir):
        qroot = os.path.realpath(queues_dir)
        for sid in sorted(target_sids):
            qpath = os.path.join(queues_dir, f"{sid}.queue.json")
            if os.path.lexists(qpath) and not os.path.islink(qpath):
                real = os.path.realpath(qpath)
                if os.path.isfile(real) and inside(real, qroot):
                    os.remove(real)
                    removed.append(real)
        if idle_sweep:
            active_sids: set[str] = set()
            for rdir in _runtime_directories():
                for entry in os.listdir(rdir):
                    if not entry.endswith(".json"):
                        continue
                    fpath = os.path.join(rdir, entry)
                    if os.path.islink(fpath) or not os.path.isfile(fpath):
                        continue
                    try:
                        with open(fpath, encoding="utf-8") as handle:
                            data = json.load(handle)
                    except (OSError, ValueError):
                        continue
                    if isinstance(data, dict) and isinstance(data.get("sessions"), dict):
                        active_sids.update(data["sessions"].keys())
            for entry in sorted(os.listdir(queues_dir)):
                if not entry.endswith(".queue.json"):
                    continue
                sid = entry.removesuffix(".queue.json")
                if sid in active_sids:
                    continue
                qpath = os.path.join(queues_dir, entry)
                if not os.path.islink(qpath):
                    real = os.path.realpath(qpath)
                    if os.path.isfile(real) and inside(real, qroot):
                        os.remove(real)
                        removed.append(real)
    return removed


def remove_tmp_records(worktree: str | None) -> list[str]:
    """Remove ``/tmp/issue-agent-worktree/<worktree>`` and ``/tmp/issue-agent/<worktree>``."""
    if not os.path.isdir(RUNNER_TMP) or os.path.islink(RUNNER_TMP):
        return []
    tmp_root = os.path.realpath(RUNNER_TMP)
    removed: list[str] = []
    if worktree is not None and WORKTREE_RE.fullmatch(worktree):
        for subdir in ("issue-agent-worktree", "issue-agent"):
            parent = os.path.join(RUNNER_TMP, subdir)
            if not os.path.isdir(parent) or os.path.islink(parent):
                continue
            parent_root = os.path.realpath(parent)
            if not inside(parent_root, tmp_root):
                continue
            target = os.path.join(parent_root, worktree)
            if not os.path.lexists(target):
                continue
            if os.path.islink(target):
                os.unlink(target)
                removed.append(target)
            elif os.path.isdir(target) and inside(os.path.realpath(target), parent_root):
                real = os.path.realpath(target)
                rmtree_agent(real)
                removed.append(real)
    return removed

def do_cleanup(
    repo: str,
    worktree: str | None,
    branch: str | None,
    codex_ids: list[str],
    hapi_ids: list[str] = (),
) -> dict:
    removed: list[str] = []
    try:
        wt_paths = worktree_target_paths(repo, worktree)
        _, all_codex_ids = discover_codex_threads(codex_ids, wt_paths, list(hapi_ids))
        if worktree is not None:
            removed += remove_worktree(repo, worktree)
        if branch is not None:
            removed += remove_branch(repo, branch)
        removed += remove_codex_records(all_codex_ids, wt_paths, list(hapi_ids))
        removed += remove_codex_project_trust(wt_paths)
        removed += remove_hapi_runtime_records(all_codex_ids, list(hapi_ids))
        removed += remove_tmp_records(worktree)
    except OSError as exc:
        raise PublisherError(HTTPStatus.INTERNAL_SERVER_ERROR, "cleanup_failed",
                             f"{exc.filename or ''}: {exc.strerror or exc}") from None
    log.info("cleaned %s worktree=%s branch=%s codex=%d: removed %d",
             repo, worktree, branch, len(codex_ids), len(removed))
    return {"removed": removed}


def _live_worktree_paths() -> set[str]:
    """All existing ``<owner>/<repo>-worktrees/<worktree>`` directories (lexical and realpath)."""
    if not os.path.isdir(CHECKOUTS) or os.path.islink(CHECKOUTS):
        return set()
    root = os.path.realpath(CHECKOUTS)
    live: set[str] = set()
    for owner in sorted(os.listdir(root)):
        owner_dir = os.path.join(root, owner)
        if os.path.islink(owner_dir) or not os.path.isdir(owner_dir):
            continue
        for repo_wt in sorted(os.listdir(owner_dir)):
            if not repo_wt.endswith("-worktrees"):
                continue
            wt_root = os.path.join(owner_dir, repo_wt)
            if os.path.islink(wt_root) or not os.path.isdir(wt_root):
                continue
            for wt in sorted(os.listdir(wt_root)):
                if not WORKTREE_RE.fullmatch(wt):
                    continue
                p_real = os.path.join(wt_root, wt)
                if os.path.islink(p_real) or not os.path.isdir(p_real):
                    continue
                p_lex = os.path.join(CHECKOUTS, owner, repo_wt, wt)
                live.add(os.path.realpath(p_real))
                live.add(p_lex)
    return live


def _active_runtime_thread_ids() -> set[str]:
    now = time.time()
    active: set[str] = set()
    for rdir in _runtime_directories():
        for entry in sorted(os.listdir(rdir)):
            if not entry.endswith(".json"):
                continue
            fpath = os.path.join(rdir, entry)
            if os.path.islink(fpath) or not os.path.isfile(fpath):
                continue
            try:
                if (now - os.lstat(fpath).st_mtime) > 6 * 3600:
                    continue
                with open(fpath, encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            sessions = data.get("sessions")
            if not isinstance(sessions, dict):
                continue
            for meta in sessions.values():
                if isinstance(meta, dict) and meta.get("active") is not False:
                    tid = str(meta.get("threadId") or "").lower()
                    if CODEX_ID_RE.fullmatch(tid):
                        active.add(tid)
    return active


def _is_worktree_cwd(cwd: str) -> bool:
    norm = cwd.replace("\\", "/")
    return "-worktrees/" in norm


def _cwd_matches_live(cwd: str, live_worktrees: set[str]) -> bool:
    if cwd in live_worktrees:
        return True
    for wt in live_worktrees:
        if cwd.startswith(wt.rstrip("/") + "/"):
            return True
    return False


def sweep_orphan_worktree_state(*, dry_run: bool = False) -> list[str]:
    """Remove Codex sessions, SQLite rows, config.toml keys and HAPI runtime files for deleted worktrees."""
    live_worktrees = _live_worktree_paths()
    active_tids = _active_runtime_thread_ids()
    removed: list[str] = []

    orphan_seed_tids: list[str] = []
    live_tids: set[str] = set(active_tids)
    state_db = _safe_sqlite_path(CODEX_HOME, "state_5.sqlite")
    if state_db is not None:
        try:
            with closing(sqlite3.connect(f"file:{state_db}?mode=ro", uri=True, timeout=30.0)) as conn:
                if _table_exists(conn, "threads"):
                    for tid, cwd in conn.execute("SELECT id, cwd FROM threads"):
                        if not isinstance(tid, str) or not CODEX_ID_RE.fullmatch(tid.lower()):
                            continue
                        tid_l = tid.lower()
                        if tid_l in active_tids:
                            live_tids.add(tid_l)
                            continue
                        if isinstance(cwd, str) and _is_worktree_cwd(cwd):
                            if _cwd_matches_live(cwd, live_worktrees):
                                live_tids.add(tid_l)
                            else:
                                orphan_seed_tids.append(tid_l)
                        elif isinstance(cwd, str) and os.path.isdir(cwd):
                            live_tids.add(tid_l)
                        else:
                            orphan_seed_tids.append(tid_l)
        except sqlite3.Error as exc:
            log.warning("orphan sweep state_5.sqlite read failed: %s", exc)

    _, orphan_all_tids = discover_codex_threads(orphan_seed_tids)
    orphan_tids = [tid for tid in orphan_all_tids if tid not in live_tids]
    orphan_tid_set = set(orphan_tids)

    # Also catch rollout files on disk whose thread is either in orphan_tids or absent from state_5.sqlite.
    if os.path.isdir(CODEX_HOME) and not os.path.islink(CODEX_HOME):
        for pattern in (
            os.path.join(CODEX_HOME, "sessions", "*", "*", "*", "rollout-*.jsonl"),
            os.path.join(CODEX_HOME, "archived_sessions", "rollout-*.jsonl"),
        ):
            for path in sorted(glob.glob(pattern)):
                m = ROLLOUT_FILE_RE.match(os.path.basename(path))
                if m is None:
                    continue
                uid = m.group(1).lower()
                if uid not in live_tids and uid not in orphan_tid_set:
                    orphan_tids.append(uid)
                    orphan_tid_set.add(uid)

    if orphan_tids:
        if dry_run:
            removed.extend(f"codex:{tid}" for tid in orphan_tids)
        else:
            removed.extend(remove_codex_records(orphan_tids, vacuum=True))

    # Orphan config.toml worktree keys
    cfg_path = _safe_sqlite_path(CODEX_HOME, "config.toml")
    if cfg_path is not None:
        try:
            with open(cfg_path, encoding="utf-8") as handle:
                cfg_data = tomllib.loads(handle.read())
            projects = cfg_data.get("projects", {})
            if isinstance(projects, dict):
                dead_cfg_keys = [
                    k for k in projects
                    if isinstance(k, str) and _is_worktree_cwd(k) and k not in live_worktrees and not os.path.isdir(k)
                ]
                if dead_cfg_keys:
                    if dry_run:
                        removed.extend(f"config.toml:{k}" for k in dead_cfg_keys)
                    else:
                        removed.extend(remove_codex_project_trust(dead_cfg_keys))
        except (OSError, tomllib.TOMLDecodeError):
            pass

    # Orphan HAPI runtime and queue files
    if not dry_run:
        removed.extend(remove_hapi_runtime_records(orphan_tids, idle_sweep=True, live_tids=live_tids))
    return removed


def _tree_newest_timestamp(path: str) -> float:
    """Newest ``max(atime, mtime)`` across regular files under ``path`` (ignoring directory atime bumps from walks)."""
    try:
        st = os.lstat(path)
    except OSError:
        return time.time()
    if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode):
        return max(st.st_atime, st.st_mtime)
    newest = st.st_mtime
    for dirpath, _, filenames in os.walk(path, onerror=lambda _e: None):
        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            try:
                fst = os.lstat(fpath)
            except OSError:
                continue
            if stat.S_ISREG(fst.st_mode) and not stat.S_ISLNK(fst.st_mode):
                ts = max(fst.st_atime, fst.st_mtime)
                if ts > newest:
                    newest = ts
    return newest


def _referenced_rust_toolchains() -> set[str]:
    channels: set[str] = {"stable"}
    if not os.path.isdir(CHECKOUTS) or os.path.islink(CHECKOUTS):
        return channels
    root = os.path.realpath(CHECKOUTS)
    for owner in sorted(os.listdir(root)):
        owner_dir = os.path.join(root, owner)
        if os.path.islink(owner_dir) or not os.path.isdir(owner_dir):
            continue
        for repo in sorted(os.listdir(owner_dir)):
            if repo.endswith("-worktrees"):
                continue
            repo_dir = os.path.join(owner_dir, repo)
            if os.path.islink(repo_dir) or not os.path.isdir(repo_dir):
                continue
            for fname in ("rust-toolchain.toml", "rust-toolchain"):
                fpath = os.path.join(repo_dir, fname)
                if os.path.islink(fpath) or not os.path.isfile(fpath):
                    continue
                try:
                    with open(fpath, encoding="utf-8") as handle:
                        text = handle.read(8192).strip()
                except OSError:
                    continue
                if fname.endswith(".toml") or text.startswith("["):
                    try:
                        parsed = tomllib.loads(text)
                        ch = (parsed.get("toolchain") or {}).get("channel")
                        if isinstance(ch, str) and ch.strip():
                            channels.add(ch.strip())
                    except tomllib.TOMLDecodeError:
                        pass
                elif text:
                    channels.add(text.splitlines()[0].strip())
    return channels


def _referenced_go_versions() -> set[str]:
    versions: set[str] = set()
    if not os.path.isdir(CHECKOUTS) or os.path.islink(CHECKOUTS):
        return versions
    root = os.path.realpath(CHECKOUTS)
    go_re = re.compile(r"^\s*(?:go|toolchain)\s+(?:go)?([0-9]+\.[0-9]+(?:\.[0-9]+)?)\s*$", re.MULTILINE)
    for owner in sorted(os.listdir(root)):
        owner_dir = os.path.join(root, owner)
        if os.path.islink(owner_dir) or not os.path.isdir(owner_dir):
            continue
        for repo in sorted(os.listdir(owner_dir)):
            if repo.endswith("-worktrees"):
                continue
            gomod = os.path.join(owner_dir, repo, "go.mod")
            if os.path.islink(gomod) or not os.path.isfile(gomod):
                continue
            try:
                with open(gomod, encoding="utf-8") as handle:
                    text = handle.read(16384)
            except OSError:
                continue
            for m in go_re.finditer(text):
                versions.add(m.group(1))
    return versions


def sweep_global_caches(max_age_days: int = DEFAULT_CACHE_MAX_AGE_DAYS, *, dry_run: bool = False) -> list[str]:
    """Clean unreferenced toolchains and stale entries in global caches older than ``max_age_days``."""
    now = time.time()
    cutoff = now - max_age_days * 86400
    log_cutoff = now - min(max_age_days, HAPI_LOG_MAX_AGE_DAYS) * 86400
    removed: list[str] = []

    # 1. Rustup unreferenced toolchains (~/.rustup/toolchains)
    tc_dir = os.path.join(RUNNER_HOME, ".rustup", "toolchains")
    if os.path.isdir(tc_dir) and not os.path.islink(tc_dir):
        tc_root = os.path.realpath(tc_dir)
        kept_channels = _referenced_rust_toolchains()
        rustup_bin = RUSTUP_BIN if os.path.isabs(RUSTUP_BIN) else shutil.which(RUSTUP_BIN)
        for entry in sorted(os.listdir(tc_root)):
            path = os.path.join(tc_root, entry)
            if os.path.islink(path) or not os.path.isdir(path):
                continue
            if any(entry == ch or entry.startswith(ch + "-") for ch in kept_channels):
                continue
            try:
                if now - os.lstat(path).st_mtime < 86400:
                    continue
            except OSError:
                continue
            if not dry_run:
                if rustup_bin and os.path.exists(rustup_bin):
                    try:
                        subprocess.run(
                            [rustup_bin, "toolchain", "uninstall", entry],
                            env={**os.environ, "RUSTUP_HOME": os.path.join(RUNNER_HOME, ".rustup")},
                            capture_output=True,
                            text=True,
                            timeout=CACHE_CMD_TIMEOUT,
                            check=False,
                        )
                    except (OSError, subprocess.SubprocessError):
                        pass
                if os.path.lexists(path) and not os.path.islink(path) and inside(os.path.realpath(path), tc_root):
                    rmtree_agent(os.path.realpath(path))
            removed.append(path)

    # 2. Go downloaded toolchains & stale module cache (~/go/pkg/mod)
    gomod_dir = os.path.join(RUNNER_HOME, "go", "pkg", "mod")
    if os.path.isdir(gomod_dir) and not os.path.islink(gomod_dir):
        gomod_root = os.path.realpath(gomod_dir)
        ref_go = _referenced_go_versions()
        golang_org = os.path.join(gomod_root, "golang.org")
        if os.path.isdir(golang_org) and not os.path.islink(golang_org):
            for entry in sorted(os.listdir(golang_org)):
                if not entry.startswith("toolchain@"):
                    continue
                tpath = os.path.join(golang_org, entry)
                if os.path.islink(tpath) or not os.path.isdir(tpath):
                    continue
                if any(f"-go{v}." in entry for v in ref_go):
                    continue
                if now - os.lstat(tpath).st_mtime < 86400:
                    continue
                if not dry_run:
                    rmtree_agent(os.path.realpath(tpath))
                removed.append(tpath)

        dl_dir = os.path.join(gomod_root, "cache", "download")
        if os.path.isdir(dl_dir) and not os.path.islink(dl_dir):
            for dirpath, _, filenames in os.walk(dl_dir, onerror=lambda _e: None):
                for fname in filenames:
                    fpath = os.path.join(dirpath, fname)
                    try:
                        st = os.lstat(fpath)
                    except OSError:
                        continue
                    if stat.S_ISREG(st.st_mode) and not stat.S_ISLNK(st.st_mode) and max(st.st_atime, st.st_mtime) < cutoff:
                        real = os.path.realpath(fpath)
                        if inside(real, gomod_root):
                            if not dry_run:
                                unblock_dir(os.path.dirname(real))
                                os.remove(real)
                            removed.append(real)

        for dirpath, dirnames, _ in os.walk(gomod_root, topdown=True, onerror=lambda _e: None):
            if dirpath == gomod_root:
                dirnames[:] = [d for d in dirnames if d != "cache"]
            keep_walk: list[str] = []
            for dname in sorted(dirnames):
                dpath = os.path.join(dirpath, dname)
                if os.path.islink(dpath):
                    continue
                if "@" in dname and not dname.startswith("toolchain@"):
                    if _tree_newest_timestamp(dpath) < cutoff:
                        real = os.path.realpath(dpath)
                        if inside(real, gomod_root):
                            if not dry_run:
                                unblock_dir(os.path.dirname(real))
                                rmtree_agent(real)
                            removed.append(real)
                    continue
                keep_walk.append(dname)
            dirnames[:] = keep_walk

    # 3. Cargo global cache (~/.cargo/.global-cache SQLite tracker)
    cargo_dir = os.path.join(RUNNER_HOME, ".cargo")
    cargo_db = _safe_sqlite_path(cargo_dir, ".global-cache")
    if cargo_db is not None:
        cargo_root = os.path.realpath(cargo_dir)
        try:
            with closing(sqlite3.connect(cargo_db, timeout=30.0)) as conn:
                indices = (
                    {int(r[0]): str(r[1]) for r in conn.execute("SELECT id, name FROM registry_index")}
                    if _table_exists(conn, "registry_index")
                    else {}
                )
                if _table_exists(conn, "registry_crate"):
                    stale_crates = conn.execute(
                        "SELECT registry_id, name FROM registry_crate WHERE timestamp < ?", (int(cutoff),)
                    ).fetchall()
                    for reg_id, crate_name in stale_crates:
                        idx_name = indices.get(int(reg_id), "")
                        if idx_name and isinstance(crate_name, str) and "/" not in crate_name and ".." not in crate_name:
                            cpath = os.path.join(cargo_root, "registry", "cache", idx_name, crate_name)
                            if os.path.lexists(cpath) and not os.path.islink(cpath):
                                real = os.path.realpath(cpath)
                                if os.path.isfile(real) and inside(real, cargo_root):
                                    if not dry_run:
                                        os.remove(real)
                                    removed.append(real)
                        if not dry_run:
                            with conn:
                                conn.execute(
                                    "DELETE FROM registry_crate WHERE registry_id = ? AND name = ?",
                                    (reg_id, crate_name),
                                )
                if _table_exists(conn, "registry_src"):
                    stale_srcs = conn.execute(
                        "SELECT registry_id, name FROM registry_src WHERE timestamp < ?", (int(cutoff),)
                    ).fetchall()
                    for reg_id, src_name in stale_srcs:
                        idx_name = indices.get(int(reg_id), "")
                        if idx_name and isinstance(src_name, str) and "/" not in src_name and ".." not in src_name:
                            spath = os.path.join(cargo_root, "registry", "src", idx_name, src_name)
                            if os.path.lexists(spath) and not os.path.islink(spath):
                                real = os.path.realpath(spath)
                                if os.path.isdir(real) and inside(real, cargo_root):
                                    if not dry_run:
                                        rmtree_agent(real)
                                    removed.append(real)
                        if not dry_run:
                            with conn:
                                conn.execute(
                                    "DELETE FROM registry_src WHERE registry_id = ? AND name = ?",
                                    (reg_id, src_name),
                                )
        except sqlite3.Error as exc:
            log.warning("cargo .global-cache cleanup failed: %s", exc)

    # 4. Bun install cache, golangci-lint, ms-playwright
    for rel_cache in (
        os.path.join(".bun", "install", "cache"),
        os.path.join(".cache", "golangci-lint"),
        os.path.join(".cache", "ms-playwright"),
    ):
        cdir = os.path.join(RUNNER_HOME, rel_cache)
        if not os.path.isdir(cdir) or os.path.islink(cdir):
            continue
        croot = os.path.realpath(cdir)
        for entry in sorted(os.listdir(croot)):
            epath = os.path.join(croot, entry)
            if os.path.islink(epath):
                continue
            if _tree_newest_timestamp(epath) >= cutoff:
                continue
            real = os.path.realpath(epath)
            if not inside(real, croot):
                continue
            if not dry_run:
                if os.path.isdir(real):
                    rmtree_agent(real)
                elif os.path.isfile(real):
                    os.remove(real)
            removed.append(real)

    # 5. npm _cacache + npm cache verify
    npm_cache = os.path.join(RUNNER_HOME, ".npm", "_cacache")
    if os.path.isdir(npm_cache) and not os.path.islink(npm_cache):
        npm_root = os.path.realpath(npm_cache)
        npm_removed = 0
        for sub in ("content-v2", "index-v5"):
            sdir = os.path.join(npm_root, sub)
            if not os.path.isdir(sdir) or os.path.islink(sdir):
                continue
            for dirpath, _, filenames in os.walk(sdir, onerror=lambda _e: None):
                for fname in filenames:
                    fpath = os.path.join(dirpath, fname)
                    try:
                        st = os.lstat(fpath)
                    except OSError:
                        continue
                    if stat.S_ISREG(st.st_mode) and not stat.S_ISLNK(st.st_mode) and max(st.st_atime, st.st_mtime) < cutoff:
                        real = os.path.realpath(fpath)
                        if inside(real, npm_root):
                            if not dry_run:
                                os.remove(real)
                            removed.append(real)
                            npm_removed += 1
        if npm_removed > 0 and not dry_run:
            npm_bin = NPM_BIN if os.path.isabs(NPM_BIN) else shutil.which(NPM_BIN)
            if npm_bin and os.path.exists(npm_bin):
                try:
                    subprocess.run(
                        [npm_bin, "cache", "verify"],
                        env={**os.environ, "HOME": RUNNER_HOME},
                        capture_output=True,
                        text=True,
                        timeout=CACHE_CMD_TIMEOUT,
                        check=False,
                    )
                except (OSError, subprocess.SubprocessError):
                    pass

    # 6. HAPI old runtime bundles & old logs
    if os.path.isdir(HAPI_HOME) and not os.path.islink(HAPI_HOME):
        hapi_root = os.path.realpath(HAPI_HOME)
        rt_dir = os.path.join(hapi_root, "runtime")
        if os.path.isdir(rt_dir) and not os.path.islink(rt_dir):
            active_ver: str | None = None
            if os.path.exists(HAPI_BIN):
                try:
                    res = subprocess.run([HAPI_BIN, "--version"], capture_output=True, text=True, timeout=10, check=False)
                    m = re.search(r"([0-9]+\.[0-9]+\.[0-9]+)", res.stdout or "")
                    if m:
                        active_ver = m.group(1)
                except (OSError, subprocess.SubprocessError):
                    pass
            entries = [
                e for e in sorted(os.listdir(rt_dir))
                if not os.path.islink(os.path.join(rt_dir, e)) and os.path.isdir(os.path.join(rt_dir, e))
            ]
            if active_ver is None and entries:
                active_ver = max(entries, key=lambda e: os.lstat(os.path.join(rt_dir, e)).st_mtime)
            for entry in entries:
                if entry == active_ver:
                    continue
                epath = os.path.join(rt_dir, entry)
                if now - os.lstat(epath).st_mtime < 86400:
                    continue
                real = os.path.realpath(epath)
                if inside(real, hapi_root):
                    if not dry_run:
                        rmtree_agent(real)
                    removed.append(real)

        logs_dir = os.path.join(hapi_root, "logs")
        if os.path.isdir(logs_dir) and not os.path.islink(logs_dir):
            live_pid: int | None = None
            state_file = os.path.join(hapi_root, "runner.state.json")
            if os.path.isfile(state_file) and not os.path.islink(state_file):
                try:
                    with open(state_file, encoding="utf-8") as handle:
                        sdata = json.load(handle)
                    if isinstance(sdata, dict) and isinstance(sdata.get("pid"), int):
                        live_pid = sdata["pid"]
                except (OSError, ValueError):
                    pass
            for entry in sorted(os.listdir(logs_dir)):
                if not entry.endswith(".log"):
                    continue
                if live_pid is not None and f"-pid-{live_pid}-" in entry:
                    continue
                lpath = os.path.join(logs_dir, entry)
                try:
                    st = os.lstat(lpath)
                except OSError:
                    continue
                if stat.S_ISREG(st.st_mode) and not stat.S_ISLNK(st.st_mode) and st.st_mtime < log_cutoff:
                    real = os.path.realpath(lpath)
                    if inside(real, hapi_root):
                        if not dry_run:
                            os.remove(real)
                        removed.append(real)

    # 7. Stale go-build temp dirs (>24h) left inside <worktree>/bin/.go-tmp
    for wt_path in sorted(_live_worktree_paths()):
        go_tmp = os.path.join(wt_path, "bin", ".go-tmp")
        if not os.path.isdir(go_tmp) or os.path.islink(go_tmp):
            continue
        gt_root = os.path.realpath(go_tmp)
        if not inside(gt_root, os.path.realpath(CHECKOUTS)):
            continue
        for entry in sorted(os.listdir(gt_root)):
            if not entry.startswith("go-build"):
                continue
            epath = os.path.join(gt_root, entry)
            try:
                st = os.lstat(epath)
            except OSError:
                continue
            if stat.S_ISLNK(st.st_mode) or now - st.st_mtime < 86400:
                continue
            real = os.path.realpath(epath)
            if inside(real, gt_root):
                if not dry_run:
                    if os.path.isdir(real):
                        rmtree_agent(real)
                    elif os.path.isfile(real):
                        os.remove(real)
                removed.append(real)
    return removed


def do_cleanup_caches(max_age_days: int = DEFAULT_CACHE_MAX_AGE_DAYS, *, dry_run: bool = False) -> dict:
    if not _is_int(max_age_days, low=1, high=365):
        raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "invalid max_age_days")
    if not isinstance(dry_run, bool):
        raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "invalid dry_run")
    try:
        orphans = sweep_orphan_worktree_state(dry_run=dry_run)
        caches = sweep_global_caches(max_age_days, dry_run=dry_run)
    except OSError as exc:
        raise PublisherError(HTTPStatus.INTERNAL_SERVER_ERROR, "cleanup_failed",
                             f"{exc.filename or ''}: {exc.strerror or exc}") from None
    log.info("cleaned caches max_age_days=%d dry_run=%s: orphans=%d caches=%d",
             max_age_days, dry_run, len(orphans), len(caches))
    return {"orphan_worktrees": orphans, "global_caches": caches}

def read_admin_file(admin: str, name: str) -> str | None:
    """Stripped contents of a regular file in a worktree admin dir; None when missing or not a regular file."""
    path = os.path.join(admin, name)
    if os.path.islink(path) or not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read(4096).strip()


def worktree_conflict(detail: str) -> PublisherError:
    return PublisherError(HTTPStatus.CONFLICT, "worktree_conflict", detail)


def admin_worktrees_root(base: str) -> str:
    """Resolved ``<base>/.git/worktrees`` (created when missing), confined to the checkouts root."""
    git_root = confined_root(os.path.join(base, ".git"))
    if not os.path.isdir(git_root):
        raise PublisherError(HTTPStatus.CONFLICT, "unsafe_path", f"{git_root} is not a git directory")
    admin_parent = os.path.join(git_root, "worktrees")
    if not os.path.lexists(admin_parent):
        os.mkdir(admin_parent, 0o700)
    admin_root = confined_root(admin_parent)
    if os.path.islink(admin_parent) or not os.path.isdir(admin_root) or not inside(admin_root, git_root):
        raise PublisherError(HTTPStatus.CONFLICT, "unsafe_path", f"{admin_parent} is not a worktrees directory")
    return admin_root


def linked_worktree_branch(base: str, path: str) -> str | None:
    """Branch checked out in ``path`` when it is a linked worktree of ``base`` whose admin dir names it back."""
    admin = worktree_admin_dir(path)
    if admin is None or not os.path.lexists(admin):
        return None
    admin_root = confined_root(os.path.join(base, ".git", "worktrees"))
    real_admin = os.path.realpath(admin)
    if os.path.islink(admin) or not os.path.isdir(real_admin) or not inside(real_admin, admin_root):
        raise PublisherError(HTTPStatus.CONFLICT, "unsafe_path", f"{admin} is not a worktree admin directory")
    gitdir = read_admin_file(real_admin, "gitdir")
    if gitdir is None or os.path.realpath(gitdir) != os.path.realpath(os.path.join(path, ".git")):
        return None
    head = read_admin_file(real_admin, "HEAD") or ""
    return head.removeprefix("ref: refs/heads/") if head.startswith("ref: refs/heads/") else None


def claim_branch(git_root: str, admin_root: str, name: str, branch: str) -> None:
    """What ``git worktree prune`` + ``git worktree add`` require before adding ``name`` on ``branch``.

    Refuses a branch checked out in the base clone or in a live worktree, and
    removes stale admin dirs (their worktree is gone) that hold the name or the
    branch, as prune would.
    """
    ref = f"ref: refs/heads/{branch}"
    if read_admin_file(git_root, "HEAD") == ref:
        raise worktree_conflict(f"{branch} is checked out in the base checkout")
    for entry in sorted(os.listdir(admin_root)):
        admin = os.path.join(admin_root, entry)
        if os.path.islink(admin) or not os.path.isdir(admin):
            continue
        holds_name, holds_branch = entry == name, read_admin_file(admin, "HEAD") == ref
        if not (holds_name or holds_branch):
            continue
        gitdir = read_admin_file(admin, "gitdir")
        if gitdir and os.path.lexists(gitdir):
            raise worktree_conflict(f"{branch} or {name} is in use by the worktree at {os.path.dirname(gitdir)}")
        rmtree_agent(admin)


def add_worktree(repo: str, base: str, path: str, name: str, branch: str, sha: str) -> None:
    """``git worktree add <path> <branch>`` without running git on the agent's checkout.

    The tree and index come from the private mirror (whose config is ours, so
    no agent-planted filter or fsmonitor runs); the admin dir and ``.git`` file
    are the layout git itself writes. ``locked`` keeps a concurrent
    ``git worktree prune`` off the admin dir until the tree is in place.
    """
    git_root = confined_root(os.path.join(base, ".git"))
    admin_root = admin_worktrees_root(base)
    claim_branch(git_root, admin_root, name, branch)
    admin = os.path.join(admin_root, name)
    os.mkdir(admin, 0o700)
    staging = tempfile.mkdtemp(prefix=f".publisher-restore-{name}-", dir=os.path.dirname(path))
    tree = os.path.join(staging, "tree")
    published = False
    try:
        locked = os.path.join(admin, "locked")
        for file_name, text in (("locked", "initializing"), ("commondir", "../.."),
                                ("gitdir", os.path.join(path, ".git")), ("HEAD", f"ref: refs/heads/{branch}")):
            with open(os.path.join(admin, file_name), "w", encoding="utf-8") as handle:
                handle.write(text + "\n")
        os.mkdir(tree, 0o700)
        result = run_git(["--git-dir", mirror_path(repo), "--work-tree", tree, "read-tree", "-u", "--reset", sha],
                         extra_env={"GIT_INDEX_FILE": os.path.join(admin, "index")})
        if result.returncode != 0:
            raise PublisherError(HTTPStatus.INTERNAL_SERVER_ERROR, "restore_failed", result.stderr)
        with open(os.path.join(tree, ".git"), "w", encoding="utf-8") as handle:
            handle.write(f"gitdir: {admin}\n")
        if os.path.lexists(path):
            raise worktree_conflict(f"{path} appeared during the restore")
        os.rename(tree, path)
        published = True
        os.remove(locked)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        if not published:
            shutil.rmtree(admin, ignore_errors=True)


def do_worktree_restore(repo: str, name: str, branch: str) -> dict:
    """Re-create the HAPI worktree ``name`` on its retained ``branch`` (never moving the branch)."""
    base = checkout_path(repo)
    worktrees_dir = base + "-worktrees"
    try:
        if not os.path.lexists(worktrees_dir) and os.path.isdir(base):
            os.mkdir(worktrees_dir, 0o700)
        worktrees_root = confined_root(worktrees_dir)
        path = os.path.join(worktrees_root, name)
        if os.path.lexists(path):
            if os.path.islink(path) or not os.path.isdir(path):
                raise PublisherError(HTTPStatus.CONFLICT, "unsafe_path", f"{path} is not a worktree directory")
            current = linked_worktree_branch(base, path)
            if current != branch:
                raise worktree_conflict(f"{path} is not a worktree of {repo} on {branch} (found {current})")
            already = True
        else:
            try:
                sha = fetch_branch(repo, branch)
            except PublisherError as exc:
                if exc.error in ("checkout_missing", "branch_missing"):
                    return {"restored": False, "reason": "no_branch"}
                raise
            add_worktree(repo, base, path, name, branch, sha)
            already = False
    except OSError as exc:
        raise PublisherError(HTTPStatus.INTERNAL_SERVER_ERROR, "restore_failed",
                             f"{exc.filename or ''}: {exc.strerror or exc}") from None
    # As /checkout does before a spawn: the session must not load the repository's .codex/ layer.
    untrust_checkout(base)
    log.info("restored %s worktree=%s branch=%s already=%s", repo, name, branch, already)
    return {"restored": True, "path": path, "already": already}


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
        payload = {"error": exc.error, "detail": exc.detail}
        candidate = exc.artifact_error
        if (isinstance(candidate, dict) and set(candidate) == {"relpath", "field", "expected", "actual"}
                and exc.error in {"artifact_mismatch", "source_sha_mismatch"}):
            safe = visual_artifact_error(candidate["relpath"], candidate["field"],
                                         candidate["expected"], candidate["actual"])
            if safe is not None:
                payload["artifact_error"] = safe
        self.reply(exc.status, payload)

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

    def body(self, fields: dict[str, re.Pattern], *, optional: dict[str, re.Pattern] | None = None,
             nullable: tuple[str, ...] = (),
             lists: dict[str, re.Pattern] | None = None, ints: tuple[str, ...] = (),
             objects: tuple[str, ...] = (), booleans: tuple[str, ...] = (),
             max_body: int = MAX_BODY) -> dict:
        """Validated JSON body: ``fields`` are required strings, ``optional`` strings are optional,
        ``lists`` string arrays, ``ints`` positive integers, and ``booleans`` actual JSON booleans."""
        lists = lists or {}
        optional = optional or {}
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            raise PublisherError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "invalid_request", "Content-Type must be application/json")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            raise PublisherError(HTTPStatus.LENGTH_REQUIRED, "invalid_request", "Content-Length required") from None
        if length < 0 or length > max_body:
            raise PublisherError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "invalid_request", "body too large")
        try:
            data = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError):
            raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "body is not valid JSON") from None
        if not isinstance(data, dict):
            raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "body must be a JSON object")
        unknown = sorted(set(data) - set(fields) - set(optional) - set(lists) - set(ints) - set(objects) - set(booleans))
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
        for name, pattern in optional.items():
            if name not in data:
                continue
            value = data[name]
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
        for name in booleans:
            if name in data and not isinstance(data[name], bool):
                raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", f"invalid {name}")
            values[name] = data.get(name, False)
        for name in objects:
            if name not in data:
                raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", f"missing {name}")
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
                args = self.body(
                    {"repo": REPO_RE, "branch": BRANCH_RE, "expected_sha": SHA_RE},
                    optional={"stale_sha": SHA_RE},
                )
                with repo_lock(args["repo"]):
                    self.reply(HTTPStatus.OK, do_push(
                        args["repo"], args["branch"], args["expected_sha"], args.get("stale_sha"),
                    ))
            elif self.path == "/visual-evidence":
                args = self.body(
                    {"repo": REPO_RE, "worktree": WORKTREE_RE, "head_sha": SHA_RE,
                     "base_sha": SHA_RE, "manifest_path": VISUAL_MANIFEST_PATH_RE,
                     "marker": re.compile(r"(?s).{1,200}"), "body": re.compile(r"(?s).{1,60000}")},
                    ints=("pr_number",), booleans=("reuse_existing",), nullable=("base_sha",),
                    max_body=MAX_VISUAL_MANIFEST_BYTES,
                )
                with repo_lock(args["repo"]):
                    self.reply(HTTPStatus.OK, do_visual_evidence(
                        args["repo"], args["worktree"], args["pr_number"], args["head_sha"],
                        args["marker"], args["body"], args["manifest_path"],
                        base_sha=args["base_sha"], reuse_existing=args["reuse_existing"],
                    ))
            elif self.path == "/cleanup":
                args = self.body(
                    {"repo": REPO_RE, "worktree": WORKTREE_RE, "branch": CLEANUP_BRANCH_RE},
                    nullable=("worktree", "branch"),
                    lists={"codex_session_ids": CODEX_ID_RE, "hapi_session_ids": HAPI_ID_RE},
                )
                with repo_lock(args["repo"]):
                    self.reply(HTTPStatus.OK, do_cleanup(
                        args["repo"], args["worktree"], args["branch"],
                        args["codex_session_ids"], args.get("hapi_session_ids", []),
                    ))
            elif self.path == "/cleanup/caches":
                args = self.body({}, ints=("max_age_days",), booleans=("dry_run",))
                self.reply(HTTPStatus.OK, do_cleanup_caches(
                    args["max_age_days"], dry_run=args.get("dry_run", False),
                ))
            elif self.path == "/worktree/restore":
                args = self.body({"repo": REPO_RE, "worktree": WORKTREE_RE, "branch": CLEANUP_BRANCH_RE})
                with repo_lock(args["repo"]):
                    self.reply(HTTPStatus.OK, do_worktree_restore(args["repo"], args["worktree"], args["branch"]))
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
