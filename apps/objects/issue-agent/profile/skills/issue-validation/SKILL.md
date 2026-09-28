---
name: issue-validation
description: Use as the reproduction/verdict step of isac-issue-triage, or directly when only claim verdicts, reproduction, mechanism-based deduplication, evidence grading, or fix provenance are needed without posting to GitHub, especially when comparing deployed artifacts, release tags, and current main. Produces a validated atomic-issue dossier; hand causal analysis to five-whys-root-cause-analysis.
---

# Issue Validation

Determine whether each reported problem is real, current, historical, environmental, duplicated, expected behavior, or unsupported — and prove it with evidence another investigator can audit. This skill owns the factual dossier: atomic claims, expected contract, reproduction, version states, verdicts, fix provenance, and relations.

## Boundary with five-whys-root-cause-analysis

Validation answers "is the claim true, where does it hold, and since when?" Root-cause analysis answers "why does the defect exist and what corrective action is adequate?"

Validation may:

- identify the mechanism that turns a defect into the observed failure — defect, infected internal state, observable symptom — bounded by evidence;
- record disproved hypotheses and bound the remaining uncertainty.

Validation must not:

- build why-chains or causal graphs;
- design corrective actions or judge their adequacy;
- declare a root cause.

When a claim is confirmed, hand the dossier to `five-whys-root-cause-analysis` using the handoff schema below. Do not start that analysis here.

## Non-negotiable output

Every atomic claim gets its own verdict, evidence, mechanism or bounded hypotheses, version status, relations, limitations, and recommended disposition.

A fixed claim also needs complete **fix provenance**. Never write only "fixed on main," "main fixed, unreleased," "already fixed," or "resolved." Those phrases hide where the fix came from and whether users can obtain it. For every fixed claim, record:

- upstream or fork repository;
- pull request number and URL, or an explicit "no PR";
- the commit that changes the behavior;
- the merge, squash, or rebase result commit on the target branch;
- merge time and base branch;
- the first release tag or version containing the fix, or "none";
- the latest published artifact version (package registry, container image, binary release);
- whether that published artifact contains the fix;
- any backport or release PR that changes availability.

An open PR, a closed-but-unmerged PR, or a PR merged only in a fork is not an upstream fix. State its actual status. Distinguish four states and never blur them: **fixed-in-PR** (commit exists on a PR branch), **merged** (on the target branch), **released** (in a published tag or artifact), **deployed** (the running artifact contains it).

## Verdict taxonomy

One verdict per atomic claim:

- **CONFIRMED_CURRENT:** executed reproduction of the defect on the current supported code or artifact (see the executed-evidence gate).
- **CONFIRMED_HISTORICAL_FIXED:** valid historical defect whose fix is verified on the target branch.
  - Record the exact fix state: **merged**, **released**, or **deployed**.
  - A repair that exists only on an open, unmerged, closed-without-merge, or fork-only PR remains **CONFIRMED_CURRENT**; record **fixed-in-PR** only in fix provenance.
- **PARTIALLY_FIXED:** one mechanism or symptom is fixed, but material reported behavior remains.
- **DUPLICATE:** the same executed-proven mechanism as a canonical issue. Name the canonical issue and the shared mechanism.
- **ENVIRONMENTAL:** the primary cause is outside the project's code or supported contract.
- **NOT_REPRODUCED:** the observation did not reproduce; state which hypotheses were disproved and which environment gaps remain.
- **NOT_A_BUG:** behavior matches the current contract or an intentional upstream boundary.
- **FEATURE_REQUEST:** the requested capability is absent but no existing contract is broken.
- **INCONCLUSIVE:** available evidence cannot distinguish the remaining explanations.

Never give a compound issue one verdict. Split it into atomic claims first.

## Executed-evidence gate

