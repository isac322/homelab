"""Unit tests for the pure logic of issue-agent-review-audit (no gh wiring)."""
import importlib.machinery
import importlib.util
import os
import sys
import tempfile
import unittest

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "issue-agent-review-audit")
_LOADER = importlib.machinery.SourceFileLoader("issue_agent_review_audit", _PATH)
_SPEC = importlib.util.spec_from_loader(_LOADER.name, _LOADER)
audit = importlib.util.module_from_spec(_SPEC)
sys.modules[_LOADER.name] = audit
_LOADER.exec_module(audit)


def commit(sha, patch=None, path="f.py", is_merge=False, status="modified", **extra):
    entry = {"filename": path, "status": status, "changes": 1, **extra}
    if patch is not None:
        entry["patch"] = patch
    return {"sha": sha, "is_merge": is_merge, "files": {path: entry}}


def delete_at(line):
    return "@@ -%d +%d,0 @@\n-x" % (line, line - 1)


def insert_after(line, count=1):
    return "@@ -%d,0 +%d,%d @@\n" % (line, line + 1, count) + "\n".join("+y" for _ in range(count))


class HunkParsingTest(unittest.TestCase):
    PATCH = (
        "@@ -1,4 +1,5 @@ def f():\n a\n-b\n+B\n+B2\n c\n d\n"
        "@@ -10,0 +12,2 @@\n+x\n+y\n\\ No newline at end of file"
    )

    def test_hunk_fields(self):
        h1, h2 = audit.parse_patch(self.PATCH)
        self.assertEqual((h1.old_start, h1.old_count, h1.new_start, h1.new_count), (1, 4, 1, 5))
        self.assertEqual(h1.deleted, [2])
        self.assertEqual(h1.inserted_after, [2])
        self.assertEqual(h1.added_new, [2, 3])
        self.assertEqual(h1.context, {1: 1, 3: 4, 4: 5})
        self.assertEqual((h2.old_start, h2.old_count, h2.new_start, h2.new_count), (10, 0, 12, 2))
        self.assertEqual(h2.inserted_after, [10])
        self.assertEqual(h2.added_new, [12, 13])
        self.assertEqual(h2.old_span(), (10, 11))
        self.assertTrue(h1.text.startswith("@@ -1,4 +1,5 @@"))
        self.assertTrue(h1.text.endswith(" d"))

    def test_default_counts_and_trailing_garbage(self):
        (hunk,) = audit.parse_patch("@@ -3 +3 @@\n-x\n+y\nnot part of the hunk")
        self.assertEqual((hunk.old_count, hunk.new_count), (1, 1))
        self.assertEqual(hunk.deleted, [3])
        self.assertEqual(hunk.added_new, [3])

    def test_map_line(self):
        hunks = audit.parse_patch(self.PATCH)
        self.assertEqual(audit.map_line(1, hunks), 1)
        self.assertIsNone(audit.map_line(2, hunks))
        self.assertEqual(audit.map_line(3, hunks), 4)
        self.assertEqual(audit.map_line(5, hunks), 6)
        self.assertEqual(audit.map_line(10, hunks), 11)
        self.assertEqual(audit.map_line(11, hunks), 14)


class AnchorTrackingTest(unittest.TestCase):
    def test_shift_then_modify(self):
        result = audit.track_anchor("f.py", 10, 10, [
            commit("c1", "@@ -0,0 +1,2 @@\n+n1\n+n2"),
            commit("c2", "@@ -12 +12 @@\n-old\n+new"),
        ])
        self.assertEqual(result["positions"], {"c1": ("f.py", 10, 10), "c2": ("f.py", 12, 12)})
        self.assertEqual(result["changed"], {1: True, 5: True})
        self.assertTrue(result["file_changed_later"])

    def test_shift_only_is_not_a_change(self):
        result = audit.track_anchor("f.py", 10, 10, [commit("c1", "@@ -0,0 +1,2 @@\n+n1\n+n2"),
                                                     commit("c2", delete_at(30))])
        self.assertEqual(result["changed"], {1: False, 5: False})
        self.assertEqual(result["positions"]["c2"], ("f.py", 12, 12))

    def test_delete_ends_mapping(self):
        result = audit.track_anchor("f.py", 10, 10, [
            commit("c1", "@@ -9,3 +9,2 @@\n a\n-b\n c"),
            commit("c2", delete_at(10)),
        ])
        self.assertEqual(result["changed"], {1: True, 5: True})
        self.assertNotIn("c2", result["positions"])
        self.assertIn("anchor deleted", result["note"])

    def test_merge_commit_shifts_without_attribution(self):
        result = audit.track_anchor("f.py", 10, 10, [
            commit("m1", "@@ -9,0 +10,3 @@\n+a\n+b\n+c", is_merge=True),
            commit("c2", delete_at(20)),
        ])
        self.assertEqual(result["changed"], {1: False, 5: False})
        self.assertTrue(result["file_changed_later"])
        self.assertEqual(result["positions"]["c2"], ("f.py", 13, 13))
        result = audit.track_anchor("f.py", 10, 10, [
            commit("m1", "@@ -9,0 +10,3 @@\n+a\n+b\n+c", is_merge=True),
            commit("c2", delete_at(13)),
        ])
        self.assertEqual(result["changed"], {1: True, 5: True})
        merge_only = audit.track_anchor("f.py", 10, 10, [commit("m1", "@@ -9,0 +10,3 @@\n+a\n+b\n+c", is_merge=True)])
        self.assertEqual(merge_only["changed"], {1: False, 5: False})
        self.assertFalse(merge_only["file_changed_later"])

    def test_merge_commit_deleting_anchor_is_not_credited(self):
        result = audit.track_anchor("f.py", 10, 10, [commit("m1", delete_at(10), is_merge=True)])
        self.assertEqual(result["changed"], {1: False, 5: False})

    def test_rename_is_followed(self):
        result = audit.track_anchor("f.py", 10, 10, [
            {"sha": "r1", "is_merge": False, "files": {"g.py": {"filename": "g.py", "previous_filename": "f.py",
                                                                "status": "renamed", "changes": 0}}},
            commit("c2", delete_at(10), path="g.py"),
        ])
        self.assertEqual(result["changed"], {1: True, 5: True})

    def test_missing_patch_makes_signals_unknown(self):
        result = audit.track_anchor("f.py", 10, 10, [commit("c1", None)])
        self.assertEqual(result["changed"], {1: None, 5: None})
        self.assertTrue(result["file_changed_later"])

    def test_missing_diff_keeps_earlier_true(self):
        result = audit.track_anchor("f.py", 10, 10, [commit("c1", delete_at(11)), {"sha": "c2", "files": None}])
        self.assertEqual(result["changed"], {1: True, 5: True})

    def test_lineless_finding_only_gets_file_signal(self):
        result = audit.track_anchor("f.py", None, None, [commit("c1", delete_at(3))])
        self.assertEqual(result["changed"], {1: None, 5: None})
        self.assertTrue(result["file_changed_later"])
        result = audit.track_anchor("f.py", None, None, [commit("c1", delete_at(3), path="other.py")])
        self.assertFalse(result["file_changed_later"])

    def test_range_anchor(self):
        result = audit.track_anchor("f.py", 10, 12, [commit("c1", delete_at(14))])
        self.assertEqual(result["changed"], {1: False, 5: True})
        result = audit.track_anchor("f.py", 10, 12, [commit("c1", delete_at(11))])
        self.assertEqual(result["changed"], {1: True, 5: True})


