# REFALL AB Report Deliverable

REFALL closeout deliverables use HTML and persistent workbench objects.
The default internal report is self-contained HTML.
It supports an internal review archive and later conversion to a disclosure package.

## Supported deliverable modes

| Mode | Purpose |
| --- | --- |
| `internal-generic` | Complete technical report for the operator or client archive. |
| `vendor-cna` | Sanitized disclosure report with validated findings. |
| `operator-debrief` | Loop activity, coverage, gaps, and next actions. |
| `finding-deep-dive` | Evidence and remediation for one finding. |
| `visual-evidence-pack` | Optional supporting diagrams, screenshots, analysis files, and graph slices. |

## Required sections

- Executive summary.
- Tested scope and exclusions.
- Methodology.
- Coverage summary.
- Evidence ledger summary.
- Closeout gate state and blocker or warning table.
- Pending actions, deferred actions, and resolution receipts.
- Validated findings.
- Provisional findings.
- False positives and duplicates.
- Attack chains.
- Reproduction and PoC notes.
- Runtime evidence from projected observations, runtime artifacts, and evidence graph counts.
- Runtime Warnings from nonfatal runtime and ledger error projections.
- Capability decisions that affected live examination or validation.
- Source and configuration freshness receipts, including available `source_hashes`.
- `capability_missing` and `scope_blocked` outcomes that affected validation limits.
- Remediation guidance.
- Visual evidence summary when visuals improve review.
- Workbench object provenance.

Show closeout gate blockers in `internal-generic` and `operator-debrief` deliverables.
Include only validated, sanitized findings in `vendor-cna` reports.
Exclude speculative leads, internal capability requests, and local paths unless disclosure is explicitly approved.

Pending actions are report inputs.
For each open, done, deferred, or cancelled action, include its status and available source event, finding, or unit.
Include its receipt or limitation text.

Runtime evidence can include structured observations, retry failures, validation events, visual artifacts, and evidence graph changes.
Use the `visual-evidence-pack` for useful Codebadger, CodeCharta, codegraph, Graphviz, screenshot, request, response, and flow artifacts.

Runtime Warnings describe nonfatal submission failures, refusals, timeouts, and blocked actions.
They also describe capability or scope failures that affected the run.
Keep these warnings separate from findings.
