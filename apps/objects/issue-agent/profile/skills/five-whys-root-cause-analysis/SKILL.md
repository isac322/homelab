---
name: five-whys-root-cause-analysis
description: Use when tracing a validated defect to actionable root causes with evidence-backed, branching Five Whys — causal graphs, counterfactual tests, occurrence/escape/containment branches, and corrective-action adequacy.
---

# Five Whys Root-Cause Analysis

Turn a validated defect into a causal graph whose every edge carries evidence, then derive corrective actions that repair the broken invariant rather than suppress the symptom. Five Whys is a prompt, not a fixed-depth linear proof: ask "why" until the cause is actionable, branch wherever the evidence branches, and stop at mechanism, never at blame.

## Prerequisites

Start only from a validated atomic issue. The `issue-validation` skill owns claim splitting, reproduction, artifact/tag/main comparison, fix provenance, evidence grading, and verdicts. Do not redo that work here.

Required inputs before the first "why":

- one atomic claim with a CONFIRMED_CURRENT, CONFIRMED_HISTORICAL_FIXED, or PARTIALLY_FIXED verdict;
- the executed reproduction that demonstrates the defect — the `issue-validation` executed-evidence gate applies; source, logs, or reports alone are not a validated input;
- the expected contract the behavior violates;
- the code state (commit, artifact, or branch) on which the defect was observed.

If the input is compound or the observable effect itself is unproven, send it back to `issue-validation`. For an INCONCLUSIVE claim whose effect is confirmed but whose explanations remain open, this skill may perform one bounded discriminator-design pass: state falsifiable hypotheses and the exact probe that would separate them, then return that probe plan to validation for execution.

## Workflow

### 1. Anchor the effect

Write the defect as one observable sentence: subject, wrong behavior, and the evidence that shows it. "The worker exceeded its 30-second deadline and remained blocked in `waitForEOF` for 84 seconds" — not "the service is buggy."

### 2. Reconstruct the sequence of events

Build the shortest ordered timeline that explains the effect across every involved component. Use timestamps when trustworthy and logical ordering when clocks are unavailable. Mark observation gaps explicitly; races, retries, lifecycle transitions, and cleanup defects cannot be analyzed without knowing what happened before what.

### 3. Build the causal graph

Ask "why did this happen?" and answer only with mechanisms you can point to in code, logs, state, or protocol events. Each answer becomes a node; each "because" becomes a directed edge from cause to effect.

The graph branches. It is not a chain:

- **AND branch:** the child required several concurrent necessary conditions. Removing any one prevents the effect. Record all of them; a fix may target the cheapest or most invariant-bearing one.
- **OR branch:** two or more explanations remain live and evidence has not yet separated them. Keep them open until a discriminator resolves the branch; never silently pick one.

### 4. Attach direct evidence to every edge

An edge without evidence is a guess. For each edge, record the observation that supports it: a log line, a status field series, a code path with line numbers, a protocol event, or a reproduction output. When the best available evidence is inference, label it `[inference]` and mark the edge provisional.

### 5. State and test competing hypotheses

For every node with more than one plausible parent, write each competing explanation as a falsifiable statement, then find the discriminator that separates them: a field value, an event ordering, a targeted probe, or a code path that only one hypothesis traverses. Record disproved hypotheses with the evidence that killed them. A hypothesis that survives is still a hypothesis until its edge carries direct evidence.

### 6. Run the counterfactual test

For each proposed cause, ask: *if this cause were absent, would the effect still occur?*

- If no, the candidate is load-bearing; keep it.
- If yes because an independent sufficient mechanism would still produce the effect, record the separate sufficient sets. Do not drop either cause merely because the effect is overdetermined.
- Otherwise, test whether the candidate is a necessary element of a minimal sufficient set. Demote it to a contributing condition only when no evidence-backed sufficient set requires it.

Also run the forward check: *does this cause, by itself, suffice?* If the effect needs the cause plus a second condition, that is an AND branch — record both.

### 7. Read the chain backward with "therefore"

Start at the deepest cause and read upward: "A, therefore B, therefore C, therefore the observed effect." Skipped links surface as gaps where the next step does not actually follow. A chain that only reads forward ("and then…") usually hides an unexamined mechanism.

### 8. Trace three branches where they apply

A defect in a guarded system has up to three independent causal questions. Trace each as its own branch:

- **Occurrence:** why did the fault happen at all?
- **Escape/detection:** why did tests, review, monitoring, or validation not catch it before it reached the observed environment?
- **Containment/impact:** why did the fault spread or persist — missing isolation, missing fail-closed behavior, missing cleanup ordering?

A single root cause that answers only occurrence leaves escape and containment unexamined. A missing test belongs in the escape branch, not as the root cause of the defect itself.

### 9. Stop at an actionable cause

Stop asking "why" when the cause is:

- a broken or absent architectural invariant the team owns;
- a missing automated guardrail, check, or enforcement point;
- a defect in a feedback or control loop (watch, requeue, retry, drain);
- a contract assumption contradicted by the platform.

Never stop at:

- exactly five questions — depth is set by evidence, not counting;
- "human error," "mistake," "oversight," or a named person — ask why the system permitted the error to take effect;
- an external cause outside the team's scope — record it, then ask why the system depended on it unguarded;
- a cause so abstract ("technical debt," "time pressure") that no concrete action follows.

If the remaining live cause is not actionable, say so and report the deepest actionable ancestor instead of inventing one.

### 10. Derive corrective actions and sweep the extent of condition

Prefer actions in this order:

1. **Eliminate** the hazard: remove the code path, state, or dependency that permits the defect.
2. **Enforce the invariant mechanically:** validation, fail-closed gates, ordering constraints, single-writer rules — things that make the defect unrepresentable.
3. **Detect and contain:** watches, alerts, bounded retries, isolation, cleanup ordering.
4. **Procedural:** documentation, checklists, review steps. Weakest; acceptable only when no mechanical option exists.

Match each action to a specific node in the graph. An action that addresses only the occurrence branch while the defect escaped through a missing test and spread through missing isolation is a partial fix — say so.

Search for other call sites, resources, or subsystems that share the broken invariant. Record the sweep as "N siblings found and included", "none found", or "not applicable"; fixing only the reported instance leaves the root cause alive elsewhere.

Record interim containment separately from the permanent correction, including its risks and the condition for retiring it. A mitigation that stops current impact is not proof that the root cause is fixed.

### 11. Verify the corrective action

A fix is adequate only when:

- it repairs the broken invariant identified in the graph, not a symptom downstream of it;
- it fails on the pre-fix state and passes post-fix under the same executed reproducer, with a healthy control still passing;
- adjacent failure modes do not merely relocate the symptom;
- escape and containment branches get their own actions when warranted;
- it adds no retry, special case, or message check that suppresses the symptom while the mechanism survives.

Do not accept a PR description, commit message, or source diff as proof. The `issue-validation` executed-evidence gate applies unchanged: run the same reproducer pre- and post-fix plus a healthy control; when a live dependency is unavailable, its contract-faithful-mock requirements govern any substitute.

This step verifies the new corrective action derived by this analysis. `issue-validation` separately verifies pre-existing fix claims when determining a verdict and tracing provenance.

## Language

Write blamelessly. Name mechanisms, states, and decisions, not people. "The scheduler had no event source for configuration changes, so the cached decision remained active" — not "the author forgot the watch." Blameless does not mean vague: the mechanism must still be exact.

## Report template

```text
Defect (one observable sentence):
Validated input (issue, verdict, evidence grade):
Observed on (commit / artifact / environment):
Sequence of events (timestamps or logical order, with gaps):

Causal graph:
  Effect
  └── Cause (evidence: …)
      ├── AND: concurrent condition (evidence: …)
      ├── OR: competing hypothesis A (evidence: …)
      │     competing hypothesis B (evidence: …; discriminator: …)
      └── …

Occurrence branch root cause:
Escape/detection branch root cause:
Containment/impact branch root cause:

Counterfactual checks:
Disproved hypotheses:
Backward "therefore" read:
Extent-of-condition sweep:
Interim containment and retirement condition:

Corrective actions (mapped to nodes, hierarchy level):
Fix verification (pre/post-fix reproduction result):
Residual risk and open OR branches:
```

## Completion criteria

The analysis is complete only when:

- the sequence of events is recorded with observation gaps explicit;
- every edge carries direct evidence or is marked provisional `[inference]`;
- every OR branch is resolved by a discriminator or reported as open;
- counterfactual and backward "therefore" checks have been run and recorded;
- occurrence, escape, and containment branches are each traced or explicitly marked not applicable;
- every root cause is actionable and inside the team's scope, or the gap is reported;
- each proposed corrective action maps to a graph node and a hierarchy level;
- the extent-of-condition sweep covers sibling sites that share the invariant, or records why it is not applicable;
- interim containment is recorded with a retirement condition, or marked not applicable;
- any corrective action claimed as implemented has executed pre-fix and post-fix reproductions under the same reproducer, plus a healthy control.

## Anti-patterns

Never:

- start from an unvalidated claim or a reporter's hypothesis;
- write a linear five-step chain when the evidence branches;
- promote correlation ("it started after commit X") into a cause without a mechanism;
- accept "human error," "forgot," or a person's name as a root cause;
- stop at exactly five whys, or keep going past an actionable invariant into abstraction;
- merge occurrence, escape, and containment into one cause;
- propose a fix that suppresses the symptom — retries, special cases, message parsing — while the mechanism survives;
- claim a fix works from its description alone;
- treat a source diff, log, or report as proof of a fix — the `issue-validation` executed-evidence gate applies to corrective actions too;
- repeat the `issue-validation` dossier: verdicts, artifact/tag/main comparison, and fix provenance live there, not here.

## References

- `references/methodology.md` explains the Toyota, causal-factor, fault-tree, counterfactual, postmortem, and systems-theoretic methods combined by this workflow.
- `references/flareway-cases.md` walks four real defects (Flareway issues #11–#14) through the workflow, including a bounded open OR branch with a named discriminator.
