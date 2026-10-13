"""Tests for publisher.py worktree removal and the janitor prune request/status.

Run: python3 -m unittest apps/objects/issue-agent/runner/test_publisher.py
(as a non-root user: root ignores the permission bits these tests rely on).
"""

from __future__ import annotations

import http.client
import json
import os
import stat
import sys
import tempfile
import threading
import unittest
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import publisher  # noqa: E402

REPO = "isac322/krema"
TOKEN = "publisher-token"
NON_ROOT = unittest.skipIf(os.geteuid() == 0, "root bypasses permission bits")


def write(path: str, text: str = "x") -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def make_writable(root: str) -> None:
    """Undo test-made modes so the temp dir can be cleaned."""
    if not os.path.lexists(root):
        return
    for dirpath, dirnames, _ in os.walk(root):
        for name in dirnames:
            path = os.path.join(dirpath, name)
            if not os.path.islink(path):
                os.chmod(path, 0o700)
    if not os.path.islink(root):
        os.chmod(root, 0o700)


class CheckoutsCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.realpath(self.tmp.name)
        self.checkouts = os.path.join(self.root, "checkouts")
        self.outside = os.path.join(self.root, "outside")
        os.makedirs(self.checkouts)
        os.makedirs(self.outside)
        write(os.path.join(self.outside, "keep"), "keep")
        self.addCleanup(make_writable, self.root)
        patcher = patch.object(publisher, "CHECKOUTS", self.checkouts)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.base = os.path.join(self.checkouts, REPO)
        self.worktrees = self.base + "-worktrees"
        os.makedirs(os.path.join(self.base, ".git", "worktrees"))
        os.makedirs(self.worktrees)

    def linked_worktree(self, name: str) -> tuple[str, str]:
        """A `git worktree add` layout: worktree .git file -> <base>/.git/worktrees/<name>."""
        path = os.path.join(self.worktrees, name)
        admin = os.path.join(self.base, ".git", "worktrees", name)
        write(os.path.join(admin, "HEAD"), "ref: refs/heads/hapi-" + name)
        write(os.path.join(path, ".git"), f"gitdir: {admin}\n")
        write(os.path.join(path, "src", "main.rs"))
        return path, admin

    def assert_outside_intact(self) -> None:
        with open(os.path.join(self.outside, "keep"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "keep")

    def assert_error(self, error: str, func, *args) -> publisher.PublisherError:
        with self.assertRaises(publisher.PublisherError) as ctx:
            func(*args)
        self.assertEqual(ctx.exception.error, error)
        return ctx.exception


class RemoveWorktreeTest(CheckoutsCase):
    def test_linked_worktree_removes_admin_dir_and_tree(self) -> None:
        path, admin = self.linked_worktree("issue-7")
        removed = publisher.remove_worktree(REPO, "issue-7")
        self.assertEqual(removed, [admin, path])
        self.assertFalse(os.path.lexists(path))
        self.assertFalse(os.path.lexists(admin))

    def test_missing_worktree_is_a_no_op(self) -> None:
        self.assertEqual(publisher.remove_worktree(REPO, "issue-8"), [])

    def test_standalone_clone_git_directory_is_removed_with_the_worktree(self) -> None:
        path = os.path.join(self.worktrees, "issue-9")
        write(os.path.join(path, ".git", "HEAD"), "ref: refs/heads/main")
        write(os.path.join(path, ".git", "objects", "pack", "pack-1.pack"))
        write(os.path.join(path, "README.md"))
        removed = publisher.remove_worktree(REPO, "issue-9")
        self.assertEqual(removed, [path])
        self.assertFalse(os.path.lexists(path))
        self.assertTrue(os.path.isdir(os.path.join(self.base, ".git", "worktrees")))

    def test_symlinked_dot_git_is_refused(self) -> None:
        path = os.path.join(self.worktrees, "issue-10")
        os.makedirs(path)
        os.symlink(self.outside, os.path.join(path, ".git"))
        self.assert_error("unsafe_path", publisher.remove_worktree, REPO, "issue-10")
        self.assertTrue(os.path.isdir(path))
        self.assert_outside_intact()

    def test_symlinked_worktree_is_refused(self) -> None:
        os.symlink(self.outside, os.path.join(self.worktrees, "issue-11"))
        self.assert_error("unsafe_path", publisher.remove_worktree, REPO, "issue-11")
        self.assert_outside_intact()

    def test_gitdir_escaping_the_admin_root_is_refused(self) -> None:
        path = os.path.join(self.worktrees, "issue-12")
        write(os.path.join(path, ".git"), f"gitdir: {self.outside}\n")
        self.assert_error("unsafe_path", publisher.remove_worktree, REPO, "issue-12")
        self.assertTrue(os.path.isdir(path))
        self.assert_outside_intact()

    def test_symlink_inside_worktree_is_removed_not_followed(self) -> None:
        path, _ = self.linked_worktree("issue-13")
        os.symlink(self.outside, os.path.join(path, "escape"))
        publisher.remove_worktree(REPO, "issue-13")
        self.assertFalse(os.path.lexists(path))
        self.assert_outside_intact()

    @NON_ROOT
    def test_read_only_agent_dirs_are_made_writable(self) -> None:
        path, _ = self.linked_worktree("issue-14")
        modcache = os.path.join(path, "pkg", "mod", "example.com", "m@v1.0.0")
        write(os.path.join(modcache, "go.mod"), "module example.com/m")
        locked = os.path.join(path, "locked")
        write(os.path.join(locked, "inner", "file"))
        for dirpath in (modcache, os.path.dirname(modcache), os.path.join(path, "pkg", "mod")):
            os.chmod(dirpath, 0o555)
        os.chmod(os.path.join(locked, "inner"), 0o000)
        os.chmod(locked, 0o000)
        publisher.remove_worktree(REPO, "issue-14")
        self.assertFalse(os.path.lexists(path))

    @NON_ROOT
    def test_rmtree_retries_after_chmod_on_eacces(self) -> None:
        # Without the pre-pass every blocked directory goes through onexc.
        path, _ = self.linked_worktree("issue-15")
        top = os.path.join(path, "a")
        write(os.path.join(top, "b", "file"))
        os.chmod(os.path.join(top, "b"), 0o500)
        os.chmod(top, 0o000)
        with patch.object(publisher, "restore_dir_modes", lambda _root: None):
            publisher.remove_worktree(REPO, "issue-15")
        self.assertFalse(os.path.lexists(path))

    @NON_ROOT
    def test_foreign_owned_directory_reports_foreign_owner(self) -> None:
        path, _ = self.linked_worktree("issue-16")
        foreign = os.path.join(path, "target")
        write(os.path.join(foreign, "debug", "app"))
        os.chmod(foreign, 0o555)
        real_lstat = os.lstat

        def lstat(target, *args, **kwargs):
            st = real_lstat(target, *args, **kwargs)
            if not kwargs.get("dir_fd") and os.fspath(target) == foreign:
                fields = list(st[:10])
                fields[stat.ST_UID] = 0
                return os.stat_result(fields)
            return st

        with patch.object(publisher.os, "lstat", lstat):
            exc = self.assert_error("foreign_owner", publisher.remove_worktree, REPO, "issue-16")
        self.assertEqual(exc.status, HTTPStatus.CONFLICT)
        self.assertIn(foreign, exc.detail)
        self.assertTrue(os.path.isdir(foreign))

    def test_foreign_owner_passes_through_cleanup_unchanged(self) -> None:
        with patch.object(publisher, "remove_worktree", side_effect=publisher.foreign_owner("/x", 0)):
            exc = self.assert_error("foreign_owner", publisher.do_cleanup, REPO, "issue-17", None, [])
        self.assertEqual(exc.status, HTTPStatus.CONFLICT)

    @NON_ROOT
    def test_unreadable_worktree_root_still_removes_admin_dir(self) -> None:
        path, admin = self.linked_worktree("issue-18")
        os.chmod(path, 0o000)
        removed = publisher.remove_worktree(REPO, "issue-18")
        self.assertEqual(removed, [admin, path])
        self.assertFalse(os.path.lexists(path))
        self.assertFalse(os.path.lexists(admin))

    def test_uninspectable_dot_git_raises_instead_of_absent(self) -> None:
        path, admin = self.linked_worktree("issue-19")
        real_lstat = os.lstat

        def lstat(target, *args, **kwargs):
            if os.fspath(target) == os.path.join(path, ".git"):
                raise PermissionError(13, "Permission denied", os.fspath(target))
            return real_lstat(target, *args, **kwargs)

        with patch.object(publisher.os, "lstat", lstat), self.assertRaises(PermissionError):
            publisher.remove_worktree(REPO, "issue-19")
        self.assertTrue(os.path.isdir(path))
        self.assertTrue(os.path.isdir(admin))


LEASE = 1791857734
STATUS = {"checked_at": 1791856534, "docker_used_pct": 73, "last_prune_at": 1791856000,
          "last_prune_lease": 1791856500, "last_prune_result": "ok"}


class PruneRequestTest(CheckoutsCase):
    def request_path(self) -> str:
        return os.path.join(self.checkouts, publisher.JANITOR_DIR, publisher.PRUNE_REQUEST)

    def test_writes_requested_at_and_lease_json(self) -> None:
        with patch.object(publisher.time, "time", return_value=1791856534.7):
            result = publisher.do_prune_request(LEASE)
        self.assertEqual(result, {"requested_at": 1791856534, "lease_until": LEASE})
        with open(self.request_path(), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), {"requested_at": 1791856534, "lease_until": LEASE})
        self.assertEqual(stat.S_IMODE(os.stat(self.request_path()).st_mode) & 0o077, 0)

    def test_rewrite_replaces_atomically_without_temp_leftovers(self) -> None:
        publisher.do_prune_request(LEASE)
        with patch.object(publisher.time, "time", return_value=2000000000):
            publisher.do_prune_request(2000001200)
        with open(self.request_path(), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), {"requested_at": 2000000000, "lease_until": 2000001200})
        self.assertEqual(os.listdir(os.path.dirname(self.request_path())), [publisher.PRUNE_REQUEST])

    def test_symlinked_janitor_dir_is_refused(self) -> None:
        os.symlink(self.outside, os.path.join(self.checkouts, publisher.JANITOR_DIR))
        self.assert_error("unsafe_path", publisher.do_prune_request, LEASE)
        self.assertEqual(os.listdir(self.outside), ["keep"])

    def test_symlinked_request_file_is_replaced_not_followed(self) -> None:
        janitor = os.path.join(self.checkouts, publisher.JANITOR_DIR)
        os.makedirs(janitor)
        os.symlink(os.path.join(self.outside, "keep"), self.request_path())
        publisher.do_prune_request(LEASE)
        self.assertFalse(os.path.islink(self.request_path()))
        self.assert_outside_intact()


