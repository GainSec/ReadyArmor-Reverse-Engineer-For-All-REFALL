# REFALL AB Codex manager

The Codex manager is the default REFALL head provider.
Use `REFALL AB` as the product name.
ArcticBase and `arctic-base` are backend implementation names.
Include separately deployed backend instances in lifecycle actions only when the operator requests them.

## What To Read First

For a new infrastructure session, read `starthere/` in numeric order.
The alternate startup pack is `docs/codex-startup/*.md`.
The documentation index is `docs/README.md`.

1. Read `AGENTS.md`.
2. Read `REFALL-MANAGER-OPERATING-GUIDE.md`.
3. Read `docs/manager/AGENTS.md`.
4. Read `OPERATING_GUIDE.md`.
5. Read `/api/workbenches/{slug}/coverage/context`.
6. Examine coverage statistics and gate state.
7. Read recent ledger entries.

## Manager Commands

Use `/api/refall/ops/command` for named operations.
For example:

```bash
curl -fsS -X POST "$REFALL_PUBLIC_BASE_URL/api/refall/ops/command" \
  -H 'content-type: application/json' \
  -d '{"command":"start example"}'
```

Subject commands are `doctor`, `estimate`, `context`, `threat-model`, `start`, `update`, `closeout`, `coverage`, and `logs`.
Each subject command takes a subject slug.
`agents` is a global command.
The equivalent CLI starts with `python3 -m ref_all_executor`.

## Context

The manager reads stored context before startup.
Startup does not generate context automatically.
The operator first creates the briefing through the Context tab or `context SUBJECT`.
That command uses the configured context-writer CLI.
The usual Codex command is:

```bash
codex exec -C /absolute/path/to/subject --sandbox read-only -c 'approval_policy="never"' -
```

Return only Markdown for `context.md`.
The backend stores the output as the Context object, `<subject-path>/context.md`, and `/api/workbenches/{slug}/coverage/context`.
A start request is rejected until stored context exists.

With `REFALL_ENABLE_LOOP_LAUNCH=true`, start and update require a subject-scoped `run_local_command` capability.
The operator must grant that capability.
Self-issued grants do not authorize live actions.

## Loop Management

1. Generate or save context.
2. Run Doctor and Estimate during subject preparation or diagnosis.
3. Start the loop.
4. Examine Ops, Debug, Ledger, Runtime, Nonfatal Errors, and Logs.
5. Request Update for a bounded cycle when necessary.
6. Request Closeout when coverage and validation are complete.

An authorized start launches this runner:

```bash
python -m ref_all_executor.standing_loop --subject example --workbench example --max-cycles 0
```

The standing loop does these tasks:

- Read context, coverage, gate state, and the ledger.
- Claim open or expired pending actions before ordinary coverage units.
- Enumerate source units when coverage is empty.
- Route work to specialist lanes.
- Dispatch Agent Canvas conversations.
- Poll active conversation identifiers, or CIDs.
- Parse `refall-submit` blocks and compatibility findings, facts, leads, and asks.
- Write ledger records and resolve pending actions with receipts.
- Submit source coverage only for completed coverage tasks.
- Maintain `.refall/blackboard.json`.
- Record runtime events and project observations and evidence relationships.
- Refresh reports at the configured interval.

Update uses the same runner with `--max-cycles 1`.
It resumes active CIDs from `.refall/loop_state.json`.
It polls those conversations and fills available slots once.

The standing loop supplies approved SSH resources in specialist task prompts.
The current aliases are `sectortw` and `sectortl`.
Assign an alias when the task requires a remote operating system or host-local environment.
Require `ssh <alias> <command>` for remote commands.

Grok is not an SSH resource.
It is an optional host-orchestrated provider lane for subject-material tasks selected by the manager.
Grok must not receive host credentials, SSH aliases, LAN authority, unrestricted host access, or operator secrets.
The manager records accepted sandbox results through the backend APIs.

Examine these resources during operation:

- `/api/refall/ops/agents`.
- `/api/refall/ops/debug/{subject}`.
- `/api/refall/ops/debug/{subject}/live`.
- `/api/workbenches/{slug}/ledger/entries`.
- `/api/workbenches/{slug}/pending-actions`.
- `/api/workbenches/{slug}/runtime/events`.
- `/api/workbenches/{slug}/runtime/manifest`.
- `/api/workbenches/{slug}/runtime/nonfatal-errors`.
- `/api/workbenches/{slug}/runtime/artifacts`.
- `/api/workbenches/{slug}/runtime/evidence-graph`.
- `/api/workbenches/{slug}/capabilities`.
- `/api/workbenches/{slug}/closeout/gate`.
- `<subject-path>/refallsubloop/logs/events/events.jsonl`.
- `<subject-path>/refallsubloop/logs/loop/standing-loop-*.log`.

Before closeout:

1. Run `report draft`.
2. Run `report enrich`.
3. Examine the closeout gate or an operator override receipt.
4. Examine the current report object.
5. Append the closeout result to the ledger.

The report must include runtime evidence and Runtime Warnings from nonfatal projections.
Include useful visual artifacts, pending or deferred state, capability decisions, and limitations.

## Report Enrich

Enrichment combines verified findings, validation, coverage, proof-of-concept artifacts, and remaining limitations.
It also includes projected observations, evidence graph counts, capability decisions, and negative coverage.

Set `REFALL_REQUIRE_STRUCTURED_SUBMIT=true` when the run requires valid structured submissions.
Malformed or missing results then become pending actions instead of completed coverage.
A `control_submit` with `status: "needs_capability"` creates pending work.
It does not complete the claimed coverage unit.
A direct `capability_missing` result opens a capability request.
A direct `scope_blocked` result opens a `scope_decision` pending action.

The standing loop writes `/api/workbenches/{slug}/runtime/manifest` and stores the manifest in runtime SQLite.
It publishes the same record as the `REFALL Run Manifest` runbook object.
Reports include the Run Manifest section when that record exists.

Use a stable `submission_id` in terminal payloads.
Duplicate submissions are ignored by `submission_id` or task and unit identity.
New findings must begin as `PROVISIONALLY_VALID` or `NEEDS_RESEARCH`.
Transitions to `VALID`, `FALSE_POSITIVE`, `DUPLICATE`, and `CHAINABLE_DEFERRED` require typed receipts through the backend.

Use `source_hashes` when a receipt depends on exact source or configuration bytes.
The backend refuses stale hashes against `refall_source_path`.
Canonical deduplication uses `dedup_key`, `canonical_finding_id`, and `related_locations`.
Preserve variant locations in the canonical finding.

Typed DTOs are in `arcticbase/backend/src/arctic_base/refall/contracts.py`.
Payload helpers are in `ref_all_executor/contract_payloads.py`.
Evidence-bearing submissions require `evidence`, `confidence`, `limitations`, and `source_anchors` or `artifact_refs`.
Nested findings require a concrete location through `code_paths`, `source_anchors`, or `artifact_refs`.
