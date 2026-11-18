# REFALL AB technical codex

This guide traces the implementation from operator intent to stored research, report updates, and checked campaign closeout.
Read [End-to-end workflows](end-to-end.md) for the operator sequence.
Read [Work modules](work-modules.md) for subject configuration.
Read [Control in depth](control-in-depth.md) for each enforcement boundary, guidance layer, default, and exception.

## 1. Operator controls reach backend operations

`WorkbenchOpsPanel.svelte` loads context, scope, threat model, coverage, ledger records, pending actions, capabilities, runtime evidence, and closeout checks.
Its lifecycle controls call the named operation API.
The Start control requests a subject launch grant through the capability API when needed.
Its browser client does not attach an operator token automatically.
When token protection is configured, an authenticated host-side client can establish the grant first.

The production CLI uses `RefallLoopManager`.
Its normal start and update methods call backend operations through `ArcticBaseClient`.
The injectable direct launcher supports controlled embedding and focused tests.

The backend `run_command` route checks whether named operations are enabled.
`_execute_named_command` validates and dispatches the requested command.
`_start_subject` creates or selects the workbench and requires stored context.
`_update_subject` reads the existing subject and requests a bounded pass.

Sources: [Ops panel](../arcticbase/frontend/src/lib/refall/WorkbenchOpsPanel.svelte#L85), [CLI manager](../ref_all_executor/loop_manager.py#L36), [backend dispatch](../arcticbase/backend/src/arctic_base/api/refall_ops_commands.py#L192).

## 2. Context becomes a shared input

`_context_subject` gathers subject material and runs the configured context writer.
The writer receives operator direction, metadata, selected source content, and workbench text.
Provider command construction is separate from the resulting briefing.
The output is Markdown rather than an agent conversation history.

`_save_context_artifacts` stores the briefing as a subject file and workbench object.
The coverage context record mirrors the same research input.
The standing loop reads that record when it builds later objectives.
The source inventory, scope overlay, and optional threat model remain distinct records.

This separation gives each specialist the same subject identity and declared boundaries.
It also lets the operator revise context without reconstructing a worker's private state.

Source: [Context generation and persistence](../arcticbase/backend/src/arctic_base/api/refall_ops_commands.py#L978).

## 3. Process launch has an authorization record

`_authorize_process_launch` constructs a `run_local_command` request.
It includes the standing-loop argument vector, a declared process effect, the requester, and the subject path.
The coverage store compares the request with active capability grants.
The backend appends the decision to the workbench ledger.
A refused decision returns HTTP 403 before process launch.

The capability matcher checks class, expiry, declared requester and grantor strings, and applicable host, port, method, and path conditions.
The token-protected grant route supplies an authenticated operator identity only when its token file is configured.
The default unset-token mode retains caller-supplied grantor fields.
It also checks declared or recognized network, Docker, Codebadger, secret, and destructive effects.
The general authorization route records a decision without executing a command.
The backend launch caller obeys refusal; direct worker tools do not automatically pass through that route.

`_launch_standing_loop` verifies the repository path, prepares the subject projection, and checks Agent Canvas.
It starts a detached process with the selected workbench URL and loop limits.
Continuous loops can install the configured supervisor schedule.
Bounded Update passes run without that continuous-loop schedule.

Sources: [Launch authorization](../arcticbase/backend/src/arctic_base/api/refall_ops_commands.py#L366), [capability matching](../arcticbase/backend/src/arctic_base/refall/coverage_store.py#L1764), [launcher](../arcticbase/backend/src/arctic_base/api/refall_ops_commands.py#L424).

## 4. Source projection and scratch state stay separate

`sync_agent_canvas_workspace` checks whether a matching Docker mount already supplies the source.
When a mount exists, it records its read-only or writable state.
Otherwise, it compares a source snapshot marker and copies the source when necessary.
The snapshot marker uses file count, total size, and modification information for synchronization.

The inventory supplies separate content hashes for research identity.
A synchronization marker and a source hash therefore serve different purposes.

The dispatcher prepares a deterministic writable directory for each assignment.
The path includes the subject, lane, task class, and unit identity or objective hash.
The objective identifies the scratch workspace and the subject source root separately.
An operator can supply a read-only source mount as an execution boundary.
The source-copy fallback does not create that restriction.
The dispatcher's read-only source statement is model guidance.
Process permissions and configured mounts determine actual file access.

Sources: [Workspace projection](../ref_all_executor/agent_workspace.py#L17), [workspace naming](../ref_all_executor/config.py#L245), [dispatcher](../ref_all_executor/standing_loop.py#L205).

## 5. Inventory establishes identity and examination units

`build_source_inventory` walks the subject under explicit exclusion rules.
It hashes content in chunks and records size, line count, and kind.
Unreadable files remain visible in the skipped list.
Symlink observations retain relevant source relationships.
Selected configuration directories, such as `.github`, remain eligible despite their dot prefix.

`_auto_enumerate_if_empty` stores the inventory and sends file records to coverage enumeration.
It runs only when coverage has no recorded lines.
A binary-only inventory creates `binary_analysis_plan_required` instead of synthetic line coverage.

`partition_file` and `build_units` turn supplied symbol ranges and uncovered lines into nonoverlapping units.
`claim_next` uses a database transaction to claim an open unit or an expired lease.
The default lease is 900 seconds.
`submit` requires file-bearing evidence and writes the characterization fields.

Sources: [Inventory builder](../ref_all_executor/source_inventory.py#L66), [automatic enumeration](../ref_all_executor/standing_loop.py#L1654), [unit and claim store](../arcticbase/backend/src/arctic_base/refall/coverage_store.py#L240).

## 6. Scheduling follows target state

`ModuleRegistry.from_config` reads the subject's module declaration.
The executable default selects security assessment and resolves its built-in characterization dependency.
Custom declarations, disabled identifiers, and overrides then shape the registry.
Validation rejects unknown classes, invalid concurrency values, missing dependencies, and dependency cycles.

Subject, finding, and later unit selection use `eligible_modules`.
That function checks supplied target properties, dependencies, completion tracking, active work, and module concurrency.
Later unit selection supplies the recorded path from its characterized-unit collection.
It does not supply the optional `unit_state` argument.
Finding selection supplies its recorded path when available.

Fresh breadth claims a coverage unit directly.
`_task_for_characterize` attaches the first active breadth module, uses task class `characterize`, and sets 30 iterations.
That branch uses the global concurrency limit rather than module path filters or per-module caps.
`ModuleScheduler` maintains subject, unit, and finding progress.
The standing loop then applies its dispatch order.

Pending actions and requested threat models take priority.
Subject modules supply foundational research.
Fresh coverage units supply breadth.
Finding and later unit modules supply additional proof and depth.

A module's `after` dependency applies to the same target.
The scheduler can therefore combine different kinds of work without a single global stage counter.

Sources: [Registry](../ref_all_executor/work_modules.py#L211), [eligibility](../ref_all_executor/work_modules.py#L333), [claim order](../ref_all_executor/standing_loop.py#L590).

## 7. Objective construction carries the contract

The task builder combines the stored briefing, scope overlay, blackboard, target, module objective, and routing reason.
Later unit passes also receive a prior-work instruction.
They must examine stored determinations and saved artifacts before extending the analysis.
The dispatcher then adds workspace and approved remote-resource information.

The output contract requests facts, leads, findings, flows, determinations, and durable artifacts.
A mapping-oriented subject can select the available no-findings contract.
That contract preserves architectural observations and leads without treating them as vulnerability findings.

Sources: [Task objective](../ref_all_executor/standing_loop.py#L888), [prior-work context](../ref_all_executor/standing_loop.py#L676), [output contracts](../ref_all_executor/standing_loop.py#L1222).

## 8. Output capture has several entry paths

An ACP worker can finish on a tool action without a populated final response.
`read_conversation_agent_text` therefore reads the persisted event stream.
It collects agent-authored message and action text in order.
A final-response request is a fallback.

While a worker runs, `_incremental_ingest` reads the event stream and workspace.
`_merge_submission_file` accepts structured submission content and embedded research observations.
`_register_workspace_artifact` preserves saved analysis material.
All paths converge on parsed findings, facts, leads, and flows.

`_persist_new_intel` computes stable identities for those records.
Incremental ingestion and terminal salvage share the same identity set.
A failed backend write removes staged identities so later polling can retry persistence.
Persistent submission markers prevent repeated terminal application across retries.

Sources: [Event capture](../ref_all_executor/standing_loop.py#L131), [workspace capture](../ref_all_executor/standing_loop.py#L932), [stable persistence](../ref_all_executor/standing_loop.py#L1073).

## 9. Evidence is retained before outcome handling

`_finish_conversation` classifies the invocation and parses the result.
It checks persistent submission identity before salvaging observations.
It then preserves available research output on both successful and failed outcomes.

A failed outcome saves its output artifact and records retry state.
A recoverable failure can launch a bounded repair attempt.
Other outcomes create capability, scope, or operator-review obligations.

The clean success path applies transitions and persists control requests.
Only a completed characterization task submits its coverage unit.
Later passes retain evidence without submitting the breadth result again.
A subject module with no canonical observations creates an ingestion-review action and remains incomplete.

Completed conversations save trajectory and event archives before cleanup.
A failed archive or cleanup has its own recorded state.

Source: [Terminal processing](../ref_all_executor/standing_loop.py#L1378).

## 10. Claim validation and disposition are separate

`evaluate_finding_candidate` examines evidence, confidence, source membership, scope, and claimed validation material.
The coverage store then establishes the canonical finding identity and related locations.
New findings begin with provisional or research-needed lifecycle state.

`transition_finding` validates the proposed current and next states.
It separately compares evidence-quality tiers.
A `VALID` transition requires a live reproduction receipt.
A quality increase requires the corresponding evidence type.
Suppression, duplicate decisions, chain deferral, and downgrades have their own receipt rules.

The store refuses stale source hashes and transitions that contradict relevant pending obligations.
It records both accepted and refused attempts.
The API layer adds the decision to the evidence trail.

Sources: [Candidate gate](../arcticbase/backend/src/arctic_base/refall/promotion_gates.py#L12), [transition store](../arcticbase/backend/src/arctic_base/refall/coverage_store.py#L1008).

## 11. Research memory uses explicit records

| Record | Responsibility |
| --- | --- |
| Coverage unit | Examination identity, lease, determination, evidence, and leads. |
| Ledger entry | Fact, lead, finding, validation, artifact, or decision event. |
| Blackboard | Compact shared notes for later tasks. |
| Module progress | Completed passes and known targets. |
| Runtime event | Run, task, session, and failure history. |
| Artifact | Durable file content and metadata. |
| Observation | Projected claim, evidence, confidence, and limitations. |
| Checkpoint | Stage state and input identities. |
| Run manifest | Current providers, source identity, resources, and stage status. |
| Analyst notes | Developing architecture and research narrative. |

The JSONL ledger records durable evidence and decisions.
Runtime SQLite stores events, projections, retries, manifests, and checkpoints.
The evidence graph relates those records.
Static call graphs remain separate tool outputs.

Resume preflight compares checkpoint input hashes before resumed work.
The manifest links source inventory and scope identifiers with the active run.
These records support continuity while the active agent or manager changes.

Sources: [Runtime store](../arcticbase/backend/src/arctic_base/refall/runtime_state.py), [projection](../arcticbase/backend/src/arctic_base/refall/projection.py), [resume check](../ref_all_executor/standing_loop.py#L2250).

## 12. Reports compile persistent evidence

`draft_report` collects coverage, ledger records, findings, runtime evidence, capabilities, and closeout information.
The HTML builder provides detailed finding articles and research sections.
The current report identifier is stored in `refall_current_report_object_id`.

`enrich_findings` merges equivalent finding locations and groups facts.
It also carries runtime observations, artifacts, pending actions, and decisions into the enriched structure.
Potential chain groupings remain hypotheses for analyst review.

Before replacement, draft and assembly paths compare populated structural sections.
A thinner candidate can be preserved as a diagnostic object while the richer report remains current.
This protects architecture, methods, and flow explanations accumulated during earlier research.

The report worker can maintain an `analyst-notes` artifact alongside the deliverable.
The determinations digest records coverage, evidence counts, and module completion counts.
Detailed per-unit determinations remain in coverage storage.

Sources: [Draft](../ref_all_executor/report_draft.py#L41), [enrichment](../ref_all_executor/report_enrich.py#L19), [replacement guard](../ref_all_executor/report_assemble.py#L16).

## 13. Closeout evaluates the campaign state

Closeout checks evidence-backed finding decisions, pending obligations, context, claims, proof, and report freshness.
A missing or stale current report blocks completion.
An open action or a deferred action without its receipt also blocks completion.

Coverage below the configured threshold produces a warning in the closeout gate.
The gate also reports advisory visual, toolchain, and disclosure conditions.
The `blocking` field distinguishes these checks from completion barriers.
Receipt-backed overrides remain explicit ledger records.

The CLI closeout path drafts, enriches, and refreshes the draft before evaluating the gate.
That last refresh includes evidence added during enrichment.
It prevents a newly updated evidence trail from leaving the report immediately stale.

Sources: [Closeout checks](../arcticbase/backend/src/arctic_base/refall/closeout_gate.py#L14), [CLI closeout](../ref_all_executor/loop_manager.py#L81).
