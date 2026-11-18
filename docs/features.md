# REFALL AB feature catalog

REFALL organizes research into persistent subjects, bounded execution, evidence, decisions, and deliverables.
These features work together around one subject workbench.

## Subject workbench

Each subject has metadata, a source path, a storage path, context, and a theme.
Coverage, ledger entries, pending actions, capabilities, and reports belong to the same workbench.
The operator can inspect the research without reconstructing it from terminal history.

The Ops panel presents Context, scope, threat model, live agent state, coverage, runtime records, and closeout information.
It can generate or save context, request a threat model, run diagnosis, estimate work, and issue lifecycle commands.
Pending actions can be resolved, deferred, or cancelled with receipts.
Capability requests and grants remain visible beside the research.

Source: [WorkbenchOpsPanel](../arcticbase/frontend/src/lib/refall/WorkbenchOpsPanel.svelte).

## Research ledger and Output projection

The subject ledger records facts, leads, findings, validation, artifacts, decisions, and operational events.
Its API appends JSONL records and supplies filtered lists, individual entries, and summary statistics.
The Ops Ledger view exposes the history.
The Output view filters research records and expands their evidence, next steps, and worker identifiers.
Reports read the ledger together with coverage and runtime state.

The ledger preserves evidence history.
Finding, capability, and pending-action APIs perform their corresponding state transitions.
Read [Ledger and wishlist](ledger-and-wishlist.md) for exact entry fields and route examples.

## Resource requests and delivery

The wishlist records missing tools, dependencies, access, and other research needs.
The watchdog reads open and provided records.
For supported executable requests, it checks host availability and can use its configured fixed installer list.
Delivery appends a provided row and a linked ledger receipt.
The original request stays in history.

