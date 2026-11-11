#!/usr/bin/env python3
"""Real CodeGraph 1.6.2 lifecycle regression, Linux runner, Python stdlib only.

Run outside production: python3 test_codegraph_lifecycle.py --codegraph
/usr/local/bin/codegraph --scratch /tmp/unique-empty-lifecycle-directory

The scratch path MUST NOT exist. It is retained with JSONL evidence and a cleanup
ledger. On exit only processes carrying this run's private environment token are
terminated (pidfds protect against PID reuse); locks are never removed. No global
kill, index repair, package installation, or production RPC is used. An unpatched
binary fails cold_shared_lifecycle with cold_topology_missing_daemon; it cannot
pass merely because its direct engine eventually opens a new index.
"""

import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import queue
import re
import select
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import uuid


TOOLS = {"codegraph_" + name for name in (
    "search", "node", "callers", "callees", "impact", "explore")}
TOKEN_KEY = "CODEGRAPH_LIFECYCLE_TEST_OWNER"
SEARCH_DECLARATION = re.compile(
    r"^\*\*([^\n*]+)\*\* \([^\n)]+\)\nfixture\.js:\d+(?=\n|$)",
    re.MULTILINE,
)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def ready(status, root, expected_head, current_head, dirty):
    """The review gate, deliberately stronger than schema/CLI exit success."""
    index = status.get("index", {})
    pending = status.get("pendingChanges", {})
    return (
        status.get("initialized") is True
        and Path(status.get("projectPath", "/")).resolve() == root.resolve()
        and "worktreeMismatch" in status and status["worktreeMismatch"] is None
        and index.get("state") == "complete"
        and index.get("reindexRecommended") is False
        and all(pending.get(k) == 0 for k in ("added", "modified", "removed"))
        and current_head == expected_head and not dirty
    )


class Client:
    def __init__(self, suite, root, env=None):
        self.suite = suite
        self.root = root
        self.next_id = 0
        self.messages = queue.Queue()
        self.process = suite.spawn([suite.binary, "serve", "--mcp", "--path", str(root)], root, env)
        threading.Thread(target=self.read_loop, daemon=True).start()
        started = time.monotonic()
        self.initialization = self.call("initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "lifecycle-regression", "version": "1"},
        })
        self.notify("notifications/initialized", {})
        listing = self.call("tools/list", {})
        require({t["name"] for t in listing["tools"]} == TOOLS, "six-tool surface changed")
        suite.record("handshake", root=str(root), pid=self.process.pid,
                     seconds=time.monotonic() - started,
                     instructions=self.initialization.get("instructions", ""))

    def read_loop(self):
        try:
            for line in self.process.stdout:
                message = json.loads(line)
                if "method" in message and "id" in message:
                    # A real MCP server may ask the host for workspace roots.
                    result = {"roots": [{"uri": self.root.as_uri(), "name": self.root.name}]} if message["method"] == "roots/list" else None
                    response = {"jsonrpc": "2.0", "id": message["id"]}
                    if result is None:
                        response["error"] = {"code": -32601, "message": "Unsupported host method"}
                    else:
                        response["result"] = result
                    self.send(response)
                else:
                    self.messages.put(message)
        except Exception as error:
            self.messages.put(error)
        finally:
            self.messages.put(EOFError("MCP stdout closed"))

    def send(self, message):
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def notify(self, method, params):
        self.send({"jsonrpc": "2.0", "method": method, "params": params})

    def call(self, method, params):
        self.next_id += 1
        request_id = self.next_id
        self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + self.suite.timeout
        while True:
            message = self.messages.get(timeout=max(0.001, deadline - time.monotonic()))
            if isinstance(message, Exception):
                raise message
            if message.get("id") != request_id:
                require(time.monotonic() < deadline, "MCP response deadline expired")
                continue
            require("error" not in message, f"JSON-RPC error: {message}")
            return message["result"]

    def tool(self, name, **arguments):
        result = self.call("tools/call", {"name": name, "arguments": arguments})
        self.suite.record("tool", root=str(self.root), name=name, result=result)
        return result

    def search(self, symbol, present=True):
        result = self.tool("codegraph_search", query=symbol, projectPath=str(self.root))
        text = "\n".join(c.get("text", "") for c in result.get("content", []))
        require(not result.get("isError"), f"search failed: {text}")
        # Results must contain a declaration location, not an echoed query/error.
        found = any(match.group(1) == symbol for match in SEARCH_DECLARATION.finditer(text))
        require(found == present, f"unexpected symbol presence {symbol}: {text}")
        return text


