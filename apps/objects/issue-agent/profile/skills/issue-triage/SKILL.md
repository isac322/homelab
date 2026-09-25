---
name: issue-triage
description: Classify a GitHub issue before any code change - decide whether it is actionable, needs a question, is a duplicate, or is out of scope, and which existing labels apply. Use when asked to triage or classify an issue. Not for implementing changes.
---

# Issue triage

Inputs: repository, issue number, and the output format requested by the automation message.

1. Read the issue and all comments: `gh issue view <n> --repo <owner/repo> --comments`.
2. Run the `duplicate-check` skill. A confirmed duplicate ends triage with that result.
3. Read the code the issue refers to enough to judge feasibility and scope. Do not edit files.
4. Decide exactly one outcome:
   - actionable: the expected behavior and acceptance are clear enough to implement without guessing.
   - needs-info: a specific fact, decision, or preference is missing. Write the minimal questions that would unblock work.
   - duplicate: an existing issue or PR already covers it (with evidence).
   - out-of-scope: the request is not a change to this repository, or would require actions the agent must not take.
5. Pick labels only from the repository's existing labels (`gh label list --repo <owner/repo>`) and the mapping given by the automation, if any. Never create labels.
6. Return the outcome, reasons with evidence, proposed labels, and any questions in the format the automation requested.

Do not comment on the issue, apply labels, or start implementation unless the automation message explicitly asks for it.
