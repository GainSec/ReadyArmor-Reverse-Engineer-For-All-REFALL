# REFALL AB agent guide

REFALL AB is the product name.
Use `REFALL AB` in status messages and lifecycle instructions.
ArcticBase and `arctic-base` identify the backend implementation and process.

A REFALL AB lifecycle request applies to the configured REFALL services.
These can include the backend, research loop, Agent Canvas/OpenHands, coverage, watchdog, and analysis tools.
Keep a separately deployed ArcticBase instance outside that request unless the operator includes it.

## Roles

| Role | Responsibilities |
| --- | --- |
| Codex manager | Read `CODEX.md`, generate context, select work, dispatch specialists, examine gates, and maintain the ledger. |
| Claude specialist | Read `CLAUDE.md`, do the assigned research or report work, and submit evidence through the backend APIs. |
| Grok specialist or manager | Use the configured optional provider role and obey the same REFALL contracts. |

Managers must read `REFALL-MANAGER-OPERATING-GUIDE.md` and `docs/manager/AGENTS.md` before infrastructure or lifecycle operations.
For a new manager session, read `starthere/` first.
The alternate startup pack is `docs/codex-startup/*.md`.
The documentation index is `docs/README.md`.

## Canonical State

The workbench backend stores the authoritative research state.
Local notes, terminal output, and chat become authoritative only after they are stored there.

The following paths use `/api/workbenches/{slug}` as their prefix.

| Path | Record |
| --- | --- |
| `/` | Workbench metadata. |
| `/coverage/context` | Shared subject briefing. |
| `/coverage/source-inventory` | Source inventory. |
| `/coverage/scope-overlay` | Scope boundaries. |
| `/coverage/threat-model` | Threat model. |
| `/coverage/*` | Coverage units, claims, and findings. |
| `/ledger/entries` | Evidence and decisions. |
| `/pending-actions` | Unresolved obligations. |
| `/runtime/events` | Runtime event records. |
| `/runtime/manifest` | Current run manifest. |
| `/runtime/nonfatal-errors` | Read-only error projection. |
| `/runtime/observations` | Projected observations. |
| `/runtime/artifacts` | Artifact records. |
| `/runtime/evidence-graph` | Evidence relationships. |
| `/capabilities` | Scoped capability records. |
| `/execution/authorize` | Authorization decisions. |
| `/closeout/gate` | Closeout conditions. |
| `/refall-report` | Current report object. |

Operation routes use `/api/refall/ops/*`.

## Required Flow

1. Create or select one workbench for each subject.
2. Generate `context {subject}` through `/api/refall/ops/command`.
3. Run `doctor {subject}` and `estimate {subject}` during preparation or diagnosis.
4. Read the stored context before you claim coverage units.
5. Examine source inventory, scope, coverage statistics, and gate state.
6. Request `threat-model {subject}` when it will guide discovery or validation.
7. Claim units through the coverage APIs.
8. Submit summaries with concrete evidence.
9. Return terminal specialist output as fenced `refall-submit` JSON.
10. Submit proposed finding changes through the disposition gate with typed receipts.
11. Resolve open or claimed pending actions before ordinary coverage work.
12. Request the required capabilities before live actions.
13. Obtain an operator launch grant before Start or Update when launch execution is enabled.
14. Assign remote SSH resources only when the subject requires them.
15. Append important decisions, findings, validation, runtime events, and report changes to the ledger.
16. Keep the runtime manifest current.
17. Read the nonfatal error projection for diagnosis.
18. Run `report draft`.
19. Run `report enrich`.
20. Resolve closeout conditions or record an operator override receipt.

Legacy terminal markers remain a compatibility format.
Payload helpers are in `ref_all_executor/contract_payloads.py`.
Backend DTO validation is in `arcticbase/backend/src/arctic_base/refall/contracts.py`.

Evidence-bearing submissions require `evidence`, `confidence`, and `limitations`.
They also require `source_anchors` or `artifact_refs`.
Typed transition receipts cover false positives, duplicates, downgrades, deferred findings, and live reproduction.
Include `source_hashes` when a receipt depends on exact source or configuration bytes.

Live network, write, Docker, Codebadger, and destructive actions require the corresponding capabilities.
A direct `capability_missing` result opens a capability request.
A direct `scope_blocked` result opens a `scope_decision` pending action.

With `REFALL_ENABLE_LOOP_LAUNCH=true`, Start and Update are `run_local_command` actions.
Each requires an operator grant scoped to the subject.
Agents cannot authorize their own live actions.
Self-issued grants do not satisfy `/api/workbenches/{slug}/execution/authorize`.

The current SSH aliases are `sectortw` and `sectortl`.
Use `ssh <alias> <command>` for an assigned resource.
Record the alias, command, evidence references, and limitations.

The standing loop writes the manifest at startup and when it returns to an idle or running state.
The backend publishes it as the `REFALL Run Manifest` runbook object.
The nonfatal error endpoint is a read-only projection of existing records.
Do not write evidence to that projection.

## Evidence Rules

Each finding requires these records:

- Source path and available line or function references.
- Reproduction steps.
- Affected component.
- Impact and likelihood.
- Remediation.
- Verification status.

Redact secret values.
Record their presence only.

Store pending actions, capability decisions, projected observations, and visual evidence in the workbench.
These records preserve research progress across manager restarts and provider changes.
Keep one canonical finding for each root cause.
Preserve variant evidence locations in `related_locations`.
Create separate findings only when the evidence supports separate root causes.
