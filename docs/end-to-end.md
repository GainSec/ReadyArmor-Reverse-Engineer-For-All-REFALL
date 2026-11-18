# REFALL AB end-to-end workflows

## From subject to research campaign

### 1. Attach the subject

Create a workbench for the selected source tree or material directory.
The subject record separates the examined source from the workspace that stores run state and outputs.
The workbench receives its own context, coverage, ledger, and report pointer.

```bash
python3 -m ref_all_executor subject create example --source-path /absolute/path/to/example
```

### 2. Establish shared context

Generate the briefing through the Context view or named context operation.
The context writer receives source material, workbench text, metadata, and operator direction.
REFALL stores the resulting Markdown in the backend and subject workspace.

Read the briefing before execution.
Use it to define the target, available material, research priorities, constraints, and done conditions.

```bash
python3 -m ref_all_executor ops command context example
```

### 3. Select the work

Choose module packs and any subject-specific declarations.
Set include or exclude globs for later passes over characterized units.
Set the scope overlay and request a threat model when useful.
A mapping campaign can select characterization and decomposition without security assessment modules.

### 4. Check readiness and authority

Run Doctor to inspect services, provider commands, paths, context, capabilities, and supporting tools.
Run Estimate to inspect remaining work and prerequisites.
Provide the subject-scoped launch grant through the capability interface.
A configured operator token authenticates grant changes; the unset default does not.
The browser client does not attach that token automatically.
Use an authenticated host-side client when token protection is active.

```bash
python3 -m ref_all_executor ops command doctor example
python3 -m ref_all_executor ops command estimate example
```

### 5. Start through backend operations

The web interface and production CLI use the same backend launch path.
The backend checks context and authorizes the process request.
It then checks Agent Canvas and projects the source into its configured workspace.
A matching bind mount can supply the source directly.
Otherwise, the source-sync helper copies a snapshot into the container.

```bash
python3 -m ref_all_executor loop start example
```

### 6. Build the examination surface

If coverage is empty, the standing loop builds a source inventory.
Each included file has a path, content hash, size, kind, and line count.
Coverage units form the denominator for recorded examination.
A binary-only root opens an analysis-plan action instead of becoming synthetic line coverage.

### 7. Assign a bounded task

The scheduler first considers pending actions and requested threat-model work.
It then considers subject modules, fresh coverage units, finding modules, and later unit passes.
Subject, finding, and later unit selection apply the relevant module eligibility checks.
Fresh characterization uses coverage claims and the global loop concurrency limit.
It attaches the first active breadth module and its objective.

The task objective contains context, scope, shared notes, target details, routing rationale, and an output contract.
The dispatcher adds source, writable workspace, and approved resource information.
Agent Canvas starts the selected specialist conversation.

### 8. Compile observations during execution

The loop polls execution state and reads agent-authored event messages.
It also reads structured submission files and registers saved analysis files.
Facts, leads, findings, and flow relationships become durable research records during the run.
The workbench can show those results before the conversation ends.

### 9. Separate evidence from completion

Terminal handling first classifies the invocation, parses its output, and checks submission identity.
It preserves useful observations before handling success, scheduling repair, or creating an operator obligation.
Only the characterization success path submits its coverage result.
Later modules extend the evidence without submitting that coverage again.

Malformed strict output, missing capability, and blocked scope create pending work.
A failed worker does not erase its supported observations.
A subject module without durable results does not advance as completed work.

### 10. Review the finding

A candidate passes through evidence and source-reference checks.
The canonical record preserves equivalent evidence locations.
A proposed state change then goes through the disposition gate.
Typed receipts explain promotion, rejection, duplicates, deferral, or downgrade.
Source-dependent receipts can include hashes for freshness checks.

### 11. Publish accumulated understanding

Periodic drafts and report workers compile findings, architecture, flows, proof, and remaining questions.
Analyst notes preserve developing understanding separately from the formal report.
The current report pointer selects the deliverable visible in the workbench.
A structural comparison can refuse a replacement that removes populated technical sections.

