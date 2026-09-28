# Issue Validation Methodology

This reference explains why the `issue-validation` workflow is structured as a factual dossier rather than a root-cause narrative.

## Methods combined

### Scientific troubleshooting

Google SRE's troubleshooting method treats diagnosis as a hypothetico-deductive loop: observe, form testable hypotheses, design discriminating experiments, and use negative results to narrow the search. The skill therefore separates reporter observations from hypotheses, requires falsifiable probes, and records disproved explanations.

Source: Google, *Site Reliability Engineering*, “Effective Troubleshooting” — https://sre.google/sre-book/effective-troubleshooting/

### Defect–infection–failure and delta debugging

Andreas Zeller distinguishes the physical defect from the infected internal state and the eventual observable failure. His delta-debugging method also motivates reducing inputs and environment differences to the smallest failure-inducing delta. The skill's “mechanism bound” field stops at this defect-to-observable path; deeper organizational or systemic causes belong to Five Whys.

Source: Andreas Zeller, *Why Programs Fail* — https://www.whyprogramsfail.com/

### Formal anomaly lifecycle

IEEE 1044 distinguishes problem recognition, investigation, action, and disposition. That separation supports one verdict per atomic claim and prevents a reporter's proposed correction from being treated as proof that the reported anomaly is real.

Source: IEEE Std 1044-2020, *IEEE Standard Classification for Software Anomalies* — https://standards.ieee.org/ieee/1044/7106/

### Factual report before causal attribution

The NTSB investigation model separates factual collection from analysis and probable-cause determination. The skill applies the same bias control: validation freezes evidence, provenance, reproduction, and version state before handing the claim to causal analysis.

Source: National Transportation Safety Board, *Major Investigations Manual* — https://www.ntsb.gov/investigations/process/Documents/MajorInvestigationsManual.pdf

### Complex-systems caution

Complex failures often require multiple concurrent conditions, and hindsight makes the final outcome appear more predictable than it was. The skill therefore records environment limits, alternative explanations, and relations such as “amplifier” rather than forcing every observation into one mechanism.

Source: Richard Cook, *How Complex Systems Fail* — https://how.complexsystems.fail/

## Evidence grades

The four grades in the skill are an operational compression, not a universal standard:

- **A:** executed reproduction on the real path;
- **B:** executed reproduction through a contract-faithful mock or controlled proxy, with stated limits;
- **C:** the core effect is not reproduced, but some hypotheses are supported or disproved — source-only analysis, however rigorous, caps here;
- **D:** inference dominates, so the verdict remains provisional.

The grade limits how strongly the dossier may speak. It does not replace the evidence itself.

The executed-evidence gate follows the same hypothetico-deductive discipline: a defect is confirmed only by running the real project code against a minimal reproducer, or — when a live dependency is unavailable — against a contract-faithful mock whose modeled behaviors are grounded in the official primary specification. Logs, reports, and source reading generate and support hypotheses; they never confirm one.

## Why version and fix provenance are separate

A defect can differ across at least five independently moving states: local checkout, target branch, release tag, published artifact, and deployed artifact. A PR commit may exist without being merged; a merged fix may not be released; a released fix may not be deployed; and a deployment may be built from an unmerged branch. The dossier records each state explicitly because “fixed” is not a single fact.

## Boundary with causal analysis

Validation may identify the physical defect and infection path needed to prove the claim. It must stop before explaining why the design, review, test, or organizational control allowed that defect. Those are occurrence, escape, and containment questions owned by `five-whys-root-cause-analysis`.
