# Ready Armor in REFALL AB

REFALL applies the Ready Armor approach to sustained technical research.
The campaign owns its state, evidence, and decisions.
Worker conversations supply bounded examination and analysis.

The distinctive design connects work allocation, evidence capture, decision receipts, unresolved obligations, and the next research cycle.
These mechanisms make earlier work usable after a conversation ends, a manager restarts, or another configured provider takes an assignment.

## The research problem

A long investigation contains several kinds of unfinished work.
Some code remains unexamined.
Some observations need interpretation.
Some findings need reproduction.
Some actions need authority or an execution resource.
A report can be readable while these obligations remain open.

REFALL gives each condition a persistent record and a corresponding decision path.
The next worker receives an assignment built from that shared state.
The operator can inspect progress without treating the latest conversation as the entire campaign.

This design is useful when a subject needs repeated source examination, binary analysis, harness work, independent review, and report revisions.
It also supports architecture mapping, where observations and relationships can be useful without vulnerability findings.

## Capability, authority, observation, and acceptance

Ready Armor separates useful capability from the authority to exercise it.
It also separates an operation from the claim made about its result.
REFALL expresses those distinctions through campaign records and checked transitions.

Control in Depth assigns each check to a defined operation or record transition.
Persistent records keep the decision available to later workers and operators.
Together, these principles connect immediate control with continuity across changes in the configured execution resources.

| Question | REFALL record or mechanism | Practical effect |
| --- | --- | --- |
| What can the worker contribute? | Provider lane, task class, execution resources, and module objective. | Assign reasoning, implementation, review, or reporting work deliberately. |
| Which work should run next? | Claims, pending actions, module dependencies, and per-target progress. | Coordinate fresh examination and later passes across workers. |
| Which presented action is authorized? | Capability request, scoped grant, broker decision, and backend launch caller. | Preserve the authority decision and enforce refusal on that launch path. |
| What was observed? | Ledger entries, determinations, artifacts, and runtime observations. | Retain material beyond the worker's final response. |
| What change is accepted? | Finding admission, typed disposition receipts, and pending-action resolution. | Check the record transition independently of the worker's narrative. |
| Is the campaign ready to close? | Closeout checks over obligations, proof, claims, context, and report freshness. | Make completion a visible decision about stored state. |

The composition matters because each question can have a different answer.
A permitted launch does not establish a validated finding.
An examined unit does not establish that every behavior is safe.
An idle coordinator does not establish campaign closeout.