### 12. Close with explicit state

Prepare the draft and enrichment before requesting closeout.
The gate checks open obligations, validation, disposition receipts, expired claims, context, and the current report.
It returns individual blocking checks and warnings.
Resolve the blocking conditions or record an operator override receipt.

```bash
python3 -m ref_all_executor report draft example
python3 -m ref_all_executor report enrich example
python3 -m ref_all_executor loop closeout example
```

## Source and binary workflows

### Main workbench loop

The main loop uses work modules and workbench-local APIs.
It combines subject tasks, coverage breadth, finding tasks, and later examination passes.
This is the loop launched by the normal Start and Update operations.

### Source investigation driver

The standalone source family uses `coverage_service.tools.seed_subject` and `drive_research.py`.
The seed scanner locates concrete source patterns for commands, parsers, files, network access, secrets, and authorization.
It groups anchors into prioritized investigation questions.

A researcher claims a question, reads the anchor, traces data, and examines related callers or callees.
Concrete leads can add child investigations to the frontier.
The driver runs batches until that frontier is exhausted, a configured limit is reached, or the operator stops it.
The specialist prompts use the standalone compatibility coverage service.

### Binary investigation driver

The binary family begins with `coverage_service.tools.seed_binary`.
It identifies executable format and imports through radare2.
It maps selected dangerous imports to callers and generates function-level investigations.

`drive_binresearch.py` assigns bounded decompilation work.
Workers examine pseudocode, disassembly, arguments, and cross-references.
They trace attacker-controlled data to the relevant operation and add concrete branch questions.

`drive_binreview.py` runs an independent adversarial review of provisional findings.
Reviewers reopen the cited function and challenge reachability, bounds checks, mitigations, and severity.
They retain exact missing proof targets when a claim remains uncertain.

`drive_binvalidate.py` selects retained findings without complete runtime proof.
Validators prepare a canonical payload, reproduction command, trace, raw output, and observed effect.
Subject-specific host actions supply the required execution surface.
The driver can publish research visuals and a disclosure package when its validation conditions are satisfied.

These standalone drivers have their own batch lifecycle and compatibility API contracts.
They are separate entry points from the module scheduler.
Read the driver arguments and subject harness requirements before selecting that family.

## Recovery without losing the campaign

An Update request runs one bounded scheduling and polling cycle.
It can resume active conversations from stored loop state.
Per-target module progress prevents already completed passes from being repeated unnecessarily.

Resume preflight compares recorded source and lane-configuration hashes.
A refused resume remains an explicit decision in runtime and pending state.
Temporary HTTP failures use transport retries.
Recoverable worker failures use bounded repair attempts.
Capability and scope failures request decisions instead of repeated execution.

Conversation trajectories and event streams are archived before successful cleanup.
The watchdog and supervisor inspect progress and service health.
Recovery restores the failed component within the configured policy.
Operator holds preserve visibility when repeated recovery is ineffective.

## Source map

| Stage | Implementation |
| --- | --- |
| Operator controls | [WorkbenchOpsPanel](../arcticbase/frontend/src/lib/refall/WorkbenchOpsPanel.svelte) |
| Backend lifecycle | [Operations](../arcticbase/backend/src/arctic_base/api/refall_ops_commands.py) |
| Scheduling and ingestion | [Standing loop](../ref_all_executor/standing_loop.py) |
| Per-target work | [Modules](../ref_all_executor/work_modules.py) |
| Coverage and decisions | [Coverage store](../arcticbase/backend/src/arctic_base/refall/coverage_store.py) |
| Source frontier | [Source research](../drive_research.py) |
| Binary frontier | [Binary research](../drive_binresearch.py) |
| Independent binary review | [Binary review](../drive_binreview.py) |
| Runtime proof | [Binary validation](../drive_binvalidate.py) |
| Closeout | [Closeout gate](../arcticbase/backend/src/arctic_base/refall/closeout_gate.py) |
