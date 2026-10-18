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
  POST /worktree/restore {repo, worktree, branch} -> {restored, path, already} | {restored: false, reason}
  POST /visual-evidence {repo, worktree, pr_number, head_sha, allowed_source_shas, marker, body, artifacts}
                                             -> {created, ref_url, commit_url, assets, asset_urls}
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
import hmac
import glob
import hashlib
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
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PUBLISHER_PORT", "8090"))
AUTH_TOKEN_FILE = os.environ.get("PUBLISHER_TOKEN_FILE", "/run/issue-agent/publisher/token")
PUSH_TOKEN_FILE = os.environ.get("GITHUB_PUSH_TOKEN_FILE", "/run/issue-agent/push/token")
MAX_VISUAL_ARTIFACTS = 20
MAX_VISUAL_ARTIFACT_BYTES = 10 * 1024 * 1024
CHECKOUTS = os.environ.get("ISSUE_AGENT_CHECKOUTS", "/home/agent/checkouts")
CODEX_HOME = os.environ.get("CODEX_HOME", "/home/agent/.codex")
STATE_DIR = os.environ.get("PUBLISHER_STATE_DIR", "/var/lib/issue-agent-publisher")
GITHUB_API = "https://api.github.com"
MAX_BODY = 16 * 1024
CLONE_TIMEOUT = 1800
GIT_TIMEOUT = 600
PUSH_RETRY_DELAYS = (1.0, 2.0)
UNTRUST = "/opt/issue-agent/bin/codex-untrust"
UNTRUST_TIMEOUT = 60

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


