---
name: pull-request-review-handling
description: "Apply when an issue agent turn collects, handles, and responds to GitHub pull request review feedback; responses go into result fields that n8n publishes."
---

## Automation adaptation

This copy adapts the global `pull-request-review-handling` rule for the homelab issue agent (n8n + bridge + HAPI + Codex). The agent runs unattended with a read-only GitHub token and ends each turn with an `ISSUE_AGENT_RESULT <nonce> {json}` line; n8n performs every GitHub write through bridge ops. Changes:

- Replying in review threads, resolving threads, and requesting or re-requesting reviews are not done by the agent. The replies go into result fields; n8n publishes them.
- Waiting on reviewers is removed; review requests and re-requests arrive as new events (`@haechibot review` comments from the PR author or an allowed user, ready/reopen, or a new issue comment).

| Original step | Result field |
|---|---|
| 3. Reply in every collected thread | Review mode: `ReviewResult.thread_replies[]` (`comment_id`, `body`, `resolve`). Implement/followup mode: `ImplementResult.issue_comment` listing each collected item with its disposition and evidence, and `ImplementResult.pr.body` updated to match the pushed head |
| 4. Request / re-request / wait transitions | Removed: n8n and the event intake handle them; the agent reports the new head in `head_sha` |

# Pull request review workflow

When handling GitHub pull request reviews:

1. At the start of each review-handling cycle, collect every current review summary, inline comment, and unresolved review thread before editing (from the message context and read-only `gh` commands).
2. Use the `receiving-code-review` skill to evaluate each item, choose its disposition, implement accepted or adapted changes, verify affected behavior, and prepare evidence-backed responses.
3. After every item collected at the cycle's start has a final disposition and required verification is complete, put the response for every collected thread (implementation, verification, clarification, or rejection evidence) into the result fields above; do not post it yourself.
4. After a head-commit change, report the new head in the result's `head_sha`; do not request, re-request, or wait for reviews.