No defect-positive verdict (CONFIRMED_CURRENT, CONFIRMED_HISTORICAL_FIXED, PARTIALLY_FIXED, DUPLICATE) and no verified-fix claim stands without an executed reproduction. Run the real project code with a minimal reproducer and record the exact version, command, input, output, and assertion, plus an independent observable of the failure — never a tool's success string. Source reading, logs, reports, and stack traces are hypotheses and support; they never substitute for a run. Reproduce each duplicate claim and demonstrate the shared mechanism; a canonical issue's reproduction is supporting evidence, not a substitute. For a reported malfunction, ENVIRONMENTAL or NOT_A_BUG also requires execution of the reported scenario and comparison with the expected contract; do not use these labels to dismiss an unexecuted report. A pure capability request without a malfunction claim may be classified as FEATURE_REQUEST from its contract.

When a live external dependency is unavailable, substitute a contract-faithful mock or fake at the dependency boundary:

- never mock the project logic under investigation or hard-code its expected defective result; injected dependency faults must themselves be contract-supported and the real project code must produce the observed failure;
- document the official primary spec or documentation URL with version and section, each modeled behavior (errors, ordering, timing, state transitions as relevant), the conformance checks run against it, and every assumption;
- behavior the mock cannot ground in the cited spec cannot confirm the claim.

A verdict reached through a mock is recorded as reproduced against a contract-faithful mock, not as a demonstrated live-provider incident; unknown real-provider triggers stay open. If the dependency is unreachable and no faithful mock is possible, report the blocker and return NOT_REPRODUCED or INCONCLUSIVE — never force a verdict.

## Validation dossier

Maintain this record for every issue or atomic claim:

```text
Issue / claim:
As-of (UTC timestamp / main HEAD SHA / artifact digest):
Reported environment:
Reported version and install method:
Observation:
Reporter hypothesis:
Expected contract:
Deployed-artifact result:
Release-tag result:
Current-main result:
Introduced by (commit / first affected release):
Reproduction execution (version / command / input / output / assertion):
Execution basis (live | contract-faithful mock):
Mock contract (spec URL+version / modeled behaviors / conformance checks / assumptions):
Healthy-control result:
Mechanism bound (defect -> observable failure):
Disproved hypotheses:
Fix provenance:
  Fix state (none | fixed-in-PR | merged | released | deployed):
  Availability (unreleased | released-undeployed | deployed):
  Repository:
  PR:
  Behavior-changing commit:
  Target-branch result commit:
  Merge time / base:
  First containing release:
  Latest published artifact:
  Published fix availability:
  Deployed fix availability:
Duplicate / related issues:
Evidence grade:
Limitations:
User impact:
Recommended disposition:
```

Use exact dates and commit SHAs. Link the PR when the reporting surface supports links.

## Workflow

### 1. Inventory the full surface

1. List every issue in scope.
2. Read the complete issue body, comments, linked pull requests, commits, releases, and external reports.
3. Record the inventory at the start and refresh it before completion.
4. Assign each issue an independent investigation when parallel work is requested.

Do not sample "important" issues or silently omit proposals and environment reports.

### 2. Split observations from hypotheses

Extract separately:

- the observable symptom;
- reproduction steps;
- expected result;
- the reporter's causal explanation;
- the proposed fix;
- environmental facts.

Treat the symptom as a claim to reproduce. Treat the causal explanation and proposed fix as hypotheses to test.

For compound reports, create a claim table before investigating. Claims that touch different code paths, contracts, or mechanisms require separate verdicts.

### 3. Establish the expected contract

Before calling behavior a bug, establish what the project and upstream platform promise:

- public API and tool descriptions;
- documentation and supported environments;
- source-level invariants;
- upstream protocol, ABI, permission, and security rules;
- existing tests and product decisions.

An unsupported capability can be a useful feature request without being a defect. An upstream security boundary is not a project bug unless the project promises to bypass or abstract it.

### 4. Build a minimal, representative reproducer

Prefer the repository's existing Docker, VM, e2e, or CLI harness. Install missing packages inside a disposable environment when needed. Reduce the reproducer to the smallest input that triggers the claim — then execute it; an unrun reproducer is a hypothesis, not evidence.

Before interpreting a clean run, verify the test bed can express the reported condition:

- architecture and pointer width;
- language runtime and native-library versions;
- display backend, GPU, and scaling where relevant;
- live physical environment versus virtual or emulated substitutes;
- namespace, permission, and sandbox boundaries;
- package resolver and distribution channel.

