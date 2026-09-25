---
name: issue-implementation
description: Implement an approved, actionable GitHub issue in the current HAPI worktree - sync with the default branch, make the scoped change, and verify it with the repository's own checks. Use when the automation asks for implementation. Not for triage or opening the PR.
---

# Issue implementation

1. Confirm the working directory is this issue's worktree (`git rev-parse --show-toplevel`, `git branch --show-current`). Never work in the base clone or on the default branch.
2. The worktree branch was created from a local checkout that may be stale. Before editing, run `git fetch origin` and rebase the branch onto `origin/<default-branch>` (`git remote show origin` shows the default branch). Do this only while the branch has no pushed commits.
3. Read the repository instructions (`AGENTS.md` or equivalent) and follow its build, test, and style rules.
4. Make the smallest change that fully satisfies the issue. Do not refactor or fix unrelated problems; list them in the report instead.
5. Add or update tests when the repository's conventions call for it.
6. Run the repository's relevant checks (formatters, linters, tests) as its instructions describe. Record each command and its result.
7. If a check fails for reasons outside the change, or the fix needs a decision you cannot make from the issue, stop and report the blocker with evidence instead of working around it.
8. Commit with a message that follows the repository's conventions and references the issue.

Report: changed files, verification commands and results, open risks, and anything not verified.
