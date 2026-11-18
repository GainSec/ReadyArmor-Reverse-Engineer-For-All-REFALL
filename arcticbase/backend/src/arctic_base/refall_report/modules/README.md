# REFALL Report Modules

REFALL closeout can produce several deliverables.
The pipeline can draft and enrich an internal report from backend coverage, ledger, finding, and object records.
Preserve enough evidence to produce the following modules.

## internal-generic

Produce a complete technical report.
Include findings, leads, false positives, duplicates, attack chains, coverage, and workbench provenance.
Include the closeout gate state, pending actions, runtime observations, capability decisions, and limitations.
Include Runtime Warnings from nonfatal projections.

## vendor-cna

Produce a disclosure package for the vendor or a CVE Numbering Authority (CNA).
Include only validated findings in the main body.
Remove local paths, speculative leads, deferred chains, secrets, and internal operator notes.

## operator-debrief

Describe loop progress, agent activity, coverage, and ledger statistics.
Include blockers, closeout gate failures, unresolved leads, pending actions, and retry failures.
Include capability decisions, negative results, and next actions.

## finding-deep-dive

Describe one finding with source anchors and request, response, or binary evidence.
Include the proof of concept, reproduction procedure, validation state, impact, likelihood, and remediation.
Include supporting visuals when useful.

## visual-evidence-pack

Create an optional bundle of supporting workbench objects.
Suitable objects include diagrams, screenshots, Graphviz images, CodeCharta data, and Codebadger or Joern slices.
They can also include codegraph output, dependency graphs, call graphs, exploit flows, coverage maps, and validation flows.

Use each visual to explain architecture, scope, an exploit path, data flow, validation, complexity, dependency risk, or coverage gaps.

## Enrichment inputs

Use ledger entries, closeout gate state, pending actions, nonfatal error projections, runtime observations, runtime artifacts, and capability decisions.
Include evidence graph counts when available.
Preserve `source_hashes` on transition receipts.
Present `capability_missing` and `scope_blocked` outcomes as validation limitations or debrief items.
Do not present those outcomes as validated findings.
Use the REFALL report contracts without report encryption.