Head cycles read the delivered resources before preparing objectives.
The research driver and three binary drivers include a provided-item snapshot loaded at startup.
Their prompts tell workers to use delivered items before requesting duplicates.
The standing loop selects pending actions, coverage units, and work modules through separate queues.
Read [the delivery lifecycle](ledger-and-wishlist.md#watchdog-provision).

## Connected research cycles

Campaign polling, module passes, worker retries, reporting, and supervision have separate triggers and state.
A coordinator cycle can ingest observations from a still-active worker.
A terminal result preserves useful evidence before handling the classified outcome or scheduling retry.
Per-target dependencies permit different components to advance at different rates.
Read [Research cycles](research-cycles.md) for the priorities, limits, and feedback paths.

## Shared context and readiness

Context generation collects subject metadata, source material, workbench text, and operator direction.
The selected provider produces a Markdown briefing.
REFALL stores the briefing in a workbench object, subject file, and coverage context record.
The backend refuses a start request without stored context.

Doctor examines services, provider commands, paths, context, capabilities, secrets presence, and relevant tooling.
Estimate combines inventory size, remaining coverage, pending actions, and readiness.
Its task count helps the operator plan the run.

Source: [Context and readiness operations](../arcticbase/backend/src/arctic_base/api/refall_ops_commands.py).

## File identity and coverage

The inventory records relative paths, SHA-256 hashes, file sizes, line counts, and detected kinds.
It streams file content without a fixed file-size ceiling.
It records unreadable files and relevant symlink observations.
Scanner exclusions keep dependencies and generated runtime state outside ordinary inventory.

Coverage units divide files into symbols or line ranges.
Claims use leases so interrupted workers do not retain permanent ownership.
A successful characterization stores a summary, sensitivity, data touched, incoming flows, outgoing flows, and leads.
The coverage view can then answer both what was examined and what the examiner learned.

A resolved percentage measures recorded characterization and dead-code dispositions.
It is distinct from vulnerability proof and behavioral completeness.
Binary-only intake requests an explicit analysis plan instead of inventing line coverage.

Sources: [Inventory](../ref_all_executor/source_inventory.py), [coverage store](../arcticbase/backend/src/arctic_base/refall/coverage_store.py).

## Composable work modules

A module declares its task class, target source, dependencies, selection rules, priority, and execution limits.
Its target can be the entire subject, an examined coverage unit, or a finding.
A dependency applies to the same target rather than imposing a global phase on every worker.

Seven packs supply characterization, reverse engineering, security assessment, research, development, dynamic examination, and static analysis.
Custom declarations can add subject-specific work without a new core driver.
Path filters focus later unit passes on recorded component paths.
Per-module limits control subject, finding, and later unit selection.
Fresh characterization uses coverage claims and the global loop concurrency limit.
That breadth path attaches the first active breadth module without applying module path filters.

The default selection enables security assessment and its characterization prerequisite.
An explicit baseline selection supports a characterization-focused campaign.
Read [Work modules](work-modules.md) for configuration examples.

Source: [Module registry and scheduler](../ref_all_executor/work_modules.py).

## Specialist routing

The router maps task classes to specialist lanes and verification expectations.
Claude normally handles research, interpretation, review, and synthesis.
Codex normally handles enumeration, tooling, harness creation, patching, and verification.
A subject lane pattern can distribute configured providers across active slots.

Optional Grok work uses a host-managed sandbox configuration.
The manager transfers permitted subject material and records accepted results through REFALL.
It has a separate execution role from the normal Claude and Codex Agent Canvas lanes.

Sources: [Router](../ref_all_executor/router.py), [lane configuration](../ref_all_executor/config.py).

## Continuous evidence capture

Agent output can occur in messages, action text, structured submission files, or saved analysis files.
REFALL reads these channels during the run.
A specialist can therefore contribute useful observations before its final response.

Incremental ingestion and terminal processing share stable evidence identities.
This prevents the same fact from appearing again on each poll.
If the backend cannot persist an item, its identity remains eligible for a later attempt.

At termination, the loop classifies the invocation and parses its output.
It checks submission identity and preserves observations before handling the classified outcome.
A stopped worker can leave valuable evidence while its assigned task remains unfinished.
A subject module with no durable observations creates pending work instead of a false success.

Source: [Evidence capture](../ref_all_executor/standing_loop.py#L932).

## Structured results

The `refall.submit.v1` schema separates task results, findings, evidence changes, control requests, and threat models.
Evidence-bearing results carry confidence, limitations, and source anchors or artifact references.
Nested findings require concrete locations.
Stable submission identifiers prevent repeated application of terminal results.

The parser also accepts legacy facts, leads, flows, coverage markers, and finding blocks.
Strict mode makes a missing or malformed structured result a pending obligation.
The loop can fill assignment metadata that it already knows.
It does not create missing source proof.

Sources: [Submission parser](../ref_all_executor/structured_submit.py), [typed contracts](../arcticbase/backend/src/arctic_base/refall/contracts.py).

## Findings and decisions

A candidate finding must supply evidence, confidence, and a source or artifact location.
The promotion gate checks source references against the inventory when that inventory is available.
It checks external hosts against explicit scope.
A claimed validation result requires verification material.

Finding identity uses the subject, vulnerability class, normalized title, and affected component.
Repeated locations stay attached to a canonical finding.

Lifecycle state and evidence quality remain separate.
An accepted `VALID` transition requires a `live_repro` receipt.
False-positive, duplicate, deferred, and downgrade decisions also require appropriate receipts.
A stale source hash or conflicting pending obligation can refuse the transition.
Accepted and refused attempts remain inspectable.

Sources: [Promotion gate](../arcticbase/backend/src/arctic_base/refall/promotion_gates.py), [finding transitions](../arcticbase/backend/src/arctic_base/refall/coverage_store.py#L1008).

## Scoped action authority

A capability grant identifies an action class, scope, grantor, expiry, and additional conditions.
Authorization requests identify the actor, command, target, and declared effects.
The broker compares these records before it returns an authorization decision.

Its checks include applicable host, port, HTTP method, filesystem path, expiry, and declared-identity conditions.
Grant and revoke authentication requires a configured `REFALL_CAPABILITY_OPERATOR_TOKEN_PATH`.
With the default unset token, the API retains caller-supplied identity fields.
It distinguishes network, Docker, Codebadger, secret use, and destructive actions.
A destructive grant can require a dry run and an approval token.
The production launch path uses this broker before starting the standing loop.

The broker governs requests submitted to its authorization route.
That route records a decision without executing the command.
Direct worker tools do not automatically pass through it.
The execution environment supplies the operating-system and container boundaries for agent processes.
Existing mounts supply their configured permissions; the source-copy fallback does not make files read-only.
Read [Control in depth](control-in-depth.md) for the complete boundary model.

Source: [Capability matching](../arcticbase/backend/src/arctic_base/refall/coverage_store.py#L1458).

## Pending obligations

Missing capability, blocked scope, incomplete proof, exhausted retries, and unanswered operator decisions become pending actions.
An action identifies its source, priority, ownership, status, and required receipt.
Workers claim eligible pending work before ordinary coverage units.
An operator can resolve, defer, or cancel the action through the workbench.

This makes a blocked result visible work.
It also gives later manager sessions an explicit account of what remains unresolved.

Source: [Pending action store](../arcticbase/backend/src/arctic_base/refall/coverage_store.py#L1161).

## Continuity and supervision

Loop state preserves active conversations and the current iteration.
Module progress preserves completed work for each target.
The blackboard supplies compact shared notes.
Runtime manifests and checkpoints connect a run to source identities, provider configuration, and stage results.
Resume preflight checks recorded input hashes before resumed execution.

Transport retries handle temporary service failures.
Worker retries distinguish repairable output from capability, scope, and operator-stop conditions.
A retry can switch from Claude to Codex within the configured attempt limit.
Successful conversations are archived before cleanup.

The watchdog examines progress, failures, budgets, and service state.
The supervisor separates fast liveness checks from broader review.
Repeated recovery can produce an operator hold rather than endless restart activity.

Sources: [Standing loop](../ref_all_executor/standing_loop.py), [watchdog](../ref_all_executor/watchdog.py), [supervisor](../ref_all_executor/supervisor.py).

## Living reports

The draft combines findings, architecture facts, flows, coverage, runtime proof, pending actions, and capability decisions.
Enrichment groups evidence and retains related locations.
A report worker can maintain analyst notes alongside the formal deliverable.
Report scheduling can use new evidence volume or reserve a continuous report slot.

The current report is an explicitly selected workbench object.
Replacement checks protect populated technical sections from a thinner generated report.
The operator can inspect a refused replacement candidate separately.

Visual evidence can include graph images, screenshots, captures, CodeCharta data, or focused property-graph slices.
The report standards connect these artifacts to their claims and provenance.

Sources: [Draft](../ref_all_executor/report_draft.py), [enrichment](../ref_all_executor/report_enrich.py), [assembly](../ref_all_executor/report_assemble.py).

## Checked closeout

The closeout gate evaluates unfinished actions, disposition receipts, proof, expired claims, context, and report freshness.
It separates blocking failures from advisory warnings.
Coverage threshold, high-impact visuals, toolchain use, and disclosure output can produce warnings.
Open obligations and a stale report can block completion.
An explicit override receipt records an operator exception.

Source: [Closeout gate](../arcticbase/backend/src/arctic_base/refall/closeout_gate.py).
