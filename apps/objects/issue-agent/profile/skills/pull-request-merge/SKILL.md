---
name: pull-request-merge
description: "Apply when an issue agent turn reaches a point where a GitHub pull request would be merged; the agent never merges and only reports merge readiness in its result."
---

## Automation adaptation

This copy adapts the global `pull-request-merge` rule for the homelab issue agent (n8n + bridge + HAPI + Codex). The agent runs unattended with a read-only GitHub token and ends each turn with an `ISSUE_AGENT_RESULT <nonce> {json}` line; n8n performs every GitHub write through bridge ops, and no bridge op merges. Changes:

- The agent never merges a pull request. Merge decisions belong to the repository maintainers.
- Presenting finalized merge details for approval becomes reporting merge readiness in the result; the agent does not wait for approval.

| Original step | Result field |
|---|---|
| 1–2. Finalize target/head/method; confirm reviews, checks, conflicts | `ReviewResult.body` (verdict line with `PR-ready` and reviewed head, per `isac-pr-review`); in implement/followup mode `ImplementResult.summary` |
| 3. Present finalized details per the merge authorization guard | `summary` (merge readiness only; no approval request, no waiting) |
| 4–5. Merge the finalized target(s) | Removed: the agent does not merge |

# Pull request merge workflow

When a GitHub pull request is ready to be merged:

1. Record the merge target, head state, and any material options a maintainer would need.
2. Check whether required reviews, checks, and conflict resolution are complete.
3. Report the result as merge readiness in the result fields above (`PR-ready: true|false` with the reason); do not ask for merge approval and do not wait.
4. Never merge, enable auto-merge, or add the pull request to a merge queue; the maintainers decide and perform the merge.