Sources: [scheduler](../ref_all_executor/standing_loop.py#L590), [capability decisions](../arcticbase/backend/src/arctic_base/refall/coverage_store.py#L1458), [finding transitions](../arcticbase/backend/src/arctic_base/refall/coverage_store.py#L1008), [closeout](../arcticbase/backend/src/arctic_base/refall/closeout_gate.py#L14).

## Host deployment and concrete enforcement

REFALL's campaign controls can operate as host services.
A virtual machine or container is not the security foundation for these backend decisions.
The enforcing code runs at API admission, work allocation, process release, record acceptance, and closeout.
These checks evaluate requests and stored state independently of the worker's prompt content.

| Boundary | Enforcing mechanism | Result |
| --- | --- | --- |
| Assignment ownership | A database transaction selects and leases an open or expired coverage unit. | Concurrent claim requests receive coordinated ownership. |
| Enabled backend loop launch | Start and Update call the capability broker before process creation. | Broker refusal returns HTTP 403 before the new process starts. |
| Candidate finding | Admission checks evidence, confidence, references, available inventory, and explicit external-target scope. | An unacceptable candidate receives refusal reasons. |
| Finding disposition | Typed receipts and applicable stored-state checks govern the requested transition. | Narrative alone cannot perform the transition. |
| Campaign closeout | Stored obligations, receipts, proof state, claims, context, and report freshness feed the closeout gate. | Blocking conditions prevent an ordinary closed result. |

The capability operator token protects grant and revoke routes when configured.
It gives the backend an authenticated operator identity for those mutations.
Without that setting, identity fields remain caller supplied.
Protecting that API access is part of the deployment's authority boundary.

The same design separates campaign control from direct execution permissions.
The host supplies filesystem, network, and process permissions.
Agent Canvas and other execution resources apply their configured environment controls.
A specialist's direct shell command does not automatically pass through REFALL's authorization broker.
Brokered callers enforce its decision before they release their own supported action.

This division makes host deployment useful without assigning every security responsibility to one sandbox or one model instruction.
The backend controls the campaign transitions it owns.
The execution host controls the resources available to the running tools.
The operator can inspect the retained authority decision, evidence, refusal, and next obligation.

Sources: [claim transaction](../arcticbase/backend/src/arctic_base/refall/coverage_store.py#L390), [launch authorization](../arcticbase/backend/src/arctic_base/api/refall_ops_commands.py#L366), [operator authentication](../arcticbase/backend/src/arctic_base/api/refall_capabilities.py#L18), [finding admission](../arcticbase/backend/src/arctic_base/refall/promotion_gates.py#L12), [typed dispositions](../arcticbase/backend/src/arctic_base/refall/coverage_store.py#L1008), [closeout gate](../arcticbase/backend/src/arctic_base/refall/closeout_gate.py#L14).

## 1. The subject retains the research

A workbench groups context, source inventory, coverage, evidence, findings, obligations, and the current report pointer.
These records have different lifecycles.
Their separation lets the operator distinguish an observation, a hypothesis, an accepted conclusion, and a completion decision.

Source inventory identifies available content with paths, hashes, sizes, line counts, and file kinds.
Coverage units turn part of that surface into claimable work.
The ledger preserves appended evidence and decision records.
Runtime storage retains events, observations, artifacts, manifests, and checkpoints.

A replacement manager can inspect those records before selecting further work.
Later unit objectives explicitly ask workers to reuse prior summaries, findings, shared notes, and saved analysis.
That guidance connects retained state with the next assignment.
It does not depend on one model retaining an unlimited conversation history.

Sources: [subject layout](../arcticbase/backend/src/arctic_base/refall/subjects.py#L56), [inventory](../ref_all_executor/source_inventory.py#L66), [ledger](../arcticbase/backend/src/arctic_base/refall/ledger.py#L41), [reuse instructions](../ref_all_executor/standing_loop.py#L676).

## 2. Breadth and depth share one campaign

Coverage establishes an examination surface.
Module passes can then deepen the understanding of individual targets.
The scheduler stores completed passes separately for each subject, unit, or finding target.
A prerequisite completed on one unit does not satisfy another unit's prerequisite.

The standing loop prioritizes worker-claimable pending actions and subject setup before fresh breadth.
Fresh coverage then precedes ordinary finding modules and later unit passes.
The built-in security path connects characterization, reconnaissance, and review.
Finding modules can request reproduction or a patch proposal.

This combination supports broad examination without losing focused questions.
Pending actions provide a route for urgent validation.
Local dependencies let different components advance at different rates.
A custom module can add a concrete research objective without replacing the entire coordinator.

Claims coordinate ownership with leases.
The backend selects open or expired units within a database transaction.
Completed module identifiers persist separately from the current conversation.
These controls reduce repeated allocation while keeping expired or unfinished work available for later examination.

Sources: [coverage claims](../arcticbase/backend/src/arctic_base/refall/coverage_store.py#L390), [module declarations](../ref_all_executor/work_modules.py#L46), [per-target progress](../ref_all_executor/work_modules.py#L386).

## 3. Useful output survives an incomplete invocation

A worker can produce useful analysis before it produces a final response.
REFALL reads available conversation events and workspace results during execution.
It can retain facts, leads, findings, flows, and saved analysis artifacts while the conversation remains active.

Terminal processing first classifies the invocation, parses its output, and checks submission identity.
It then preserves available observations before handling the classified outcome or scheduling a replacement.
A duplicate applied submission returns before terminal salvage.

Successful assignment completion has separate conditions.
Characterization coverage submission requires its own completion branch.
A module task without a unit record must produce durable canonical observations before its progress can advance.
The campaign can therefore retain partial research while still showing an unfinished assignment.

This separation is useful when a provider stops, output is truncated, or a worker saves files without a complete final narrative.
It preserves the available material for repair and review.
It also keeps an execution failure from being reported as completed examination merely because some evidence was captured.

Sources: [incremental ingestion](../ref_all_executor/standing_loop.py#L1115), [terminal order](../ref_all_executor/standing_loop.py#L1378), [empty-output check](../ref_all_executor/standing_loop.py#L1161).

## 4. Conclusions have their own acceptance path

The finding store checks proposed evidence, confidence, source references, and explicit external-target scope.
Inventory membership is checked when inventory is available.
A canonical finding can retain related evidence locations without representing each location as a different root cause.

Later finding decisions use typed receipts.
False-positive, duplicate, downgrade, deferred-chain, and live-validation decisions have distinct requirements.
Unresolved contradictory obligations can refuse a suppressive change.
A receipt that supplies source hashes also activates applicable source-root and current-content checks.

These decisions preserve negative conclusions as well as positive findings.
A later reviewer can inspect why a claim was rejected, deferred, reduced, or accepted.
A supported research primitive can remain visible while its wider exploitability still needs examination.

The gates check specified record, reference, and receipt conditions.
The operator reviews the interpretation and the meaning of the proof.
A well-written explanation alone does not perform the corresponding finding transition.

Sources: [candidate admission](../arcticbase/backend/src/arctic_base/refall/promotion_gates.py#L12), [canonical finding storage](../arcticbase/backend/src/arctic_base/refall/coverage_store.py#L749), [disposition receipts](../arcticbase/backend/src/arctic_base/refall/coverage_store.py#L1008).

## 5. Missing resources and missing authority remain distinct

A wishlist records a requested tool, environment, access requirement, or other research resource.
The watchdog can recognize host availability and process supported tool requests through its allowlisted installation path.
Delivery appends a provided record and a linked ledger receipt.
Supported head and research-driver prompts can include delivered resources in later objectives.

A pending action records work or a decision that remains unfinished.
A capability grant records authority for a presented action class and scope.
Providing a tool does not grant permission to use it against every target.
Recording a capability request does not resolve the related obligation automatically.

Backend Start and Update provide a concrete release boundary.
They consult the broker before an enabled loop process launch.
A refused decision gives HTTP 403 before that process starts.
Grant and revoke authentication requires the configured operator token file.
Without that token setting, the API retains caller-supplied identities.

REFALL supplies those campaign and broker controls.
The chosen execution environment supplies filesystem permissions, network boundaries, and any direct tool interception.
The generic authorization endpoint records a decision without executing an arbitrary command.
Callers need an integration that obeys the decision before action release.

Sources: [wishlist lifecycle](ledger-and-wishlist.md), [backend launch](../arcticbase/backend/src/arctic_base/api/refall_ops_commands.py#L366), [operator authentication](../arcticbase/backend/src/arctic_base/api/refall_capabilities.py#L18).

## 6. Reports and closeout compile the campaign state

Reports read stored evidence, findings, coverage, runtime material, capabilities, and unresolved work.
A current report has an explicit workbench object identifier.
The report assembly path can refuse a structural replacement that loses populated technical sections.
This preserves accumulated explanation while the underlying research continues.

Closeout examines the campaign through a separate gate.
Open obligations, missing required receipts, unproved finding states, expired claims, missing context, and stale reports can block the closed result.
Coverage below the default 95-percent threshold is advisory.
Draft and current report objects can exist before closeout succeeds.

The distinction makes a useful report and a completed campaign separately visible.
The operator can resolve the blocking work or record an explicit exception for identified checks.
The exception remains linked to its decision record.

Sources: [report inputs](../ref_all_executor/report_draft.py#L41), [replacement protection](../ref_all_executor/report_assemble.py#L16), [closeout checks](../arcticbase/backend/src/arctic_base/refall/closeout_gate.py#L14).

## A continuation example

Consider a source campaign that has characterized a parser and recorded a concrete reproduction lead.
The current worker stops after saving an analysis artifact.

1. The loop preserves available observations and records the failed invocation.
2. A recoverable failure can receive a bounded replacement attempt.
3. An unresolved proof or authority question remains a pending action.
4. The manager reads the stored evidence and selects the next eligible work.
5. The replacement worker receives the subject context, target, objective, and prior-work instructions.
6. It extends the evidence and proposes any necessary finding transition.
7. The backend evaluates the transition receipt independently of the new narrative.
8. Reports reuse the accumulated state, and closeout checks the remaining obligations.

Changing a configured worker provider does not replace the subject's evidence identifiers, finding history, or module progress.
A resumed coordinator can recover saved active conversations and progress.
Supported resume checks compare recorded inputs before continuing active work.
The detailed continuation behavior and its activation conditions are in [Control in depth](control-in-depth.md).

## The distinctive contribution

REFALL connects retained technical knowledge with the machinery that selects the next research task.
Coverage, claims, evidence, decisions, and obligations participate in the same continuing campaign.
This gives the operator a practical explanation of what was examined, what supports a conclusion, and what should happen next.

ARA, BRA, and REFALL apply related Ready Armor principles through separate implementations.
ARA addresses agent runtime and capability composition.
BRA addresses governed assessment operations and materialization.
REFALL addresses persistent research coordination, evidence acceptance, and campaign completion.

Its contribution is that connected research lifecycle.
The model supplies analysis, tools supply observations, and the campaign retains the records needed to continue and review the work.

Read [Research cycles](research-cycles.md) for scheduling and stopping behavior.
Read [Ledger and wishlist](ledger-and-wishlist.md) for the persistent resource and evidence paths.
Read [Control in depth](control-in-depth.md) for each actual decision boundary.