class VicinityBoundaryTest(unittest.TestCase):
    def changed(self, patch):
        return audit.track_anchor("f.py", 10, 10, [commit("c1", patch)])["changed"]

    def test_deletion_boundaries(self):
        self.assertEqual(self.changed(delete_at(10)), {1: True, 5: True})
        self.assertEqual(self.changed(delete_at(11)), {1: True, 5: True})
        self.assertEqual(self.changed(delete_at(9)), {1: True, 5: True})
        self.assertEqual(self.changed(delete_at(12)), {1: False, 5: True})
        self.assertEqual(self.changed(delete_at(15)), {1: False, 5: True})
        self.assertEqual(self.changed(delete_at(5)), {1: False, 5: True})
        self.assertEqual(self.changed(delete_at(16)), {1: False, 5: False})
        self.assertEqual(self.changed(delete_at(4)), {1: False, 5: False})

    def test_insertion_boundaries(self):
        self.assertEqual(self.changed(insert_after(10)), {1: True, 5: True})
        self.assertEqual(self.changed(insert_after(11)), {1: True, 5: True})
        self.assertEqual(self.changed(insert_after(12)), {1: False, 5: True})
        self.assertEqual(self.changed(insert_after(15)), {1: False, 5: True})
        self.assertEqual(self.changed(insert_after(16)), {1: False, 5: False})
        self.assertEqual(self.changed(insert_after(4)), {1: False, 5: True})
        self.assertEqual(self.changed(insert_after(3)), {1: False, 5: False})