class JanitorStatusTest(CheckoutsCase):
    def status_path(self) -> str:
        return os.path.join(self.checkouts, publisher.JANITOR_DIR, publisher.JANITOR_STATUS)

    def write_status(self, text: str) -> None:
        write(self.status_path(), text)

    def test_reads_the_status(self) -> None:
        self.write_status(json.dumps(STATUS))
        self.assertEqual(publisher.read_janitor_status(), STATUS)

    def test_nulls_are_allowed_and_extra_keys_dropped(self) -> None:
        status = {**STATUS, "last_prune_at": None, "last_prune_lease": None, "last_prune_result": None}
        self.write_status(json.dumps({**status, "extra": 1}))
        self.assertEqual(publisher.read_janitor_status(), status)

    def test_missing_status_is_no_status(self) -> None:
        exc = self.assert_error("no_status", publisher.read_janitor_status)
        self.assertEqual(exc.status, HTTPStatus.NOT_FOUND)
        os.makedirs(os.path.dirname(self.status_path()))
        self.assert_error("no_status", publisher.read_janitor_status)

    def test_malformed_status_is_no_status(self) -> None:
        for text in ("not json", "[]", json.dumps({**STATUS, "checked_at": "now"}),
                     json.dumps({**STATUS, "docker_used_pct": 101}), json.dumps({**STATUS, "checked_at": True}),
                     json.dumps({**STATUS, "last_prune_result": "skipped"}),
                     json.dumps({k: v for k, v in STATUS.items() if k != "docker_used_pct"}),
                     " " * (publisher.MAX_JANITOR_STATUS_BYTES + 1)):
            with self.subTest(text=text[:40]):
                self.write_status(text)
                self.assert_error("no_status", publisher.read_janitor_status)

    def test_symlinks_are_refused(self) -> None:
        write(os.path.join(self.outside, "status"), json.dumps(STATUS))
        os.makedirs(os.path.dirname(self.status_path()))
        os.symlink(os.path.join(self.outside, "status"), self.status_path())
        self.assert_error("no_status", publisher.read_janitor_status)
        os.unlink(self.status_path())
        os.rmdir(os.path.dirname(self.status_path()))
        os.symlink(self.outside, os.path.dirname(self.status_path()))
        self.assert_error("no_status", publisher.read_janitor_status)