def do_push(repo: str, branch: str, expected_sha: str) -> dict:
    token = read_secret(PUSH_TOKEN_FILE, "push token")
    sha = fetch_branch(repo, branch)
    # The caller resolved the branch first; refuse if it moved since.
    if sha != expected_sha:
        raise PublisherError(HTTPStatus.CONFLICT, "sha_mismatch", f"{branch} is at {sha}, expected {expected_sha}")

    push_args = [
        "--git-dir", mirror_path(repo),
        "push", "--quiet", "--porcelain", "--no-verify", "--",
        f"https://github.com/{repo}.git",
        f"{sha}:refs/heads/{branch}",
    ]
    for attempt in range(len(PUSH_RETRY_DELAYS) + 1):
        result = run_git(push_args, token=token)
        output = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
        if result.returncode == 0:
            break
        if any(marker in output for marker in ("non-fast-forward", "fetch first", "[rejected]", "stale info", "cannot lock ref", "failed to update ref")):
            raise PublisherError(HTTPStatus.CONFLICT, "non_fast_forward", output or "non-fast-forward")
        if attempt < len(PUSH_RETRY_DELAYS):
            time.sleep(PUSH_RETRY_DELAYS[attempt])
            continue
        raise PublisherError(HTTPStatus.BAD_GATEWAY, "push_failed", output or "git push failed")
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
            raise PublisherError(HTTPStatus.CONFLICT, "source_sha_mismatch", "artifact source_sha is not allowed")
        if (not isinstance(item["bytes"], int) or isinstance(item["bytes"], bool)
                or item["bytes"] <= 0 or item["bytes"] > MAX_VISUAL_ARTIFACT_BYTES):
            raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "invalid artifact size")
        if item["media_type"] not in VISUAL_MEDIA_TYPES:
            raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "invalid artifact media_type")
        if not isinstance(item["caption"], str) or not item["caption"].strip() or len(item["caption"]) > 500:
            raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "invalid artifact caption")
        path = visual_artifact_path(root, relpath)
        if path in seen_paths:
            raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "repeated artifact path")
        st = os.stat(path)
        if st.st_size != item["bytes"]:
            raise PublisherError(HTTPStatus.BAD_REQUEST, "artifact_mismatch", f"{relpath}: bytes")
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
            raise PublisherError(HTTPStatus.BAD_REQUEST, "artifact_mismatch", f"{relpath}: magic/MIME")
        if digest.hexdigest() != item["sha256"]:
            raise PublisherError(HTTPStatus.BAD_REQUEST, "artifact_mismatch", f"{relpath}: sha256")
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
            raise PublisherError(HTTPStatus.CONFLICT, "artifact_mismatch", f"{item['relpath']}: changed during publish")
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
                       body: str, artifacts: Any, allowed_source_shas: Any = None) -> dict[str, Any]:
    if not SHA_RE.fullmatch(head_sha) or not _is_int(pr_number):
        raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "invalid PR head")
    if allowed_source_shas is None:
        allowed_source_shas = [head_sha]
    if (not isinstance(allowed_source_shas, list) or not allowed_source_shas
            or len(allowed_source_shas) > MAX_CODEX_IDS
            or not all(isinstance(sha, str) and SHA_RE.fullmatch(sha) for sha in allowed_source_shas)):
        raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "invalid allowed_source_shas")
    marker = normalize_visual_marker(marker)
    if not isinstance(body, str) or not body.strip() or len(body) > 60000:
        raise PublisherError(HTTPStatus.BAD_REQUEST, "invalid_request", "invalid visual evidence body")
    root = visual_worktree_path(repo, worktree)
    if visual_worktree_head(root) != head_sha:
        raise PublisherError(HTTPStatus.CONFLICT, "worktree_head_mismatch", f"worktree HEAD is not {head_sha}")
    branch = f"hapi-{worktree}"
    if fetch_branch(repo, branch) != head_sha:
        raise PublisherError(HTTPStatus.CONFLICT, "worktree_head_mismatch", f"{branch} is not {head_sha}")
    mirror = ensure_mirror(repo)
    allowed = visual_verified_ancestor_sources(mirror, head_sha, artifacts, set(allowed_source_shas))
    validated = validate_visual_artifacts(root, artifacts, allowed)
    token = read_secret(PUSH_TOKEN_FILE, "push token")
    ref = visual_evidence_ref(pr_number, head_sha)
    marker_text = f"Marker: <!-- issue-agent:visual-evidence:{marker} -->"
    remote_commit, exists = visual_existing_ref(repo, ref, token, mirror)
    if exists:
        assert remote_commit is not None
        indexed: list[tuple[dict[str, Any], str, str]] = []
        for item, source in validated:
            result = run_git(["--git-dir", mirror, "hash-object", source])
            visual_git_error(result, "cannot inspect evidence blob")
            indexed.append((item, source, result.stdout.strip()))
        visual_verify_commit(mirror, remote_commit, head_sha, marker_text, indexed, pr_number)
        commit, created = remote_commit, False
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
        "created": created, "marker": marker, "ref": ref, "commit_sha": commit,
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
             lists: dict[str, re.Pattern] | None = None, ints: tuple[str, ...] = (),
             objects: tuple[str, ...] = (), max_body: int = MAX_BODY) -> dict:
        """Validated JSON body: ``fields`` are strings (None allowed for ``nullable``), ``lists`` string
        arrays, ``ints`` required positive integers."""
        lists = lists or {}
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
        unknown = sorted(set(data) - set(fields) - set(lists) - set(ints) - set(objects))
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
                args = self.body({"repo": REPO_RE, "branch": BRANCH_RE, "expected_sha": SHA_RE})
                with repo_lock(args["repo"]):
                    self.reply(HTTPStatus.OK, do_push(args["repo"], args["branch"], args["expected_sha"]))
            elif self.path == "/visual-evidence":
                args = self.body(
                    {"repo": REPO_RE, "worktree": WORKTREE_RE, "head_sha": SHA_RE,
                     "marker": re.compile(r"(?s).{1,200}"), "body": re.compile(r"(?s).{1,60000}")},
                    lists={"allowed_source_shas": SHA_RE}, ints=("pr_number",), objects=("artifacts",),
                    max_body=256 * 1024,
                )
                with repo_lock(args["repo"]):
                    self.reply(HTTPStatus.OK, do_visual_evidence(
                        args["repo"], args["worktree"], args["pr_number"], args["head_sha"],
                        args["marker"], args["body"], args["artifacts"], args["allowed_source_shas"],
                    ))
            elif self.path == "/cleanup":
                args = self.body({"repo": REPO_RE, "worktree": WORKTREE_RE, "branch": CLEANUP_BRANCH_RE},
                                 nullable=("worktree", "branch"), lists={"codex_session_ids": CODEX_ID_RE})
                with repo_lock(args["repo"]):
                    self.reply(HTTPStatus.OK, do_cleanup(args["repo"], args["worktree"], args["branch"],
                                                         args["codex_session_ids"]))
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
