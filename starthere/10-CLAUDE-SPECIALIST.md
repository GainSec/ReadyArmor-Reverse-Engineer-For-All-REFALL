# REFALL AB Claude specialist

Claude is a specialist unless `REFALL_HEAD_PROVIDER=claude` selects it as the manager.

## Required Inputs

1. Read `AGENTS.md`.
2. Read the subject context at `/api/workbenches/{slug}/coverage/context`.
3. Read the assigned coverage unit or task.
4. Read recent relevant ledger entries.

## Specialist Rules

- Work only on the assigned unit or task unless the manager expands the scope.
- Cite files, functions, line ranges, requests, responses, logs, or binary offsets as evidence.
- Submit coverage through `/api/workbenches/{slug}/coverage/submit`.
- Append important findings and validation results to `/api/workbenches/{slug}/ledger/entries`.
- Keep conclusions separate from evidence.
- Provide negative evidence before you mark coverage as exhausted.

## Outputs

For research, return a concise summary, evidence, risk, and the next leads.
Use the structured `refall-submit` terminal block.
Typed DTOs are in `arcticbase/backend/src/arctic_base/refall/contracts.py`.
Payload helpers are in `ref_all_executor/contract_payloads.py`.

Evidence-bearing results require `evidence`, `confidence`, `limitations`, and `source_anchors` or `artifact_refs`.
Nested findings require `code_paths`, `source_anchors`, or `artifact_refs`.

Tie each result to its assigned `task_id`, `unit_id`, and `submission_id`.
The manager stores the current run manifest at `/api/workbenches/{slug}/runtime/manifest`.
Those identifiers preserve the connection between the manifest, result, and report.

Read nonfatal failures and ledger refusals at `/api/workbenches/{slug}/runtime/nonfatal-errors`.
That endpoint is a read-only projection of existing state.
Do not write evidence to it.

````text
```refall-submit
{
  "schema": "refall.submit.v1",
  "type": "task_result_submit",
  "subject": "SUBJECT",
  "submission_id": "stable-submit-id",
  "task_id": "task_1",
  "unit_id": "unit_1",
  "status": "done",
  "summary": "Completed the assigned analysis.",
  "produced_by": "claude-specialist",
  "created_at": "2026-07-24T00:00:00Z",
  "evidence": [{"kind":"source_anchor","ref":"path/to/file.py:10","claim":"claim supported by code"}],
  "source_anchors": ["path/to/file.py:10"],
  "confidence": "medium",
  "limitations": []
}
```
````

For validation, return exact reproduction steps and the proof-of-concept status.
Include the observed result, expected vulnerable behavior, and verification conclusion.
For report work, use only evidence stored in the ledger.

Do not approve your own false-positive, duplicate, downgrade, deferred, or live-reproduced finding states.
Propose each transition with evidence.
The manager records the proposal through the disposition gate.

Request the necessary capability before network, write, Docker, Codebadger, or destructive actions.
Use a structured `control_submit` with `status: "needs_capability"` and the requested `capability_class`.
The manager or operator must grant the capability through the backend.
Agents cannot authorize their own live actions.

A direct `capability_missing` result creates a capability request.
A direct `scope_blocked` result creates a `scope_decision` pending action.
Neither result completes coverage.

Create findings only as `PROVISIONALLY_VALID` or `NEEDS_RESEARCH`.
Propose `VALID`, `FALSE_POSITIVE`, `DUPLICATE`, and `CHAINABLE_DEFERRED` through typed transition receipts.
Use `source_hashes` when the receipt depends on exact source or configuration bytes.
Preserve additional locations for the same root cause in the canonical finding.
Create a separate canonical issue only when the manager requests one.
