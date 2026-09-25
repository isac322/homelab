---
name: pr-delivery
description: Push the issue worktree branch and open or update a pull request that references the issue, then report the result on the issue. Use when the automation asks to deliver a verified implementation. Never merges.
---

# PR delivery

1. Check the branch: `git branch --show-current` must be this issue's worktree branch, not the default branch. Use the actual branch name; do not rename it.
2. Confirm verification from `issue-implementation` passed. If not, report instead of delivering.
3. Push: `git push -u origin HEAD`. Never force-push unless the automation explicitly asks and the branch is yours.
4. If a PR for this branch exists (`gh pr list --repo <owner/repo> --head <branch> --state open`), update it; otherwise create one:
   `gh pr create --repo <owner/repo> --base <default-branch> --head <branch> --title "<title>" --body-file <file>`
   The body states what changed, why, how it was verified, remaining risks, and `Closes #<n>` (or `Refs #<n>` if it only partly resolves the issue).
5. Follow the repository's PR template and conventions when present.
6. Post one concise comment on the issue linking the PR, unless the automation says it posts the result itself.

Never merge, enable auto-merge, approve your own PR, or request reviewers the automation did not name. Report the PR URL, branch, and head commit.