class BodyFindingTest(unittest.TestCase):
    BODY = (
        "**Verdict: BLOCKING** reviewed at abc\n\n"
        "## Blocking\n"
        "- **P1** `src/a.py:10`: race in x. Fix: lock.\n"
        "  continuation line\n"
        "- **P2 (unrefuted)** `src/b.py:20-22`: leak.\n"
        "- **P1** `src/c.py:50`: twin of an inline comment.\n\n"
        "## Non-blocking\n"
        "- **P3** general wording without a path.\n"
        "- **P3** `README.md`: doc.\n"
        "- **P3** `foo()` is not a path.\n\n"
        "## Previous findings\n"
        "- Closed: P1 `src/a.py:3` old thing. Fixed at `src/a.py:5`.\n"
        "- Open: P2 `src/z.py:7` Missing timeout on dial. Unchanged.\n"
    )

    def test_extraction_and_twin_dedupe(self):
        found = audit.extract_body_findings(self.BODY, [("src/c.py", None, 53), ("src/a.py", None, 14)])
        got = [(f["severity"], f["path"], f["start_line"], f["line"]) for f in found]
        self.assertEqual(got, [
            ("P1", "src/a.py", None, 10),
            ("P2", "src/b.py", 20, 22),
            ("P3", None, None, None),
            ("P3", "README.md", None, None),
            ("P3", None, None, None),
        ])
        self.assertIn("continuation line", found[0]["body"])
        self.assertTrue(found[0]["title"].startswith("**P1** `src/a.py:10`"))

    def test_twin_window_edge(self):
        body = "- **P1** `src/c.py:50`: x\n"
        self.assertEqual(audit.extract_body_findings(body, [("src/c.py", None, 53)]), [])
        self.assertEqual(len(audit.extract_body_findings(body, [("src/c.py", None, 54)])), 1)
        self.assertEqual(len(audit.extract_body_findings(body, [("src/other.py", None, 50)])), 1)
        self.assertEqual(audit.extract_body_findings(body, [("src/c.py", 40, 47)]), [])

    def test_inline_severity(self):
        self.assertEqual(audit.inline_severity("[P1] thing"), "P1")
        self.assertEqual(audit.inline_severity("**P2** thing"), "P2")
        self.assertEqual(audit.inline_severity("**[P0]** thing"), "P0")
        self.assertIsNone(audit.inline_severity("no tag P1"))

    def test_inline_severity_real_formats(self):
        real = ("P2: `before is None` also occurs when the assignment query times out or its reply is "
                "malformed. The script assigns `w.desktops` before reporting over D-Bus")
        self.assertEqual(audit.inline_severity(real), "P2")
        self.assertEqual(audit.inline_severity("P2: Include new same-scope owner PIDs in the stability comparison."),
                         "P2")
        self.assertEqual(audit.inline_severity("[P1] Refuse invocation when target discovery is incomplete."), "P1")
        self.assertEqual(audit.inline_severity("**[P1]** Title"), "P1")
        self.assertEqual(audit.inline_severity("**P2: Title**"), "P2")
        self.assertEqual(audit.inline_severity("**P2** text"), "P2")
        self.assertIsNone(audit.inline_severity("Please retain restoration ownership; this is a P2 risk."))
        self.assertIsNone(audit.inline_severity("P20 is not a severity"))

    def test_real_body_lines(self):
        en_dash = ("- **P1** `src/kwin_mcp/server.py:1195\u20131197`: if a client stops reading stdout while a "
                   "response writer fills the pipe, the watcher blocks in `stdout.flush()` after cleanup completes.")
        (found,) = audit.extract_body_findings(en_dash, [])
        self.assertEqual((found["severity"], found["path"], found["start_line"], found["line"]),
                         ("P1", "src/kwin_mcp/server.py", 1195, 1197))
        unbolded = ("- P2 `src/kwin_mcp/session.py:371`: restoration ownership is removed before the D-Bus "
                    "operation completes.")
        (found,) = audit.extract_body_findings(unbolded, [])
        self.assertEqual((found["severity"], found["path"], found["line"]), ("P2", "src/kwin_mcp/session.py", 371))
        not_findings = "\n".join([
            "- Closed: P1 cleanup errors bypassed forced exit.",
            "- **Closed:** P1 cleanup errors bypassed forced exit. `server.py:1191\u20131194` now catches cleanup exceptions.",
            "- **Closed \u2014 P2, misleading \u201cunchanged\u201d outcome:** assignment-response failures now "
            "explicitly warn that the window may already have moved (`src/kwin_mcp/core.py:1600`).",
            "- Open: P2 `src/z.py:7` Missing timeout on dial. Unchanged.",
            "- Reproduced the P2 case: a second same-scope owner PID introducing an identical-caption/size window "
            "leaves the initial mapping available.",
        ])
        self.assertEqual(audit.extract_body_findings(not_findings, []), [])

    def test_real_range_twin(self):
        en_dash = "- **P1** `src/kwin_mcp/server.py:1195\u20131197`: watcher blocks in `stdout.flush()`."
        self.assertEqual(audit.extract_body_findings(en_dash, [("src/kwin_mcp/server.py", None, 1197)]), [])
        self.assertEqual(audit.extract_body_findings(en_dash, [("src/kwin_mcp/server.py", None, 1200)]), [])
        self.assertEqual(audit.extract_body_findings(en_dash, [("src/kwin_mcp/server.py", None, 1192)]), [])
        self.assertEqual(len(audit.extract_body_findings(en_dash, [("src/kwin_mcp/server.py", None, 1201)])), 1)
        self.assertEqual(len(audit.extract_body_findings(en_dash, [("src/kwin_mcp/server.py", None, 1191)])), 1)

    def test_review_verdict(self):
        dismissed = ("## Previous findings\n- **Closed:** P1 cleanup errors bypassed forced exit.\n\n"
                     "**Verdict: GREEN** (PR-ready: false) re-reviewed at 0848f6338c32bbce8824cc9387384c2eba4e0934. "
                     "No blocking findings.")
        self.assertEqual(audit.review_verdict(dismissed, "DISMISSED"), "APPROVED")
        self.assertEqual(audit.review_verdict("**Verdict: BLOCKING** (PR-ready: false) reviewed at e923117",
                                              "DISMISSED"), "CHANGES_REQUESTED")
        self.assertEqual(audit.review_verdict("**Verdict: OPEN** reviewed at abc", "COMMENTED"), "COMMENTED")
        self.assertEqual(audit.review_verdict("", "DISMISSED"), "DISMISSED")

    def test_previous_finding_matcher(self):
        body = (
            "## Previous findings\n"
            "- **Closed:** P1 cleanup errors bypassed forced exit. The cleanup exception guard and independent "
            "directory-error handling remain intact.\n"
            "- **Closed:** P1 blocked output prevented forced exit. `_finish` no longer flushes stdout.\n\n"
            "**Verdict: GREEN** re-reviewed at 49c45008.\n"
        )
        items = audit.previous_findings(body)
        self.assertEqual([(s, sev) for s, sev, _ in items], [("Closed", "P1"), ("Closed", "P1")])
        first = {"severity": "P1", "path": "src/kwin_mcp/server.py",
                 "title": "[P1] Ensure fallback cleanup errors cannot bypass the final exit."}
        status, line = audit.match_previous_status(first, items)
        self.assertEqual(status, "Closed")
        self.assertIn("cleanup errors bypassed", line)
        second = {"severity": "P1", "path": "src/kwin_mcp/server.py",
                  "title": "[P1] Keep forced exit independent of blocked output streams."}
        self.assertIn("blocked output prevented", audit.match_previous_status(second, items)[1])
        other_severity = dict(first, severity="P2")
        self.assertEqual(audit.match_previous_status(other_severity, items), (None, None))
        unrelated = {"severity": "P1", "path": "src/kwin_mcp/core.py",
                     "title": "[P1] Refuse invocation when target discovery is incomplete."}
        self.assertEqual(audit.match_previous_status(unrelated, items), (None, None))
        prior = audit.previous_findings("## Prior findings\n- Open: P2 `src/z.py:7` Missing timeout on dial.\n")
        self.assertEqual(audit.match_previous_status({"severity": "P2", "path": "src/z.py", "title": "x"}, prior)[0],
                         "Open")


class WilsonTest(unittest.TestCase):
    def test_reference_values(self):
        lo, hi = audit.wilson(12, 20)
        self.assertAlmostEqual(lo, 0.387, places=3)
        self.assertAlmostEqual(hi, 0.781, places=3)
        lo, hi = audit.wilson(0, 10)
        self.assertAlmostEqual(lo, 0.0, places=9)
        self.assertAlmostEqual(hi, 0.278, places=3)
        lo, hi = audit.wilson(10, 10)
        self.assertAlmostEqual(lo, 0.722, places=3)
        self.assertAlmostEqual(hi, 1.0, places=9)
        self.assertEqual(audit.wilson(0, 0), (None, None))