class Suite:
    def __init__(self, args):
        require(sys.platform.startswith("linux") and hasattr(os, "pidfd_open")
                and hasattr(signal, "pidfd_send_signal"), "requires Linux Python with pidfd support")
        self.binary = str(Path(args.codegraph).absolute())
        require(os.access(self.binary, os.X_OK), "--codegraph must be an installed executable")
        self.scratch = Path(args.scratch).absolute()
        require(not any((parent / ".git").exists() or (parent / ".codegraph").exists()
                        for parent in self.scratch.parents),
                "--scratch must be outside existing Git and CodeGraph roots")
        self.scratch.mkdir(mode=0o700, parents=False, exist_ok=False)
        self.token = uuid.uuid4().hex
        self.timeout = args.timeout
        self.processes = []
        self.captured = {}
        self.ledger = self.scratch / "cleanup-ledger.jsonl"
        self.events = self.scratch / "evidence.jsonl"
        self.ledger_entry("directory", str(self.scratch), "Retained; remove only after caller cleanup approval")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("CODEGRAPH_")}
        home = self.scratch / "home"
        home.mkdir()
        tmp = self.scratch / "tmp"
        tmp.mkdir()
        self.env.update({"HOME": str(home), "XDG_CACHE_HOME": str(home / ".cache"),
                         "XDG_CONFIG_HOME": str(home / ".config"), "TMPDIR": str(tmp),
                         "CODEGRAPH_NO_DOWNLOAD": "1", TOKEN_KEY: self.token,
                         "CODEGRAPH_MCP_TOOLS": "search,node,callers,callees,impact,explore",
                         "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
                         "GIT_TERMINAL_PROMPT": "0"})
        print(json.dumps({"cleanup_ledger": str(self.ledger), "scratch": str(self.scratch)}), flush=True)

    def ledger_entry(self, kind, identifier, cleanup):
        with self.ledger.open("a") as file:
            file.write(json.dumps({"kind": kind, "identifier": identifier,
                                   "created_at": time.time(), "cleanup": cleanup}) + "\n")

    def record(self, event, **data):
        with self.events.open("a") as file:
            file.write(json.dumps({"event": event, "at": time.time(), **data}) + "\n")

    def spawn(self, command, cwd, extra=None):
        env = {**self.env, **(extra or {})}
        log = self.scratch / f"process-{len(self.processes)}.stderr"
        with log.open("w") as stderr:
            process = subprocess.Popen(command, cwd=cwd, env=env, text=True,
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=stderr, start_new_session=True, bufsize=1)
        self.processes.append(process)
        self.ledger_entry("process", str(process.pid), "Close owned stdin; pidfd signal only with matching private owner token")
        return process

    def run(self, command, root=None, extra=None, check=True):
        started = time.monotonic()
        process = self.spawn(command, root or self.scratch, extra)
        try:
            stdout, _ = process.communicate(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            self.record("command_timeout", command=command, pid=process.pid)
            raise
        self.record("command", command=command, returncode=process.returncode,
                    seconds=time.monotonic() - started, stdout=stdout)
        if check:
            require(process.returncode == 0, f"command failed ({process.returncode}): {command}")
        return process.returncode, stdout

    def git(self, root, *args):
        return self.run(["git", "-C", str(root), *args])[1].strip()

    def fixture(self, name, symbol="coldTarget", git=True):
        root = self.scratch / name
        root.mkdir()
        (root / ".gitignore").write_text(".codegraph/\n")
        (root / "fixture.js").write_text(f"export function {symbol}(value) {{ return value + 1; }}\nexport function caller(value) {{ return {symbol}(value); }}\n")
        if git:
            self.git(root, "init", "-q")
            self.commit(root, "fixture")
        return root

    def commit(self, root, message):
        self.git(root, "add", "fixture.js", ".gitignore")
        self.git(root, "-c", "user.name=Lifecycle Test", "-c", "user.email=lifecycle@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "-qm", message)
        return self.git(root, "rev-parse", "HEAD")

    def status(self, root):
        code, text = self.run([self.binary, "status", "--json", str(root)], check=False)
        if code:
            return {"status_error": code, "stdout": text}
        return json.loads(text)

    def assert_ready(self, root, head):
        status = self.status(root)
        current = self.git(root, "rev-parse", "HEAD") if head is not None else None
        dirty = self.git(root, "status", "--porcelain", "--untracked-files=all") if head is not None else ""
        require(ready(status, root, head, current, dirty), f"index not ready: {status}; dirty={dirty!r}")
        self.record("ready", root=str(root), head=head, status=status)
        return status

    def init(self, root):
        self.run([self.binary, "init", "--yes", str(root)])

    def capture_owned(self):
        # The private token is inherited by shim, bundled Node, daemon and workers.
        # Open pidfd BEFORE checking identity, so a later reused PID cannot be hit.
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit() or int(proc.name) in self.captured:
                continue
            pid = int(proc.name)
            fd = None
            try:
                fd = os.pidfd_open(pid)
                environment = (proc / "environ").read_bytes().split(b"\0")
                if f"{TOKEN_KEY}={self.token}".encode() not in environment:
                    os.close(fd)
                    continue
                self.captured[pid] = fd
                self.ledger_entry("owned-process", str(pid), "pidfd_send_signal after matching private owner token; never unlink locks")
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                if fd is not None and pid not in self.captured:
                    os.close(fd)

    def daemon(self, root):
        deadline = time.monotonic() + min(self.timeout, 15)
        while time.monotonic() < deadline:
            self.capture_owned()
            try:
                daemon = json.loads((root / ".codegraph/daemon.pid").read_text())
                writer = json.loads((root / ".codegraph/writer.pid").read_text())
                if daemon["pid"] == writer["pid"] and writer["mode"] == "daemon":
                    require(daemon["pid"] in self.captured, "daemon owner is not this harness")
                    self.record("daemon", root=str(root), daemon=daemon, writer=writer)
                    return daemon["pid"]
            except (FileNotFoundError, json.JSONDecodeError):
                pass
            time.sleep(0.05)
        raise AssertionError("cold_topology_missing_daemon: no native shared writer before target preparation")

    def cleanup(self):
        for process in self.processes:
            if process.poll() is None and process.stdin and not process.stdin.closed:
                process.stdin.close()
        # Discover detached children before their short-lived launchers disappear.
        self.capture_owned()
        for sig in (signal.SIGTERM, signal.SIGKILL):
            for fd in self.captured.values():
                try:
                    signal.pidfd_send_signal(fd, sig)
                except ProcessLookupError:
                    pass
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if not self.captured or len(select.select(list(self.captured.values()), [], [], 0)[0]) == len(self.captured):
                    break
                time.sleep(0.05)
        for process in self.processes:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.record("cleanup_error", pid=process.pid)
                raise AssertionError(f"owned process {process.pid} survived cleanup")
        for fd in self.captured.values():
            os.close(fd)
        survivors = []
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit():
                continue
            try:
                if f"{TOKEN_KEY}={self.token}".encode() in (proc / "environ").read_bytes().split(b"\0"):
                    survivors.append(int(proc.name))
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                pass
        require(not survivors, f"owned processes remain after cleanup: {survivors}")
        self.record("cleanup", retained_scratch=str(self.scratch), locks_unlinked=False)

    def cold_shared_lifecycle(self):
        root = self.fixture("cold")
        base = self.git(root, "rev-parse", "HEAD")
        main = Client(self, root)
        instructions = main.initialization.get("instructions", "")
        require("per-project; pass projectPath" in instructions,
                "cold initialize did not return truthful no-root instructions")
        children = [Client(self, root), Client(self, root)]
        owner = self.daemon(root)
        require(not (root / ".codegraph/codegraph.db").exists(), "MCP eagerly extracted before target checkout")
        missing = main.tool("codegraph_search", query="coldTarget", projectPath=str(root))
        require("codegraph init" in json.dumps(missing), "missing-index request lacks actionable guidance")
        require(not (root / ".codegraph/codegraph.db").exists(), "missing-index call initialized implicitly")
        (root / "fixture.js").write_text("export function reviewTarget(value) { return value + 2; }\nexport function caller(value) { return reviewTarget(value); }\n")
        head = self.commit(root, "verified review target")
        require(head != base, "fixture did not move HEAD")
        self.init(root)  # Extraction lock is separate from the live daemon's writer.pid.
        self.assert_ready(root, head)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda client: client.search("reviewTarget"), [main, *children]))
        require(self.daemon(root) == owner, "init or child discovery replaced native writer")
        main.search("coldTarget", present=False)
        alias = self.scratch / "cold-alias"
        alias.symlink_to(root, target_is_directory=True)
        Client(self, alias).search("reviewTarget")
        subdir = root / "subdir"
        subdir.mkdir()
        Client(self, subdir).search("reviewTarget")
        require(self.daemon(root) == owner, "canonical aliases split writer identity")
        self.run([self.binary, "sync", str(root)])
        self.assert_ready(root, head)
        main.search("reviewTarget")
        require(self.daemon(root) == owner, "warm CLI sync changed writer")
        # HEAD-only and dirty-source gates reject stale readiness even if a watcher
        # is fast enough to reconcile between status and this assertion.
        current_status = self.status(root)
        require(not ready(current_status, root, base, head, ""), "HEAD drift accepted")
        (root / "fixture.js").write_text("export function changedTarget(value) { return value + 3; }\n")
        require(not ready(self.status(root), root, head, head, self.git(root, "status", "--porcelain")), "dirty review source accepted")
        changed = self.commit(root, "changed review head")
        self.run([self.binary, "sync", str(root)])
        self.assert_ready(root, changed)
        main.search("changedTarget")
        main.search("reviewTarget", present=False)
        require(self.daemon(root) == owner, "changed-head CLI sync changed writer")

    def linked_worktree_isolation(self):
        root = self.fixture("linked-main", "mainOnly")
        linked = self.scratch / "linked-child"
        self.git(root, "worktree", "add", "--detach", str(linked), "HEAD")
        (linked / "fixture.js").write_text("export function linkedOnly(value) { return value + 7; }\n")
        child_head = self.commit(linked, "linked target")
        clients = [Client(self, root), Client(self, linked)]
        owners = [self.daemon(root), self.daemon(linked)]
        require(owners[0] != owners[1], "linked worktrees shared a daemon")
        for directory, head in ((root, self.git(root, "rev-parse", "HEAD")), (linked, child_head)):
            self.init(directory)
            self.assert_ready(directory, head)
        clients[0].search("mainOnly")
        clients[0].search("linkedOnly", present=False)
        clients[1].search("linkedOnly")
        clients[1].search("mainOnly", present=False)

    def direct_and_unsafe(self):
        nongit = self.fixture("nongit", git=False)
        client = Client(self, nongit)
        result = client.tool("codegraph_search", query="coldTarget", projectPath=str(nongit))
        require("codegraph init" in json.dumps(result), "nongit missing-index guidance changed")
        require(not (nongit / ".codegraph").exists(), "nongit cold startup created daemon state")
        # Existing indexed nongit projects must still select the original proxy.
        self.init(nongit)
        self.assert_ready(nongit, None)
        Client(self, nongit).search("coldTarget")
        self.daemon(nongit)
        optout = self.fixture("optout")
        direct = Client(self, optout, {"CODEGRAPH_NO_DAEMON": "1"})
        direct.tool("codegraph_search", query="coldTarget", projectPath=str(optout))
        require(not (optout / ".codegraph").exists(), "explicit daemon opt-out ignored")
        self.init(optout)
        direct.search("coldTarget")
        require(not (optout / ".codegraph/daemon.pid").exists(), "indexed opt-out spawned a daemon")
        writer = json.loads((optout / ".codegraph/writer.pid").read_text())
        require(writer["mode"] != "daemon", "opt-out lost direct ownership")
        unsafe = self.fixture("unsafe-home")
        client = Client(self, unsafe, {"HOME": str(unsafe)})
        client.tool("codegraph_search", query="coldTarget", projectPath=str(unsafe))
        artifacts = ("daemon.pid", "writer.pid", "daemon.sock", "codegraph.db")
        require(not any((unsafe / ".codegraph" / name).exists() for name in artifacts),
                "unsafe HOME Git root created daemon/index state")
        parent = self.fixture("unsafe-parent")
        home = parent / "home"
        home.mkdir()
        client = Client(self, parent, {"HOME": str(home)})
        client.tool("codegraph_search", query="coldTarget", projectPath=str(parent))
        require(not any((parent / ".codegraph" / name).exists() for name in artifacts),
                "ancestor-of-HOME root created daemon/index state")

    def invalid_partial_readiness(self):
        invalid = self.fixture("invalid")
        data = invalid / ".codegraph"
        data.mkdir()
        (data / "codegraph.db").write_bytes(b"deliberately invalid sqlite database\n")
        head = self.git(invalid, "rev-parse", "HEAD")
        require(not ready(self.status(invalid), invalid, head, head, ""), "invalid DB certified ready")
        # Real schema and status, then a crash-state fixture in an idle database.
        partial = self.fixture("partial")
        self.init(partial)
        head = self.git(partial, "rev-parse", "HEAD")
        self.assert_ready(partial, head)
        with sqlite3.connect(partial / ".codegraph/codegraph.db") as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(project_metadata)")}
            require({"key", "value", "updated_at"} <= columns, "pinned metadata schema changed")
            for state in ("partial", "indexing", "failed"):
                cursor = db.execute(
                    "UPDATE project_metadata SET value=?, updated_at=? WHERE key='index_state'",
                    (state, int(time.time() * 1000)),
                )
                require(cursor.rowcount == 1, "missing native index_state marker")
                db.commit()
                status = self.status(partial)
                require(status.get("index", {}).get("state") == state, f"native status hid {state}")
                require(not ready(status, partial, head, head, ""), f"{state} certified ready")
        # Deliberately race a real graph call with init. The CLI may report a
        # lock-contention failure; record that honestly and never equate a zero
        # exit or an early schema with readiness. This does not mock extraction.
        racing = self.fixture("init-in-flight", "inFlightTarget")
        head = self.git(racing, "rev-parse", "HEAD")
        client = Client(self, racing)
        self.daemon(racing)
        process = self.spawn([self.binary, "init", "--yes", str(racing)], racing)
        result = client.tool("codegraph_search", query="inFlightTarget", projectPath=str(racing))
        before_completion = self.status(racing)
        completed_at_observation = process.poll() is not None
        stdout, _ = process.communicate(timeout=self.timeout)
        status = self.status(racing)
        accepted = process.returncode == 0 and ready(status, racing, head,
                    self.git(racing, "rev-parse", "HEAD"), self.git(racing, "status", "--porcelain"))
        self.record("init_race", result=result, before_completion=before_completion,
                    completed_at_observation=completed_at_observation, returncode=process.returncode,
                    stdout=stdout, final_status=status, graph_evidence_accepted=accepted)
        if accepted:
            client.search("inFlightTarget")
        else:
            require(not ready(status, racing, head, head, ""),
                    "nonzero init result with ready status requires investigation")
            self.record("raw_source_fallback", root=str(racing), reason="init race did not establish readiness")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codegraph", required=True)
    parser.add_argument("--scratch", required=True, help="new path outside any existing repository; retained")
    parser.add_argument("--timeout", type=float, default=120, help="finite per-command/MCP deadline")
    parser.add_argument("--case", action="append", choices=("cold_shared_lifecycle", "linked_worktree_isolation", "direct_and_unsafe", "invalid_partial_readiness"))
    args = parser.parse_args()
    require(0 < args.timeout < 3600, "timeout must be positive and finite, below 3600s")
    suite = Suite(args)
    results = []
    try:
        _, version = suite.run([suite.binary, "--version"])
        require("1.6.2" in version, "harness targets pinned CodeGraph 1.6.2")
        for name in args.case or ("cold_shared_lifecycle", "linked_worktree_isolation", "direct_and_unsafe", "invalid_partial_readiness"):
            started = time.monotonic()
            try:
                getattr(suite, name)()
                result = {"case": name, "passed": True}
            except Exception as error:
                result = {"case": name, "passed": False, "error": f"{type(error).__name__}: {error}"}
            result["seconds"] = time.monotonic() - started
            results.append(result)
            suite.record("case", **result)
            print(json.dumps(result), flush=True)
    finally:
        try:
            suite.cleanup()
        except Exception as error:
            result = {"case": "owned_cleanup", "passed": False, "error": f"{type(error).__name__}: {error}"}
            results.append(result)
            suite.record("case", **result)
    passed = bool(results) and all(result["passed"] for result in results)
    print(json.dumps({"passed": passed, "cases": results, "evidence": str(suite.events),
                      "cleanup_ledger": str(suite.ledger), "retained_scratch": str(suite.scratch)}), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
