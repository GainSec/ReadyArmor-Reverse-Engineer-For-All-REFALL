# REFALL AB evidence requirements

## Evidence model

An observation records what the specialist examined or measured.
A lead records a question that requires more work.
A finding records a supported security conclusion.
A receipt records evidence for a decision or state transition.

Each finding includes the affected component, source anchors, reproduction procedure, impact, likelihood, remediation, and verification state.
Evidence-bearing submissions also include confidence and limitations.
Use artifact references when source anchors cannot represent the proof.

## Structured submissions

Return terminal results in a fenced `refall-submit` JSON block.
The schema name is `refall.submit.v1`.
The submission event is `task_result_submit`.
Use `submission_id` to identify the result.

The executor validates the payload before it applies coverage updates.
Duplicate structured submissions do not create duplicate findings.
`ref_all_executor/contract_payloads.py` supplies payload helpers.
Backend DTO validation is in `arcticbase/backend/src/arctic_base/refall/contracts.py`.

Set `REFALL_REQUIRE_STRUCTURED_SUBMIT=true` to require valid structured results.
A missing or malformed result then creates pending work instead of completed coverage.
Legacy terminal markers remain a compatibility format.

## Finding status and evidence quality

Status and evidence quality describe different properties.
Status describes the research workflow.
Quality describes the strength of the proof.

| Status | Meaning |
| --- | --- |
| `PROVISIONALLY_VALID` | Candidate finding that requires review. |
| `NEEDS_RESEARCH` | Finding that requires more examination. |
| `VALID` | Finding that passed the required checks. |
| `FALSE_POSITIVE` | Rejected finding with a supporting receipt. |
| `DUPLICATE` | Finding equivalent to a canonical finding. |
| `CHAINABLE_DEFERRED` | Preserved primitive that requires chain analysis. |

Evidence quality uses `HYPOTHESIS`, `CODE_CONFIRMED`, and `LIVE_CONFIRMED`.
Static confirmation does not establish runtime exploitability.

## Disposition receipts

Submit status changes through the finding transition endpoint.
Use typed evidence receipts for rejection, duplicates, deferral, severity reduction, and quality reduction.

| Receipt type | Evidence |
| --- | --- |
| `code_anchor` | Source or binary location that supports the claim. |
| `live_repro` | Reproduced runtime behavior. |
| `non_reachability_proof` | Routing or configuration proof that excludes the sink. |
| `duplicate_equivalence` | Same root cause, sink, and remediation as the canonical finding. |
| `scope_boundary` | Recorded scope or exclusion boundary. |
| `downgrade_with_trigger_inventory` | Relevant trigger paths and reason for reduced severity. |
| `chain_preservation` | Preserved primitive and remaining chain questions. |
| `patch_verification` | Patch evidence and verification results. |
| `operator_override` | Explicit operator decision and reason. |

A duplicate receipt identifies `duplicate_of`.
Receipts can include `source_hashes`.
The backend refuses a receipt when its source or configuration hashes are stale.
Accepted and refused transitions remain in the ledger.

## Pending actions and capabilities

Pending actions preserve unfinished obligations.
Examples include missing validation, exhausted retries, scope decisions, and operator requests.
A direct `capability_missing` result creates a capability request.
A direct `scope_blocked` result creates a `scope_decision` action.
Neither result completes the research unit.

Capabilities restrict live actions to the operator-approved class and scope.
The worker cannot approve its own live actions.

## Closeout and reports

The closeout gate checks unresolved pending actions, refused transitions, suppressive finding changes, report freshness, and validation proof.
Resolve each condition or record an operator override receipt.

Reports include scope, methods, findings, evidence, limitations, remediation, and verification state.
A visual evidence pack can contain screenshots, traces, CodeCharta views, Codebadger output, or exploit-flow diagrams.
Link each visual to the claim that it supports.

The ledger can record `codebadger-toolchain-not-run` when that tool did not run.
The publication flow records `vendor-cna-report-generated` for the corresponding report artifact.
Read the runtime report specification in `docs/superpowers/specs/2026-07-16-refall-report-format-spec.md`.