class IdsAndTypesTest(unittest.TestCase):
    def test_content_addressed_candidate_ids(self):
        (hunk,) = audit.parse_patch("@@ -3,2 +3,4 @@\n a\n+b\n+c\n d")
        self.assertEqual(audit.hunk_candidate_id("o/r#1", "0123456789abcdef", "src/a.py", hunk),
                         "o/r#1/hunk/0123456789ab/src/a.py@-3,2+3,4")
        self.assertEqual(audit.hunk_candidate_id("o/r#1", "compare:" + "a" * 40 + "..." + "b" * 40, "x.py", None),
                         "o/r#1/hunk/cmp-aaaaaaaaaaaa-bbbbbbbbbbbb/x.py@nopatch")
        self.assertEqual(audit.comment_candidate_id("o/r#1", "review_comment", 42), "o/r#1/comment/review_comment/42")
        self.assertEqual(audit.postmerge_candidate_id("o/r#1", "f" * 40), "o/r#1/postmerge/ffffffffffff")
        self.assertEqual(audit.xref_candidate_id("o/r#1", "o/r", 7), "o/r#1/xref/o/r#7")

    def test_miss_row_ids(self):
        cand = "o/r#1/hunk/0123456789ab/src/a.py@-3,2+3,4"
        units = {"candidates": {cand: {"id": cand, "pr_id": "o/r#1"}}}
        head = "a" * 12
        self.assertEqual(audit.miss_base_id(cand + "@" + head), cand)
        self.assertEqual(audit.miss_base_id(cand), cand)
        self.assertEqual(audit.candidate_of(cand + ".2@" + head, units)["id"], cand)
        self.assertEqual(audit.candidate_of(cand + "@" + head, units)["id"], cand)
        self.assertEqual(audit.miss_pr_id("o/r#1/p3@" + head, units), "o/r#1")

    def test_author_and_file_types(self):
        self.assertEqual(audit.author_type("isac322"), "owner")
        self.assertEqual(audit.author_type("bulgasaribot[bot]"), "implementer_bot")
        self.assertEqual(audit.author_type("dependabot[bot]"), "automation")
        self.assertEqual(audit.author_type("someone"), "external")
        self.assertEqual(audit.file_type("src/kwin_mcp/server.py"), "code")
        self.assertEqual(audit.file_type("tests/test_server.py"), "test")
        self.assertEqual(audit.file_type("pkg/foo_test.go"), "test")
        self.assertEqual(audit.file_type("Dockerfile"), "build_config")
        self.assertEqual(audit.file_type(".github/workflows/ci.yml"), "build_config")
        self.assertEqual(audit.file_type("README.md"), "docs")
        self.assertIsNone(audit.file_type(None))


class EvidenceHorizonTest(unittest.TestCase):
    def test_keep_candidate_boundary(self):
        since, until = audit.parse_time("2026-10-11"), audit.parse_time("2026-10-18")
        collector = audit.Collector(None, "/nonexistent", since, until, "haechibot[bot]", 3)
        out = []
        base = {"kind": "human_comment", "anchor_at": "2026-10-12T00:00:00Z"}
        collector.keep_candidate(out, dict(base, id="a", event_at="2026-10-15T00:00:00Z"))
        collector.keep_candidate(out, dict(base, id="b", event_at="2026-10-15T00:00:01Z"))
        collector.keep_candidate(out, dict(base, id="c", anchor_at=None, event_at="2026-12-01T00:00:00Z"))
        self.assertEqual([c["id"] for c in out], ["a", "c"])
        self.assertEqual(out[0]["evidence_deadline"], "2026-10-15T00:00:00Z")
        self.assertEqual(collector.evidence_dropped["human_comment"], 1)


class FakeGh:
    """In-memory stand-in for Gh: canned responses keyed by endpoint path (query ignored)."""

    def __init__(self, routes):
        self.routes = routes
        self.errors = []

    def rest_obj(self, endpoint, paginate=False):
        return self.routes.get(endpoint.split("?")[0])

    def rest_list(self, endpoint, paginate=True):
        return self.routes.get(endpoint.split("?")[0], [])

    def review_threads(self, owner, name, number):
        return []


class CollectorSignalTest(unittest.TestCase):
    """Regression: single-line comments (start_line null) must get vicinity signals."""

    C1, C2 = "1" * 40, "2" * 40

    def collect(self):
        def commit(sha, parent, date):
            return {"sha": sha, "parents": [{"sha": parent}], "author": {"login": "isac322"},
                    "commit": {"committer": {"date": date}}}

        def comment(cid, login, review_id):
            return {"id": cid, "pull_request_review_id": review_id, "user": {"login": login}, "path": ".github/ci.yml",
                    "line": 139, "original_line": 139, "start_line": None, "original_start_line": None,
                    "side": "RIGHT", "body": "[P1] pin the action", "original_commit_id": self.C1,
                    "in_reply_to_id": None, "created_at": "2026-10-12T00:05:00Z"}

        routes = {
            "repos/o/r/pulls/1": {"number": 1, "title": "t", "user": {"login": "isac322"}, "state": "open",
                                  "merged_at": None, "head": {"sha": self.C2}, "base": {"ref": "main", "sha": "0" * 40},
                                  "additions": 1, "deletions": 1, "changed_files": 1},
            "repos/o/r/pulls/1/commits": [commit(self.C1, "0" * 40, "2026-10-11T23:00:00Z"),
                                          commit(self.C2, self.C1, "2026-10-12T01:00:00Z")],
            "repos/o/r/pulls/1/comments": [comment(100, "haechibot[bot]", 5), comment(101, "alice", 6)],
            "repos/o/r/commits/" + self.C2: {
                "sha": self.C2, "parents": [{"sha": self.C1}], "commit": {"committer": {"date": "2026-10-12T01:00:00Z"}},
                "files": [{"filename": ".github/ci.yml", "status": "modified", "changes": 2,
                           "patch": "@@ -139 +139 @@\n-uses: x@v1\n+uses: x@0123abcd"}]},
        }
        reviews = [{"id": 5, "user": {"login": "haechibot[bot]"}, "state": "CHANGES_REQUESTED", "commit_id": self.C1,
                    "submitted_at": "2026-10-12T00:00:00Z", "body": "**Verdict: BLOCKING** reviewed at 1111"},
                   {"id": 6, "user": {"login": "alice"}, "state": "COMMENTED", "commit_id": self.C1,
                    "submitted_at": "2026-10-12T00:05:00Z", "body": ""}]
        out = tempfile.mkdtemp()
        collector = audit.Collector(FakeGh(routes), out, audit.parse_time("2026-10-11"),
                                    audit.parse_time("2026-10-13"), "haechibot[bot]", 3,
                                    now=audit.parse_time("2026-10-20"))
        collector.collect_pr("o/r", 1, reviews)
        return collector

    def test_single_line_inline_finding_is_tracked(self):
        collector = self.collect()
        (finding,) = collector.findings
        self.assertIsNone(finding["start_line"])
        self.assertEqual(finding["vicinity_method"], "commit-walk")
        self.assertIs(finding["changed_in_vicinity_1"], True)
        self.assertIs(finding["changed_in_vicinity_5"], True)

    def test_single_line_human_comment_is_tracked(self):
        collector = self.collect()
        (human,) = [c for c in collector.candidates if c["kind"] == "human_comment" and c["author"] == "alice"]
        self.assertTrue(human["is_root_inline"])
        self.assertIs(human["changed_in_vicinity_1"], True)