class JanitorEndpointTest(CheckoutsCase):
    def setUp(self) -> None:
        super().setUp()
        token_file = os.path.join(self.root, "token")
        write(token_file, TOKEN)
        patcher = patch.object(publisher, "AUTH_TOKEN_FILE", token_file)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), publisher.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def call(self, method: str, path: str, body: bytes | None = None, token: str = TOKEN) -> tuple[int, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
        self.addCleanup(conn.close)
        headers = {"Authorization": f"Bearer {token}"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        return response.status, json.loads(response.read())

    def post(self, body: bytes, token: str = TOKEN) -> tuple[int, dict]:
        return self.call("POST", "/janitor/prune-request", body, token)

    def test_lease_writes_the_request(self) -> None:
        status, payload = self.post(json.dumps({"lease_until": LEASE}).encode())
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIsInstance(payload["requested_at"], int)
        self.assertEqual(payload["lease_until"], LEASE)
        with open(os.path.join(self.checkouts, publisher.JANITOR_DIR, publisher.PRUNE_REQUEST), encoding="utf-8") as h:
            self.assertEqual(json.load(h), payload)

    def test_missing_or_invalid_lease_is_refused(self) -> None:
        for body in (b"{}", b'{"lease_until": "soon"}', b'{"lease_until": true}', b'{"lease_until": 0}',
                     b'{"lease_until": 1.5}', b'{"lease_until": null}'):
            with self.subTest(body=body):
                status, payload = self.post(body)
                self.assertEqual((status, payload["error"]), (HTTPStatus.BAD_REQUEST, "invalid_request"))
        self.assertFalse(os.path.lexists(os.path.join(self.checkouts, publisher.JANITOR_DIR)))

    def test_wrong_token_is_refused(self) -> None:
        status, payload = self.post(json.dumps({"lease_until": LEASE}).encode(), token="nope")
        self.assertEqual((status, payload["error"]), (HTTPStatus.UNAUTHORIZED, "unauthorized"))
        self.assertFalse(os.path.lexists(os.path.join(self.checkouts, publisher.JANITOR_DIR)))

    def test_unknown_fields_are_refused(self) -> None:
        status, payload = self.post(json.dumps({"lease_until": LEASE, "force": True}).encode())
        self.assertEqual((status, payload["error"]), (HTTPStatus.BAD_REQUEST, "invalid_request"))

    def test_status_is_served(self) -> None:
        write(os.path.join(self.checkouts, publisher.JANITOR_DIR, publisher.JANITOR_STATUS), json.dumps(STATUS))
        self.assertEqual(self.call("GET", "/janitor/status"), (HTTPStatus.OK, STATUS))

    def test_status_requires_the_token(self) -> None:
        write(os.path.join(self.checkouts, publisher.JANITOR_DIR, publisher.JANITOR_STATUS), json.dumps(STATUS))
        status, payload = self.call("GET", "/janitor/status", token="nope")
        self.assertEqual((status, payload["error"]), (HTTPStatus.UNAUTHORIZED, "unauthorized"))

    def test_missing_status_is_404_no_status(self) -> None:
        status, payload = self.call("GET", "/janitor/status")
        self.assertEqual((status, payload["error"]), (HTTPStatus.NOT_FOUND, "no_status"))

    def test_healthz_needs_no_token(self) -> None:
        self.assertEqual(self.call("GET", "/healthz", token="nope"), (HTTPStatus.OK, {"ok": True}))


if __name__ == "__main__":
    unittest.main()