A clean run in an incapable environment is not evidence against the issue. Record which reported conditions the test bed could not express.

Choose the smallest probe that isolates the mechanism:

- **FFI and native crashes:** audit `argtypes`/`restype`/ownership/variadic boundaries; capture registers, fault address, and first dereference; vary runtime and library versions to separate mechanism from correlation.
- **Hangs and timeouts:** replace the child with controlled variants (immediate exit, sleep, open socket, held pipe, forked descendants); record elapsed time, process tree, file descriptors, and every blocking primitive. Child exit does not imply pipe EOF.
- **Environment leaks:** put a fake helper first in `PATH` and dump its actual environment; trace every merge layer — a lower layer can reintroduce variables an upper builder removed.
- **Sockets, D-Bus, and daemons:** inspect arguments, socket files, listeners, ownership, and `/proc/<pid>/ns/*`; for D-Bus verify the exact bus name, object path, interface, and method. Distinguish a daemon visible in the process namespace from a socket or bus visible in the caller's namespace.
- **Coordinates and focus:** compare accessibility rectangles, compositor geometry, screenshot pixels, input-device regions, and output scale; name every coordinate space. Use `WAYLAND_DEBUG=1` or an equivalent event probe when applicable, and verify effects through independent application state rather than a tool's success string.
- **Dependencies and packaging:** inspect published package metadata, not only repository declarations; resolve in a clean environment; compare the release artifact with current main.

### 5. Compare three code states and trace provenance

Always compare:

1. the actual deployed or published artifact, including package metadata and installed source;
2. the release tag corresponding to that artifact;
3. current `main` or the requested HEAD.

Then trace any behavior difference to its origin:

1. use blame/log/bisect to identify the behavior-changing commit;
2. map that commit to its upstream PR;
3. verify whether it was merged, rebased, squashed, or cherry-picked;
4. determine which release tag first contains the target-branch result commit;
5. query the real distribution channel to see whether that release is published;
6. check which commit the deployed artifact was built from — it may be an unmerged PR head.

"Present in source" and "available to users" are different states. A local checkout, default branch, release tag, package registry, and running deployment may all behave differently.

### 6. Verify fixes bidirectionally

A verified fix requires:

1. an executed reproduction in which pre-fix code or artifact fails;
2. post-fix code passes under the same reproducer;
3. a healthy control still works;
4. adjacent failure modes do not merely move the symptom;
5. fix provenance is complete;
6. release and deployment availability are separately verified.

Do not accept a PR description or commit message as proof; the executed-evidence gate applies to fix claims exactly as to defect claims.

This step verifies a fix already claimed by the issue, PR, release, or artifact so the verdict and provenance are accurate. The Five Whys skill separately verifies a new corrective action derived from its causal graph.

### 7. Search for duplicates by mechanism

Group issues by proven mechanism, not title or visible symptom. Useful keys include crash frame, call site and malformed value, protocol event or missing state transition, dependency-resolution path, blocking primitive, coordinate-space mismatch, and permission or namespace boundary.

Use the earliest report as the canonical issue unless project policy says otherwise. A later report may remain the evidence of record when it contains stronger proof.

Issues fixed in one PR are not automatically duplicates. One PR may repair several unrelated mechanisms.

### 8. Grade evidence

- **A:** executed reproduction on the real path.
- **B:** executed reproduction through a contract-faithful mock or controlled proxy, with environment limits stated.
- **C:** the core symptom is not reproduced; some hypotheses supported or disproved. Source-only analysis, however rigorous, caps here.
- **D:** inference dominates; verdict remains provisional.

The verdict must not be stronger than the evidence grade permits.

### 9. Report relations precisely

Use distinct relation labels:

- **duplicate:** same mechanism;
- **same workflow:** blocks the same user journey through a different mechanism;
- **prerequisite:** one issue prevents reproduction or use of another;
- **adjacent contract:** shares a boundary such as coordinates, permissions, or lifecycle;
- **compound subclaim:** one part of a multi-problem issue;
- **amplifier:** a separate change that worsens the symptom without causing it.