class StatisticsTest(unittest.TestCase):
    def test_garwood_textbook(self):
        lo, hi = audit.garwood(3)
        self.assertAlmostEqual(lo, 0.619, places=3)
        self.assertAlmostEqual(hi, 8.767, places=3)
        lo, hi = audit.garwood(0)
        self.assertEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 3.689, places=3)

    def test_newcombe_published_example(self):
        # Newcombe (1998), example (a): 56/70 vs 48/80, method 10 -> 0.0524 to 0.3339.
        result = audit.newcombe_diff(48, 80, 56, 70)
        self.assertAlmostEqual(result["diff"], 0.2, places=9)
        self.assertAlmostEqual(result["ci95"][0], 0.0524, places=3)
        self.assertAlmostEqual(result["ci95"][1], 0.3339, places=3)
        self.assertTrue(result["changed"])

    def test_fisher_lady_tasting_tea(self):
        self.assertAlmostEqual(audit.fisher_exact(3, 1, 1, 3), 34 / 70, places=9)
        self.assertAlmostEqual(audit.fisher_exact(4, 0, 0, 4), 2 / 70, places=9)

    def test_conditional_binomial(self):
        self.assertAlmostEqual(audit.conditional_binomial(0, 10, 10, 10)["p_value"], 2 / 1024, places=12)
        self.assertAlmostEqual(audit.conditional_binomial(5, 10, 5, 10)["p_value"], 1.0, places=12)
        self.assertEqual(audit.conditional_binomial(0, 10, 0, 10)["p_value"], 1.0)
        self.assertAlmostEqual(audit.conditional_binomial(2, 10, 4, 10)["rate_ratio"], 2.0)

    def test_cohen_kappa_textbook(self):
        # Wikipedia "Cohen's kappa" example: 20 yes/yes, 5 yes/no, 10 no/yes, 15 no/no -> 0.4.
        pairs = [("yes", "yes")] * 20 + [("yes", "no")] * 5 + [("no", "yes")] * 10 + [("no", "no")] * 15
        stats = audit.kappa_stats(pairs, ("yes", "no"), positive="yes")
        self.assertAlmostEqual(stats["kappa"], 0.4, places=9)
        self.assertAlmostEqual(stats["raw"], 0.7, places=9)
        self.assertAlmostEqual(stats["pabak"], 0.4, places=9)
        self.assertAlmostEqual(stats["ci95"][0], 0.146, places=3)
        self.assertAlmostEqual(stats["ci95"][1], 0.654, places=3)
        self.assertAlmostEqual(stats["pos"], 40 / 55, places=9)
        self.assertAlmostEqual(stats["neg"], 30 / 45, places=9)

    def test_weighted_kappa(self):
        pairs = [("a", "a"), ("b", "b"), ("c", "c"), ("a", "b")]
        self.assertAlmostEqual(audit.kappa_stats(pairs, ("a", "b", "c"))["kappa"], 0.4375 / 0.6875, places=9)
        linear = audit.kappa_stats(pairs, ("a", "b", "c"), weights="linear")
        self.assertAlmostEqual(linear["kappa"], 0.3125 / 0.4375, places=9)
        self.assertAlmostEqual(linear["pabak"], 0.625, places=9)
        self.assertIsNone(audit.kappa_stats([], ("a", "b"))["kappa"])

    def test_p2_blocking_agreement_only_on_shared_p2(self):
        row = lambda sev, blocking=None: {"adjudicated_severity": sev, **({} if blocking is None else
                                                                          {"p2_blocking": blocking})}
        rows_a = {"1": row("P2", True), "2": row("P2"), "3": row("P2", True), "4": row("P1"), "5": row("P2", False)}
        rows_b = {"1": row("P2", True), "2": row("P2", False), "3": row("P2", False), "4": row("P2", True),
                  "5": row("P3")}
        stats = audit.agreement(rows_a, rows_b, kinds=("findings",), irr_only=False)["p2_blocking"]
        self.assertEqual(stats["n"], 3)
        self.assertAlmostEqual(stats["raw"], 2 / 3, places=9)
        self.assertAlmostEqual(stats["pabak"], 1 / 3, places=9)
        self.assertAlmostEqual(stats["kappa"], 0.4, places=9)
        self.assertIn("p2_blocking", [f[0] for f in audit.KAPPA_FIELDS])
        args = audit.build_parser().parse_args(["kappa", "--a", "x", "--b", "y", "--field", "p2_blocking"])
        self.assertEqual(args.field, ["p2_blocking"])

    def test_capture_estimators(self):
        self.assertAlmostEqual(audit.chapman(10, 10, 5), 121 / 6 - 1, places=9)
        self.assertAlmostEqual(audit.chao2(10, 4, 3, 3), 11.0, places=9)

    def test_capture_recapture_at_target_head(self):
        def defect(i, bot_hit, panel, head="t"):
            return {"pr_id": "p", "status_at": {head: "hit" if bot_hit else "miss"},
                    "channels": {"panel"} if panel else {"post_review_hunk"}, "human_blind": False}

        defects = [defect(i, i <= 8, i >= 2) for i in range(10)] + [defect(10, True, True, head="other")]
        result = audit.capture_recapture(defects, {"p": "t"})
        self.assertEqual(result["defects_at_target"], 10)
        self.assertEqual((result["method"], result["m"], result["status"]), ("chapman", 7, "ok"))
        self.assertAlmostEqual(result["estimate"], audit.chapman(9, 8, 7), places=9)
        sparse = audit.capture_recapture(defects[:7] + defects[9:10], {"p": "t"})
        self.assertEqual(sparse["status"], "not estimable")
        self.assertIsNone(sparse["estimate"])
        self.assertEqual(audit.capture_recapture(None)["status"], "no panel")


