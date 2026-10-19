"""Execute session-workflow result handling in Node.js, then validate bridge schemas.

Run: python3 -m unittest apps/objects/issue-agent/test_workflow_results.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bridge  # noqa: E402


WORKFLOW = Path(__file__).with_name("n8n-session-workflow.json")
HEAD_SHA = "2" * 40

# Follow the deployed graph instead of choosing a particular preservation node.
RUN_RETURN_GRAPH = r"""
const fs = require('node:fs');
const { workflowPath, request, turn } = JSON.parse(fs.readFileSync(0, 'utf8'));
const workflow = JSON.parse(fs.readFileSync(workflowPath, 'utf8'));
const nodes = new Map(workflow.nodes.map(node => [node.name, node]));
const outputs = new Map([['Session request', [{ json: request }]]]);
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const queue = [{ name: 'Return turn', items: [{ json: turn }] }];
const leaves = [];
let steps = 0;

(async () => {
  while (queue.length) {
    if (++steps > workflow.nodes.length) throw new Error('Result graph contains a cycle');
    const { name, items } = queue.shift();
    const node = nodes.get(name);
    if (!node) throw new Error(`Missing workflow node: ${name}`);
    let result;
    if (node.type === 'n8n-nodes-base.noOp') {
      result = items;
    } else if (node.type === 'n8n-nodes-base.code') {
      const input = { all: () => items, first: () => items[0], item: items[0] };
      const lookup = name => {
        const values = outputs.get(name);
        if (!values) throw new Error(`Node has not executed: ${name}`);
        return { all: () => values, first: () => values[0], item: values[0] };
      };
      const execute = new AsyncFunction('$json', '$input', '$', node.parameters.jsCode);
      result = await execute(items[0].json, input, lookup);
    } else {
      throw new Error(`Unsupported result-graph node: ${node.type}`);
    }
    outputs.set(name, result);
    const connections = workflow.connections[name]?.main?.[0] || [];
    if (!connections.length) leaves.push(...result);
    for (const connection of connections) {
      queue.push({ name: connection.node, items: structuredClone(result) });
    }
  }
  process.stdout.write(JSON.stringify(leaves));
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
"""
RUN_MAIN_NODES = r"""
const fs = require('node:fs');
const { workflowPath, items, actions, previousNode } = JSON.parse(fs.readFileSync(0, 'utf8'));
const workflow = JSON.parse(fs.readFileSync(workflowPath, 'utf8'));
const nodes = new Map(workflow.nodes.map(node => [node.name, node]));
const outputs = new Map(Object.entries(items).map(([name, json]) => [name, [{ json }]]));
const lookup = name => {
  const values = outputs.get(name);
  if (!values) throw new Error(`Missing node output: ${name}`);
  return { all: () => values, first: () => values[0], item: values[0] };
};
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
(async () => {
  const results = [];
  for (const { name, input } of actions) {
    const node = nodes.get(name);
    if (!node) throw new Error(`Missing workflow node: ${name}`);
    const json = input || {};
    const $input = { first: () => ({ json }), all: () => [{ json }] };
    const evaluate = expression => new Function('$json', '$', '$prevNode',
      'return (' + expression.replace(/^=\{\{\s*/, '').replace(/\s*\}\}$/, '') + ')'
    )(json, lookup, { name: previousNode });
    let result;
    if (node.type === 'n8n-nodes-base.code') {
      result = await new AsyncFunction('$input', '$', node.parameters.jsCode)($input, lookup);
      outputs.set(name, result);
    } else if (node.type === 'n8n-nodes-base.if') {
      result = node.parameters.conditions.conditions.every(condition => Boolean(evaluate(condition.leftValue)));
    } else if (node.type === 'n8n-nodes-base.httpRequest') {
      result = JSON.parse(evaluate(node.parameters.jsonBody));
    } else {
      throw new Error(`Unsupported workflow node: ${node.type}`);
    }
    results.push(result);
  }
  process.stdout.write(JSON.stringify(results));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""


def run_main_nodes(actions: list[dict], *, items: dict | None = None, previous_node: str = "") -> list:
    completed = subprocess.run(
        ["node", "-e", RUN_MAIN_NODES],
        input=json.dumps({"workflowPath": str(WORKFLOW.with_name("n8n-workflow.json")),
                          "items": items or {}, "actions": actions, "previousNode": previous_node}),
        capture_output=True, text=True, timeout=10, check=True,
    )
    return json.loads(completed.stdout)



def implementation_result() -> dict:
    return {
        "status": "ready",
        "pr": {
            "title": "Fix panel-relative notification margins",
            "body": "Fixes #7\n\nMeasure notification margins from the panel edge.",
        },
        "issue_comment": None,
        "questions": [],
        "summary": "Corrected panel-relative spacing and captured before/after screenshots.",
        "blockers": [],
        "local_checks": [{"command": "make test", "exit_code": 0}],
        "visual_evidence_manifest": "artifacts/visual-evidence.json",
    }


class SessionWorkflowResultTests(unittest.TestCase):
    def assert_result_roundtrip(self, mode: str, result: dict) -> None:
        self.assertEqual(bridge.validate_result(mode, result, 7), result, "Invalid test fixture")
        turn = {"ok": True, "state": "done", "session_id": "session-7", "mode": mode, "result": result}
        request = {
            "delivery_id": "delivery-7",
            "lane": "review" if mode == "review" else "issue",
            "mode": mode,
            "instructions": "Check panel-relative notification spacing.",
            "context": {},
        }
        completed = subprocess.run(
            ["node", "-e", RUN_RETURN_GRAPH],
            input=json.dumps({"workflowPath": str(WORKFLOW), "request": request, "turn": turn}),
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        items = json.loads(completed.stdout)
        self.assertEqual(len(items), 1)
        output = items[0]["json"]
        self.assertEqual(bridge.validate_result(mode, output["result"], 7), result)
        self.assertEqual(output, turn)

    def test_review_result_remains_valid_without_visual_evidence(self) -> None:
        self.assert_result_roundtrip("review", {
            "status": "reviewed",
            "head_sha": HEAD_SHA,
            "event": "REQUEST_CHANGES",
            "body": "The panel-relative margin still fails when the panel moves to the top.",
            "comments": [{
                "path": "src/notifications.cpp", "line": 42, "side": "RIGHT", "start_line": None,
                "body": "Use the panel's occupied edge rather than the screen edge here.",
            }],
            "thread_replies": [{"comment_id": 901, "body": "The bottom-edge case is fixed.", "resolve": True}],
            "open_items": ["Handle a panel on the top edge."],
            "summary": "One panel-position regression remains.",
            "blockers": [],
        })

    def test_triage_result_remains_valid_without_visual_evidence(self) -> None:
        self.assert_result_roundtrip("triage", {
            "status": "triaged", "verdict": "CONFIRMED_CURRENT", "fault_domain": "product",
            "duplicate_of": None, "labels": {"add": ["bug", "repro:reproduced"], "remove": []},
            "comment": "Reproduced notification overlap with a bottom panel.",
            "next_action": "implement",
            "implementation_brief": "Measure the notification margin from the occupied panel edge.",
            "questions": [], "summary": "Panel-relative spacing is incorrect.", "blockers": [],
            "security_advisory": None,
        })

    def test_reopen_result_remains_valid_without_visual_evidence(self) -> None:
        self.assert_result_roundtrip("reopen_check", {
            "status": "reopen",
            "reason": "The shipped margin is measured from the screen edge, not the panel edge.",
            "comment": "Reopening: notifications still overlap a panel at the top edge.",
            "summary": "The original overlap remains reproducible.", "blockers": [],
        })

    def test_implement_result_preserves_manifest_path(self) -> None:
        self.assert_result_roundtrip("implement", implementation_result())

    def test_followup_result_preserves_manifest_path(self) -> None:
        result = implementation_result()
        result["pr"]["body"] += "\n\nAlso cover the top-panel case raised in review."
        result["summary"] = "Addressed the top-panel review finding and refreshed visual evidence."
        self.assert_result_roundtrip("followup", result)

    def test_implementation_statuses_preserve_null_manifest(self) -> None:
        for mode in ("implement", "followup"):
            for status in ("ready", "no_change", "needs_info", "blocked"):
                with self.subTest(mode=mode, status=status):
                    result = implementation_result()
                    result.update(status=status, visual_evidence_manifest=None)
                    if status != "ready":
                        result.update(pr=None, local_checks=[])
                    if status == "no_change":
                        result["issue_comment"] = "The existing implementation already meets this request."
                    elif status == "needs_info":
                        result.update(issue_comment="Which panel edge?", questions=["Which panel edge?"])
                    elif status == "blocked":
                        result["blockers"] = ["The capture device is unavailable."]
                    self.assert_result_roundtrip(mode, result)


class VisualWorkflowConsumerTests(unittest.TestCase):
    def test_ready_and_no_change_publish_manifest_without_artifact_transcription(self) -> None:
        for status, guard, publish in (
            ("ready", "Visual evidence requested?", "Publish visual evidence"),
            ("no_change", "No-change visual evidence requested?", "Publish no-change visual evidence"),
        ):
            for manifest in ("artifacts/visual-evidence.json", None):
                for kind in ("issue_comment", "pr_repair", "pr_review"):
                    with self.subTest(status=status, manifest=manifest, kind=kind):
                        result = implementation_result()
                        result.update(status=status, visual_evidence_manifest=manifest,
                                      issue_comment="Captured the requested panel margin.")
                        if status != "ready":
                            result.update(pr=None, local_checks=[])
                        if status == "needs_info":
                            result.update(questions=["Which panel edge?"])
                        elif status == "blocked":
                            result.update(blockers=["The capture device is unavailable."])
                        self.assertIsInstance(bridge.validate_result("followup", result, 7), dict)
                        event = {"delivery_id": "d7", "repo": "isac322/cc-lb", "kind": kind,
                                 "issue_number": 7, "pr_number": 12, "head_sha": HEAD_SHA}
                        report, requested = run_main_nodes(
                            [{"name": "Compose implement report", "input": {"result": result}},
                             {"name": guard}],
                            items={"Begin": {"event": event}, "Upsert pull request": {"number": 12},
                                   "Push branch": {"sha": HEAD_SHA}},
                        )
                        self.assertEqual(report[0]["json"]["status"], status)
                        self.assertEqual(requested, manifest is not None)
                        if not requested:
                            continue
                        payload, = run_main_nodes(
                            [{"name": publish}],
                            items={"Begin": {"event": event}, "Upsert pull request": {"number": 12},
                                   "Push branch": {"sha": HEAD_SHA},
                                   "Compose implement report": report[0]["json"]},
                        )
                        self.assertEqual(payload["manifest_path"], manifest)
                        self.assertEqual(payload["head_sha"], HEAD_SHA)
                        self.assertEqual(payload["pr_number"], 12)
                        self.assertEqual(payload["worktree"], ("review-pr-" if kind == "pr_review" else "issue-") + "7")
                        self.assertEqual(payload.get("reuse_existing", False), status == "no_change")
                        self.assertNotIn("artifacts", payload)
                        self.assertNotIn("allowed_source_shas", payload)


if __name__ == "__main__":
    unittest.main()
