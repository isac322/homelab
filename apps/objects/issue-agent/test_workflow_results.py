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
BASE_SHA = "1" * 40
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
        "visual_evidence": [
            {
                "id": "panel-margin-before",
                "role": "before",
                "relpath": "artifacts/panel-margin-before.png",
                "sha256": "a" * 64,
                "bytes": 48217,
                "media_type": "image/png",
                "source_sha": BASE_SHA,
                "caption": "Notification overlaps the panel at the base revision.",
            },
            {
                "id": "panel-margin-after",
                "role": "after",
                "relpath": "artifacts/panel-margin-after.png",
                "sha256": "b" * 64,
                "bytes": 49328,
                "media_type": "image/png",
                "source_sha": HEAD_SHA,
                "caption": "Notification keeps the requested margin from the panel edge.",
            },
        ],
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

    def test_implement_result_preserves_nonempty_visual_evidence(self) -> None:
        self.assert_result_roundtrip("implement", implementation_result())

    def test_followup_result_preserves_nonempty_visual_evidence(self) -> None:
        result = implementation_result()
        result["pr"]["body"] += "\n\nAlso cover the top-panel case raised in review."
        result["summary"] = "Addressed the top-panel review finding and refreshed visual evidence."
        self.assert_result_roundtrip("followup", result)


if __name__ == "__main__":
    unittest.main()