class CompareTest(unittest.TestCase):
    def test_primary_endpoints(self):
        def metrics(k_valid, n_valid, escaped, prs):
            prop = lambda k, n: {"overall": {"k": k, "n": n, "rate": k / n, "ci95": list(audit.wilson(k, n))}}
            return {"evidence_days": 3, "figures": {
                "validity_precision": prop(k_valid, n_valid),
                "noise_rate": prop(3, 10),
                "important_escaped_per_pr": {"overall": {"k": escaped, "n": prs, "rate": escaped / prs}},
                "silent_review_share": prop(1, 4),
            }}

        result = audit.compare_results(metrics(48, 80, 0, 10), metrics(56, 70, 10, 10))
        vp = result["comparison"]["validity_precision"]
        self.assertAlmostEqual(vp["newcombe"]["ci95"][0], 0.0524, places=3)
        self.assertIn("fisher_p", vp)
        self.assertAlmostEqual(result["comparison"]["important_escaped_per_pr"]["conditional_binomial"]["p_value"],
                               2 / 1024, places=12)
        self.assertEqual(result["comparison"]["approve_with_important_miss.per_pr"], {"status": "missing"})
        self.assertNotIn("approve_with_important_miss.merged_final", result["comparison"])
        self.assertIn("silent_review_share", result["descriptive"])
        self.assertEqual(result["warnings"], [])


class PanelDrawTest(unittest.TestCase):
    def units(self):
        prs, reviews, coverage = {}, {}, {}
        for i in range(12):
            pr_id = "o/r%d#%d" % (i % 2, i)
            prs[pr_id] = {"id": pr_id, "repo": "o/r%d" % (i % 2), "author_type": "automation" if i == 11 else "owner"}
            reviews[pr_id + "@review/1"] = {"id": pr_id + "@review/1", "pr_id": pr_id, "is_bot": True, "in_window": True,
                                            "submitted_at": "2026-10-12T00:00:00Z", "reviewed_head_sha": "h%d" % i,
                                            "verdict": "APPROVED" if i % 3 else "CHANGES_REQUESTED"}
            coverage[pr_id] = {"id": pr_id, "heads": ["h%d" % i], "bot_reviewed_heads": ["h%d" % i],
                               "first_foreign_commit_after_review": None}
        return {"prs": prs, "reviews": reviews, "coverage": coverage}

    def test_seeded_and_stratified(self):
        first = audit.draw_panel(self.units(), seed=7, n=6)
        self.assertEqual(first, audit.draw_panel(self.units(), seed=7, n=6))
        self.assertEqual(len(first["prs"]), 6)
        self.assertNotIn("o/r1#11", [p["pr_id"] for p in first["prs"]])
        self.assertEqual(sum(s["eligible"] for s in first["strata"]), 11)
        self.assertEqual(sum(s["drawn"] for s in first["strata"]), 6)
        self.assertEqual(len(audit.draw_panel(self.units(), seed=7, n=50)["prs"]), 11)

    def test_target_head_rules(self):
        cov = {"heads": ["h1", "h2", "h3", "h4"], "bot_reviewed_heads": ["h1", "h2", "h4"],
               "first_foreign_commit_after_review": "h3"}
        reviews = [{"id": "1", "submitted_at": "1", "reviewed_head_sha": "h1", "verdict": "CHANGES_REQUESTED"},
                   {"id": "2", "submitted_at": "2", "reviewed_head_sha": "h2", "verdict": "APPROVED"},
                   {"id": "3", "submitted_at": "3", "reviewed_head_sha": "h4", "verdict": "APPROVED"}]
        self.assertEqual(audit.panel_target_head(cov, reviews), ("h2", "pre_foreign_fix"))
        self.assertEqual(audit.panel_target_head(dict(cov, first_foreign_commit_after_review=None), reviews),
                         ("h2", "first_green"))
        reviews[1]["verdict"] = reviews[2]["verdict"] = "COMMENTED"
        self.assertEqual(audit.panel_target_head(dict(cov, first_foreign_commit_after_review=None), reviews),
                         ("h4", "final_reviewed"))


