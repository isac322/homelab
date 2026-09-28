# Evidence-Backed Five Whys Methodology

The skill keeps the accessibility of Five Whys while adding the branching, evidence, stopping, and corrective-action rules required for modern software systems.

## Methods combined

### Toyota Five Whys

Toyota's Why-Why practice asks repeatedly why an observed problem occurred so the correction reaches the process or mechanism rather than the visible symptom. The number five is a prompt, not a required depth.

Source: Toyota Motor Corporation, *Toyota Production System* — https://global.toyota/en/company/vision-and-philosophy/production-system/

### Sequence and causal-factor charting

DOE and NASA root-cause guidance reconstructs event sequences and distinguishes events from conditions before assigning causes. That practice motivates the mandatory timeline, evidence on every edge, and explicit observation gaps.

Sources:

- U.S. Department of Energy, *Root Cause Analysis Guidance Document*, DOE-NE-STD-1004-92 — https://www.standards.doe.gov/standards-documents/1000/1004-astd-1992
- NASA, *Root Cause Analysis* resources — https://www.nasa.gov/offices/ochmo/resources/rca/

### Fault-tree branching

Fault Tree Analysis uses AND gates for concurrent necessary conditions and OR gates for alternative paths. The skill borrows that notation without claiming a complete probabilistic fault tree. AND branches prevent a trigger from being mistaken for a sufficient cause; provisional OR branches keep competing explanations open until a discriminator resolves them.

Source: U.S. Nuclear Regulatory Commission, *Fault Tree Handbook*, NUREG-0492 — https://www.nrc.gov/reading-rm/doc-collections/nuregs/contract/cr0492/

### Counterfactual and sufficient-set reasoning

A cause should change the outcome under a suitable intervention, but a naive “remove X; does Y still happen?” test fails when two independent mechanisms can each produce Y. The skill therefore tests necessity within a minimal sufficient set and records independent sufficient sets rather than discarding overdetermined causes.

Source: Judea Pearl, *Causality: Models, Reasoning, and Inference* — http://bayes.cs.ucla.edu/BOOK-2K/

### Blameless postmortems

Google SRE postmortems treat human actions as system inputs, not terminal root causes, and require concrete follow-up actions. The skill names mechanisms and decisions, separates occurrence from escape and containment, and rejects “be more careful” as a correction.

Source: Google, *Site Reliability Engineering*, “Postmortem Culture: Learning from Failure” — https://sre.google/sre-book/postmortem-culture/

### Systems-theoretic controls

STAMP/CAST treats safety and reliability as control problems. Components may behave locally as designed while inadequate constraints or feedback permit a system-level failure. The skill uses this insight for its stop rule: continue until an actionable invariant, boundary, or feedback control is found, but do not force heavyweight CAST analysis onto every small defect.

Source: Nancy Leveson, *Engineering a Safer World* — https://mitpress.mit.edu/9780262533690/engineering-a-safer-world/

## Required distinctions

- **Occurrence:** why the defect or failure mechanism existed.
- **Escape:** why tests, review, monitoring, or validation did not detect it.
- **Containment:** why the effect spread, persisted, or became customer-visible.
- **Interim containment:** the temporary action that stops current impact while the permanent correction is developed.

These are separate causal and action branches. A test gap is usually an escape cause, not the cause of the defect; a rollback can contain impact without correcting the root cause.

## Corrective-action hierarchy

Prefer, in order:

1. eliminate the unsafe mechanism;
2. enforce the invariant mechanically at the source;
3. detect and contain recurrence automatically;
4. use procedural guidance only when stronger controls are impossible.

Every action maps to a causal node. The extent-of-condition sweep then searches for sibling sites that share the same broken invariant.

## Verification of corrective actions

Corrective-action verification follows the executed-evidence contract owned by `issue-validation`: the same reproducer must fail pre-fix and pass post-fix against the real code, with a healthy control, and any dependency substitute must be a contract-faithful mock grounded in the official primary specification. A source diff, log, or report is never proof that a corrective action works.

## Method limits

Five Whys remains an investigator-guided model. It can miss unobserved states, feedback loops, or emergent interactions; different investigators can build different graphs from the same sparse evidence. For high-consequence or strongly coupled failures, escalate from the compact causal graph to a fuller fault tree, barrier analysis, or STAMP/CAST study.
