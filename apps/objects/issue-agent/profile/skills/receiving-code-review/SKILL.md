---
name: receiving-code-review
description: Use in the GitHub issue automation's `followup` mode to evaluate a new issue comment on an issue already being implemented and turn each item into an accepted, adapted, clarified, or rejected disposition reported through the ImplementResult fields.
---

## Automation adaptation

이 사본은 homelab GitHub 이슈 자동화(`isac-issue-to-pr`의 `followup` 모드)용으로 기계적으로 고친 것이다. 나머지 문장은 원본 그대로다.

- 에이전트의 GitHub 토큰은 읽기 전용이다. 스레드 답글(`gh api .../replies`), 스레드 resolve, push, 리뷰어 재요청을 하지 않는다. n8n이 결과를 보고 게시·push한다.
- 단계 → 결과 필드:
  - 8. Respond의 답변 → `issue_comment`(항목별 disposition과 근거). 코드를 바꿨으면 `pr.body`를 현재 diff에 맞게 고치고 `pr.title`과 함께 반환한다.
  - 6. Implement의 결과 → `hapi-issue-<n>` 브랜치의 로컬 커밋. 최종 커밋이 `head_sha`이고 `status: "ready"`다.
  - 구현 없이 답만 하는 경우 → `status: "no_change"`와 `issue_comment`.
  - 질문(2. Understand, 4. Verify the claim, Clarification needed, 막힌 cluster) → `questions`와 `issue_comment`, `status: "needs_info"`. 채팅으로 기다리지 않고 턴을 끝낸다.

# Receiving Code Review

Treat review feedback as technical input to evaluate, not a command to obey or an argument to win. Understand the requested outcome, check it against the repository, and respond with evidence.

## Scope

This skill covers reusable evaluation, implementation, pushback, and response technique.

The active pull request review policy owns mandatory reviewer authority, state capture, complete thread collection, reviewer re-request, `runbear-bot` waiting, completion gates, and merge gates. Follow that policy when it applies. Do not use this skill to replace, weaken, or reconstruct it.

## Evidence standard

Evaluate technical claims against the code, tests, documented contracts, supported environments, repository decisions, and the user's requested outcome. A suggestion may be correct, partially correct, unnecessary, out of scope, or based on missing context.

Neither confidence nor politeness is evidence. Prefer reproducible behavior, source code, tests, specifications, and explicit project decisions.

## Evaluation stages

Apply these stages to each item or to a group of items that must be reasoned about together.

### 1. Read

Read the full item and its surrounding context before reacting. Identify the claimed problem, requested change, cited evidence, and affected behavior.

Do not begin from the reviewer's proposed patch alone. The proposal may solve the wrong problem even when the underlying finding is valid.

### 2. Understand

Restate the item as an observable requirement:

- What behavior is allegedly wrong?
- Under which inputs, platforms, or states?
- What result should replace it?
- Is the reviewer reporting a defect, requesting a design change, or expressing a preference?

If the intended behavior is ambiguous, ask a precise question (put it in `questions` and end the turn with `needs_info`). Do not guess at an interpretation that changes scope or product intent.

### 3. Dependency map

Trace the relevant code and constraints before judging the suggestion. Inspect callers, callees, data flow, public contracts, tests, configuration, compatibility requirements, and nearby decisions that explain the current implementation.

Map interactions among review items. Treat items as independent only when their behavior, contracts, implementation, and verification do not depend on one another. If independence cannot be established, evaluate them as a cluster and do not make an isolated edit that prejudges an unresolved dependency.

### 4. Verify the claim

Try to reproduce the reported behavior or otherwise establish whether the claim holds. Compare the suggestion with repository conventions and the supported runtime or platform.

Check for consequences beyond the reviewer's example:

- regressions in existing behavior;
- invalid assumptions about callers or data;
- compatibility or performance costs;
- security and failure-mode changes;
- unnecessary features or abstractions;
- conflict with the user's requested outcome.

When a suggestion asks to make something "proper," "professional," generic, or extensible, trace actual callers and product requirements before adding scope. If the behavior is unused, consider removing the unused path when removal is in scope; otherwise decline the expansion. If it is used, implement only the verified need rather than the reviewer's speculative end state.

