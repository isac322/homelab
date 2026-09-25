---
name: duplicate-check
description: Search a repository's open and closed issues and pull requests for work that already covers an issue, and decide duplicate or not with evidence. Use during triage and before starting implementation.
---

# Duplicate check

1. Extract 2-4 distinctive search terms from the issue: error messages, identifiers, file or command names, feature names.
2. Search issues and pull requests, open and closed, in the same repository:
   - `gh search issues --repo <owner/repo> --include-prs --state open "<terms>"`
   - `gh search issues --repo <owner/repo> --include-prs --state closed "<terms>"`
   Repeat with different terms if the first queries return nothing relevant.
3. Open each plausible match (`gh issue view` / `gh pr view`) and compare the actual request, not only the title.
4. Classify:
   - duplicate: the same problem or request is already tracked, or a merged PR already fixes it (confirm against the current default branch).
   - related: overlapping but different; cite it and continue.
   - none.
5. Report the classification with links and one-line reasons. Ignore the current issue itself and deliveries of the same event.

Never close, label, or comment on issues as part of this check.