Explain why each relation applies. Do not use "related" without a mechanism.

## Handoff to five-whys-root-cause-analysis

A claim is ready for causal analysis when its dossier is complete and the verdict is CONFIRMED_CURRENT, CONFIRMED_HISTORICAL_FIXED, or PARTIALLY_FIXED — each of which already requires an executed reproduction under the gate above. Never hand off a claim confirmed only by source, logs, or reports. Hand off this schema:

```text
Validated claim:
Verdict + evidence grade:
As-of (UTC timestamp / main HEAD SHA / artifact digest):
Expected contract:
Minimal reproducer (executed; version / command / input / output / assertion; live or mock basis):
Mechanism bound (defect -> observable failure):
Disproved hypotheses:
Open hypotheses for RCA:
Environment limits:
Version states (artifact / tag / main / deployed):
Introduced by (commit / first affected release):
Fix provenance (if any):
Relations:
```

The Five Whys skill owns everything downstream: the causal graph, competing hypotheses, counterfactuals, occurrence/escape/containment branches, stop criteria, and corrective-action adequacy. Do not duplicate that work in the dossier, and do not repeat this dossier's version-provenance workflow there.

For an INCONCLUSIVE claim whose observable effect is confirmed but whose explanations remain indistinguishable, send the effect, evidence, and open hypotheses to Five Whys for one bounded discriminator-design pass. Validation executes the returned probe, records the output in the dossier, and issues a new verdict; Five Whys does not execute the probe or continue the causal analysis until that verdict is ready.

## Completion criteria

Validation is complete only when:

- every issue and atomic claim has a verdict;
- pre-fix and post-fix behavior are compared for every fixed claim;
- the mechanism is independently observed through an executed reproduction, or the remaining uncertainty is bounded;
- deployed artifact, release tag, and current main are distinguished;
- every verdict is anchored to an exact as-of state, and provenance is re-verified when HEAD or the deployed digest has moved;
- every claim records the introducing commit and first affected release, or the explicit provenance bound that remains when a full bisection is impractical;
- every fixed claim has complete PR/commit/release/artifact/deployment provenance;
- duplicates and related issues are grouped by mechanism;
- the test bed's ability to express each defect is documented;
- direct verification and skipped or unrepresentable conditions are listed;
- each confirmed claim has a completed handoff schema;
- the final issue inventory still matches the requested scope.

## Anti-patterns

Never:

- promote a version correlation into a mechanism;
- confirm a defect from source reading, logs, or reports alone — they are hypotheses and support, never a substitute for an executed reproduction;
- mock the project logic under investigation, encode the desired failure into a fake, or let spec-ungrounded mock behavior confirm a claim;
- report a mock-based reproduction as a demonstrated live-provider incident;
- force a verdict when a dependency is unreachable and no faithful mock exists — report the blocker and return NOT_REPRODUCED or INCONCLUSIVE;
- trust a fix PR or commit message without verifying its effect;
- inspect only current main and declare the user problem fixed;
- write "main fixed, unreleased" without the fixing PR, commits, first containing release, and current artifact status;
- treat an open, unmerged, closed-without-merge, or fork-only PR as an upstream resolution;
- call a fix deployed when only the source or release contains it;
- group duplicates by title or symptom;
- give a compound report one verdict;
- trust a success string instead of an independent observable;
- treat process liveness, or an artifact's absence from a different namespace or vantage point, as proof of function or failure;
- use a clean run on another architecture or incapable environment as disproof;
- claim behavior was tested when the environment could not express it;
- verify a fix without a healthy control and the same reproducer pre- and post-fix;
- omit limitations, disproved hypotheses, or release and deployment availability;
- continue past a bounded mechanism into why-chains or corrective-action design — that is the Five Whys skill's scope.

## References

- `references/methodology.md` explains the scientific-debugging, anomaly-lifecycle, provenance, and factual-report methods behind this workflow.
- `references/flareway-cases.md` shows the workflow applied to four real controller and harness defects, including atomic-claim splitting, artifact/tag/main/deployed comparison, complete fix provenance, and the distinction between a cause and an amplifier.