class MetricsTest(unittest.TestCase):
    PR = "o/r#1"
    R1 = "o/r#1@review/1"
    R2 = "o/r#1@review/2"
    HA = "a" * 40
    HB = "b" * 40
    CAND = "o/r#1/hunk/0123456789ab/src/a.py@-1,1+1,2"

    def units(self):
        def finding(fid, review, head, severity, cv1, submitted):
            return {"id": fid, "pr_id": self.PR, "review_id": review, "reviewed_head_sha": head, "severity": severity,
                    "in_window": True, "changed_in_vicinity_1": cv1, "author_reply_kind": "none",
                    "submitted_at": submitted, "file_type": "code"}

        f1, f2, f3, f4 = self.R1 + "/f1", self.R1 + "/f2", self.R1 + "/f3", self.R2 + "/f1"
        return {
            "prs": {self.PR: {"id": self.PR, "repo": "o/r", "size_bucket": "S", "author": "isac322",
                              "author_type": "owner", "state": "closed", "merged": True, "final_head_sha": self.HB}},
            "reviews": {
                self.R1: {"id": self.R1, "pr_id": self.PR, "event": "DISMISSED", "verdict": "CHANGES_REQUESTED",
                          "is_bot": True, "in_window": True, "submitted_at": "2026-10-12T00:00:00Z",
                          "reviewed_head_sha": self.HA, "finding_ids": [f1, f2, f3]},
                self.R2: {"id": self.R2, "pr_id": self.PR, "event": "APPROVED", "verdict": "APPROVED", "is_bot": True,
                          "in_window": True, "submitted_at": "2026-10-13T00:00:00Z", "reviewed_head_sha": self.HB,
                          "finding_ids": [f4]},
            },
            "findings": {f1: finding(f1, self.R1, self.HA, "P1", True, "2026-10-12T00:00:00Z"),
                         f2: finding(f2, self.R1, self.HA, "P1", False, "2026-10-12T00:00:00Z"),
                         f3: finding(f3, self.R1, self.HA, "P3", None, "2026-10-12T00:00:00Z"),
                         f4: finding(f4, self.R2, self.HB, "P1", True, "2026-10-13T00:00:00Z")},
            "candidates": {self.CAND: {"id": self.CAND, "pr_id": self.PR, "kind": "post_review_hunk"}},
            "coverage": {},
        }

    def finding_labels(self):
        base = {"rater": "final", "value": "normal", "noise_codes": []}
        return [
            {**base, "id": self.R1 + "/f1", "validity": "valid", "adjudicated_severity": "P1", "dedup_key": "k1",
             "defect_type": "functional/logic"},
            {**base, "id": self.R1 + "/f2", "validity": "valid", "adjudicated_severity": "nit",
             "author_action": "rejected", "defect_type": "evolvability/structure"},
            {**base, "id": self.R1 + "/f3", "validity": "invalid", "adjudicated_severity": "none"},
            {**base, "id": self.R2 + "/f1", "validity": "valid", "adjudicated_severity": "P1", "dedup_key": "k1"},
            # bad: unknown id, derived code labelled, duplicate (id, rater)
            {**base, "id": self.R1 + "/f9", "validity": "valid", "adjudicated_severity": "P3"},
            {**base, "id": self.R1 + "/f3", "rater": "labelerA", "validity": "invalid", "adjudicated_severity": "none",
             "noise_codes": ["SEVERITY_INFLATED"]},
            {**base, "id": self.R1 + "/f3", "validity": "invalid", "adjudicated_severity": "none"},
            # IRR rows
            {**base, "id": self.R1 + "/f1", "rater": "labelerA", "validity": "valid", "adjudicated_severity": "P1",
             "irr_sample": True},
            {**base, "id": self.R1 + "/f2", "rater": "labelerA", "validity": "invalid", "adjudicated_severity": "none",
             "irr_sample": True},
            {**base, "id": self.R1 + "/f1", "rater": "labelerB", "validity": "valid", "adjudicated_severity": "P1",
             "irr_sample": True},
            {**base, "id": self.R1 + "/f2", "rater": "labelerB", "validity": "invalid", "adjudicated_severity": "none",
             "irr_sample": True},
        ]

    def miss_labels(self):
        def miss(mid, head, match, **extra):
            row = {"id": "%s@%s" % (mid, head[:12]), "rater": "final", "channel": "post_review_hunk",
                   "verdict": "defect_fix", "is_defect": True, "present_at_reviewed_head": "yes",
                   "adjudicated_severity": "P1", "bot_match": match, "matched_finding_id": None,
                   "reviewed_head_sha": head, "latest_present_head": self.HB, "dedup_key": "k2"}
            row.update(extra)
            return row

        return [
            miss(self.CAND, self.HA, "miss", match_sample=True),
            miss(self.CAND, self.HB, "partial", review_id=self.R2),
            miss(self.PR + "/p1", self.HA, "miss", channel="panel", adjudicated_severity="P0", dedup_key="k3",
                 latest_present_head=self.HA),
            miss(self.PR + "/p4", self.HA, "miss", channel="panel", verdict="pre_existing", dedup_key="k4"),
            # bad: missing latest_present_head, @head suffix mismatch, unknown PR
            miss(self.PR + "/p2", self.HA, "miss", channel="panel", latest_present_head=None, dedup_key="k5"),
            dict(miss(self.CAND + ".1", self.HB, "miss"), reviewed_head_sha=self.HA),
            miss("x/y#9/p1", self.HA, "miss", channel="panel"),
        ]

    def compute(self, **kwargs):
        return audit.compute_metrics(self.units(), self.finding_labels(), self.miss_labels(), 3, **kwargs)

    def kn(self, summary):
        return summary["k"], summary["n"]

    def test_finding_figures(self):
        fig = self.compute()["figures"]
        self.assertEqual(self.kn(fig["validity_precision"]["overall"]), (2, 3))
        self.assertEqual(self.kn(fig["blocking_precision"]["overall"]), (2, 2))
        self.assertEqual(self.kn(fig["noise_rate"]["overall"]), (2, 3))
        self.assertEqual(self.kn(fig["code_rate"]["SEVERITY_INFLATED"]["overall"]), (1, 3))
        self.assertEqual(self.kn(fig["code_rate"]["INVALID"]["overall"]), (1, 3))
        self.assertEqual(self.kn(fig["duplicate_rate"]["overall"]), (1, 4))
        self.assertEqual(self.kn(fig["over_severity_rate"]["overall"]), (0, 2))
        self.assertEqual(self.kn(fig["severity_inflated_rate"]["overall"]), (1, 2))
        self.assertEqual(self.kn(fig["nit_share"]["overall"]), (1, 2))
        self.assertEqual(fig["findings_per_pr"]["overall"]["rate"], 3.0)
        self.assertNotIn("ci95", fig["findings_per_pr"]["overall"])
        self.assertEqual(fig["findings_per_pr"]["valid_blocking"]["k"], 1)
        self.assertEqual(self.kn(fig["silent_review_share"]["overall"]), (0, 2))
        self.assertEqual(fig["validity_precision"]["breakdown"]["verdict"], {
            "CHANGES_REQUESTED": fig["validity_precision"]["overall"]})

    def test_addressed_figures(self):
        fig = self.compute()["figures"]
        self.assertEqual(self.kn(fig["addressed_rate"]["overall"]), (1, 2))
        self.assertEqual(fig["addressed_rate"]["null_vicinity_excluded"], 1)
        self.assertEqual(self.kn(fig["effective_fp_rate"]["overall"]), (1, 2))
        pooled = fig["explicit_not_useful_rate"]["*.*"]
        self.assertEqual((pooled["k"], pooled["n"], pooled["status"]), (1, 2, "insufficient"))
        finding = {"next_bot_review_status": "Closed", "changed_in_vicinity_1": None, "author_reply_kind": "none"}
        self.assertFalse(audit.finding_addressed(finding))
        self.assertTrue(audit.finding_addressed(finding, {"author_action": "addressed"}))

    def test_escape_figures(self):
        fig = self.compute()["figures"]
        self.assertEqual(fig["important_escaped"]["overall"]["count"], 1)
        self.assertEqual(fig["important_escaped"]["evidence_days"], 3)
        self.assertEqual(self.kn(fig["important_miss_rate_rel"]["all_prs"]["overall"]), (1, 2))
        self.assertIsNone(fig["important_miss_rate_rel"]["panel_prs"])
        self.assertEqual(fig["important_partial"]["overall"]["count"], 1)
        self.assertEqual(self.kn(fig["subtotal_p0p1"]["overall"]), (1, 2))
        self.assertEqual(self.kn(fig["first_exposure_miss"]["overall"]), (1, 2))
        self.assertEqual(fig["important_escaped_per_pr"]["overall"]["rate"], 1.0)
        approve = fig["approve_with_important_miss"]
        self.assertEqual(self.kn(approve["overall"]), (1, 1))
        self.assertEqual(self.kn(approve["merged_final"]["overall"]), (1, 1))
        self.assertEqual(self.kn(approve["per_pr"]["overall"]), (1, 1))
        self.assertIn("ci95", approve["per_pr"]["overall"])
        per_pr = fig["important_escaped_per_pr"]["overall"]
        self.assertEqual((per_pr["k"], per_pr["n"]), (1, 1))
        self.assertAlmostEqual(per_pr["ci95"][0], audit.garwood(1)[0], places=9)
        self.assertAlmostEqual(per_pr["ci95"][1], audit.garwood(1)[1], places=9)
        self.assertEqual(fig["important_escaped"]["panel_only"]["defects"], 0)
        self.assertEqual(fig["important_escaped"]["panel_only"]["outside_panel_prs"], 1)
        self.assertEqual(self.kn(approve["superseded"]["overall"]), (0, 0))
        self.assertEqual(self.kn(approve["miss_only"]), (0, 1))
        self.assertEqual(self.kn(fig["rc_without_valid_blocking"]["overall"]), (0, 1))

    def test_panel_only_defects(self):
        units = self.units()
        units["panel"] = {"prs": [{"pr_id": self.PR, "target_head_sha": self.HA}]}
        fig = audit.compute_metrics(units, self.finding_labels(), self.miss_labels(), 3)["figures"]
        panel_only = fig["important_escaped"]["panel_only"]
        self.assertEqual((panel_only["escaped"], panel_only["defects"], panel_only["outside_panel_prs"]), (1, 1, 0))
        self.assertEqual(fig["important_escaped"]["overall"]["count"], 1)
        self.assertEqual(self.kn(fig["important_miss_rate_rel"]["all_prs"]["overall"]), (1, 2))
        self.assertEqual(self.kn(fig["important_miss_rate_rel"]["panel_prs"]["overall"]), (2, 3))

    def test_bad_rows_are_reported_not_raised(self):
        result = self.compute()
        reasons = {(row["file"], row["id"]): row["reason"] for row in result["bad_rows"]}
        self.assertEqual(len(result["bad_rows"]), 6)
        self.assertIn("unknown finding id", reasons[("labels-findings", self.R1 + "/f9")])
        self.assertIn("duplicate (id, rater)", reasons[("labels-findings", self.R1 + "/f3")])
        self.assertIn("missing latest_present_head", reasons[("labels-misses", self.PR + "/p2@" + self.HA[:12])])
        self.assertIn("suffix", reasons[("labels-misses", self.CAND + ".1@" + self.HB[:12])])
        self.assertIn(("labels-misses", "x/y#9/p1@" + self.HA[:12]), reasons)
        derived = [r for r in result["bad_rows"] if "derived" in r["reason"]]
        self.assertEqual(len(derived), 1)

    def test_irr_judge_and_matcher(self):
        judge = [{"id": self.R1 + "/f1", "validity": "valid"}, {"id": self.R1 + "/f2", "validity": "valid"}]
        matcher = [{"id": self.CAND + "@" + self.HA[:12], "bot_match": "miss", "order": "defect_first"},
                   {"id": self.CAND + "@" + self.HA[:12], "bot_match": "partial", "order": "review_first",
                    "review_id": self.R1},
                   {"id": self.CAND + "@" + self.HB[:12], "bot_match": "miss", "rater": "matcher-defect_first"}]
        result = self.compute(judge_rows=judge, matcher_rows=matcher)
        fig = result["figures"]
        self.assertEqual(len(result["bad_rows"]), 6)  # both orders on one id are not duplicates
        self.assertEqual((fig["irr"]["validity"]["n"], fig["irr"]["validity"]["kappa"]), (2, 1.0))
        self.assertEqual((fig["judge_bias"]["n"], fig["judge_bias"]["raw"]), (2, 0.5))
        self.assertEqual((fig["match_kappa"]["defect_first"]["n"], fig["match_kappa"]["defect_first"]["raw"]), (1, 1.0))
        self.assertEqual((fig["match_kappa"]["review_first"]["n"], fig["match_kappa"]["review_first"]["raw"]), (1, 0.0))
        bad = self.compute(matcher_rows=[{"id": self.CAND + "@" + self.HA[:12], "bot_match": "miss"}])["bad_rows"]
        self.assertTrue(any(r["file"] == "labels-matcher" for r in bad))

    def test_coverage_only_rows(self):
        coverage_only = {"id": self.PR + "/os1", "rater": "final", "channel": "owner_session", "verdict": "defect_fix",
                         "is_defect": True, "present_at_reviewed_head": "unknown", "adjudicated_severity": "P1",
                         "bot_match": None, "matched_finding_id": None, "reviewed_head_sha": None,
                         "latest_present_head": None, "coverage_only": True, "dedup_key": "k9"}
        result = audit.compute_metrics(self.units(), self.finding_labels(), self.miss_labels() + [
            coverage_only, dict(coverage_only, id=self.PR + "/os2", adjudicated_severity="P3", dedup_key="k10")], 3)
        self.assertEqual(len(result["bad_rows"]), 6)
        fig = result["figures"]
        self.assertEqual(fig["coverage_unreviewed_defects"]["overall"]["count"], 2)
        self.assertEqual(fig["coverage_unreviewed_defects"]["important"], 1)
        self.assertEqual(fig["coverage_unreviewed_defects"]["breakdown"]["adjudicated_severity"],
                         {"P1": {"count": 1}, "P3": {"count": 1}})
        self.assertEqual(fig["important_escaped"]["overall"]["count"], 1)
        self.assertEqual(self.kn(fig["important_miss_rate_rel"]["all_prs"]["overall"]), (1, 2))
        self.assertEqual(result["coverage"]["miss_rows_coverage_only"], 2)

    def test_exclude_pr(self):
        result = self.compute(exclude_prs=[self.PR])
        self.assertEqual(result["coverage"]["reviewed_prs"], 0)
        self.assertEqual(result["coverage"]["excluded_prs"], [self.PR])
        self.assertTrue(all(pr not in (row["id"] or "") for row in result["bad_rows"] for pr in [self.PR]))


if __name__ == "__main__":
    unittest.main()