If available evidence cannot establish the answer, say what is missing and seek the narrowest clarification or experiment that can resolve it.

### 5. Disposition

Choose and record a technical disposition:

- **Accept:** the finding and proposed direction are correct.
- **Adapt:** the finding is correct, but a different implementation better preserves contracts or scope.
- **Clarify:** intent, evidence, or an interacting dependency remains unresolved.
- **Reject:** evidence shows the suggestion is incorrect, harmful, unnecessary, or outside the authorized scope.

Do not implement merely to appear cooperative. Do not reject merely because the current code is familiar.

### 6. Implement

For accepted or adapted items, fix the underlying problem rather than suppressing its symptom. Reuse established patterns, update affected callers, and remove code made obsolete by the change when that removal is in scope.

For multiple items, resolve blocking clarifications first, then order implementation by dependency. Address correctness, security, and broken behavior before cosmetic cleanup. Implement the smallest coherent item or interacting cluster and verify it before continuing, so failures remain attributable.

Keep the implementation tied to the verified requirement. Do not batch unrelated fixes, and do not treat review feedback as permission for unrelated cleanup or speculative architecture.

### 7. Verify the change

Exercise the observable behavior that the item concerns. Use the smallest convincing reproduction, focused test, build, or runtime check appropriate to the change, then check relevant neighboring behavior for regressions.

A successful edit is not proof. Report only verification that actually ran and describe any remaining limitation precisely.

### 8. Respond

Write the response into the result `issue_comment`; n8n posts it on the issue. Do not post, reply to, or resolve anything on GitHub yourself. Keep each response specific to that item or interacting cluster, addressing items by quoting or naming them. Lead with the disposition, evidence, or result rather than praise or gratitude.

- **Implemented:** state what changed and cite the relevant verification; return the new `head_sha` and an updated `pr.body` with `status: "ready"`.
- **Adapted:** explain the verified concern and why the chosen implementation differs.
- **Clarification needed:** ask one concrete question and name the dependency it blocks; put the question in `questions` and return `status: "needs_info"`.
- **Rejected:** give the shortest sufficient technical reason, backed by code, tests, contracts, or reproduced behavior.

Do not mark an item handled while leaving its disposition implicit.

## Unclear and interacting items

An unclear item blocks itself and every item whose design, scope, implementation, or verification depends on the missing answer. Before progressing with another item, establish that independence from the code and requirements rather than assuming it. If independence remains uncertain, treat the items as one cluster and end the turn with `needs_info` instead of waiting. Do not make partial changes that would constrain the eventual resolution.

When several comments describe one root cause, reason about the root cause once, but answer each item in `issue_comment` with the disposition relevant to that item. When comments conflict, identify the conflicting assumptions and resolve them against user intent and repository evidence rather than choosing the more forceful reviewer.

## Evidence-based pushback

Push back when the suggestion would break a supported contract, contradict verified behavior, add unused scope, ignore a required compatibility constraint, or solve a problem the repository does not have.

Good pushback contains:

1. the conclusion;
2. the evidence that supports it;
3. the consequence of following the suggestion; and
4. a focused alternative or question when one is useful.

Keep the tone calm and collaborative. A brief courtesy may follow a substantive response, but generic thanks or praise must not serve as the acknowledgment. Avoid performative agreement, defensive language, status contests, and claims of certainty stronger than the evidence.

If later evidence disproves your position, correct it directly: state what changed your conclusion, adopt the supported disposition, and continue without defending the earlier mistake or writing a long apology.

## Compact examples

### Compatibility

Reviewer: "Remove this legacy branch."

Check the supported deployment targets before changing it. If the branch is still required, reject removal with the compatibility evidence. If the branch is required but contains the reported defect, adapt the suggestion by fixing that defect without dropping support.

### Unused expansion

Reviewer: "Implement proper metrics storage, filtering, and export."

Trace callers and the product contract first. If nothing uses the endpoint, propose removing the unused path or leaving it unchanged rather than building an unrequested subsystem. If it is used, implement only the metrics behavior the caller requires.

### Unclear interaction

Items 2 and 3 both change an API contract, and item 2 is ambiguous. Treat them as one blocked cluster. A separate typo fix may proceed only after verifying that it does not depend on or constrain that contract.
